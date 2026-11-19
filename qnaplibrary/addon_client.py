"""PatentBuddy's bounded HTTP clients. No database or Host-internal imports."""
import ipaddress
import json
import os
import re
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

ADDON_ID = 'patent-buddy'


class AddonError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AddonError(502, '接続先のリダイレクトを拒否しました')


def validate_url(url, host=False):
    parsed = urllib.parse.urlsplit(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise AddonError(503, '接続先URLの設定が不正です')
    try:
        address = ipaddress.ip_address(parsed.hostname or '')
        port = parsed.port
    except ValueError:
        raise AddonError(503, '接続先にはIPアドレスを指定してください')
    if host and not address.is_loopback:
        raise AddonError(503, 'ControlDeck Hostは同じPCのloopbackを指定してください')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and address.is_loopback):
        raise AddonError(503, '別端末のResearchDataHubにはHTTPSが必要です')
    if not address.is_loopback and not (address.is_private or address in ipaddress.ip_network('100.64.0.0/10')):
        raise AddonError(503, '接続先はLANまたはTailscaleに限定してください')
    if not port:
        raise AddonError(503, '接続先ポートを指定してください')
    return url.rstrip('/')


def request_json(base, method, path, body=None, headers=None, timeout=20, max_bytes=8 * 1024 * 1024):
    payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=payload, method=method,
        headers=dict({'Content-Type': 'application/json'}, **(headers or {})))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(req, timeout=timeout) as response:
            raw = response.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise AddonError(502, '応答が上限を超えています')
        return json.loads(raw)
    except urllib.error.HTTPError as error:
        error.close()
        status = error.code if error.code in (400, 401, 403, 404, 409, 429, 503) else 502
        raise AddonError(status, '接続先が要求を受け付けませんでした (HTTP %d)' % error.code) from None
    except (OSError, ValueError) as error:
        if isinstance(error, AddonError):
            raise
        raise AddonError(502, '接続先との通信に失敗しました') from None


