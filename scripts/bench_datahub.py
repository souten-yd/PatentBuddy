#!/usr/bin/env python3
"""Opt-in Linux API benchmark. Only synthetic data in a fresh temporary directory.

Use the same script with --repo BASELINE and --repo CANDIDATE. Device counters
include unrelated activity; process I/O includes client/server in this process.
No cache drops, global sync, service changes or production data are performed.
"""
import argparse
import hashlib
import http.cookiejar
import inspect
import json
import math
import os
from pathlib import Path
import platform
import resource
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

SAMPLE = '固体電解質を含む蓄電装置の正極と負極の間に硫化物層を設け、安全性を改善する。'
SQL = {'seconds': 0.0, 'calls': 0}


class TimedCursor(sqlite3.Cursor):
    def execute(self, *args, **kwargs):
        start = time.perf_counter()
        try:
            return super().execute(*args, **kwargs)
        finally:
            SQL['seconds'] += time.perf_counter() - start
            SQL['calls'] += 1

    def fetchall(self):
        start = time.perf_counter()
        try:
            return super().fetchall()
        finally:
            SQL['seconds'] += time.perf_counter() - start

    def fetchone(self):
        start = time.perf_counter()
        try:
            return super().fetchone()
        finally:
            SQL['seconds'] += time.perf_counter() - start


class TimedConnection(sqlite3.Connection):
    def execute(self, *args, **kwargs):
        return self.cursor(factory=TimedCursor).execute(*args, **kwargs)


def documents(start, end, changed=False):
    for i in range(start, end):
        yield {'id': 'SYN%09d' % i, 'title': '評価用研究資料 %d' % i,
               'body': SAMPLE * 8 + ('改訂版。' if changed else ''), 'date': '2026-01-01',
               'source': 'synthetic', 'meta': {'license': 'synthetic-test-only',
               'revision': '2' if changed else '1', 'ipc': ['H01M'], 'standard': 'IEC-SYN'}}


def percentile(samples):
    data = sorted(samples)
    return {key: data[max(0, math.ceil(len(data) * fraction) - 1)]
            for key, fraction in [('p50_ms', .50), ('p95_ms', .95), ('p99_ms', .99)]} if data else {}


def io_snapshot(root):
    proc = {k: int(v) for k, v in (line.split(':') for line in Path('/proc/self/io').read_text().splitlines())}
    dev = os.stat(root).st_dev
    stat = Path('/sys/dev/block/%d:%d/stat' % (os.major(dev), os.minor(dev)))
    device = None
    if stat.exists():
        fields = stat.read_text().split()
        device = {'read_bytes': int(fields[2]) * 512, 'write_bytes': int(fields[6]) * 512}
    return {'process': proc, 'device': device}


