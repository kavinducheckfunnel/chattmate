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

Platform backups: build the archive, and put it somewhere that is not this
server.

Two things make this more than a `pg_dump` wrapper.

The first is what a restore actually needs. Attachments and knowledge documents
live on disk, not in Postgres, so a database-only restore comes back looking
complete and is not — every message with a file in it points at something that
no longer exists. And tenant API keys are stored as ciphertext under
ENCRYPTION_KEY, so a dump restored without that key is unreadable. The archive
therefore carries both the dump and the uploads tree, and ships a RESTORE file
that says in plain words that the key is the operator's to keep somewhere else.

The second is that the archive is every tenant's data in one file, about to be
copied to a third party's storage. It is encrypted here, before it leaves the
process, so what lands in OneDrive is ciphertext — a compromised Microsoft
account, a mis-shared folder, or a subpoena served on the wrong party yields
nothing readable. Encryption is streaming rather than whole-file because these
archives run to gigabytes and holding one in memory would OOM the container.
"""

import asyncio
import hashlib
import hmac
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO, Optional
from urllib.parse import quote, urlparse

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logger import get_logger
from app.core.security import decrypt_api_key
from app.models.platform_backup import (BackupContents, BackupMethod,
                                        BackupStatus, PlatformBackupRun,
                                        PlatformBackupSettings)

logger = get_logger(__name__)


class BackupError(Exception):
    """Anything the operator needs to read on screen rather than in a log."""


# Archive format marker. Versioned so a future change to the cipher can be
# detected by the restore script instead of producing garbage plaintext.
MAGIC = b"CMBK1\n"
SALT_BYTES = 16
IV_BYTES = 16
MAC_BYTES = 32
# Multiple of 320 KiB — Graph rejects upload chunks that are not, except the
# final one. 10 units keeps requests near 3 MB, comfortably under the timeout
# on a slow uplink while still finishing a 2 GB archive in ~600 requests.
GRAPH_CHUNK_BYTES = 10 * 320 * 1024
GRAPH_SMALL_FILE_LIMIT = 4 * 1024 * 1024
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
LOGIN_BASE = "https://login.microsoftonline.com"
# A prepared download is a complete copy of the platform sitting on disk. It is
# deleted on delivery; this is the backstop for the operator who never clicks.
DOWNLOAD_TTL = timedelta(hours=2)
PG_DUMP_TIMEOUT = 60 * 60
HTTP_TIMEOUT = httpx.Timeout(120.0, connect=30.0)

RESTORE_NOTES = """ChatterMate platform backup
===========================

This archive was produced by the operator console (Backups & recovery).

Contents
--------
  database.dump   Postgres custom-format dump  (pg_restore)
  uploads/        Attachments, knowledge documents and images
  RESTORE.txt     This file

Restoring
---------
  1. Decrypt:  python backend/scripts/restore_backup.py <file> --out backup.tar.gz
     The decryption key is derived from ENCRYPTION_KEY, so that variable must be
     set in the environment where you run the script.
  2. Unpack:   tar xzf backup.tar.gz
  3. Database: pg_restore --clean --if-exists --no-owner --no-acl \\
                          -d "$DATABASE_URL" database.dump
  4. Files:    copy uploads/ back to the application's uploads directory.

