"""Host embedding snapshots in the single canonical DB, isolated by model space."""
from array import array
import hashlib
import math
import re
from .store import StoreError

SCHEMA = '''
CREATE TABLE IF NOT EXISTS host_vector_spaces(
 model_ref TEXT PRIMARY KEY, dimensions INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS host_vectors(
 chunk_id INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
 model_ref TEXT NOT NULL REFERENCES host_vector_spaces(model_ref) ON DELETE CASCADE,
 revision TEXT NOT NULL, vec BLOB NOT NULL, PRIMARY KEY(chunk_id,model_ref));
CREATE INDEX IF NOT EXISTS host_vectors_model ON host_vectors(model_ref,chunk_id);
CREATE TRIGGER IF NOT EXISTS host_vectors_source_changed AFTER UPDATE OF hash,source ON documents
WHEN OLD.hash != NEW.hash OR OLD.source != NEW.source BEGIN
 DELETE FROM host_vectors WHERE chunk_id IN (SELECT id FROM chunks WHERE doc_id=NEW.id);
END;
'''


def model_id(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}',value):
        raise StoreError('invalid Host model reference')
    return value


def pending(store, model_ref, after=0, limit=32):
    model_id(model_ref)
    if type(after) is not int or not 0 <= after <= 2**63-1 or type(limit) is not int or not 1 <= limit <= 32:
        raise StoreError('invalid embedding cursor or limit')
    rows = store.q('''SELECT c.id,c.doc_id,c.text,d.hash,d.source FROM chunks c
 JOIN documents d ON d.id=c.doc_id LEFT JOIN host_vectors v ON v.chunk_id=c.id AND v.model_ref=?
 WHERE c.id>? AND v.chunk_id IS NULL ORDER BY c.id LIMIT ?''',(model_ref,after,limit))
    return {'items':[{'chunk_id':r['id'],'doc_id':r['doc_id'],'text':r['text'],
                     'revision':store.document_revision(r),
                     'chunk_sha256':hashlib.sha256(r['text'].encode()).hexdigest()} for r in rows],
            'next_cursor':rows[-1]['id'] if rows else None,'model_ref':model_ref}


def save(store, value, actor):
    if not isinstance(value,dict) or value.get('revision_kind')!='host_file_metadata_v1':
        raise StoreError('invalid Host vector batch')
    model = model_id(value.get('model_ref'));items=value.get('items');dim=value.get('dimensions')
    if (type(dim) is not int or not 1<=dim<=8192 or not isinstance(items,list) or not 1<=len(items)<=32):
        raise StoreError('invalid vector batch size or dimension')
    seen=set();validated=[]
    for item in items:
        if not isinstance(item,dict):raise StoreError('invalid vector row')
        cid=item.get('chunk_id');vec=item.get('vector')
        if type(cid) is not int or not 1<=cid<=2**63-1 or cid in seen:
            raise StoreError('invalid or duplicate chunk id')
        seen.add(cid)
        if not isinstance(vec,list) or len(vec)!=dim or not any(vec):
            raise StoreError('invalid vector shape')
        try:
            if any(type(x) not in (int,float) or not math.isfinite(x) for x in vec):raise ValueError()
            packed=array('f',vec)
            if any(not math.isfinite(x) for x in packed) or not any(packed):raise ValueError()
        except (ValueError,TypeError,OverflowError):
            raise StoreError('vectors require finite nonzero float32 values') from None
        validated.append((item,packed.tobytes()))
    stored=unchanged=0
    with store.tx() as db:
        space=db.execute('SELECT dimensions FROM host_vector_spaces WHERE model_ref=?',(model,)).fetchone()
        if space and space['dimensions']!=dim:raise StoreError('model space dimension mismatch')
        if not space:
            if db.execute('SELECT COUNT(*) FROM host_vector_spaces').fetchone()[0]>=8:
                raise StoreError('model space limit reached; remove an unused space explicitly')
            db.execute('INSERT INTO host_vector_spaces VALUES(?,?)',(model,dim))
        for item,blob in validated:
            row=db.execute('''SELECT c.text,d.hash,d.source FROM chunks c JOIN documents d ON c.doc_id=d.id
 WHERE c.id=?''',(item['chunk_id'],)).fetchone()
            if (row is None or store.document_revision(row)!=item.get('revision')
                    or hashlib.sha256(row['text'].encode()).hexdigest()!=item.get('chunk_sha256')):
                raise StoreError('chunk content or source revision changed; re-extract embeddings')
            old=db.execute('SELECT revision,vec FROM host_vectors WHERE chunk_id=? AND model_ref=?',
                           (item['chunk_id'],model)).fetchone()
            if old:
                if old['revision']!=item['revision'] or bytes(old['vec'])!=blob:
                    raise StoreError('existing model/chunk has a different vector; remove space before rebuilding')
                unchanged+=1
            else:
                db.execute('INSERT INTO host_vectors VALUES(?,?,?,?)',(item['chunk_id'],model,item['revision'],blob));stored+=1
        if stored:store.audit(actor,'vectors.host.add','%s count:%d'%(model,stored))
    return {'stored':stored,'unchanged':unchanged,'model_ref':model}


def remove(store, model_ref, actor):
    model_id(model_ref)
    with store.tx() as db:
        count=db.execute('DELETE FROM host_vector_spaces WHERE model_ref=?',(model_ref,)).rowcount
        if count:store.audit(actor,'vectors.host.remove',model_ref)
    return {'removed':bool(count)}
