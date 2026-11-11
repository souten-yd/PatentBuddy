"""Disposable PC vector cache. Contains identifiers/revisions/vectors, never document text."""
from array import array
from contextlib import closing
import base64
import hashlib
import heapq
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time
import urllib.parse
from .addon_client import AddonError
from .host_vectors import model_id

MAX_BYTES = 2 * 1024**3
MAX_ROWS = 1000000


def _decode(raw, dimensions):
    if not isinstance(raw,bytes) or len(raw)!=dimensions*4:
        raise AddonError(502,'ベクトルの次元が一致しません')
    values=array('f');values.frombytes(raw)
    if sys.byteorder!='little':values.byteswap()
    if any(not math.isfinite(v) for v in values):raise AddonError(502,'ベクトルの値が不正です')
    norm=math.sqrt(sum(v*v for v in values))
    if not norm:raise AddonError(502,'ゼロベクトルです')
    return values,norm


def _state(value,model):
    if (not isinstance(value,dict) or value.get('model_ref')!=model or value.get('encoding')!='float32-le'
            or type(value.get('dimensions')) is not int or not 1<=value['dimensions']<=8192
            or type(value.get('vector_count')) is not int or not 0<=value['vector_count']<=MAX_ROWS
            or not isinstance(value.get('etag'),str) or not re.fullmatch('[a-f0-9]{32}:[0-9]+',value['etag'])
            or value['vector_count']*(value['dimensions']*4+128)>MAX_BYTES):
        raise AddonError(502,'ベクトル索引が対応するサイズ・形式の上限を超えています')
    return {k:value[k] for k in ('model_ref','dimensions','vector_count','etag','encoding')}


