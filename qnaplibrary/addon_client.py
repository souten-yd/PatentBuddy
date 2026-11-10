"""PatentBuddy's bounded HTTP clients. No database or Host-internal imports."""
import ipaddress
import json
import os
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


def request_json(base, method, path, body=None, headers=None, timeout=20):
    payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=payload, method=method,
        headers=dict({'Content-Type': 'application/json'}, **(headers or {})))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(req, timeout=timeout) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise AddonError(502, '応答が上限を超えています')
        return json.loads(raw)
    except urllib.error.HTTPError as error:
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

    def data(self, method, path, body=None):
        config = self.settings()
        token = config.get('server_token')
        if not isinstance(token, str) or not token or '\n' in token or '\r' in token:
            raise AddonError(503, 'ResearchDataHubの接続トークンを設定してください')
        return request_json(validate_url(config['server_url']), method, path, body,
                            {'Authorization': 'Bearer ' + token})

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
                           'auth_method': config.get('auth_method', 'manual')}}