Keep ENCRYPTION_KEY somewhere else
----------------------------------
Tenant provider keys and channel credentials are stored as ciphertext under
ENCRYPTION_KEY, and this archive is encrypted with a key derived from it. If
that value is lost, this file cannot be opened and a database restored from it
by other means would still be unreadable. Store it in a password manager, not
only in backend/.env on the server this is a backup of.
"""


# --------------------------------------------------------------- encryption


def _derive_keys(salt: bytes) -> tuple[bytes, bytes]:
    """Two independent 32-byte keys from ENCRYPTION_KEY.

    Separate keys for the cipher and the MAC: reusing one key for both is the
    classic way an encrypt-then-MAC construction stops being sound.
    """
    secret = (settings.ENCRYPTION_KEY or "").encode()
    if not secret:
        raise BackupError(
            "ENCRYPTION_KEY is not set on this server, so a backup cannot be "
            "encrypted. Set it before creating a backup.")
    material = HKDF(algorithm=hashes.SHA256(), length=64, salt=salt,
                    info=b"chattermate-platform-backup-v1").derive(secret)
    return material[:32], material[32:]


class _EncryptingWriter:
    """File-like sink that encrypts as it is written, then appends its MAC.

    Written for `tarfile`'s stream mode, which only ever calls `write()` — so
    the tar is built, gzipped and encrypted in one pass with nothing but a
    buffer resident. AES-CTR is used rather than GCM because GCM in this library
    wants the whole message to authenticate; the trailing HMAC gives the same
    encrypt-then-MAC guarantee over a stream of any size.
    """

    def __init__(self, raw: BinaryIO):
        self._raw = raw
        salt = os.urandom(SALT_BYTES)
        iv = os.urandom(IV_BYTES)
        enc_key, mac_key = _derive_keys(salt)
        self._encryptor = Cipher(algorithms.AES(enc_key), modes.CTR(iv)).encryptor()
        self._mac = hmac.new(mac_key, digestmod=hashlib.sha256)
        header = MAGIC + salt + iv
        self._raw.write(header)
        self._mac.update(header)
        self.bytes_written = len(header)

    def write(self, data: bytes) -> int:
        if not data:
            return 0
        chunk = self._encryptor.update(bytes(data))
        self._raw.write(chunk)
        self._mac.update(chunk)
        self.bytes_written += len(chunk)
        return len(data)

    def flush(self) -> None:
        self._raw.flush()

    def finalize(self) -> None:
        tail = self._encryptor.finalize()
        if tail:
            self._raw.write(tail)
            self._mac.update(tail)
            self.bytes_written += len(tail)
        self._raw.write(self._mac.digest())
        self.bytes_written += MAC_BYTES
        self._raw.flush()


# ------------------------------------------------------------------ archive


def _pg_dump_env_and_args(dump_path: Path) -> tuple[dict, list[str]]:
    """pg_dump invocation for the configured DATABASE_URL.

    The password goes in the environment, never in argv — anything in argv is
    readable by every process on the box through /proc.
    """
    raw = settings.DATABASE_URL or ""
    # SQLAlchemy's driver suffix ("+psycopg") is not a libpq scheme.
    parsed = urlparse(raw.replace("+psycopg", "").replace("+psycopg2", ""))
    database = (parsed.path or "/").lstrip("/")
    if not parsed.hostname or not database:
        raise BackupError("DATABASE_URL is not set to a database this server can dump.")

    env = dict(os.environ)
    if parsed.password:
        env["PGPASSWORD"] = parsed.password

    args = [
        "pg_dump",
        "--host", parsed.hostname,
        "--port", str(parsed.port or 5432),
        "--dbname", database,
        "--format", "custom",
        "--compress", "6",
        # A restore into a fresh cluster has different role names and the
        # extension objects are owned by the superuser that created them.
        # Without these, pg_restore fails on every GRANT it cannot map.
        "--no-owner",
        "--no-acl",
        "--file", str(dump_path),
    ]
    if parsed.username:
        args[1:1] = ["--username", parsed.username]
    return env, args


def _uploads_dir() -> Optional[Path]:
    """The uploads tree, or None when this deployment does not keep one locally.

    S3-backed deployments have no local tree; returning None there is correct
    rather than an error, because nothing was lost.
    """
    path = Path("uploads").resolve()
    return path if path.is_dir() else None


def build_archive(contents: str, out_dir: Path) -> tuple[Path, int]:
    """Dump, pack and encrypt. Returns the archive path and its size in bytes.

    Blocking — callers run it off the event loop.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"chattermate-backup-{stamp}.cmbk"
    include_files = contents == BackupContents.DATABASE_AND_FILES.value

    with tempfile.TemporaryDirectory(prefix="cm-backup-") as staging:
        dump_path = Path(staging) / "database.dump"
        env, args = _pg_dump_env_and_args(dump_path)
        try:
            result = subprocess.run(args, env=env, capture_output=True,
                                    timeout=PG_DUMP_TIMEOUT)
        except FileNotFoundError:
            raise BackupError(
                "pg_dump is not installed in this container, so the database "
                "cannot be exported. Rebuild the backend image.") from None
        except subprocess.TimeoutExpired:
            raise BackupError("The database export timed out after an hour.") from None
        if result.returncode != 0:
            detail = (result.stderr or b"").decode(errors="replace").strip()
            # The last line is the actual failure; the rest is context nobody
            # can act on from a toast.
            detail = detail.splitlines()[-1] if detail else "unknown error"
            raise BackupError(f"pg_dump failed: {detail}")

        notes_path = Path(staging) / "RESTORE.txt"
        notes_path.write_text(RESTORE_NOTES, encoding="utf-8")

        with open(out_path, "wb") as raw:
            writer = _EncryptingWriter(raw)
            # Stream mode ("w|gz"): never seeks, so it can write straight into
            # the encryptor. The seekable "w:gz" mode cannot.
            with tarfile.open(fileobj=writer, mode="w|gz") as tar:
                tar.add(dump_path, arcname="database.dump")
                tar.add(notes_path, arcname="RESTORE.txt")
                if include_files:
                    uploads = _uploads_dir()
                    if uploads is not None:
                        tar.add(uploads, arcname="uploads")
                    else:
                        logger.warning(
                            "Backup asked for uploaded files but no local uploads "
                            "directory exists; archiving the database only")
            writer.finalize()

    return out_path, out_path.stat().st_size


