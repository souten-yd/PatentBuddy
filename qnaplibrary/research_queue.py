"""Durable, bounded bibliography requests with fenced worker completion."""
import json
import re
import secrets
import time

from . import research_store
from .store import StoreError


def _id(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{32}', value):
        raise StoreError('invalid research request id')
    return value


def get(store, identifier):
    row = store.one('SELECT id,params,state,revision,snapshot_id,error,created,updated '
                    'FROM research_requests WHERE id=?', (_id(identifier),))
    if row is None:
        raise StoreError('research request not found')
    result = dict(row)
    result['params'] = json.loads(result['params'])
    return result


def create(store, value, actor):
    if not isinstance(value, dict) or set(value) != {'id', 'query', 'limit', 'confirm_public'}:
        raise StoreError('invalid research request fields')
    identifier = _id(value['id'])
    query, limit = value['query'], value['limit']
    if (value['confirm_public'] is not True or not isinstance(query, str) or not query.strip()
            or len(query) > 2000 or type(limit) is not int or not 1 <= limit <= 100):
        raise StoreError('confirm public query and candidate limit 1..100')
    params = json.dumps(dict(query=query, limit=limit, provider='epo_ops'), sort_keys=True, ensure_ascii=False)
    with store.tx() as db:
        old = db.execute('SELECT params FROM research_requests WHERE id=?', (identifier,)).fetchone()
        if old:
            if old['params'] != params:
                raise StoreError('request id already used for different conditions')
        else:
            if db.execute("SELECT count(*) FROM research_requests WHERE state IN ('queued','discovering')").fetchone()[0] >= 100:
                raise StoreError('pending research request limit reached')
            now = time.time()
            db.execute('INSERT INTO research_requests(id,params,state,revision,created,updated) VALUES(?,?,?,?,?,?)',
                       (identifier, params, 'queued', 1, now, now))
            store.audit(actor, 'research.request', identifier)
        return get(store, identifier)


def list_requests(store, before=None):
    if before is not None:
        _id(before)
    rows = store.q('SELECT id,state,revision,created,updated,snapshot_id FROM research_requests ' +
                   ('WHERE id<? ' if before else '') + 'ORDER BY id DESC LIMIT 51', (before,) if before else ())
    return dict(items=[dict(row) for row in rows[:50]], next_cursor=rows[49]['id'] if len(rows) > 50 else None)


def transition(store, identifier, expected, action, actor):
    if type(expected) is not int or expected < 1 or action not in ('cancel', 'retry'):
        raise StoreError('invalid research transition')
    with store.tx() as db:
        current = get(store, identifier)
        if current['revision'] != expected:
            raise StoreError('research request changed; reload')
        if action == 'retry' and current['state'] not in ('failed', 'waiting_credentials', 'canceled'):
            raise StoreError('research request cannot be retried in this state')
        if action == 'cancel' and current['state'] not in ('queued', 'discovering', 'waiting_credentials'):
            raise StoreError('research request cannot be canceled in this state')
        if action == 'retry' and db.execute("SELECT count(*) FROM research_requests WHERE state IN ('queued','discovering')").fetchone()[0] >= 100:
            raise StoreError('pending research request limit reached')
        state = 'queued' if action == 'retry' else 'canceled'
        db.execute('UPDATE research_requests SET state=?,revision=revision+1,lease=NULL,lease_until=0,error=?,updated=? WHERE id=?',
                   (state, '', time.time(), identifier))
        store.audit(actor, 'research.' + action, identifier)
        return get(store, identifier)


def claim(store):
    """Private worker operation. Lease tokens never appear in public GETs."""
    with store.tx() as db:
        now = time.time()
        row = db.execute("SELECT id FROM research_requests WHERE state='queued' OR "
                         "(state='discovering' AND lease_until<?) ORDER BY created,id LIMIT 1", (now,)).fetchone()
        if row is None:
            return None
        lease = secrets.token_hex(16)
        db.execute("UPDATE research_requests SET state='discovering',revision=revision+1,lease=?,lease_until=?,updated=? WHERE id=?",
                   (lease, now + 180, now, row['id']))
        return dict(get(store, row['id']), lease=lease)


def finish(store, job, result=None, error=None):
    if error not in (None, 'credentials_not_configured', 'provider_failed'):
        raise StoreError('invalid research failure code')
    with store.tx() as db:
        row = db.execute('SELECT state,lease,lease_until,revision FROM research_requests WHERE id=?', (_id(job['id']),)).fetchone()
        if (row is None or row['state'] != 'discovering' or row['lease'] != job['lease']
                or row['revision'] != job['revision'] or row['lease_until'] <= time.time()):
            raise StoreError('research worker lease is stale')
        sid = None
        if error:
            state = 'waiting_credentials' if error == 'credentials_not_configured' else 'failed'
        else:
            if not isinstance(result, dict) or set(result) != {'records','provider','fetched','reported_total','truncated'}:
                raise StoreError('invalid research result')
            context = {k:v for k,v in result.items() if k != 'records'}
            context.update(query=job['params']['query'], requested_limit=job['params']['limit'])
            saved = research_store.create(store, result['records'], 'research-worker', discovery=context, _connection=db)
            sid = saved['snapshot']['revision']
            state = 'awaiting_selection'
        db.execute('UPDATE research_requests SET state=?,revision=revision+1,lease=NULL,lease_until=0,snapshot_id=?,error=?,updated=? WHERE id=?',
                   (state, sid, error or '', time.time(), job['id']))
        store.audit('research-worker', 'research.' + state, job['id'])
        return get(store, job['id'])
