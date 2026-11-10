#!/usr/bin/env python3
"""Sign a reviewed Feature archive using an EXISTING publisher key and OpenSSL.

No key generation, upload, or private key contents enter the bundle/output.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--private-key', type=Path, required=True)
    args = parser.parse_args()
    expected = 'control-deck-patent-buddy-%s-linux-x86_64.tar.gz' % args.version
    if args.artifact.name != expected or not args.private_key.is_file() or args.private_key.stat().st_mode & 0o077:
        parser.error('artifact identity or existing private key permissions are invalid')
    manifest = {'schema_version': 1, 'feature_id': 'patent-buddy', 'version': args.version,
                'platform': 'linux', 'architecture': 'x86_64', 'artifact_name': args.artifact.name,
                'sha256': hashlib.sha256(args.artifact.read_bytes()).hexdigest(),
                'size_bytes': args.artifact.stat().st_size}
    canonical = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
    with tempfile.TemporaryDirectory(prefix='pb-sign-') as tmp:
        root = Path(tmp); message = root / 'manifest'; signature = root / 'signature'; public = root / 'public.pem'
        message.write_bytes(canonical)
        commands = [
            ['openssl', 'pkeyutl', '-sign', '-rawin', '-inkey', str(args.private_key), '-in', str(message), '-out', str(signature)],
            ['openssl', 'pkey', '-in', str(args.private_key), '-pubout', '-out', str(public)],
            ['openssl', 'pkeyutl', '-verify', '-pubin', '-inkey', str(public), '-rawin', '-in', str(message), '-sigfile', str(signature)]]
        for command in commands:
            subprocess.run(command, check=True, stdin=subprocess.DEVNULL, capture_output=True)
        signed = signature.read_bytes()
        if len(signed) != 64:
            parser.error('publisher key must produce an Ed25519 signature')
    args.artifact.with_name(args.artifact.name + '.manifest.json').write_bytes(canonical)
    args.artifact.with_name(args.artifact.name + '.manifest.json.sig').write_text(base64.b64encode(signed).decode() + '\n')
    print(json.dumps(dict(manifest, signature_verified=True)))


if __name__ == '__main__':
    main()
