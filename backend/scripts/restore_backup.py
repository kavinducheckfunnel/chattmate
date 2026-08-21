#!/usr/bin/env python3
"""
Copyright 2024-2026 ChatterMate

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

Decrypt a .cmbk platform backup into a plain .tar.gz.

Deliberately standalone: it imports nothing from the application, so it still
runs on a laptop, in a rescue shell, or from a checkout of this repo when the
server the backup came from no longer exists. That is the only situation in
which anyone ever needs it.

    ENCRYPTION_KEY=... python restore_backup.py backup.cmbk --out backup.tar.gz
    tar xzf backup.tar.gz
    pg_restore --clean --if-exists --no-owner --no-acl -d "$DATABASE_URL" database.dump
"""

import argparse
import hashlib
import hmac
import os
import sys

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
except ImportError:
    sys.exit("This script needs the 'cryptography' package:  pip install cryptography")

MAGIC = b"CMBK1\n"
SALT_BYTES = 16
IV_BYTES = 16
MAC_BYTES = 32
CHUNK = 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Decrypt a .cmbk ChatterMate platform backup into a .tar.gz")
    parser.add_argument("archive", help="the .cmbk file")
    parser.add_argument("--out", "-o", help="output .tar.gz (default: alongside the input)")
    parser.add_argument("--key", help="ENCRYPTION_KEY (default: read from the environment)")
    args = parser.parse_args()

    secret = args.key or os.environ.get("ENCRYPTION_KEY", "")
    if not secret:
        return fail("Set ENCRYPTION_KEY in the environment, or pass --key.\n"
                    "It is the same value the server used; without it this file "
                    "cannot be opened by anyone, including you.")

    out_path = args.out or (args.archive[:-5] if args.archive.endswith(".cmbk")
                            else args.archive) + ".tar.gz"
    total = os.path.getsize(args.archive)
    if total < len(MAGIC) + SALT_BYTES + IV_BYTES + MAC_BYTES:
        return fail("That file is too small to be a ChatterMate backup.")

    with open(args.archive, "rb") as source:
        if source.read(len(MAGIC)) != MAGIC:
            return fail("That is not a ChatterMate backup archive "
                        "(or it was produced by a newer version).")
        salt = source.read(SALT_BYTES)
        iv = source.read(IV_BYTES)

        material = HKDF(algorithm=hashes.SHA256(), length=64, salt=salt,
                        info=b"chattermate-platform-backup-v1").derive(secret.encode())
        decryptor = Cipher(algorithms.AES(material[:32]), modes.CTR(iv)).decryptor()
        mac = hmac.new(material[32:], digestmod=hashlib.sha256)
        mac.update(MAGIC + salt + iv)

        # The trailing MAC covers the whole ciphertext, so it can only be checked
        # once everything has been read. The output is written as we go — a
        # multi-gigabyte archive will not fit in memory — and deleted if the
        # check fails, so a tampered or truncated file never leaves a
        # half-restored tree behind that looks usable.
        remaining = total - len(MAGIC) - SALT_BYTES - IV_BYTES - MAC_BYTES
        ok = False
        try:
            with open(out_path, "wb") as target:
                while remaining > 0:
                    block = source.read(min(CHUNK, remaining))
                    if not block:
                        return fail("The archive ended early — the file is truncated.")
                    remaining -= len(block)
                    mac.update(block)
                    target.write(decryptor.update(block))
                target.write(decryptor.finalize())
            expected = source.read(MAC_BYTES)
            if not hmac.compare_digest(mac.digest(), expected):
                return fail("Integrity check failed. Either ENCRYPTION_KEY is wrong, "
                            "or this file was corrupted or modified in transit.")
            ok = True
        finally:
            if not ok:
                try:
                    os.remove(out_path)
                except OSError:
                    pass

    print(f"Wrote {out_path} ({os.path.getsize(out_path):,} bytes)")
    print("Next:  tar xzf " + out_path)
    return 0


def fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
