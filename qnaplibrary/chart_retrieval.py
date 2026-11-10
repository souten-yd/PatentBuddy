"""Bounded keyword/vector/approved-graph/rerank candidate retrieval on the PC.

The caller must hold a Host CPU lease and maintain its job heartbeat. This
module does not create a document database or choose an external AI provider.
"""
import re
import urllib.parse

from .addon_client import AddonError
from .embedding_build import model_reference
from .retrieval_contract import validate_result
from .vector_cache import VectorCache


class ChartRetrieval:
    def __init__(self, client, session, directory):
        self.client, self.session = client, session
        self.model = model_reference(session)
        caps = session.call('GET', '/ai/retrieval/capabilities').get('text.rerank', {})
        self.reranker = caps.get('model_ref')
        if (caps.get('available') is not True or caps.get('execution_policy') != 'local_only'
                or caps.get('revision_kind') != 'host_file_metadata_v1'
                or not isinstance(self.reranker, str) or not re.fullmatch('[a-f0-9]{64}', self.reranker)):
            raise AddonError(503, 'Hostのローカル再順位付けモデルを利用できません')
        self._complete_index()
        self.cache = VectorCache(directory)
        self.path, self.snapshot = self.cache.synchronize(client, self.model, session.aborted)

    def _complete_index(self):
        pending = self.client.data('GET', '/api/v1/host-vectors/pending?model_ref=' + self.model + '&limit=1')
        if pending.get('model_ref') != self.model or pending.get('items') != []:
            raise AddonError(409, '未索引の資料があります。「検索索引を構築・更新」を実行してください')

    def finish(self):
        self._complete_index()
        current = self.client.data('GET', '/api/v1/host-vectors/' + self.model + '/manifest')
        if current.get('etag') != self.snapshot['etag']:
            raise AddonError(409, '検索中に索引の原文が更新されました。再実行してください')

    def retrieve(self, query, keyword_query, excluded_doc, label):
        if self.session.aborted.is_set():
            raise AddonError(409, '検索を中断しました')
        hits = self.client.data('POST', '/api/v1/search', {
            'q': keyword_query, 'mode': 'keyword', 'rerank': False,
            'limit': 8, 'include_text': False, 'group_by_doc': True})['results']
        embedded = validate_result(self.session.retrieval('text.embed', [query]), 'text.embed', 1, self.model)
        found = self.cache.search(self.path, self.snapshot, embedded['vectors'][0],
                                  limit=8, cancel=self.session.aborted)
        candidates = []
        def append(value, via):
            if value['doc_id'] == excluded_doc or not value.get('quote'):
                return False
            if any((c['doc_id'], c['start'], c['end']) == (value['doc_id'], value['start'], value['end']) for c in candidates):
                return False
            candidates.append({k: value[k] for k in ('doc_id', 'revision', 'start', 'end', 'quote')})
            candidates[-1]['via'] = via
            return True
        for source, via in ((hits, 'keyword'), (found['results'], 'vector')):
            added = 0
            for hit in source:
                if hit['doc_id'] == excluded_doc:
                    continue
                value = self.client.data('GET', '/api/v1/chunks/%d/evidence' % hit['chunk_id'])
                if value.get('chunk_id') != hit['chunk_id'] or value.get('doc_id') != hit['doc_id']:
                    raise AddonError(409, '検索候補が変更されました')
                if via == 'vector' and value.get('revision') != hit['revision']:
                    raise AddonError(409, '索引の原文が変更されました')
                if value.get('citable') is True and append(value, via):
                    added += 1
                if added == 4:
                    break
        # Include seeds from both retrieval methods. Bound document/node counts
        # independently so one document's graph cannot make the request unbounded.
        seed_docs = []
        for pair in zip(hits, found['results']):
            for hit in pair:
                if hit['doc_id'] not in seed_docs:
                    seed_docs.append(hit['doc_id'])
        seed_docs.extend(h['doc_id'] for h in hits + found['results'] if h['doc_id'] not in seed_docs)
        seeds = set()
        for did in seed_docs[:3]:
            seeds.update(n['id'] for n in self.client.data('GET', '/api/v1/graph/documents/%d' % did)['nodes'])
        graph_truncated = False
        if seeds:
            expanded = self.client.data('GET', '/api/v1/graph/expand?' + urllib.parse.urlencode({
                'seeds': ','.join(str(s) for s in sorted(seeds)[:20]), 'hops': 2, 'max_nodes': 20, 'max_edges': 20}))
            graph_truncated = expanded['truncated'] or len(seeds) > 20
            added = 0
            for edge in expanded['edges']:
                if edge['evidence_doc_id'] == excluded_doc:
                    continue
                end = min(edge['end'], edge['start'] + 650)
                value = self.client.data('GET', '/api/v1/documents/%d/evidence?' % edge['evidence_doc_id'] +
                    urllib.parse.urlencode({'revision': edge['revision'], 'start': edge['start'], 'end': end}))
                if value.get('quote') != edge['quote'][:650]:
                    raise AddonError(409, 'グラフの引用が変更されました')
                if append(value, 'graph:' + edge['id']):
                    candidates[-1]['graph'] = {k: edge[k] for k in ('id', 'graph_revision', 'fingerprint', 'basis', 'relation', 'model', 'confidence', 'retrieved_at', 'method')}
                    added += 1
                if added == 4:
                    break
        evidence = []
        if candidates:
            ranked = validate_result(self.session.retrieval('text.rerank', [c['quote'] for c in candidates], query),
                                     'text.rerank', len(candidates), self.reranker)
            for rank in sorted(ranked['rankings'], key=lambda r: (-r['score'], r['index']))[:3]:
                evidence.append(dict(candidates[rank['index']], ref=label + '-E' + str(len(evidence) + 1),
                                     rerank_score=rank['score']))
        return evidence, {'stages': ['keyword', 'vector', 'graph', 'rerank'],
            'embedding_model_ref': self.model, 'reranker_model_ref': self.reranker,
            'revision_kind': 'host_file_metadata_v1', 'snapshot_etag': self.snapshot['etag'],
            'vector_scanned': found['scanned'], 'vector_total': found['total'],
            'vector_truncated': found['truncated'], 'graph_truncated': graph_truncated,
            'candidate_count': len(candidates)}