# ----------------------------------------------------------------- OneDrive


class OneDriveClient:
    """App-only Microsoft Graph access to one user's drive.

    Client-credentials rather than a delegated sign-in: a backup that runs at
    02:00 cannot depend on a refresh token that expires while nobody is looking,
    and an unattended schedule has no browser to re-consent in. The cost is that
    Graph has no `/me`, so every path names the drive owner explicitly.
    """

    def __init__(self, tenant_id: str, client_id: str, client_secret: str,
                 account_email: str, folder: str):
        self.tenant_id = tenant_id.strip()
        self.client_id = client_id.strip()
        self.client_secret = client_secret
        self.account_email = account_email.strip()
        self.folder = normalise_folder(folder)
        self._token: Optional[str] = None
        self._token_expires_at = 0.0

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        response = await client.post(
            f"{LOGIN_BASE}/{quote(self.tenant_id)}/oauth2/v2.0/token",
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
        )
        if response.status_code >= 300:
            raise BackupError(_entra_error(response))
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise BackupError("Microsoft returned no access token for these credentials.")
        self._token = token
        # 60s of slack so a token cannot expire between the check and the call.
        self._token_expires_at = time.monotonic() + max(int(payload.get("expires_in", 3600)) - 60, 60)
        return token

    def _drive_root(self) -> str:
        return f"{GRAPH_BASE}/users/{quote(self.account_email)}/drive"

    async def test(self) -> dict:
        """Prove the credentials can actually write, not merely authenticate.

        Reading the drive is not enough: an app with Files.Read.All authenticates
        fine and fails at 02:00 on the first upload. So this writes a small probe
        file into the configured folder and deletes it, which is the same
        permission, the same path and the same folder the real backup uses.
        """
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            token = await self._access_token(client)
            headers = {"Authorization": f"Bearer {token}"}

            drive = await client.get(self._drive_root(), headers=headers)
            if drive.status_code >= 300:
                raise BackupError(_graph_error(drive, self.account_email))
            info = drive.json()

            probe_name = f".chattermate-connection-test-{int(time.time())}.txt"
            probe = await client.put(
                f"{self._drive_root()}/root:{_encode_path(self.folder)}/{quote(probe_name)}:/content",
                headers={**headers, "Content-Type": "text/plain"},
                content=b"ChatterMate connection test. Safe to delete.\n",
            )
            if probe.status_code >= 300:
                raise BackupError(_graph_error(probe, self.account_email))
            item_id = probe.json().get("id")
            if item_id:
                await client.delete(f"{self._drive_root()}/items/{item_id}", headers=headers)

            quota = info.get("quota") or {}
            return {
                "drive_id": info.get("id"),
                "drive_name": info.get("name"),
                "owner": ((info.get("owner") or {}).get("user") or {}).get("displayName"),
                "quota_total": quota.get("total"),
                "quota_remaining": quota.get("remaining"),
            }

    async def upload(self, path: Path, filename: str) -> dict:
        size = path.stat().st_size
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            token = await self._access_token(client)
            headers = {"Authorization": f"Bearer {token}"}
            target = f"{self._drive_root()}/root:{_encode_path(self.folder)}/{quote(filename)}:"

            if size <= GRAPH_SMALL_FILE_LIMIT:
                response = await client.put(
                    f"{target}/content", headers=headers,
                    content=path.read_bytes())
                if response.status_code >= 300:
                    raise BackupError(_graph_error(response, self.account_email))
                return response.json()

            session = await client.post(
                f"{target}/createUploadSession", headers=headers,
                json={"item": {"@microsoft.graph.conflictBehavior": "replace"}})
            if session.status_code >= 300:
                raise BackupError(_graph_error(session, self.account_email))
            upload_url = session.json().get("uploadUrl")
            if not upload_url:
                raise BackupError("Microsoft did not return an upload session.")

            return await self._upload_chunks(client, upload_url, path, size)

    async def _upload_chunks(self, client: httpx.AsyncClient, upload_url: str,
                             path: Path, size: int) -> dict:
        """PUT the file in ranges, retrying the transient failures Graph expects.

        The upload URL is pre-authorised, so these carry no bearer token — adding
        one makes Graph reject the chunk.
        """
        offset = 0
        with open(path, "rb") as handle:
            while offset < size:
                chunk = handle.read(GRAPH_CHUNK_BYTES)
                if not chunk:
                    break
                end = offset + len(chunk) - 1
                headers = {
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {offset}-{end}/{size}",
                }
                response = None
                for attempt in range(3):
                    response = await client.put(upload_url, headers=headers, content=chunk)
                    # 429/5xx are Graph asking us to slow down, not to give up;
                    # abandoning here would waste an upload that is 90% done.
                    if response.status_code in (429, 500, 502, 503, 504):
                        await asyncio.sleep(min(2 ** attempt, 8))
                        continue
                    break
                if response is None or response.status_code >= 300:
                    raise BackupError(_graph_error(response, self.account_email)
                                      if response is not None
                                      else "The upload was interrupted.")
                if response.status_code in (200, 201):
                    return response.json()
                offset = end + 1
        raise BackupError("The upload finished without Microsoft confirming the file.")


