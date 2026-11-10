"""Bounded ControlDeck AI/Jobs client. Credentials stay in process memory."""
import http.client
import json
import socket
import urllib.parse
import re
import threading
import time

from .addon_client import ADDON_ID, AddonError, request_json


REQUIRED = frozenset(('context.read', 'ai.inference', 'jobs.write'))
BASE = '/api/v1/addon-runtime/' + ADDON_ID


def owner_key(identity):
    actor = identity.get('actor_subject')
    if isinstance(actor, str) and re.fullmatch(r'user:[1-9][0-9]*', actor):
        return actor
    subject = identity.get('subject', '')
    if isinstance(subject, str) and re.fullmatch(r'[1-9][0-9]*', subject):
        return 'user:' + subject
    raise AddonError(403, '操作の所有者を確認できません')


class HostSession:
    def __init__(self, client, headers):
        self.client = client
        self.lock = threading.RLock()
        self.headers = {'Authorization': headers.get('Authorization', ''),
                        'X-Control-Deck-Addon-ID': ADDON_ID}
        self.identity = client.authenticate(self.headers)
        self.owner = owner_key(self.identity)
        self.job_id = None
        self.transport = None
        self.aborted = threading.Event()
        self.require_capabilities()

    def require_capabilities(self):
        if not REQUIRED.issubset(self.identity['granted_capabilities']):
            raise AddonError(403, 'ControlDeckでAIとジョブの権限を有効にしてください')

    def call(self, method, path, body=None, timeout=20):
        with self.lock:
            headers = dict(self.headers)
        return request_json(self.client.host_url, method, BASE + path, body, headers, timeout=timeout)

    def local_available(self):
        caps = self.call('GET', '/ai/capabilities').get('text.generate', {})
        option = caps.get('request_options', {}).get('local_only', {})
        return (caps.get('available') is True and caps.get('local_only_available') is True
                and option.get('supported') is True)

    def complete(self, messages):
        # An old Host must reject BEFORE any source text is sent to its AI API.
        if not self.local_available():
            raise AddonError(503, 'Hostのローカル限定AIを利用できません。モデルとHostの更新を確認してください')
        result = self.call('POST', '/ai/complete', {
            'capability': 'text.generate', 'local_only': True, 'messages': messages,
            'temperature': 0.0, 'max_tokens': 4096, 'timeout_seconds': 300,
        }, timeout=310)
        if (result.get('execution_policy') != 'local_only' or not isinstance(result.get('content'), str)
                or not result['content'].strip() or len(result['content']) > 100000):
            raise AddonError(502, 'ローカルAIの応答を検証できません')
        return result['content']

    def create_job(self):
        if self.job_id is not None:
            raise AddonError(409, 'ジョブは作成済みです')
        result = self.call('POST', '/jobs', {'title': 'PatentBuddy 文献分析', 'detached': True})
        job_id = result.get('job', {}).get('id')
        if result.get('created') is not True or not isinstance(job_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', job_id):
            raise AddonError(502, 'Hostジョブの作成を確認できません')
        self.job_id = job_id
        self._replace_credential(result)
        return job_id

    def _replace_credential(self, response):
        token = response.get('access_token')
        if not isinstance(token, str) or not token or '\r' in token or '\n' in token:
            raise AddonError(502, 'Hostジョブ認証を確認できません')
        headers = {'Authorization': 'Bearer ' + token, 'X-Control-Deck-Addon-ID': ADDON_ID}
        identity = self.client.authenticate(headers)
        if (identity['subject'] != 'job:' + self.job_id
                or identity.get('actor_subject', self.owner) != self.owner
                or not REQUIRED.issubset(identity['granted_capabilities'])):
            raise AddonError(403, 'Hostジョブの認証範囲が一致しません')
        with self.lock:
            self.headers = headers
            self.identity = identity

    def heartbeat(self):
        if not self.job_id:
            raise AddonError(409, 'Hostジョブがありません')
        if self.identity['expires_at'] - time.time() < 90:
            self._replace_credential(self.call('POST', '/jobs/' + self.job_id + '/credential/refresh', {}))
        current = self.client.authenticate(dict(self.headers))
        if current['subject'] != 'job:' + self.job_id or not REQUIRED.issubset(current['granted_capabilities']):
            raise AddonError(403, 'Hostジョブの権限が変更されました')
        state = self.call('GET', '/jobs/' + self.job_id + '/control')
        if state.get('host_job_id') != self.job_id:
            raise AddonError(403, 'Hostジョブの認証範囲が一致しません')
        return state

    def progress(self, phase, completed, total):
        return self.call('PATCH', '/jobs/' + self.job_id, {
            'phase': phase, 'progress': {'completed': completed, 'total': total}})

    def finish(self, status, result=None):
        # Result contains source/result IDs only, never document text or prompts.
        if status not in ('succeeded', 'failed', 'canceled'):
            raise AddonError(400, 'ジョブ状態が不正です')
        return self.call('POST', '/jobs/' + self.job_id + '/terminal/reconcile', {
            'status': status, 'result': result,
            'error': '文献分析を完了できませんでした' if status == 'failed' else None})


    def abort(self):
        self.aborted.set()
        with self.lock:
            transport = self.transport
        if transport is not None:
            try:
                transport.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def stream(self, messages):
        if not self.local_available():
            raise AddonError(503, 'Hostのローカル限定AIを利用できません')
        if self.aborted.is_set():
            raise AddonError(409, '分析はキャンセルされました')
        url = urllib.parse.urlsplit(self.client.host_url)
        cls = http.client.HTTPSConnection if url.scheme == 'https' else http.client.HTTPConnection
        connection = cls(url.hostname, url.port, timeout=310)
        content = []
        length = 0
        try:
            connection.connect()
            with self.lock:
                if self.aborted.is_set():
                    raise AddonError(409, "分析はキャンセルされました")
                self.transport = connection.sock
                headers = dict(self.headers, **{'Content-Type': 'application/json'})
            body = json.dumps({'capability': 'text.generate', 'local_only': True, 'messages': messages,
                               'max_tokens': 4096, 'timeout_seconds': 300, 'temperature': 0.0}).encode()
            connection.request('POST', BASE + '/ai/stream', body=body, headers=headers)
            response = connection.getresponse()
            if response.status != 200:
                raise AddonError(502, 'HostのローカルAI要求が拒否されました')
            done = False
            while True:
                line = response.readline(65537)
                if not line:
                    break
                if len(line) > 65536:
                    raise AddonError(502, 'AI応答が上限を超えました')
                if not line.startswith(b'data: '):
                    continue
                event = json.loads(line[6:])
                if event.get('type') == 'error':
                    raise AddonError(502, 'ローカルAIの生成に失敗しました')
                if event.get('type') == 'done':
                    done = True
                    break
                if event.get('type') == 'content':
                    value = event.get('content')
                    if not isinstance(value, str):
                        raise AddonError(502, 'AI応答の形式が不正です')
                    length += len(value)
                    if length > 100000:
                        raise AddonError(502, 'AI応答が上限を超えました')
                    content.append(value)
            answer = ''.join(content)
            if not done or not answer.strip():
                raise AddonError(502, 'AI応答が完了していません')
            return answer
        except (OSError, ValueError, http.client.HTTPException):
            raise AddonError(502, 'ローカルAIとの接続が終了しました') from None
        finally:
            with self.lock:
                self.transport = None
            connection.close()
