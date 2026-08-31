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

Operator console: backups and recovery.

Guarded by require_platform_admin like the rest of the console — these routes
can hand back a complete copy of every tenant's data, so they are the last place
an authorisation shortcut belongs.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core.logger import get_logger
from app.core.platform_auth import audit, require_platform_admin
from app.core.security import encrypt_api_key
from app.database import get_db
from app.models.platform_backup import (BackupContents, BackupFrequency,
                                        BackupMethod, BackupStatus,
                                        PlatformBackupRun)
from app.models.user import User
from app.services import platform_backup
from app.services.platform_backup import BackupError

router = APIRouter()
logger = get_logger(__name__)

HISTORY_LIMIT = 25


# ------------------------------------------------------------------ schemas


class ConnectionIn(BaseModel):
    tenant_id: str = Field("", max_length=128)
    client_id: str = Field("", max_length=128)
    # Absent means "keep the stored secret". The console is never sent the
    # existing one, so it cannot echo it back, and treating absent as "clear"
    # would wipe a working connection on any save that only changed the folder.
    client_secret: Optional[str] = Field(None, max_length=512)
    account_email: str = Field("", max_length=320)
    folder: str = Field("/ChatterMate Backups", max_length=512)


class ScheduleIn(BaseModel):
    enabled: bool = False
    frequency: str = BackupFrequency.DAILY.value
    weekday: int = Field(6, ge=0, le=6)
    day_of_month: int = Field(1, ge=1, le=31)
    backup_time: str = "02:00"
    timezone: str = Field("UTC", max_length=64)
    contents: str = BackupContents.DATABASE_AND_FILES.value

    @field_validator("frequency")
    @classmethod
    def _known_frequency(cls, value: str) -> str:
        allowed = {item.value for item in BackupFrequency}
        if value not in allowed:
            raise ValueError(f"frequency must be one of {sorted(allowed)}")
        return value

    @field_validator("contents")
    @classmethod
    def _known_contents(cls, value: str) -> str:
        allowed = {item.value for item in BackupContents}
        if value not in allowed:
            raise ValueError(f"contents must be one of {sorted(allowed)}")
        return value

    @field_validator("backup_time")
    @classmethod
    def _valid_time(cls, value: str) -> str:
        try:
            hour, minute = (int(part) for part in value.split(":", 1))
        except ValueError:
            raise ValueError("backup_time must be HH:MM") from None
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError("backup_time must be HH:MM")
        return f"{hour:02d}:{minute:02d}"

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"{value} is not a known time zone") from None
        return value


class LocalBackupIn(BaseModel):
    contents: str = BackupContents.DATABASE_AND_FILES.value

    @field_validator("contents")
    @classmethod
    def _known_contents(cls, value: str) -> str:
        allowed = {item.value for item in BackupContents}
        if value not in allowed:
            raise ValueError(f"contents must be one of {sorted(allowed)}")
        return value


# ------------------------------------------------------------------ reading


def _payload(db: Session) -> dict:
    row = platform_backup.get_settings(db)
    history = (db.query(PlatformBackupRun)
               .order_by(PlatformBackupRun.created_at.desc())
               .limit(HISTORY_LIMIT)
               .all())
    data = row.to_dict()
    data["history"] = [run.to_dict() for run in history]
    data["server"] = {
        "timezone": row.schedule_timezone,
        "disk_free_bytes": platform_backup.disk_free_bytes(),
        # The page must not offer a button that cannot work. Without pg_dump the
        # honest thing is to say so up front rather than after a 40-second wait.
        "can_dump": platform_backup.pg_dump_available(),
    }
    return data