def normalise_folder(folder: str) -> str:
    """A leading-slash, no-trailing-slash OneDrive path. Empty means the root."""
    cleaned = (folder or "").strip().replace("\\", "/")
    parts = [segment.strip() for segment in cleaned.split("/") if segment.strip()]
    return "/" + "/".join(parts) if parts else ""


def _encode_path(folder: str) -> str:
    if not folder:
        return ""
    return "/" + "/".join(quote(segment) for segment in folder.strip("/").split("/"))


def _entra_error(response: httpx.Response) -> str:
    """Turn a token failure into the thing the operator has to change.

    Entra's own descriptions are long and start with a correlation id, which is
    useless on screen; the error code is what identifies the misconfiguration.
    """
    try:
        payload = response.json()
    except ValueError:
        return f"Microsoft rejected the sign-in ({response.status_code})."
    code = payload.get("error", "")
    description = (payload.get("error_description") or "").split("\r\n")[0]
    if code == "invalid_client":
        return ("Microsoft rejected the client secret. Check you copied the secret "
                "*value*, not the secret ID, and that it has not expired.")
    if code == "unauthorized_client":
        return "That application ID is not authorised in this directory."
    if "AADSTS90002" in description:
        return "That directory (tenant) ID does not exist."
    return description or f"Microsoft rejected the sign-in ({response.status_code})."


def _graph_error(response: httpx.Response, account_email: str) -> str:
    try:
        error = (response.json().get("error") or {})
    except ValueError:
        error = {}
    code = error.get("code", "")
    message = error.get("message", "")
    if response.status_code == 403 or code == "accessDenied":
        return ("Microsoft refused access to that drive. The application needs the "
                "Files.ReadWrite.All *application* permission with admin consent "
                "granted in your directory.")
    if response.status_code == 404:
        return (f"Microsoft could not find a OneDrive for {account_email}. Check the "
                "address, and that the account has a OneDrive licence.")
    if response.status_code == 507 or code == "quotaLimitReached":
        return "That OneDrive is out of space."
    return message or f"Microsoft Graph returned {response.status_code}."


# ------------------------------------------------------------------ storage


def get_settings(db: Session) -> PlatformBackupSettings:
    """The singleton row, created empty on first read.

    Committed on creation rather than left pending. Some callers read the
    settings after their own commit and return without another one, which would
    silently discard the new row and re-create it on every request.
    """
    row = db.get(PlatformBackupSettings, PlatformBackupSettings.SINGLETON_ID)
    if row is None:
        row = PlatformBackupSettings(id=PlatformBackupSettings.SINGLETON_ID)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def client_for(row: PlatformBackupSettings) -> OneDriveClient:
    if not row.is_configured:
        raise BackupError("OneDrive is not configured yet.")
    return OneDriveClient(
        tenant_id=row.tenant_id,
        client_id=row.client_id,
        client_secret=decrypt_api_key(row.encrypted_client_secret),
        account_email=row.account_email,
        folder=row.folder,
    )


def download_dir() -> Path:
    """Where prepared downloads wait. Outside uploads/, which is web-served."""
    path = Path(tempfile.gettempdir()) / "chattermate-backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def sweep_expired(db: Session) -> None:
    """Delete prepared archives nobody collected.

    Runs on every list, so an operator who prepares a download and closes the
    tab does not leave a complete copy of the platform on disk indefinitely.
    """
    now = datetime.now(timezone.utc)
    stale = (db.query(PlatformBackupRun)
             .filter(PlatformBackupRun.status == BackupStatus.READY.value,
                     PlatformBackupRun.expires_at <= now)
             .all())
    for run in stale:
        discard_file(run.local_path)
        run.local_path = None
        run.status = BackupStatus.EXPIRED.value
    if stale:
        db.commit()


