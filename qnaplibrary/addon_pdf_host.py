"""Host-owned file grant and CPU/RAM lease for the local PDF worker."""
import http.client
import os
import re
import time
import urllib.parse

from .addon_client import AddonError
from .addon_host import BASE
from .addon_compute_host import ComputeHostSession, HOST_BYTES
from .pdf_extract import MAX_PDF_BYTES


class PDFHostSession(ComputeHostSession):
    required = frozenset(('context.read', 'jobs.write', 'files.pick', 'resources.acquire'))
    capability_message = 'ControlDeckでファイル選択・ジョブ・資源利用の権限を有効にしてください'

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