class VectorCache:
    def __init__(self,directory):
        self.root=Path(directory)/'vector-cache'
        self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir() or self.root.stat().st_mode & 0o077:
            raise AddonError(503,'ベクトルキャッシュは非公開の通常ディレクトリが必要です')

    def synchronize(self,client,model,cancel=None):
        model_id(model)
        def check():
            if cancel and cancel.is_set():raise AddonError(409,'索引同期を中断しました')
        check()
        base='/api/v1/host-vectors/'+model
        state=_state(client.data('GET',base+'/manifest'),model)
        server=client.settings()['server_url']
        key=hashlib.sha256(json.dumps([server,state],sort_keys=True).encode()).hexdigest()
        target=self.root/(key+'.sqlite3')
        if target.exists():
            if target.is_symlink() or not target.is_file() or target.stat().st_mode & 0o077:
                raise AddonError(503,'不正なキャッシュファイルです')
            with closing(sqlite3.connect('file:'+urllib.parse.quote(str(target))+'?mode=ro',uri=True)) as db:
                saved=json.loads(db.execute('SELECT value FROM metadata').fetchone()[0])
                if saved!=state:raise AddonError(503,'索引の状態が一致しません。キャッシュを再構築してください')
            return target,state
        fd,name=tempfile.mkstemp(prefix='building-',suffix='.sqlite3',dir=self.root);os.close(fd)
        temporary=Path(name)
        try:
            with closing(sqlite3.connect(temporary)) as db, db:
                db.execute('PRAGMA synchronous=FULL')
                db.execute('PRAGMA cache_size=-8192')
                db.execute('CREATE TABLE vectors(chunk_id INTEGER PRIMARY KEY,doc_id INTEGER,revision TEXT,vec BLOB,norm REAL)')
                db.execute('CREATE TABLE metadata(value TEXT)')
                last=count=0
                while True:
                    check()
                    batch=client.data('GET',base+'/page?'+urllib.parse.urlencode({'etag':state['etag'],'after':last,'limit':128}))
                    if _state(batch,model)!=state:raise AddonError(409,'同期中に正本が更新されました')
                    rows=batch.get('items')
                    if not isinstance(rows,list) or len(rows)>128:raise AddonError(502,'索引ページが不正です')
                    for row in rows:
                        if not isinstance(row,dict):raise AddonError(502,'索引行が不正です')
                        cid,did,rev=row.get('chunk_id'),row.get('doc_id'),row.get('revision')
                        if (type(cid) is not int or not last<cid<=2**63-1 or type(did) is not int or not 1<=did<=2**63-1
                                or not isinstance(rev,str) or not re.fullmatch('[a-f0-9]{64}',rev)):
                            raise AddonError(502,'索引のID・版が不正です')
                        encoded=row.get('vector_base64')
                        if not isinstance(encoded,str) or len(encoded)>44000:raise AddonError(502,'ベクトルが上限を超えました')
                        raw=base64.b64decode(encoded,validate=True);_,norm=_decode(raw,state['dimensions'])
                        db.execute('INSERT INTO vectors VALUES(?,?,?,?,?)',(cid,did,rev,raw,norm));last=cid;count+=1
                        if count>state['vector_count']:raise AddonError(502,'索引件数が一致しません')
                    if batch.get('next_cursor')!=(last if rows else None):raise AddonError(502,'索引カーソルが一致しません')
                    if not rows:break
                    if temporary.stat().st_size>MAX_BYTES:raise AddonError(507,'索引容量の上限を超えました')
                if count!=state['vector_count'] or _state(client.data('GET',base+'/manifest'),model)!=state:
                    raise AddonError(409,'同期中に正本の索引が変わりました')
                check()
                db.execute('INSERT INTO metadata VALUES(?)',(json.dumps(state,sort_keys=True),))
            if temporary.stat().st_size>MAX_BYTES:raise AddonError(507,'索引容量の上限を超えました')
            os.replace(temporary,target)
            # At most two completed, reproducible cache files; no canonical data.
            old=sorted((p for p in self.root.glob('*.sqlite3') if re.fullmatch('[a-f0-9]{64}\\.sqlite3',p.name) and p!=target),key=lambda p:p.stat().st_mtime,reverse=True)
            for path in old[1:]:
                if not path.is_symlink() and path.is_file():path.unlink()
            return target,state
        finally:
            temporary.unlink(missing_ok=True)
            Path(str(temporary)+'-journal').unlink(missing_ok=True)

    def search(self,path,state,query,limit=20,cancel=None,seconds=30):
        if (type(limit) is not int or not 1<=limit<=100 or not isinstance(query,list) or len(query)!=state['dimensions']
                or type(seconds) not in (int,float) or not math.isfinite(seconds) or not 0<=seconds<=30):
            raise AddonError(400,'検索条件またはベクトル次元が不正です')
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in query):raise AddonError(400,'検索ベクトルが不正です')
        norm=math.sqrt(sum(v*v for v in query))
        if not norm or not math.isfinite(norm):raise AddonError(400,'検索ベクトルの大きさが不正です')
        query=[v/norm for v in query];heap=[];scanned=0;start=time.monotonic();truncated=False
        with closing(sqlite3.connect('file:'+urllib.parse.quote(str(path))+'?mode=ro',uri=True)) as db:
            db.execute('PRAGMA cache_size=-8192')
            cursor=db.execute('SELECT chunk_id,doc_id,revision,vec,norm FROM vectors ORDER BY chunk_id')
            while True:
                if cancel and cancel.is_set():raise AddonError(409,'ベクトル検索を中断しました')
                rows=cursor.fetchmany(128)
                if not rows:break
                if time.monotonic()-start>seconds:truncated=True;break
                for cid,did,revision,raw,vnorm in rows:
                    values,_=_decode(raw,state['dimensions'])
                    score=sum(a*b for a,b in zip(values,query))/vnorm
                    item=(score,-cid,did,revision)
                    if len(heap)<limit:heapq.heappush(heap,item)
                    elif item>heap[0]:heapq.heapreplace(heap,item)
                    scanned+=1
        return {'results':[{'chunk_id':-cid,'doc_id':did,'revision':revision,'score':score} for score,cid,did,revision in sorted(heap,reverse=True)],
                'scanned':scanned,'total':state['vector_count'],'truncated':truncated,'model_ref':state['model_ref']}
