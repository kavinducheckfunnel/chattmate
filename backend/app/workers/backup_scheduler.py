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

Fires the scheduled OneDrive backup.

Runs inside the API process rather than as its own service or a host crontab.
That is deliberate: a schedule an operator sets in the console must be the
schedule that runs, and a crontab entry drifts from the database the first time
someone edits one and not the other. The cost is that the API process must be
up at 02:00 — it is, or nothing else works either.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core.logger import get_logger
from app.database import SessionLocal
from app.models.platform_backup import BackupMethod
from app.services import platform_backup

logger = get_logger(__name__)

# A minute is fine: schedules are set to the minute, and a tick that costs one
# indexed read of a single row is not worth stretching out.
TICK_SECONDS = 60
# Arbitrary but fixed. Postgres advisory locks share one namespace per database,
# so this number must not collide with another feature's.
ADVISORY_LOCK_KEY = 8_242_197_310_155_001


async def _run_if_due() -> None:
    db = SessionLocal()
    try:
        row = platform_backup.get_settings(db)
        db.commit()

        if not row.schedule_enabled or not row.is_connected:
            return

        now = datetime.now(timezone.utc)
        # Base the window on the last completed attempt so a restart mid-window
        # does not skip it. A schedule that has never run is measured from when
        # it was saved, otherwise enabling it at 14:00 fires a backup on the
        # spot for a 02:00 window that already passed.
        baseline = row.last_run_at or row.updated_at or row.created_at or (now - timedelta(minutes=1))
        if baseline.tzinfo is None:
            baseline = baseline.replace(tzinfo=timezone.utc)

        due_at = row.next_run_after(baseline)
        if due_at is None or due_at > now:
            return

        # Two API workers would otherwise each build a multi-gigabyte archive and
        # upload it. The lock is held only for the run and released with the
        # connection, so a crashed worker cannot wedge the schedule permanently.
        acquired = db.execute(text("SELECT pg_try_advisory_lock(:key)"),
                              {"key": ADVISORY_LOCK_KEY}).scalar()
        if not acquired:
            return

        try:
            # Claim the window before the work starts. A crash during a two-hour
            # upload must not re-enter the same window on the next tick.
            row.last_run_at = now
            db.commit()

            logger.info("Scheduled OneDrive backup starting (due %s)", due_at.isoformat())
            run = await platform_backup.run_onedrive_backup(db, BackupMethod.SCHEDULED.value)
            if run.status == "uploaded":
                logger.info("Scheduled backup uploaded: %s (%s bytes)",
                            run.filename, run.size_bytes)
            else:
                logger.error("Scheduled backup failed: %s", run.error)
        finally:
            db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": ADVISORY_LOCK_KEY})
            db.commit()
    finally:
        db.close()


async def run_backup_scheduler_loop() -> None:
    """Tick forever. Never lets one bad tick stop the loop."""
    logger.info("Backup scheduler started (tick %ss)", TICK_SECONDS)
    while True:
        try:
            await _run_if_due()
        except Exception:
            # Swallowed on purpose: a transient database error at 02:00 must not
            # silently end the only thing that keeps backups running.
            logger.error("Backup scheduler tick failed", exc_info=True)
        await asyncio.sleep(TICK_SECONDS)
