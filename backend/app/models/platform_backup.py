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
"""

import enum
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import (BigInteger, Boolean, Column, DateTime, Integer, String,
                        Text, func)
from sqlalchemy.dialects.postgresql import UUID

from app.core.logger import get_logger
from app.database import Base

logger = get_logger(__name__)


class BackupContents(str, enum.Enum):
    """What goes into the archive.

    The database alone restores the product; it does not restore the
    conversation. Attachments and knowledge documents live on disk, and a
    database row pointing at a file that is gone is worse than an obvious gap —
    it looks intact until someone opens the message.
    """
    DATABASE_AND_FILES = "database_and_files"
    DATABASE_ONLY = "database_only"


class BackupMethod(str, enum.Enum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    LOCAL = "local"


class BackupStatus(str, enum.Enum):
    RUNNING = "running"
    UPLOADED = "uploaded"
    DOWNLOADED = "downloaded"
    READY = "ready"
    FAILED = "failed"
    EXPIRED = "expired"


class BackupFrequency(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class PlatformBackupSettings(Base):
    """OneDrive destination and schedule for the operator's backups.

    Single row (``id == SINGLETON_ID``), like PlatformAIConfig: there is one
    platform, so there is one backup destination. A key/value table would let
    half a connection be saved — a tenant id with no client secret — which is
    exactly the state that produces a schedule that fires nightly and uploads
    nothing.

    The client secret is Fernet-encrypted at rest and never returned by the API,
    not even masked. A masked secret still leaks its length, and the console
    only ever needs to know whether one is set.
    """

    __tablename__ = "platform_backup_settings"

    SINGLETON_ID = 1

    id = Column(Integer, primary_key=True, default=SINGLETON_ID)

    # --- Microsoft Entra application (app-only, client credentials) ---------
    tenant_id = Column(String(128), nullable=True)
    client_id = Column(String(128), nullable=True)
    encrypted_client_secret = Column(Text, nullable=True)
    # App-only tokens have no signed-in user, so Graph has no /me. Every call
    # has to name the drive owner explicitly, which is why this is required
    # rather than cosmetic.
    account_email = Column(String(320), nullable=True)
    folder = Column(String(512), nullable=False, default="/ChatterMate Backups")

    # Set only by a connection test that actually reached the drive. Storing
    # credentials is not the same as having a working connection, and the
    # console must not offer to schedule uploads against untested settings.
    connected_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)

    # --- Schedule ----------------------------------------------------------
    schedule_enabled = Column(Boolean, nullable=False, default=False)
    frequency = Column(String(16), nullable=False, default=BackupFrequency.DAILY.value)
    # 0 = Monday … 6 = Sunday (datetime.weekday()). Only read when weekly.
    weekday = Column(Integer, nullable=False, default=6)
    # Only read when monthly. Clamped to the length of the month at run time so
    # "31" does not silently skip February.
    day_of_month = Column(Integer, nullable=False, default=1)
    # "HH:MM" in `schedule_timezone`, not UTC. An operator who sets 02:00 means
    # 02:00 where they are; storing UTC would move the backup twice a year.
    backup_time = Column(String(5), nullable=False, default="02:00")
    schedule_timezone = Column(String(64), nullable=False, default="UTC")
    contents = Column(String(32), nullable=False,
                      default=BackupContents.DATABASE_AND_FILES.value)

    # Advances only on a completed attempt, success or failure. A crash mid-run
    # therefore retries on the next tick instead of skipping the window.
    last_run_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # ---------------------------------------------------------------- state

    @property
    def has_client_secret(self) -> bool:
        return bool(self.encrypted_client_secret)

    @property
    def is_configured(self) -> bool:
        """Whether a connection attempt is even possible."""
        return bool(self.tenant_id and self.client_id
                    and self.encrypted_client_secret and self.account_email)

    @property
    def is_connected(self) -> bool:
        """Whether a test has succeeded against these exact settings.

        `connected_at` is cleared whenever any credential field changes, so this
        can never report a connection that belongs to a previous secret.
        """
        return bool(self.connected_at and self.is_configured)

    # ------------------------------------------------------------- schedule

    def tz(self) -> timezone:
        try:
            return ZoneInfo(self.schedule_timezone or "UTC")
        except (ZoneInfoNotFoundError, ValueError):
            # An unknown zone must not stop the scheduler dead — a backup at the
            # wrong hour beats no backup at all.
            return timezone.utc

    def next_run_after(self, moment: datetime) -> Optional[datetime]:
        """The first scheduled instant strictly after `moment` (UTC in, UTC out).

        Returns None when automatic backups are off or the destination is not
        connected — both are real states in which nothing should fire, and
        collapsing them into a date would make the console promise a run that
        can never happen.
        """
        if not self.schedule_enabled or not self.is_connected:
            return None

        zone = self.tz()
        local = moment.astimezone(zone)
        # Range-checked here as well as in the API schema. This runs on every
        # console read, so a row that predates the validator — or one written by
        # hand — must degrade to the default rather than raise and take the whole
        # Backups page down with it.
        try:
            hour, minute = (int(part) for part in (self.backup_time or "02:00").split(":", 1))
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError(self.backup_time)
        except ValueError:
            logger.warning("Ignoring unusable backup_time %r; using 02:00", self.backup_time)
            hour, minute = 2, 0

        candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)

        if self.frequency == BackupFrequency.WEEKLY.value:
            days_ahead = (self.weekday - candidate.weekday()) % 7
            candidate += timedelta(days=days_ahead)
            if candidate <= local:
                candidate += timedelta(days=7)
        elif self.frequency == BackupFrequency.MONTHLY.value:
            candidate = _clamp_day(candidate, self.day_of_month or 1)
            if candidate <= local:
                nxt = candidate.replace(day=1) + timedelta(days=32)
                candidate = _clamp_day(nxt.replace(day=1), self.day_of_month or 1)
        else:
            if candidate <= local:
                candidate += timedelta(days=1)

        return candidate.astimezone(timezone.utc)

    def to_dict(self) -> dict:
        now = datetime.now(timezone.utc)
        next_run = self.next_run_after(now)
        return {
            "connection": {
                "tenant_id": self.tenant_id or "",
                "client_id": self.client_id or "",
                "has_client_secret": self.has_client_secret,
                "account_email": self.account_email or "",
                "folder": self.folder or "/ChatterMate Backups",
                "is_configured": self.is_configured,
                "is_connected": self.is_connected,
                "connected_at": self.connected_at.isoformat() if self.connected_at else None,
                "last_error": self.last_error,
            },
            "schedule": {
                "enabled": self.schedule_enabled,
                "frequency": self.frequency,
                "weekday": self.weekday,
                "day_of_month": self.day_of_month,
                "backup_time": self.backup_time,
                "timezone": self.schedule_timezone,
                "contents": self.contents,
                "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
                "next_run_at": next_run.isoformat() if next_run else None,
            },
        }


def _clamp_day(moment: datetime, day: int) -> datetime:
    """`moment` moved to `day` of its own month, or the last day if shorter."""
    first_next = (moment.replace(day=28) + timedelta(days=4)).replace(day=1)
    days_in_month = (first_next - timedelta(days=1)).day
    return moment.replace(day=min(max(day, 1), days_in_month))


class PlatformBackupRun(Base):
    """One backup attempt — the delivery record, not the archive.

    Rows are written before the work starts and updated when it finishes, so a
    run killed mid-upload leaves a `running` row rather than vanishing. The
    console shows that as an incomplete attempt, which is the truth; a table
    that only records successes is the reason nobody notices backups stopped.

    `local_path` is set only for downloads that are waiting to be collected. The
    file is deleted the moment it is delivered — a plaintext-adjacent archive of
    every tenant's data is not something to leave sitting on the server.
    """

    __tablename__ = "platform_backup_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    method = Column(String(16), nullable=False)
    contents = Column(String(32), nullable=False)
    destination = Column(String(512), nullable=False)
    size_bytes = Column(BigInteger, nullable=True)
    status = Column(String(16), nullable=False, default=BackupStatus.RUNNING.value)
    error = Column(Text, nullable=True)

    filename = Column(String(512), nullable=True)
    remote_item_id = Column(String(256), nullable=True)
    remote_web_url = Column(Text, nullable=True)

    local_path = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    # Null for scheduled runs — nobody pressed anything.
    actor_email = Column(String(320), nullable=True)

    @property
    def is_downloadable(self) -> bool:
        if self.status != BackupStatus.READY.value or not self.local_path:
            return False
        if self.expires_at and self.expires_at <= datetime.now(timezone.utc):
            return False
        return True

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "method": self.method,
            "contents": self.contents,
            "destination": self.destination,
            "size_bytes": self.size_bytes,
            "status": self.status,
            "error": self.error,
            "filename": self.filename,
            "web_url": self.remote_web_url,
            "is_downloadable": self.is_downloadable,
            "actor_email": self.actor_email,
        }