@router.get("/backups")
async def get_backups(
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Connection, schedule and delivery history in one read."""
    platform_backup.sweep_expired(db)
    payload = _payload(db)
    db.commit()
    return payload


# --------------------------------------------------------------- connection


@router.put("/backups/onedrive")
async def save_connection(
    body: ConnectionIn,
    request: Request,
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Store the Entra application details.

    Saving does not connect. Any change to a credential clears `connected_at`,
    so the console can never show "Connected" for a secret that was never tested
    — the state that produces a schedule which fires nightly and uploads nothing.
    """
    row = platform_backup.get_settings(db)
    folder = platform_backup.normalise_folder(body.folder)

    changed_credentials = (
        (body.tenant_id or "").strip() != (row.tenant_id or "")
        or (body.client_id or "").strip() != (row.client_id or "")
        or (body.account_email or "").strip() != (row.account_email or "")
        or bool(body.client_secret)
    )

    row.tenant_id = (body.tenant_id or "").strip() or None
    row.client_id = (body.client_id or "").strip() or None
    row.account_email = (body.account_email or "").strip() or None
    row.folder = folder or "/ChatterMate Backups"
    if body.client_secret:
        row.encrypted_client_secret = encrypt_api_key(body.client_secret.strip())
    if changed_credentials:
        row.connected_at = None
        row.last_error = None

    audit(db, current_user, request, "backups.connection_saved",
          tenant_id=row.tenant_id, client_id=row.client_id,
          account_email=row.account_email, folder=row.folder)
    db.commit()
    return _payload(db)


@router.post("/backups/onedrive/test")
async def test_connection(
    request: Request,
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Sign in, write a probe file into the destination folder, delete it.

    Writing is the point. An application granted only Files.Read.All
    authenticates perfectly and then fails on the first real upload at 02:00,
    which is the worst possible moment to discover a permission gap.
    """
    row = platform_backup.get_settings(db)
    if not row.is_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Fill in the tenant ID, client ID, client secret and account email first.")

    try:
        drive = await platform_backup.client_for(row).test()
    except BackupError as exc:
        row.connected_at = None
        row.last_error = str(exc)
        audit(db, current_user, request, "backups.connection_failed",
              error=str(exc))
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    row.connected_at = datetime.now(timezone.utc)
    row.last_error = None
    audit(db, current_user, request, "backups.connected",
          account_email=row.account_email, folder=row.folder,
          drive_id=drive.get("drive_id"))
    db.commit()
    payload = _payload(db)
    payload["drive"] = drive
    return payload


@router.delete("/backups/onedrive")
async def disconnect(
    request: Request,
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Forget the credentials and stop the schedule.

    The schedule is disabled in the same transaction rather than left enabled
    against a destination that no longer exists — otherwise every night produces
    a failed run and an alert nobody can act on.
    """
    row = platform_backup.get_settings(db)
    row.tenant_id = None
    row.client_id = None
    row.encrypted_client_secret = None
    row.account_email = None
    row.connected_at = None
    row.last_error = None
    row.schedule_enabled = False

    audit(db, current_user, request, "backups.disconnected")
    db.commit()
    return _payload(db)


# ----------------------------------------------------------------- schedule


@router.put("/backups/schedule")
async def save_schedule(
    body: ScheduleIn,
    request: Request,
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    row = platform_backup.get_settings(db)
    if body.enabled and not row.is_connected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connect OneDrive before turning on scheduled backups.")

    row.schedule_enabled = body.enabled
    row.frequency = body.frequency
    row.weekday = body.weekday
    row.day_of_month = body.day_of_month
    row.backup_time = body.backup_time
    row.schedule_timezone = body.timezone
    row.contents = body.contents

    audit(db, current_user, request, "backups.schedule_saved",
          enabled=body.enabled, frequency=body.frequency,
          backup_time=body.backup_time, timezone=body.timezone,
          contents=body.contents)
    db.commit()
    return _payload(db)


# -------------------------------------------------------------------- runs


@router.post("/backups/run")
async def run_now(
    request: Request,
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Build and upload immediately, using the saved schedule's contents."""
    try:
        run = await platform_backup.run_onedrive_backup(
            db, BackupMethod.MANUAL.value, actor_email=current_user.email)
    except BackupError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    audit(db, current_user, request, "backups.run",
          status=run.status, size_bytes=run.size_bytes)
    db.commit()

    if run.status == BackupStatus.FAILED.value:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=run.error or "The backup failed.")
    return _payload(db)


@router.post("/backups/local")
async def prepare_local(
    body: LocalBackupIn,
    request: Request,
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Build an archive and hold it on disk for a single download."""
    run = await platform_backup.prepare_local_backup(
        db, body.contents, actor_email=current_user.email)

    audit(db, current_user, request, "backups.local_prepared",
          status=run.status, contents=body.contents, size_bytes=run.size_bytes)
    db.commit()

    if run.status == BackupStatus.FAILED.value:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=run.error or "The backup could not be created.")
    payload = _payload(db)
    payload["prepared"] = run.to_dict()
    return payload


@router.get("/backups/local/{run_id}/download")
async def download_local(
    run_id: str,
    request: Request,
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Stream a prepared archive, then delete the server's copy.

    The delete runs as a response background task, so it happens after the last
    byte is sent rather than while the client is still reading. A second request
    for the same run finds the row marked `downloaded` and 404s, which is
    correct: one preparation, one delivery.
    """
    try:
        run = db.get(PlatformBackupRun, UUID(run_id))
    except ValueError:
        run = None
    if run is None or not run.is_downloadable:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="That backup is no longer available. Prepare a new one.")

    path = run.local_path
    filename = run.filename or "chattermate-backup.cmbk"

    run.status = BackupStatus.DOWNLOADED.value
    run.local_path = None
    run.expires_at = None
    audit(db, current_user, request, "backups.local_downloaded",
          size_bytes=run.size_bytes, filename=filename)
    db.commit()

    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=filename,
        background=BackgroundTask(platform_backup.discard_file, path),
    )
