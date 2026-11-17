"""K3: bounded, read-only projection of reviewed knowledge and PR23 evidence graph.

The Knowledge Map never registers technical relationships. Document->essence
arcs mean 'source proposal' only; they are not factual patent claims. GraphRAG
traversal remains exclusively approved, fresh and factual by default.
"""
import json

from . import evidence_graph
from .knowledge_reviews import latest
from .knowledge_essence import KnowledgeProposalError, validate
from .store import StoreError

MAX_NODES = 36
MAX_EDGES = 52
MAX_PROPOSALS = 20
# Reserve room for reviewed knowledge even if evidence GraphRAG is dense.
GRAPH_NODES = 24
GRAPH_EDGES = 36


def _id(value):
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise StoreError('invalid knowledge map document')
    return value


def _node_id(node):
    if node['kind'] == 'document' and type(node['doc_id']) is int:
        return 'd:%d' % node['doc_id']
    return 'g:%d' % node['id']


def read(store, doc_id, *, hops=1, include_unreviewed=False):
    """Project a single document neighborhood with stable bounds and no writes."""
    _id(doc_id)
    if type(hops) is not int or hops not in (1, 2):
        raise StoreError('knowledge map supports only 1 or 2 hops')
    if type(include_unreviewed) is not bool:
        raise StoreError('invalid review visibility')

    with store.lock:
        doc = store.db.execute(
            'SELECT id,title,hash,source FROM documents WHERE id=?',
            (doc_id,),
        ).fetchone()
        if doc is None:
            raise StoreError('knowledge map source not found')
        current_revision = store.document_revision(doc)
        root_id = 'd:%d' % doc_id
        nodes = [{
            'id': root_id, 'kind': 'document',
            'label': doc['title'] or '文献 %d' % doc_id,
            'document_id': doc_id, 'status': 'source',
        }]
        edges = []
        seen = {root_id}
        truncated = False

        # Read from the exact PR23 Evidence GraphRAG tables. Do not materialize
        # a second graph or infer a relation from similarity/LLM prose.
        graph_root = store.db.execute(
            "SELECT id FROM graph_nodes WHERE kind='document' AND doc_id=? LIMIT 1",
            (doc_id,),
        ).fetchone()
        if graph_root:
            expanded = evidence_graph.expand(
                store, [graph_root['id']], hops=hops,
                max_nodes=GRAPH_NODES, max_edges=GRAPH_EDGES,
                include_inferred=False,
            )
            truncated = expanded['truncated']
            by_graph_id = {n['id']: n for n in expanded['nodes']}
            for edge in expanded['edges']:
                # PR23 already filters approved/factual/nonstale; recheck
                # evidence revision and exact quote at the read boundary.
                # SQLite substr counts Unicode characters and returns only the
                # bounded quoted span, not a potentially 20 MB patent body.
                if (edge['start'] < 0 or edge['end'] <= edge['start']
                        or edge['end'] - edge['start'] > 4000):
                    continue
                source_doc = store.db.execute(
                    'SELECT hash,source,substr(body,?,?) AS excerpt '
                    'FROM documents WHERE id=?',
                    (edge['start'] + 1, edge['end'] - edge['start'],
                     edge['evidence_doc_id']),
                ).fetchone()
                if (source_doc is None or
                        store.document_revision(source_doc) != edge['revision'] or
                        source_doc['excerpt'] != edge['quote']):
                    continue
                src = by_graph_id.get(edge['source_node'])
                dst = by_graph_id.get(edge['target_node'])
                if src is None or dst is None:
                    continue
                for graph_node in (src, dst):
                    nid = _node_id(graph_node)
                    if nid not in seen:
                        if len(nodes) >= MAX_NODES:
                            truncated = True
                            break
                        nodes.append({
                            'id': nid, 'kind': graph_node['kind'],
                            'label': graph_node['label'],
                            'document_id': graph_node['doc_id'],
                            'status': 'reviewed_graph_node',
                        })
                        seen.add(nid)
                else:
                    if len(edges) >= MAX_EDGES:
                        truncated = True
                        break
                    edges.append({
                        'id': 'g:' + edge['id'], 'source': _node_id(src),
                        'target': _node_id(dst), 'relation': edge['relation'],
                        'basis': 'factual', 'review_status': 'approved',
                        'evidence': {
                            'doc_id': edge['evidence_doc_id'],
                            'revision': edge['revision'],
                            'start': edge['start'], 'end': edge['end'],
                            'quote': edge['quote'],
                        },
                    })

        snapshots = store.db.execute(
            "SELECT id,source_revision,content FROM document_analyses "
            "WHERE doc_id=? AND kind='knowledge' "
            "ORDER BY created DESC,id DESC LIMIT ?",
            (doc_id, MAX_PROPOSALS + 1),
        ).fetchall()
        if len(snapshots) > MAX_PROPOSALS:
            truncated = True
        snapshots = snapshots[:MAX_PROPOSALS]
        review_map = latest(store, [r['id'] for r in snapshots],
                            {r['id']: current_revision for r in snapshots})
        body = None  # load the source text only when current proposals exist
        for row in snapshots:
            stale = row['source_revision'] != current_revision
            if stale and not include_unreviewed:
                continue
            try:
                proposal = json.loads(row['content'])
                if not stale:
                    if body is None:
                        body = store.db.execute(
                            'SELECT body FROM documents WHERE id=?', (doc_id,)
                        ).fetchone()['body']
                    proposal = validate({
                        'id': doc_id, 'revision': current_revision,
                        'body': body,
                    }, proposal)
                if not isinstance(proposal, dict) or not isinstance(proposal.get('items'), list):
                    continue
            except (ValueError, TypeError, KeyError, KnowledgeProposalError):
                continue
            for index, item in enumerate(proposal['items'][:12]):
                review = review_map.get(row['id'], {}).get(str(index), {})
                state = 'unreviewed' if stale else review.get('status', 'unreviewed')
                # Explicit opt-in to inspect unreviewed/rejected/stale nodes.
                if state != 'approved' and not include_unreviewed:
                    continue
                if not isinstance(item, dict) or not isinstance(item.get('evidence'), dict):
                    continue
                if len(nodes) >= MAX_NODES or len(edges) >= MAX_EDGES:
                    truncated = True
                    break
                nid = 'k:%s:%d' % (row['id'], index)
                nodes.append({
                    'id': nid, 'kind': item.get('kind', 'concept'),
                    'label': item.get('statement', ''),
                    'document_id': doc_id,
                    'review_status': state,
                    'previous_decision': review.get('previous_decision'),
                    'stale': stale,
                    'basis': 'model_inference',
                    'evidence': {
                        'doc_id': doc_id,
                        'revision': row['source_revision'],
                        'start': item['evidence'].get('start'),
                        'end': item['evidence'].get('end'),
                        'quote': item['evidence'].get('quote'),
                    },
                    'conditions': item.get('conditions', []),
                    'limitations': item.get('limitations', []),
                })
                edges.append({
                    'id': 'p:%s:%d' % (row['id'], index),
                    'source': root_id, 'target': nid,
                    'relation': 'proposal_evidence_source',
                    'basis': 'provenance_only',
                    'review_status': state, 'stale': stale,
                })
        return {
            'root': root_id, 'nodes': nodes, 'edges': edges,
            'hops': hops, 'truncated': truncated,
            'limits': {'nodes': MAX_NODES, 'edges': MAX_EDGES},
            'include_unreviewed': include_unreviewed,
            'direction': 'outgoing',
            'disclaimer': 'AI inference is not a verified patent fact; provenance links do not imply technical relationships',
        }
