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
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Column, DateTime, Enum as SAEnum, ForeignKey, Integer, String, func, Index
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class TokenPurpose(str, enum.Enum):
    """What a token entitles the bearer to do.

    Kept as one table with a purpose discriminator rather than two tables: the
    lifecycle (issue, hash, expire, consume, throttle) is identical for both,
    and a single consume path means a fix or an audit only has to happen once.
    """
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"


def hash_token(raw: str) -> str:
    """SHA-256 of the value that was emailed out.

    Only the digest is stored. Anyone who reads the table — a leaked backup, an
    over-broad support query, the AI ticket SQL tool — gets digests, not live
    credentials. SHA-256 rather than bcrypt is deliberate: these are
    high-entropy random strings with a short TTL, not user-chosen passwords, so
    there is no dictionary to slow down, and verification sits in the request
    path. The 6-digit reset code is the exception — it has only 10^6 possible
    values, so its protection comes from MAX_ATTEMPTS and the short expiry
    below, not from the hash.
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AuthToken(Base):
    """A single-use, expiring credential emailed to a user."""

    __tablename__ = "auth_tokens"

    # Verification links are clicked from an inbox, sometimes days later on a
    # different device; a reset code is typed within minutes, and a longer
    # window is just more time to brute-force six digits.
    EMAIL_VERIFICATION_TTL = timedelta(hours=48)
    PASSWORD_RESET_TTL = timedelta(minutes=15)

    # Wrong-code guesses before the token is burned. Six digits with unlimited
    # guesses is not a secret, and rate limiting by IP alone does not stop a
    # distributed guesser working one account.
    MAX_ATTEMPTS = 5

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        # ondelete at the database level, not just the ORM cascade: these rows
        # are also deleted by the cleanup path and by tenant offboarding, which
        # do not always load the User object first.
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    purpose = Column(
        SAEnum(TokenPurpose, name="token_purpose", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    token_hash = Column(String(64), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="auth_tokens")

    __table_args__ = (
        # The consume path looks up by (purpose, hash); the reissue path clears
        # by (user, purpose). One composite index serves the first, the user_id
        # index above serves the second.
        Index("ix_auth_tokens_purpose_hash", "purpose", "token_hash"),
    )

    @classmethod
    def issue(cls, user_id, purpose: TokenPurpose) -> tuple["AuthToken", str]:
        """Mint a token. Returns (row_to_persist, raw_value_to_email).

        The raw value is returned once and never stored, so a lost email means
        a new token rather than a lookup.
        """
        if purpose == TokenPurpose.PASSWORD_RESET:
            # Typed by hand off a phone screen, so digits only. secrets, not
            # random: this is a credential.
            raw = f"{secrets.randbelow(1_000_000):06d}"
            ttl = cls.PASSWORD_RESET_TTL
        else:
            # Travels in a URL, so nobody types it — use full entropy.
            raw = secrets.token_urlsafe(32)
            ttl = cls.EMAIL_VERIFICATION_TTL

        token = cls(
            user_id=user_id,
            purpose=purpose,
            token_hash=hash_token(raw),
            expires_at=datetime.now(timezone.utc) + ttl,
        )
        return token, raw

    @property
    def is_expired(self) -> bool:
        expires = self.expires_at
        # Rows read back from Postgres carry tzinfo; one built in memory and not
        # yet flushed may not. Comparing naive to aware raises TypeError, which
        # inside the consume path would surface as a 500 on a valid token.
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= expires

    @property
    def is_usable(self) -> bool:
        return (
            self.used_at is None
            and not self.is_expired
            and self.attempts < self.MAX_ATTEMPTS
        )

    def consume(self) -> None:
        self.used_at = datetime.now(timezone.utc)
