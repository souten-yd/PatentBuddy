"""Validate the opaque Host-local generation provenance contract."""
import re
from .addon_client import AddonError


def validate_provenance(value):
    if (not isinstance(value, dict)
            or set(value) != {'execution_policy', 'revision_kind', 'model_ref', 'runtime_ref'}
            or value.get('execution_policy') != 'local_only'
            or value.get('revision_kind') != 'host_process_file_metadata_v1'
            or any(not isinstance(value.get(k), str) or not re.fullmatch('[a-f0-9]{64}', value[k])
                   for k in ('model_ref', 'runtime_ref'))):
        raise AddonError(502, 'Hostの生成モデル版を確認できません')
    return dict(value)