class AddonClient:
    def __init__(self, data_dir):
        self.path = Path(data_dir) / 'connection.json'
        self.host_url = validate_url(os.environ.get('CONTROL_DECK_HOST_URL', 'http://127.0.0.1:8765'), host=True)

    def settings(self):
        if not self.path.exists():
            from .local_auth import connect
            try:
                return dict(connect(17871), auth_method='local_peer')
            except (OSError, ValueError):
                return {'server_url': 'http://127.0.0.1:17871'}
        if self.path.is_symlink() or self.path.stat().st_mode & 0o077:
            raise AddonError(503, '接続設定は通常ファイル・権限0600で保存してください')
        try:
            value = json.loads(self.path.read_text())
            if not isinstance(value, dict):
                raise ValueError()
            validate_url(value.get('server_url', ''))
            return value
        except (OSError, ValueError):
            raise AddonError(503, '接続設定を確認してください') from None

    def authenticate(self, headers):
        authorization = headers.get('Authorization', '')
        if headers.get('X-Control-Deck-Addon-ID') != ADDON_ID or not authorization.startswith('Bearer ') or len(authorization.split()) != 2:
            raise AddonError(401, 'ControlDeckから開いてください')
        identity = request_json(self.host_url, 'POST', '/api/v1/addon-runtime/token/introspect',
            headers={'Authorization': authorization, 'X-Control-Deck-Addon-ID': ADDON_ID})
        expiry = identity.get('expires_at')
        caps = identity.get('granted_capabilities')
        if (identity.get('active') is not True or identity.get('addon_id') != ADDON_ID
                or not isinstance(identity.get('subject'), str) or not identity['subject']
                or isinstance(expiry, bool) or not isinstance(expiry, int) or not time.time() < expiry <= time.time() + 630
                or not isinstance(caps, list) or not all(isinstance(c, str) for c in caps)):
            raise AddonError(401, 'ControlDeck認証が無効または期限切れです')
        if 'context.read' not in caps:
            raise AddonError(403, '文献閲覧のHost権限がありません')
        return identity

    def knowledge_write_ready(self):
        """Probe the dedicated credential before starting costly inference."""
        config = self.settings()
        if config.get('auth_method') == 'local_peer':
            from .local_auth import connect
            try:
                scoped = connect(17871, 'knowledge_propose')
            except (OSError, ValueError):
                return False
            return isinstance(scoped.get('server_token'), str) and scoped['server_token'].startswith('qlk_')
        token = config.get('knowledge_server_token')
        return isinstance(token, str) and len(token) > 8 and not any(ord(char) in (10, 13) for char in token)

    def knowledge_review_ready(self):
        """A reviewer uses an independent, narrowly scoped RDH credential."""
        config = self.settings()
        if config.get('auth_method') == 'local_peer':
            from .local_auth import connect
            try:
                scoped = connect(17871, 'knowledge_review')
            except (OSError, ValueError):
                return False
            return (isinstance(scoped.get('server_token'), str)
                    and scoped['server_token'].startswith('qlv_'))
        token = config.get('knowledge_review_token')
        return (isinstance(token, str) and len(token) > 8
                and not any(ord(char) in (10, 13) for char in token))

    def knowledge_link_ready(self):
        """Expose only a boolean; never send link credentials to the iframe."""
        config = self.settings()
        if config.get('auth_method') == 'local_peer':
            from .local_auth import connect
            try:
                scoped = connect(17871, 'knowledge_link')
            except (OSError, ValueError):
                return False
            token = scoped.get('server_token')
            return isinstance(token, str) and token.startswith('qle_')
        token = config.get('knowledge_link_token')
        return (isinstance(token, str) and len(token) > 8
                and not any(ord(c) in (10, 13) for c in token))

    def idea_write_ready(self):
        """Only boolean to the iframe; no draft write secrets in browser state."""
        config = self.settings()
        if config.get('auth_method') == 'local_peer':
            from .local_auth import connect
            try:
                scoped = connect(17871, 'idea_write')
            except (OSError, ValueError):
                return False
            token = scoped.get('server_token')
            return isinstance(token, str) and token.startswith('qlj_')
        token = config.get('idea_write_token')
        return (isinstance(token, str) and len(token) > 8
                and '\n' not in token and '\r' not in token)

    def data(self, method, path, body=None):
        config = self.settings()
        local_peer = config.get('auth_method') == 'local_peer'
        knowledge_write = (method == 'POST' and re.fullmatch(
            r'/api/v1/documents/[1-9][0-9]{0,17}/knowledge-proposals', path) is not None)
        review_write = (method == 'POST' and re.fullmatch(
            r'/api/v1/documents/[1-9][0-9]{0,17}/knowledge-proposals/[A-Za-z0-9_-]{1,128}/reviews',
            path) is not None)
        idea_write = ((method == 'POST' and path == '/api/v1/ideas')
                      or (method == 'PUT' and re.fullmatch(
                          r'/api/v1/ideas/idea_[a-f0-9]{32}', path) is not None))
        link_write = (method == 'POST' and (
            re.fullmatch(
                r'/api/v1/documents/[1-9][0-9]{0,17}/knowledge-proposals/'
                r'[A-Za-z0-9_-]{1,128}/links', path) is not None
            or re.fullmatch(
                r'/api/v1/knowledge-links/klink_[a-f0-9]{64}/review', path)
            is not None))
        if local_peer and (
                (method == 'POST' and (path.endswith('/analyses') or
                    path == '/api/v1/pdf-imports' or knowledge_write or
                    review_write or link_write)) or idea_write):
            from .local_auth import connect
            try:
                scope = ('idea_write' if idea_write else
                         'knowledge_link' if link_write else
                         'knowledge_review' if review_write else
                         'knowledge_propose' if knowledge_write else
                         'pdf_import' if path == '/api/v1/pdf-imports' else 'analysis')
                config = connect(17871, scope)
            except (OSError, ValueError):
                raise AddonError(503, 'ResearchDataHubの保存用認証を利用できません') from None
        if idea_write and not local_peer:
            token = config.get('idea_write_token')
            if not token:
                raise AddonError(503, 'Idea保存専用の権限を設定してください')
        elif link_write and not local_peer:
            token = config.get('knowledge_link_token')
            if not token:
                raise AddonError(503, '技術仮説リンク専用権限を設定してください')
        elif review_write and not local_peer:
            token = config.get('knowledge_review_token')
            if not token:
                raise AddonError(503, '知識の人間レビュー専用権限を設定してください')
        elif knowledge_write and not local_peer:
            token = config.get('knowledge_server_token')
            if not token:
                raise AddonError(503, '専用の知識保存権限を設定してください')
        else:
            token = config.get('server_token')
        if not isinstance(token, str) or not token or '\n' in token or '\r' in token:
            raise AddonError(503, 'ResearchDataHubの接続トークンを設定してください')
        return request_json(validate_url(config['server_url']), method, path, body,
                            {'Authorization': 'Bearer ' + token},
                            max_bytes=16 * 1024 * 1024 if path.endswith('/pdf-extraction') else 8 * 1024 * 1024)

    def original_pdf(self, doc_id):
        return self._document_bytes(doc_id, 'original.pdf', 50 * 1024 * 1024, b'%PDF-')

    def image_png(self, doc_id, image_id):
        return self._document_bytes(doc_id, 'images/%d' % image_id, 2 * 1024 * 1024, b'\x89PNG\r\n\x1a\n')

    def image_webp(self, doc_id, image_id):
        from .pdf_webp import webp_size
        raw = self._document_bytes(doc_id, 'images/%d' % image_id, 2 * 1024 * 1024, b'RIFF')
        try:
            webp_size(raw)
        except ValueError:
            raise AddonError(502, '可逆WebPの応答が不正です') from None
        return raw

    def _document_bytes(self, doc_id, suffix, limit, signature):
        config = self.settings()
        token = config.get('server_token')
        if not isinstance(token, str) or not token or '\r' in token or '\n' in token:
            raise AddonError(503, 'ResearchDataHubの認証設定を確認してください')
        url = validate_url(config['server_url']) + '/api/v1/documents/%d/%s' % (doc_id, suffix)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token}), timeout=30) as response:
                raw = response.read(limit + 1)
            if len(raw) > limit or not raw.startswith(signature):
                raise AddonError(502, '資料の応答が不正です')
            return raw
        except urllib.error.HTTPError as error:
            error.close()
            raise AddonError(error.code if error.code in (401, 403, 404) else 502, '資料を取得できません') from None
        except OSError:
            raise AddonError(502, '資料との通信に失敗しました') from None

    def status(self):
        config = self.settings()
        url = validate_url(config['server_url'])
        try:
            health = request_json(url, 'GET', '/api/health')
        except AddonError:
            health = {'ok': False}
        return {'addon': {'name': 'PatentBuddy', 'role': '特許分析アドオン'},
                'server': {'name': 'ResearchDataHub', 'role': '資料保存・検索サーバー', 'url': url,
                           'version': health.get('version'), 'reachable': health.get('ok') is True,
                           'setup_required': health.get('setup_required', True),
                           'token_configured': bool(config.get('server_token')),
                           'knowledge_review_available': self.knowledge_review_ready(),
                           'knowledge_link_available': self.knowledge_link_ready(),
                           'idea_write_available': self.idea_write_ready(),
                           'auth_method': config.get('auth_method', 'manual')}}
