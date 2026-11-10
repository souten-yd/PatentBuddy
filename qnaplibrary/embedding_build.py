"""Bounded, resumable canonical indexing using the Host's local embedding model.

The caller owns the Host job, CPU lease, heartbeat and terminal reconciliation.
Only successfully committed batches are checkpoints; no source text is persisted
in the PC worker. A retry asks the canonical server for remaining chunks.
"""
import hashlib
import re

from .addon_client import AddonError
from .retrieval_contract import validate_result


def build(client, host):
    caps = host.call('GET', '/ai/retrieval/capabilities').get('text.embed', {})
    model = caps.get('model_ref')
    if (caps.get('available') is not True or caps.get('execution_policy') != 'local_only'
            or caps.get('revision_kind') != 'host_file_metadata_v1'
            or not isinstance(model, str) or not re.fullmatch('[a-f0-9]{64}', model)):
        raise AddonError(503, 'Hostのローカル埋め込みモデルを利用できません')
    after = completed = 0
    dimensions = None

    def check_cancel():
        if host.aborted.is_set():
            raise AddonError(409, '索引構築を中断しました。保存済みの部分から再開できます')

    def save_batch(rows):
        nonlocal completed, dimensions
        check_cancel()
        result = validate_result(host.retrieval('text.embed', [r['text'] for r in rows]),
                                 'text.embed', len(rows), model)
        if dimensions is not None and dimensions != result['dimensions']:
            raise AddonError(409, '埋め込みモデルの次元が変更されました')
        dimensions = result['dimensions']
        check_cancel()
        payload = {'model_ref': model, 'dimensions': dimensions,
                   'revision_kind': 'host_file_metadata_v1', 'items': [
                       {**{k: row[k] for k in ('chunk_id', 'revision', 'chunk_sha256')}, 'vector': vec}
                       for row, vec in zip(rows, result['vectors'])]}
        saved = client.data('POST', '/api/v1/host-vectors', payload)
        if (saved.get('model_ref') != model or type(saved.get('stored')) is not int
                or type(saved.get('unchanged')) is not int or saved['stored'] < 0
                or saved['unchanged'] < 0 or saved['stored'] + saved['unchanged'] != len(rows)):
            raise AddonError(502, '索引の保存結果を確認できません。再開時に保存済み部分を照合します')
        completed += len(rows)
        # Total is intentionally unknown while the corpus may be changing.
        host.progress('embedding', completed, None)

    while True:
        check_cancel()
        page = client.data('GET', '/api/v1/host-vectors/pending?model_ref=%s&after=%d&limit=32' % (model, after))
        rows = page.get('items')
        if page.get('model_ref') != model or not isinstance(rows, list) or len(rows) > 32:
            raise AddonError(502, '索引対象の応答を検証できません')
        if not rows:
            # Edits to chunks below the cursor must not silently look complete.
            remaining = client.data('GET', '/api/v1/host-vectors/pending?model_ref=%s&limit=1' % model)
            if remaining.get('model_ref') != model or remaining.get('items') != []:
                raise AddonError(409, '資料が更新されています。索引構築を再開してください')
            return {'model_ref': model, 'completed_chunks': completed, 'dimensions': dimensions}
        batch = []; size = 0
        for row in rows:
            if not isinstance(row, dict):
                raise AddonError(502, '索引対象が不正です')
            cid = row.get('chunk_id'); text = row.get('text')
            if (type(cid) is not int or not after < cid <= 2**63-1
                    or not isinstance(text, str) or not text.strip() or len(text) > 8192
                    or not isinstance(row.get('revision'), str)
                    or not re.fullmatch('[a-f0-9]{64}', row['revision'])
                    or hashlib.sha256(text.encode()).hexdigest() != row.get('chunk_sha256')):
                raise AddonError(502, '索引対象の本文・版・大きさを確認できません')
            nbytes = len(text.encode())
            if batch and size + nbytes > 64 * 1024:
                save_batch(batch); batch = []; size = 0
            batch.append(row); size += nbytes; after = cid
        if page.get('next_cursor') != after:
            raise AddonError(502, '索引対象のカーソルが一致しません')
        if batch:
            save_batch(batch)
