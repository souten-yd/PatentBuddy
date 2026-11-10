"""Linux same-UID authentication. No TCP bootstrap and no persistent secrets."""
import json
import os
from pathlib import Path
import socket
import stat
import struct
import threading


def peer_uid(sock):
    return struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]


def socket_path(port):
    if not hasattr(socket, 'SO_PEERCRED') or os.getuid() == 0:
        raise OSError('local authentication requires an unprivileged Linux user')
    base = Path('/run/user') / str(os.getuid())
    check_private(base, directory=True)
    directory = base / 'researchdatahub'
    directory.mkdir(mode=0o700, exist_ok=True)
    check_private(directory, directory=True)
    return directory / ('%d.sock' % port)


def check_private(path, directory=False):
    info = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISSOCK
    if info.st_uid != os.getuid() or info.st_mode & 0o077 or not expected(info.st_mode):
        raise OSError('unsafe local authentication endpoint')


class LocalAuthServer:
    def __init__(self, auth, port):
        self.auth = auth
        self.port = port
        self.path = socket_path(port)
        # A process lock prevents a second server from removing a live endpoint.
        import fcntl
        fd = os.open(str(self.path) + '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        self.lock = os.fdopen(fd, 'rb')
        try:
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or info.st_mode & 0o077 or not stat.S_ISREG(info.st_mode):
                raise OSError('unsafe local authentication lock')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.path.exists() or self.path.is_symlink():
                check_private(self.path)
                self.path.unlink()
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.bind(str(self.path))
            self.path.chmod(0o600)
            self.sock.listen(8)
            self.sock.settimeout(0.25)
        except Exception:
            self.lock.close()
            raise
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while not self.stopping.is_set():
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                try:
                    conn.settimeout(1)
                    if peer_uid(conn) != os.getuid():
                        continue
                    token = self.auth.local_token()
                    if token:
                        conn.sendall(json.dumps({'server_url': 'http://127.0.0.1:%d' % self.port,
                                                 'server_token': token}).encode() + b'\n')
                except OSError:
                    pass

    def close(self):
        self.stopping.set()
        self.sock.close()
        self.thread.join(timeout=2)
        self.path.unlink(missing_ok=True)
        self.lock.close()


def connect(port):
    path = socket_path(port)
    check_private(path)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(2)
        sock.connect(str(path))
        if peer_uid(sock) != os.getuid():
            raise OSError('local server user mismatch')
        raw = b''
        while not raw.endswith(b'\n'):
            part = sock.recv(4096 - len(raw))
            if not part or len(raw) + len(part) >= 4096:
                raise OSError('invalid local authentication response')
            raw += part
    value = json.loads(raw)
    if value.get('server_url') != 'http://127.0.0.1:%d' % port or not isinstance(value.get('server_token'), str):
        raise OSError('invalid local server identity')
    return value
