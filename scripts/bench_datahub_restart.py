#!/usr/bin/env python3
"""Explicit synthetic process restart/restore acceptance; no existing data touched."""
import argparse
import contextlib
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--documents', type=int, default=1000)
    parser.add_argument('--workdir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.documents <= 100000:
        parser.error('documents must be 1..100000')
    sys.path.insert(0, str(args.repo.resolve()))
    from qnaplibrary.config import Config
    from qnaplibrary.store import Store
    from tests.helpers import Client
    args.workdir.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rdh-restart-', dir=args.workdir) as tmp:
        root = Path(tmp).resolve(); data = root / 'data'; data.mkdir()
        Config(data).update({'update': {'auto_check': False}, 'auth': {'rp_id': 'synthetic.example.invalid', 'session_hours': 123}})
        Config(data).set_secret('passkey_user_handle', 'synthetic-stable-handle')
        store = Store(data / 'library.sqlite3')
        cid = store.create_collection('synthetic')['id']
        for start in range(0, args.documents, 200):
            store.add_documents(cid, [{'id': 'SYN%d' % i, 'body': '電池の構造。' * 40,
                'meta': {'license': 'synthetic-only'}} for i in range(start, min(start + 200, args.documents))])
        store.db.execute("INSERT INTO passkeys(credential_id,public_key,alg,sign_count,name,created) VALUES(?,?,?,?,?,?)",
                         (b'synthetic-credential', b'synthetic-key', -7, 0, 'fixture', time.time()))
        store.close()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        client = Client('http://127.0.0.1:%d' % port)
        @contextlib.contextmanager
        def running(directory):
            start = time.perf_counter()
            with open(root / 'server.log', 'ab') as log:
                proc = subprocess.Popen([sys.executable, '-m', 'researchdatahub', '--data', str(directory),
                    '--bind', '127.0.0.1', '--port', str(port)], cwd=args.repo, stdout=log, stderr=log)
                try:
                    for _ in range(600):
                        if proc.poll() is not None:
                            raise RuntimeError('server exited before readiness')
                        try:
                            status, health = client.call('GET', '/api/health')
                            if status == 200:
                                break
                        except (OSError, urllib.error.URLError):
                            pass
                        time.sleep(.05)
                    else:
                        raise RuntimeError('health readiness timeout')
                    yield time.perf_counter() - start
                finally:
                    proc.terminate()
                    try:
                        proc.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        proc.kill(); proc.wait(timeout=5)
                        raise RuntimeError('graceful shutdown timeout')
        def check():
            status, collections = client.call('GET', '/api/v1/collections')
            assert status == 200
            assert next(c['documents'] for c in collections['collections'] if c['id'] == cid) == args.documents
            status, found = client.call('POST', '/api/v1/search', {'q': '電池', 'mode': 'keyword', 'collections': [cid]})
            assert status == 200 and len(found['results']) == min(20, args.documents)
            status, me = client.call('GET', '/api/auth/me')
            assert status == 200 and me['passkeys'] == 1
            return [r['doc_id'] for r in found['results']]
        result = {'documents': args.documents, 'repo': str(args.repo.resolve()),
            'commit': subprocess.check_output(['git', '-C', str(args.repo), 'rev-parse', 'HEAD'], text=True).strip()}
        with running(data) as elapsed:
            result['initial_health_seconds'] = elapsed
            client.login_setup()
            expected = check()
            status, backup = client.call('POST', '/api/backups', {})
            assert status == 200
        with running(data) as elapsed:
            result['restart_health_seconds'] = elapsed
            assert check() == expected
            # The old cookie/CSRF still authorize a write after process restart.
            assert client.call('POST', '/api/v1/collections', {'name': 'restart-proof'})[0] == 200
        restored = root / 'restored'; restored.mkdir()
        original = data / backup['snapshot']['path']
        shutil.copyfile(original, restored / 'library.sqlite3')
        for name in ('settings.json', 'secrets.json'):
            assert (data / name).is_file()
            shutil.copy2(data / name, restored / name)
            assert (data / name).read_bytes() == (restored / name).read_bytes()
        assert Config(restored).get('auth', 'rp_id') == 'synthetic.example.invalid'
        assert Config(restored).get('auth', 'session_hours') == 123
        assert Config(restored).secret('passkey_user_handle') == 'synthetic-stable-handle'
        assert hashlib.sha256(original.read_bytes()).digest() == hashlib.sha256((restored / 'library.sqlite3').read_bytes()).digest()
        with sqlite3.connect(restored / 'library.sqlite3') as db:
            assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        with running(restored) as elapsed:
            result['restored_health_seconds'] = elapsed
            assert check() == expected
            assert client.call('POST', '/api/v1/collections', {'name': 'restore-proof'})[0] == 200
        result.update(session_csrf_preserved=True, counts_search_preserved=True, snapshot_hash_verified=True,
                      single_writer=True, settings_secrets_preserved=True, synthetic_passkey_record_preserved=True, notes='Synthetic Linux process test, not QTS; readiness polling resolution 50ms')
        args.output.write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
