"""Explicit, bounded PDF retrieval from the official EPO publication REST API."""
import re
import threading
import time
import urllib.error
import urllib.request
from .connectors import ConnectorError

BASE = 'https://data.epo.org/publication-server/rest/v1.2/patents/'
MAX_BYTES = 16 * 1024 * 1024
RATE = 100000  # bytes/sec, below EPO's approximately 1 Mbit/sec shared service limit
_lock = threading.Lock()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ConnectorError('取得元からの転送を拒否しました')


def publication(value):
    if not isinstance(value, str) or len(value)>40:
        raise ConnectorError('欧州公報番号を指定してください（例: EP1004359B1）')
    value = re.sub(r'[ -]', '', value).upper()
    match = re.fullmatch(r'EP([0-9]{7})(?:NW)?([AB][1-9])', value)
    if not match:
        raise ConnectorError('欧州公報番号を指定してください（例: EP1004359B1）')
    return 'EP'+match[1]+'NW'+match[2]


def download(value):
    number = publication(value)
    if not _lock.acquire(blocking=False):
        raise ConnectorError('公報を取得中です。完了後に再度実行してください')
    try:
        started = time.monotonic()
        req = urllib.request.Request(BASE+number+'/document.pdf', headers={
            'User-Agent':'PatentBuddy/official-publication-download', 'Accept':'application/pdf', 'Accept-Encoding':'identity'})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(req, timeout=20) as response:
            length = response.headers.get('Content-Length')
            if length and (not length.isdigit() or int(length)>MAX_BYTES):
                raise ConnectorError('公報PDFが16MiBの上限を超えています')
            parts=[]; size=0
            while True:
                if time.monotonic()-started>180:
                    raise ConnectorError('公報取得の時間上限を超えました')
                block=response.read(min(65536, MAX_BYTES+1-size))
                if not block:break
                parts.append(block);size+=len(block)
                if size>MAX_BYTES:raise ConnectorError('公報PDFが16MiBの上限を超えています')
                delay=size/RATE-(time.monotonic()-started)
                if delay>0:time.sleep(delay)
            raw=b''.join(parts)
            if not raw.startswith(b'%PDF-') or (length and len(raw)!=int(length)):
                raise ConnectorError('完全なPDF応答を確認できません')
        return number.replace('NW','')+'.pdf', raw
    except urllib.error.HTTPError as error:
        raise ConnectorError('EPOの公報取得に失敗しました（HTTP %d）' % error.code) from None
    except (urllib.error.URLError, OSError):
        raise ConnectorError('EPOへ接続できませんでした') from None
    finally:
        _lock.release()
