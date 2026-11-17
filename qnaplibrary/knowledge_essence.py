"""Pure validation for evidence-backed, unreviewed knowledge proposals.

K1a contract only: no model invocation, network, database mutation or automatic
adoption. The Host/local-only policy is checked again at the eventual API exit.
"""
import re


class KnowledgeProposalError(ValueError):
    """Invalid knowledge proposal; messages contain no source or model output."""


KINDS = frozenset((
    'problem', 'cause', 'constraint', 'principle', 'mechanism',
    'implementation', 'effect', 'observation', 'application',
))
MAX_BODY = 100_000
MAX_ITEMS = 12
MAX_QUOTE = 1_200
_PROVENANCE_FIELDS = frozenset((
    'execution_policy', 'revision_kind', 'model_ref', 'runtime_ref',
))
_ITEM_FIELDS = frozenset((
    'kind', 'statement', 'basis', 'review_status', 'evidence',
    'conditions', 'limitations',
))


def _string(value, limit, field):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise KnowledgeProposalError('invalid ' + field)
    if any(ord(char) < 32 and char not in '\n\t' for char in value):
        raise KnowledgeProposalError('invalid ' + field)
    return value


def _list_of_strings(value, field):
    if not isinstance(value, list) or len(value) > 4:
        raise KnowledgeProposalError('invalid ' + field)
    return [_string(item, 240, field) for item in value]


def _provenance(value):
    if not isinstance(value, dict) or set(value) != _PROVENANCE_FIELDS:
        raise KnowledgeProposalError('invalid generation provenance')
    if value['execution_policy'] != 'local_only' or value['revision_kind'] != 'host_process_file_metadata_v1':
        raise KnowledgeProposalError('local-only generation provenance required')
    for name in ('model_ref', 'runtime_ref'):
        if not isinstance(value[name], str) or not re.fullmatch(r'[a-f0-9]{64}', value[name]):
            raise KnowledgeProposalError('invalid generation provenance')
    return {field: value[field] for field in (
        'execution_policy', 'revision_kind', 'model_ref', 'runtime_ref',
    )}


def validate(document, proposal):
    """Validate and detach a model proposal against a versioned source document.

    Document requires id, revision and body, and may contain additional keys.
    The proposal must have exactly the specified fields. All model-extracted
    statements are *inferred/unreviewed*, even when their quote is literal.
    A correct quote proves only a text span, not a technical or legal inference.
    """
    if not isinstance(document, dict) or type(document.get('id')) is not int or document['id'] < 1:
        raise KnowledgeProposalError('invalid source document')
    revision = _string(document.get('revision'), 128, 'source revision')
    body = document.get('body')
    if not isinstance(body, str) or not body.strip() or len(body) > MAX_BODY:
        raise KnowledgeProposalError('invalid source body')
    if not isinstance(proposal, dict) or set(proposal) != {
        'schema_version', 'doc_id', 'source_revision', 'generation', 'items',
    }:
        raise KnowledgeProposalError('invalid proposal envelope')
    if (type(proposal['schema_version']) is not int or proposal['schema_version'] != 1
            or type(proposal['doc_id']) is not int or proposal['doc_id'] != document['id']
            or proposal['source_revision'] != revision):
        raise KnowledgeProposalError('proposal source mismatch')
    generation = _provenance(proposal['generation'])
    items = proposal['items']
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise KnowledgeProposalError('invalid proposal items')
    result = []
    seen = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != _ITEM_FIELDS:
            raise KnowledgeProposalError('invalid knowledge item fields')
        kind = item['kind']
        if not isinstance(kind, str) or kind not in KINDS:
            raise KnowledgeProposalError('invalid knowledge kind')
        statement = _string(item['statement'], 500, 'statement')
        if item['basis'] != 'model_inference' or item['review_status'] != 'unreviewed':
            raise KnowledgeProposalError('model proposals cannot be approved or factual')
        evidence = item['evidence']
        if not isinstance(evidence, dict) or set(evidence) != {'start', 'end', 'quote'}:
            raise KnowledgeProposalError('invalid evidence fields')
        start, end = evidence['start'], evidence['end']
        if (type(start) is not int or type(end) is not int or start < 0
                or end <= start or end > len(body) or end - start > MAX_QUOTE):
            raise KnowledgeProposalError('invalid evidence range')
        quote = _string(evidence['quote'], MAX_QUOTE, 'evidence quote')
        if body[start:end] != quote:
            raise KnowledgeProposalError('evidence quote or revision mismatch')
        conditions = _list_of_strings(item['conditions'], 'conditions')
        limitations = _list_of_strings(item['limitations'], 'limitations')
        key = (kind, statement, start, end)
        if key in seen:
            raise KnowledgeProposalError('duplicate knowledge item')
        seen.add(key)
        result.append({
            'kind': kind, 'statement': statement, 'basis': 'model_inference',
            'review_status': 'unreviewed',
            'evidence': {'start': start, 'end': end, 'quote': quote},
            'conditions': conditions, 'limitations': limitations,
        })
    return {
        'schema_version': 1, 'doc_id': document['id'],
        'source_revision': revision, 'generation': generation, 'items': result,
    }
