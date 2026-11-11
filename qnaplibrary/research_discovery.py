"""Bounded official OPS bibliography discovery; never acquires PDFs."""
import base64
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .connectors import ConnectorError, _epo_docs
from .research_selection import snapshot

_lock = threading.Lock()
_last_call = 0.0
MAX_BYTES = 8 * 1024 * 1024
BASE = 'https://ops.epo.org/3.2/'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ConnectorError('OPS redirect refused')


def _request(path, headers, data=None):
    request = urllib.request.Request(BASE + path, headers=headers, data=data)
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=30) as response:
            chunks = []
            received = 0
            deadline = time.monotonic() + 30
            while True:
                if time.monotonic() >= deadline:
                    raise ConnectorError('OPS response deadline exceeded')
                chunk = response.read1(min(65536, MAX_BYTES + 1 - received))
                if not chunk:
                    break
                chunks.append(chunk)
                received += len(chunk)
                if received > MAX_BYTES:
                    raise ConnectorError('OPS response exceeds size limit')
            raw = b''.join(chunks)
        if len(raw) > MAX_BYTES:
            raise ConnectorError('OPS response exceeds size limit')
        return json.loads(raw)
    except (OSError, ValueError, urllib.error.URLError):
        # Never echo provider bodies, credentials, or query URLs into errors.
        raise ConnectorError('OPS request failed; check service availability and credentials') from None


def search(query, limit, key, secret):
    global _last_call
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise ConnectorError('search expression must be 1..2000 characters')
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ConnectorError('candidate limit must be 1..100')
    if not key or not secret:
        raise ConnectorError('EPO OPS credentials are not configured')
    if not _lock.acquire(blocking=False):
        raise ConnectorError('OPS discovery is busy; retry later')
    try:
        time.sleep(max(0, 1.0 - (time.monotonic() - _last_call)))
        basic = base64.b64encode((key + ':' + secret).encode()).decode()
        auth = _request('auth/accesstoken', {'Authorization': 'Basic ' + basic,
                        'Content-Type': 'application/x-www-form-urlencoded'}, b'grant_type=client_credentials')
        token = auth.get('access_token') if isinstance(auth, dict) else None
        if not isinstance(token, str) or not token or len(token) > 8192 or '\r' in token or '\n' in token:
            raise ConnectorError('OPS returned invalid authentication data')
        data = _request('rest-services/published-data/search/biblio?' + urllib.parse.urlencode({'q': query}),
                        {'Authorization': 'Bearer ' + token, 'Accept': 'application/json', 'X-OPS-Range': '1-%d' % limit})
        try:
            root = data['ops:world-patent-data']['ops:biblio-search']
            raw_total = root['@total-result-count']
            if not isinstance(raw_total, (str, int)) or isinstance(raw_total, bool) or not str(raw_total).isdigit():
                raise ValueError()
            total = int(raw_total)
            if total < 0:
                raise ValueError()
            docs = _epo_docs(data)
            if len(docs) > limit or len(docs) > total or (total and not docs):
                raise ValueError()
            records = []
            for doc in docs:
                meta = doc['meta']
                records.append(dict(publication=meta['publication_number'], language=meta['language'],
                                    family=('epo:' + str(meta['family_id'])) if meta['family_id'] else None,
                                    title=doc['title'], sources=['epo_ops'],
                                    cells=['IPC:' + ipc for ipc in meta['ipc'] if ipc]))
            snapshot(records)  # Reject malformed/oversize results before any persistence.
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ConnectorError('OPS returned unsupported bibliography; nothing saved') from None
        return dict(records=records, provider='epo_ops', fetched=len(records),
                    reported_total=total, truncated=total > len(records))
    finally:
        _last_call = time.monotonic()
        _lock.release()
