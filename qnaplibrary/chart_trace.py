"""Validate bounded retrieval metadata at the canonical chart write boundary."""
import math
import re
from .store import StoreError

STAGES = ['keyword', 'vector', 'graph', 'rerank']
FIELDS = {'label','stages','embedding_model_ref','reranker_model_ref','revision_kind','snapshot_etag',
          'vector_scanned','vector_total','vector_truncated','graph_truncated','candidate_count'}


def validate(chart):
    trace = chart.get('retrieval')
    if (not isinstance(trace, dict) or set(trace) != {'stages','rows','graph_truncated','vector_truncated'}
            or trace['stages'] != STAGES or not isinstance(trace['rows'], list)
            or len(trace['rows']) != len(chart['rows'])):
        raise StoreError('invalid chart retrieval trace')
    identity = None
    for row, t in zip(chart['rows'], trace['rows']):
        if (not isinstance(t, dict) or set(t) != FIELDS or t['label'] != row['element']['label']
                or t['stages'] != STAGES or t['revision_kind'] != 'host_file_metadata_v1'
                or any(not isinstance(t[k], str) or not re.fullmatch('[a-f0-9]{64}', t[k])
                       for k in ('embedding_model_ref','reranker_model_ref'))
                or not isinstance(t['snapshot_etag'], str) or not re.fullmatch('[a-f0-9]{32}:[0-9]{1,20}', t['snapshot_etag'])
                or any(type(t[k]) is not bool for k in ('vector_truncated','graph_truncated'))
                or any(type(t[k]) is not int for k in ('vector_scanned','vector_total','candidate_count'))
                or not 0 <= t['vector_scanned'] <= t['vector_total'] <= 1000000
                or not 0 <= t['candidate_count'] <= 12
                or len(row['evidence']) != min(3, t['candidate_count'])
                or (not t['vector_truncated'] and t['vector_scanned'] != t['vector_total'])):
            raise StoreError('invalid chart retrieval row')
        current = tuple(t[k] for k in ('embedding_model_ref','reranker_model_ref','snapshot_etag','vector_total'))
        if identity is not None and identity != current:
            raise StoreError('chart retrieval model or snapshot changed between rows')
        identity = current
        seen, last_score = set(), math.inf
        for e in row['evidence']:
            via = e.get('via'); score = e.get('rerank_score')
            if (not isinstance(via, str) or (via not in ('keyword','vector') and not re.fullmatch('graph:[A-Za-z0-9_-]{1,128}', via))
                    or type(score) not in (int, float) or not math.isfinite(score) or score > last_score):
                raise StoreError('invalid chart evidence retrieval path or ranking')
            key = (e['doc_id'], e['start'], e['end'])
            if key in seen:
                raise StoreError('duplicate chart evidence range')
            seen.add(key); last_score = score
    for flag in ('graph_truncated','vector_truncated'):
        if type(trace[flag]) is not bool or trace[flag] != any(t[flag] for t in trace['rows']):
            raise StoreError('chart truncation summary differs from retrieval rows')
