"""Host-owned file grant and CPU/RAM lease for the local PDF worker."""
import http.client
import os
import re
import time
import urllib.parse

from .addon_client import AddonError
from .addon_host import HostSession, BASE
from .pdf_extract import MAX_PDF_BYTES

HOST_BYTES = 2 * 1024 ** 3


class PDFHostSession(HostSession):
    required = frozenset(('context.read', 'jobs.write', 'files.pick', 'resources.acquire'))

    def __init__(self, client, headers):
        super().__init__(client, headers)
        self.request_id = None
        self.lease_id = None
        self._last_progress = None

    def progress(self, phase, completed, total):
        # Host external Jobs allow at most 2Hz; fast native PDF pages can
        # finish in milliseconds. Coalesce intermediate reports to 1Hz.
        now = time.monotonic()
        if self._last_progress is not None and now - self._last_progress < 1:
            if completed != total:
                return None
            if self.aborted.wait(1 - (now - self._last_progress)):
                raise AddonError(409, "PDF処理を中断しました")
        result = super().progress(phase, completed, total)
        self._last_progress = time.monotonic()
        return result

    def grant(self, grant_id):
        if not isinstance(grant_id, str) or not re.fullmatch(r'grant:[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', grant_id):
            raise AddonError(400, 'ControlDeckでPDFを選択してください')
        value = self.call('GET', '/grants/' + grant_id)
        size = value.get('size')
        if (value.get('grant_id') != grant_id or value.get('kind') != 'read'
                or type(size) is not int or not 5 <= size <= MAX_PDF_BYTES
                or not isinstance(value.get('name'), str) or not value['name'].lower().endswith('.pdf')
                or not isinstance(value.get('expires_at'), (int, float)) or value['expires_at'] <= time.time()):
            raise AddonError(400, '50MiB以内の有効なPDF読取権限が必要です')
        return value

    def acquire_cpu(self):
        if not self.job_id:
            raise AddonError(409, 'Hostジョブが必要です')
        value = self.call('POST', '/resources/requests', {
            'job_id': self.job_id, 'device': 'auto', 'preferred_devices': ['host'],
            'host_bytes': HOST_BYTES,
            'vram': {'resident_bytes': 0, 'execution_peak_bytes': 0,
                     'cold_load_peak_bytes': 0, 'headroom_bytes': 0, 'confidence': 'estimated'},
            'compute_mode': 'shared-safe', 'class': 'interactive', 'priority': 0,
            'max_wait_sec': 60, 'estimated_runtime_sec': 120, 'on_insufficient': 'queue'})
        identifier = value.get('request_id')
        if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', identifier):
            raise AddonError(502, 'Host資源要求を確認できません')
        self.request_id = identifier
        deadline = time.monotonic() + 65
        while True:
            if self.aborted.is_set():
                raise AddonError(409, 'PDF処理を中断しました')
            if value.get('job_id') != self.job_id or value.get('owner') != 'addon:' + self.identity['addon_id']:
                raise AddonError(403, 'Host資源の所有者が一致しません')
            if value.get('state') == 'granted':
                lease = value.get('lease_id')
                if not isinstance(lease, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', lease):
                    raise AddonError(502, 'Host資源leaseを確認できません')
                self.lease_id = lease
                if value.get('device_id') != 'host' or (type(value.get('granted_bytes')) is not int or value['granted_bytes'] < HOST_BYTES):
                    raise AddonError(503, 'CPU用のHost資源を確保できません')
                active = self.call('POST', '/resources/leases/' + lease + '/activate', {})
                self._check_lease(active)
                return
            if value.get('state') != 'waiting' or time.monotonic() > deadline:
                raise AddonError(503, 'Host資源待ちが終了しました。再実行してください')
            self.aborted.wait(.5)
            value = self.call('GET', '/resources/requests/' + identifier)

    def _check_lease(self, value):
        if (value.get('lease_id') != self.lease_id or value.get('device_id') != 'host'
                or value.get('job_id') != self.job_id or value.get('state') != 'active'
                or value.get('owner') != 'addon:' + self.identity['addon_id'] or (type(value.get('reserved_bytes')) is not int or value['reserved_bytes'] < HOST_BYTES)):
            raise AddonError(503, 'HostのCPU資源leaseが無効です')

    def heartbeat(self):
        state = super().heartbeat()
        if self.lease_id:
            self._check_lease(self.call('POST', '/resources/leases/' + self.lease_id + '/renew', {}))
        return state

    def release_cpu(self):
        # Release must happen before terminal Job reconciliation. Expiry remains
        # the Host fallback if credentials were revoked or the Host is offline.
        if self.lease_id:
            value = self.call('POST', '/resources/leases/' + self.lease_id + '/release', {})
            if value.get('lease_id') != self.lease_id or value.get('state') != 'released' or value.get('job_id') != self.job_id:
                raise AddonError(502, 'Host資源の解放を確認できません')
            self.lease_id = None
        if self.request_id:
            self.call('DELETE', '/resources/requests/' + self.request_id)
            self.request_id = None

    def download(self, grant_id, destination):
        metadata = self.grant(grant_id)
        url = urllib.parse.urlsplit(self.client.host_url)
        cls = http.client.HTTPSConnection if url.scheme == 'https' else http.client.HTTPConnection
        connection = cls(url.hostname, url.port, timeout=30)
        try:
            connection.connect()
            with self.lock:
                if self.aborted.is_set():
                    raise AddonError(409, 'PDF処理を中断しました')
                self.transport = connection.sock
                headers = dict(self.headers)
            connection.request('GET', BASE + '/grants/' + grant_id + '/content', headers=headers)
            response = connection.getresponse()
            if response.status != 200 or response.getheader('Content-Length') != str(metadata['size']):
                raise AddonError(502, '選択したPDFを取得できません')
            size = 0
            fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                while True:
                    if self.aborted.is_set():
                        raise AddonError(409, 'PDF処理を中断しました')
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > metadata['size'] or size > MAX_PDF_BYTES:
                        raise AddonError(413, 'PDFが上限を超えました')
                    stream.write(chunk)
            if size != metadata['size']:
                raise AddonError(502, 'PDFの受信が完了していません')
            return metadata
        except (OSError, http.client.HTTPException):
            raise AddonError(502, 'PDFの転送が中断されました') from None
        finally:
            with self.lock:
                self.transport = None
            connection.close()
