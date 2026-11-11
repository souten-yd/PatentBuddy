"""Canonical research snapshots; no provider calls or implicit download approval."""
import json
from contextlib import nullcontext
import re
import time

from .research_selection import snapshot, select
from .store import StoreError


def _encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _id(identifier):
    if not isinstance(identifier, str) or not re.fullmatch('[a-f0-9]{64}', identifier):
        raise StoreError('invalid research snapshot id')
    return identifier


def create(store, records, actor, discovery=None, _connection=None):
    state = snapshot(records)
    # The identity covers merged content; duplicate input counts are not canonical.
    state.pop('input_count')
    payload = _encode(state)
    if len(payload.encode()) > 8 * 1024 * 1024:
        raise StoreError('research snapshot exceeds size limit')
    identifier = state['revision']
    if _connection is not None and (_connection is not store.db or not store.db.in_transaction):
        raise StoreError('internal research transaction is not active')
    with (nullcontext(_connection) if _connection is not None else store.tx()) as db:
        old = db.execute('SELECT payload FROM research_snapshots WHERE id=?', (identifier,)).fetchone()
        if old is None:
            db.execute('INSERT INTO research_snapshots VALUES(?,?,?)', (identifier, payload, time.time()))
            store.audit(actor, 'research.snapshot', identifier)
        elif old['payload'] != payload:
            raise StoreError('research snapshot content conflict')
        if discovery is not None:
            db.execute('INSERT INTO research_discoveries(snapshot_id,context,created) VALUES(?,?,?)',
                       (identifier, _encode(discovery), time.time()))
    return get(store, identifier)


def get(store, identifier):
    _id(identifier)
    # One lock makes the snapshot and selection a consistent response.
    with store.lock:
        row = store.one('SELECT payload FROM research_snapshots WHERE id=?', (identifier,))
        if row is None:
            raise StoreError('research snapshot not found')
        selection = store.one('SELECT revision,payload FROM research_selections WHERE snapshot_id=?', (identifier,))
        discovery = store.one('SELECT context,created FROM research_discoveries WHERE snapshot_id=? ORDER BY id DESC LIMIT 1', (identifier,))
        return dict(snapshot=json.loads(row['payload']),
                    discovery=dict(json.loads(discovery['context']), acquired_at=discovery['created']) if discovery else None,
                    selection_revision=selection['revision'] if selection else 0,
                    selection=json.loads(selection['payload']) if selection else None)


def save_selection(store, identifier, value, actor):
    _id(identifier)
    fields = {'snapshot_revision', 'expected_revision', 'masked_cells', 'pinned', 'selected', 'limit'}
    if not isinstance(value, dict) or set(value) != fields:
        raise StoreError('invalid research selection fields')
    expected = value['expected_revision']
    if type(expected) is not int or expected < 0:
        raise StoreError('invalid selection revision')
    with store.tx() as db:
        current = get(store, identifier)
        preview = select(current['snapshot'], value['snapshot_revision'], value['masked_cells'],
                         value['pinned'], value['selected'], value['limit'])
        saved = dict(masked_cells=sorted(value['masked_cells']), pinned=sorted(value['pinned']),
                     selected=sorted(value['selected']), preview=preview)
        payload = _encode(saved)
        # Retrying a lost response is a no-op, including audit/WAL writes.
        if current['selection'] == saved:
            return current
        if expected != current['selection_revision']:
            raise StoreError('selection changed; reload before saving')
        revision = expected + 1
        db.execute('INSERT INTO research_selections VALUES(?,?,?,?) '
                   'ON CONFLICT(snapshot_id) DO UPDATE SET revision=excluded.revision, '
                   'payload=excluded.payload,updated=excluded.updated',
                   (identifier, revision, payload, time.time()))
        store.audit(actor, 'research.selection', identifier + ':' + str(revision))
        return get(store, identifier)


def list_snapshots(store, cursor=None):
    if cursor is not None:
        _id(cursor)
    rows = store.q('SELECT id,created FROM research_snapshots ' +
                   ('WHERE id>? ' if cursor else '') + 'ORDER BY id LIMIT 51',
                   (cursor,) if cursor else ())
    return dict(items=[dict(row) for row in rows[:50]],
                next_cursor=rows[49]['id'] if len(rows) > 50 else None)
