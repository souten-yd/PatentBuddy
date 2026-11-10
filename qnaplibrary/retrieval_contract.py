"""Validate Host retrieval attestation and preserve exact input row coverage."""
import math
from .addon_client import AddonError


def validate_result(value, capability, count, model_ref):
    def fail():
        raise AddonError(502, '検索AIの実行条件・応答を検証できません')
    if (not isinstance(value, dict) or value.get('execution_policy') != 'local_only'
            or value.get('model_ref') != model_ref or value.get('revision_kind') != 'host_file_metadata_v1'):
        fail()
    if capability == 'text.embed':
        vectors = value.get('vectors'); dim = value.get('dimensions')
        if type(dim) is not int or not 1 <= dim <= 8192 or not isinstance(vectors, list) or len(vectors) != count:
            fail()
        for vector in vectors:
            if (not isinstance(vector, list) or len(vector) != dim or not any(vector)
                    or any(type(x) not in (int, float) or not math.isfinite(x) for x in vector)):
                fail()
    else:
        rows = value.get('rankings')
        if not isinstance(rows, list) or len(rows) != count:
            fail()
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                fail()
            index, score = row.get('index'), row.get('score')
            if (type(index) is not int or not 0 <= index < count or index in seen
                    or type(score) not in (int, float) or not math.isfinite(score)):
                fail()
            seen.add(index)
    return value