def discard_file(path: Optional[str]) -> None:
    if not path:
        return
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("Could not delete prepared backup %s: %s", path, exc)


def start_run(db: Session, method: str, contents: str, destination: str,
              actor_email: Optional[str] = None) -> PlatformBackupRun:
    """Record the attempt before doing the work.

    Deliberately committed on its own: if the process dies during a two-hour
    upload the row survives as `running`, which is the honest record. Writing
    history only on success is how a stopped backup goes unnoticed for months.
    """
    run = PlatformBackupRun(
        method=method, contents=contents, destination=destination,
        status=BackupStatus.RUNNING.value, actor_email=actor_email,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finish_run(db: Session, run: PlatformBackupRun, status: str,
               size_bytes: Optional[int] = None, error: Optional[str] = None,
               filename: Optional[str] = None, local_path: Optional[str] = None,
               remote_item_id: Optional[str] = None,
               remote_web_url: Optional[str] = None) -> PlatformBackupRun:
    run.status = status
    run.finished_at = datetime.now(timezone.utc)
    if size_bytes is not None:
        run.size_bytes = size_bytes
    if error is not None:
        run.error = error[:2000]
    if filename is not None:
        run.filename = filename
    if local_path is not None:
        run.local_path = local_path
        run.expires_at = datetime.now(timezone.utc) + DOWNLOAD_TTL
    if remote_item_id is not None:
        run.remote_item_id = remote_item_id
    if remote_web_url is not None:
        run.remote_web_url = remote_web_url
    db.commit()
    db.refresh(run)
    return run


# ------------------------------------------------------------------- orchestration


async def prepare_local_backup(db: Session, contents: str,
                               actor_email: Optional[str]) -> PlatformBackupRun:
    """Build an archive and hold it for one download."""
    run = start_run(db, BackupMethod.LOCAL.value, contents, "Local computer", actor_email)
    try:
        path, size = await asyncio.to_thread(build_archive, contents, download_dir())
    except BackupError as exc:
        return finish_run(db, run, BackupStatus.FAILED.value, error=str(exc))
    except Exception as exc:
        logger.error("Local backup failed", exc_info=True)
        return finish_run(db, run, BackupStatus.FAILED.value,
                          error=f"The backup could not be created: {exc}")
    return finish_run(db, run, BackupStatus.READY.value, size_bytes=size,
                      filename=path.name, local_path=str(path))


async def run_onedrive_backup(db: Session, method: str,
                              actor_email: Optional[str] = None) -> PlatformBackupRun:
    """Build an archive, upload it, and delete the local copy either way.

    The temporary archive is removed in a finally block rather than after a
    successful upload: a failed transfer is precisely when a forgotten copy of
    every tenant's data is most likely to sit on disk unnoticed.
    """
    row = get_settings(db)
    if not row.is_connected:
        raise BackupError("OneDrive is not connected.")

    contents = row.contents
    destination = row.folder or "/"
    run = start_run(db, method, contents, destination, actor_email)

    path: Optional[Path] = None
    try:
        path, size = await asyncio.to_thread(build_archive, contents, download_dir())
        item = await client_for(row).upload(path, path.name)
        return finish_run(db, run, BackupStatus.UPLOADED.value, size_bytes=size,
                          filename=path.name,
                          remote_item_id=item.get("id"),
                          remote_web_url=item.get("webUrl"))
    except BackupError as exc:
        return finish_run(db, run, BackupStatus.FAILED.value, error=str(exc))
    except Exception as exc:
        logger.error("OneDrive backup failed", exc_info=True)
        return finish_run(db, run, BackupStatus.FAILED.value,
                          error=f"The backup could not be uploaded: {exc}")
    finally:
        if path is not None:
            discard_file(str(path))


def format_size(size_bytes: Optional[int]) -> str:
    if not size_bytes:
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size_bytes)
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    return f"{value:.0f} {units[index]}" if index < 2 else f"{value:.1f} {units[index]}"



def pg_dump_available() -> bool:
    """Whether the database can be exported from this container at all.

    Checked up front so the console can say the image is missing pg_dump instead
    of offering a button that spends forty seconds failing.
    """
    return shutil.which("pg_dump") is not None

def disk_free_bytes() -> Optional[int]:
    try:
        return shutil.disk_usage(str(download_dir())).free
    except OSError:
        return None
