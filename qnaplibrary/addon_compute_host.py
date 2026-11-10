"""Host-owned CPU/RAM lease shared by bounded local computation workers."""
import re
import time

from .addon_client import AddonError
from .addon_host import HostSession, REQUIRED

HOST_BYTES = 2 * 1024 ** 3


class ComputeHostSession(HostSession):
    required = REQUIRED | frozenset(('resources.acquire',))
    capability_message = 'ControlDeckでAI・ジョブ・資源利用の権限を有効にしてください'

    def __init__(self, client, headers):
        super().__init__(client, headers)
        self.request_id = None
        self.lease_id = None
        self._last_progress = None
        self.resource_changed = lambda: None

    def progress(self, phase, completed, total):
        # Host external Jobs allow at most 2Hz; fast worker batches can
        # finish in milliseconds. Coalesce intermediate reports to 1Hz.
        now = time.monotonic()
        if self._last_progress is not None and now - self._last_progress < 1:
            if completed != total:
                return None
            if self.aborted.wait(1 - (now - self._last_progress)):
                raise AddonError(409, "処理を中断しました")
        result = super().progress(phase, completed, total)
        self._last_progress = time.monotonic()
        return result

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
        self.resource_changed()
        deadline = time.monotonic() + 65
        while True:
            if self.aborted.is_set():
                raise AddonError(409, '処理を中断しました')
            if value.get('job_id') != self.job_id or value.get('owner') != 'addon:' + self.identity['addon_id']:
                raise AddonError(403, 'Host資源の所有者が一致しません')
            if value.get('state') == 'granted':
                lease = value.get('lease_id')
                if not isinstance(lease, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', lease):
                    raise AddonError(502, 'Host資源leaseを確認できません')
                self.lease_id = lease
                self.resource_changed()
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
            try:
                value = self.call('POST', '/resources/leases/' + self.lease_id + '/release', {})
            except AddonError as error:
                if error.status != 409:
                    raise
                value = self.call('GET', '/resources/leases/' + self.lease_id)
            if value.get('lease_id') != self.lease_id or value.get('state') not in ('released', 'expired', 'canceled') or value.get('job_id') != self.job_id:
                raise AddonError(502, 'Host資源の解放を確認できません')
            self.lease_id = None
        if self.request_id:
            self.call('DELETE', '/resources/requests/' + self.request_id)
            self.request_id = None