def fingerprint(store):
    digest = hashlib.sha256()
    with store.lock:
        for row in store.db.execute('SELECT id,ext_id,hash FROM documents ORDER BY id'):
            digest.update(json.dumps(tuple(row), ensure_ascii=False).encode())
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--documents', type=int, default=1000)
    parser.add_argument('--batch', type=int, default=200)
    parser.add_argument('--repeats', type=int, default=30)
    parser.add_argument('--idle-seconds', type=int, default=0)
    parser.add_argument('--workdir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.documents <= 100000 or not 1 <= args.batch <= 1000 or args.repeats < 2 or args.idle_seconds < 0:
        parser.error('documents 1..100000, batch 1..1000, repeats >=2, idle >=0 required')
    sys.path.insert(0, str(args.repo.resolve()))
    from qnaplibrary.server import App, Server
    from qnaplibrary import debuglog
    from qnaplibrary.store import Store
    debuglog.setup('WARNING', stderr=False)
    args.workdir.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rdh-bench-', dir=args.workdir) as tmp:
        root = Path(tmp)
        original_connect = sqlite3.connect
        sqlite3.connect = lambda *a, **kw: original_connect(*a, **dict(kw, factory=TimedConnection))
        try:
            app = App(root)
        finally:
            sqlite3.connect = original_connect
        server = Server(('127.0.0.1', 0), app)
        app.httpd = server
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:%d' % server.server_address[1]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        csrf = None
        def call(method, path, body=None):
            headers = {'Content-Type': 'application/json'}
            if csrf:
                headers['X-CSRF-Token'] = csrf
            req = urllib.request.Request(base + path, method=method, headers=headers,
                data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None)
            with opener.open(req, timeout=300) as response:
                return json.load(response)
        def snapshot():
            sizes = {suffix or 'db': (Path(app.store.path + suffix).stat().st_size if Path(app.store.path + suffix).exists() else 0)
                     for suffix in ('', '-wal', '-shm')}
            return {'io': io_snapshot(root), 'sizes': sizes, 'changes': app.store.db.total_changes,
                    'cpu': time.process_time(), 'sql': dict(SQL), 'time': time.perf_counter()}
        result = {'repo': str(args.repo.resolve()), 'commit': subprocess.check_output(['git', '-C', str(args.repo), 'rev-parse', 'HEAD'], text=True).strip(),
                  'documents': args.documents, 'batch': args.batch, 'sqlite': sqlite3.sqlite_version,
                  'platform': platform.platform(), 'cpu': platform.processor(), 'fts5': app.store.fts,
                  'cpu_model': next((line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), ''),
                  'memory_total': Path('/proc/meminfo').read_text().splitlines()[0],
                  'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  'filesystem_device': os.readlink('/sys/dev/block/%d:%d' % (os.major(os.stat(root).st_dev), os.minor(os.stat(root).st_dev))),
                  'phases': {}, 'notes': ['synthetic data; warm OS cache; no cache drops',
                    'device counters include other processes', 'SQL timing covers execute/fetch calls, excludes executescript and row iteration',
                    'API/client and server CPU/RSS share this process; scheduler/background collection not started']}
        def phase(name, fn, repetitions=1):
            before = snapshot(); times = []; last = None
            for _ in range(repetitions):
                t = time.perf_counter(); last = fn(); times.append((time.perf_counter() - t) * 1000)
            after = snapshot()
            entry = {'seconds': after['time'] - before['time'], 'cpu_seconds': after['cpu'] - before['cpu'],
                     'sqlite_row_changes': after['changes'] - before['changes'],
                     'sql_seconds': after['sql']['seconds'] - before['sql']['seconds'],
                     'sql_calls': after['sql']['calls'] - before['sql']['calls'], 'samples': repetitions,
                     'rss_peak_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                     'files_before': before['sizes'], 'files_after': after['sizes'], **percentile(times)}
            entry['io_delta'] = {scope: {k: after['io'][scope][k] - value for k, value in before['io'][scope].items()}
                                 if before['io'][scope] is not None else None for scope in ('process', 'device')}
            result['phases'][name] = entry
            print(json.dumps({'phase': name, 'seconds': entry['seconds'], 'changes': entry['sqlite_row_changes']}), flush=True)
            return last
        try:
            csrf = call('POST', '/api/auth/setup', {'password': 'synthetic-benchmark-only'})['csrf']
            cid = call('POST', '/api/v1/collections', {'name': 'synthetic', 'kind': 'generic'})['id']
            path = '/api/v1/collections/%d/documents' % cid
            def ingest(changed=False, count=None):
                totals = {'added': 0, 'updated': 0, 'unchanged': 0}; latencies = []
                for start in range(0, count or args.documents, args.batch):
                    t = time.perf_counter()
                    response = call('POST', path, {'documents': list(documents(start, min(start + args.batch, count or args.documents), changed))})
                    latencies.append((time.perf_counter() - t) * 1000)
                    for key in totals: totals[key] += response[key]
                return dict(totals, batch_latency=percentile(latencies), batches=len(latencies))
            for name, changed, count in [('ingest', False, args.documents), ('identical_reingest', False, args.documents), ('update_1_percent', True, max(1, args.documents // 100))]:
                counts = phase(name, lambda: ingest(changed, count))
                expected_key = {'ingest': 'added', 'identical_reingest': 'unchanged', 'update_1_percent': 'updated'}[name]
                assert counts[expected_key] == count, counts
                result['phases'][name].update(counts)
                result['phases'][name]['docs_per_second'] = count / result['phases'][name]['seconds']
                result['phases'][name]['body_mib_per_second'] = sum(len(d['body'].encode()) for d in documents(0, count, changed)) / 1048576 / result['phases'][name]['seconds']
            for name, suffix in [('first_page', '?limit=50'), ('deep_page', '?limit=50&offset=%d' % max(0, args.documents-50)), ('title_filter', '?limit=50&q=999')]:
                page = phase(name, lambda: call('GET', path + suffix), args.repeats)
                assert all('body' not in d for d in page['items'])
            if 'cursor' in inspect.signature(app.store.list_documents).parameters:
                phase('cursor_deep', lambda: call('GET', path + '?limit=50&cursor=51'), args.repeats)
                found = phase('exact_id', lambda: call('GET', path + '?ext_id=SYN000000050'), args.repeats)
                assert len(found['items']) == (1 if args.documents > 50 else 0)
            else:
                result['unsupported_baseline'] = ['cursor_deep', 'exact_id API']
            query = {'q': '固体電解質', 'collections': [cid], 'mode': 'keyword', 'limit': 20}
            hits = phase('keyword', lambda: call('POST', '/api/v1/search', query), args.repeats)
            assert len(hits['results']) == min(20, args.documents)
            if args.idle_seconds:
                phase('idle', lambda: time.sleep(args.idle_seconds))
            expected = fingerprint(app.store)
            original_hits = app.store.fts_search('固体電解質', [cid], limit=20)
            result['storage'] = {'pragmas': {p: app.store.one('PRAGMA ' + p)[0] for p in ('journal_mode', 'synchronous', 'foreign_keys', 'wal_autocheckpoint')},
                'counts': {t: app.store.one('SELECT COUNT(*) FROM ' + t)[0] for t in ('documents', 'chunks', 'vectors')}}
            try:
                result['storage']['index_bytes'] = {r[0]: r[1] for r in app.store.q('SELECT name,SUM(pgsize) FROM dbstat GROUP BY name')}
            except sqlite3.OperationalError:
                result['storage']['index_bytes'] = None
            backup = phase('backup', app.backups.create)
            server.shutdown(); server.server_close(); app.store.close()
            t = time.perf_counter(); reopened = Store(root / 'library.sqlite3')
            assert fingerprint(reopened) == expected
            assert reopened.fts_search('固体電解質', [cid], limit=20) == original_hits
            result['store_reopen_and_verify_seconds'] = time.perf_counter() - t; reopened.close()
            t = time.perf_counter(); restored_path = root / 'restored.sqlite3'
            shutil.copyfile(root / backup['path'], restored_path)
            restored = Store(restored_path)
            assert restored.one('PRAGMA quick_check')[0] == 'ok'
            assert fingerprint(restored) == expected
            assert restored.fts_search('固体電解質', [cid], limit=20) == original_hits
            result['copy_restore_and_verify_seconds'] = time.perf_counter() - t; restored.close()
            result['restart_restore_verified'] = True
        finally:
            if thread.is_alive():
                server.shutdown(); server.server_close(); app.store.close()
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
