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

Public account-lifecycle endpoints: email verification and password reset.

Every route here is unauthenticated by necessity — someone who has forgotten
their password cannot present a session, and someone verifying an address is
usually clicking a link in a mail client. Two rules follow from that and are
applied throughout:

  1. Responses must not reveal whether an account exists. Every reset request
     returns the same body and status whether the address is real, unknown, or
     belongs to a deactivated user. Anything else turns this into a free
     customer-list oracle for a competitor.

  2. Every route is rate limited by IP, and the reset request additionally by
     target address, so neither a single victim nor the address space at large
     can be swept.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logger import get_logger
from app.core.security import revoke_user_sessions, validate_password_strength
from app.database import get_db
from app.models.auth_token import AuthToken, TokenPurpose, hash_token
from app.models.user import User
from app.services.public_rate_limit import allow_request
from app.services.transactional_email import (
    is_configured as email_is_configured,
    send_password_reset_email,
    send_verification_email,
)

logger = get_logger(__name__)
router = APIRouter()

# Deliberately identical for every outcome of a reset request. Assigned once so
# a later edit cannot accidentally make the branches differ.
_RESET_REQUESTED_MESSAGE = (
    "If an account exists for that address, we've sent a reset code to it."
)


def _client_ip(request: Request) -> str:
    """Caller IP, honouring the reverse proxy.

    nginx terminates TLS in front of this app, so request.client.host is the
    proxy for every request; without the forwarded header every user on the
    platform would share one rate-limit bucket.
    """
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def _too_many(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
        headers={"Retry-After": "3600"},
    )


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordVerify(BaseModel):
    email: EmailStr
    otp: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _check_strength(cls, value: str) -> str:
        # The same validator used by signup, invitations and admin resets. A
        # reset is a password-setting path like any other, and a weaker rule
        # here would make "forgot password" the cheapest way to get a weak
        # password onto an account.
        return validate_password_strength(value)


class VerifyEmailRequest(BaseModel):
    token: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------

async def issue_and_send_verification(db: Session, user: User) -> bool:
    """Mint a verification token for `user` and email it.

    Shared by signup and by resend. Caller commits.
    """
    # Invalidate outstanding tokens first: a user who clicks "resend" three
    # times should end up with one working link, not three. Without this, an
    # old link forwarded to someone else stays live for its full 48 hours.
    db.query(AuthToken).filter(
        AuthToken.user_id == user.id,
        AuthToken.purpose == TokenPurpose.EMAIL_VERIFICATION,
        AuthToken.used_at.is_(None),
    ).update({"used_at": datetime.now(timezone.utc)}, synchronize_session=False)

    token, raw = AuthToken.issue(user.id, TokenPurpose.EMAIL_VERIFICATION)
    db.add(token)
    db.flush()
    return await send_verification_email(user.email, user.full_name or "", raw)


@router.post("/verify-email")
async def verify_email(
    payload: VerifyEmailRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Consume a verification token from an emailed link."""
    ip = _client_ip(request)
    # The token is high-entropy, so this is not really anti-guessing — it stops
    # this endpoint being used as a cheap way to generate database load.
    if not allow_request(f"verify_email:{ip}", 30, 3600):
        raise _too_many("Too many verification attempts. Please try again later.")

    row = (
        db.query(AuthToken)
        .filter(
            AuthToken.purpose == TokenPurpose.EMAIL_VERIFICATION,
            AuthToken.token_hash == hash_token(payload.token),
        )
        .first()
    )

    if row is None or not row.is_usable:
        # One message for absent, expired and already-used. The distinction is
        # of no use to a legitimate user — the remedy is "request a new link"
        # in every case — and telling them apart would confirm to a third party
        # that a token they hold was genuine.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This verification link is invalid or has expired. Request a new one.",
        )

    user = db.query(User).filter(User.id == row.user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This verification link is invalid or has expired. Request a new one.",
        )

    row.consume()
    if not user.is_email_verified:
        user.is_email_verified = True
        user.email_verified_at = datetime.now(timezone.utc)
    db.commit()

    logger.info("Email verified for user %s", user.id)
    return {"message": "Email verified", "email": user.email}


@router.post("/resend-verification")
async def resend_verification(
    payload: ResendVerificationRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Send a fresh verification link.

    Unauthenticated so it works from the login screen, which means it gets the
    same non-disclosure treatment as password reset.
    """
    ip = _client_ip(request)
    email = payload.email.strip().lower()

    if not allow_request(f"resend_verify_ip:{ip}", 10, 3600):
        raise _too_many("Too many requests. Please try again later.")
    if not allow_request(f"resend_verify_email:{email}", 5, 3600):
        # Per-address as well as per-IP: without this, one address can be
        # mailbombed from a rotating pool of IPs, and it is our SMTP reputation
        # that pays for it.
        raise _too_many("Too many requests for that address. Please try again later.")

    user = db.query(User).filter(User.email == email).first()
    if user is not None and not user.is_email_verified:
        await issue_and_send_verification(db, user)
        db.commit()

    return {
        "message": "If that address needs verifying, we've sent a new link to it."
    }


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

@router.post("/forgot-password/request")
async def request_password_reset(
    payload: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Step 1: email a 6-digit reset code."""
    ip = _client_ip(request)
    email = payload.email.strip().lower()

    if not allow_request(f"pwreset_ip:{ip}", settings.PASSWORD_RESET_RATE_LIMIT_PER_HOUR * 4, 3600):
        raise _too_many("Too many password reset requests. Please try again later.")
    if not allow_request(f"pwreset_email:{email}", settings.PASSWORD_RESET_RATE_LIMIT_PER_HOUR, 3600):
        raise _too_many("Too many password reset requests. Please try again later.")

    if not email_is_configured():
        # A 503 here is honest and does not leak anything: it is a property of
        # the deployment, identical for every address. Returning the usual
        # success message would leave the user waiting for mail that the server
        # already knows it cannot send.
        logger.error("Password reset requested but SMTP is not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Password reset is temporarily unavailable. Please contact support.",
        )

    user = db.query(User).filter(User.email == email, User.is_active == True).first()
    if user is not None:
        db.query(AuthToken).filter(
            AuthToken.user_id == user.id,
            AuthToken.purpose == TokenPurpose.PASSWORD_RESET,
            AuthToken.used_at.is_(None),
        ).update({"used_at": datetime.now(timezone.utc)}, synchronize_session=False)

        token, raw = AuthToken.issue(user.id, TokenPurpose.PASSWORD_RESET)
        db.add(token)
        db.commit()
        await send_password_reset_email(user.email, user.full_name or "", raw)
    else:
        logger.info("Password reset requested for unknown address from %s", ip)

    # Same response either way — see the module docstring.
    return {"message": _RESET_REQUESTED_MESSAGE}


@router.post("/forgot-password/verify")
async def verify_password_reset(
    payload: ForgotPasswordVerify,
    request: Request,
    db: Session = Depends(get_db),
):
    """Step 2: exchange the code for a new password."""
    ip = _client_ip(request)
    email = payload.email.strip().lower()

    if not allow_request(f"pwverify_ip:{ip}", 20, 3600):
        raise _too_many("Too many attempts. Please try again later.")

    invalid = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="That code is invalid or has expired. Request a new one.",
    )

    user = db.query(User).filter(User.email == email, User.is_active == True).first()
    if user is None:
        raise invalid

    row = (
        db.query(AuthToken)
        .filter(
            AuthToken.user_id == user.id,
            AuthToken.purpose == TokenPurpose.PASSWORD_RESET,
            AuthToken.token_hash == hash_token(payload.otp.strip()),
        )
        .first()
    )

    if row is None:
        # Wrong code. Burn an attempt on the newest live token for this user,
        # otherwise the MAX_ATTEMPTS ceiling never engages: a guesser supplying
        # wrong codes would never match a row, so nothing would ever count.
        live = (
            db.query(AuthToken)
            .filter(
                AuthToken.user_id == user.id,
                AuthToken.purpose == TokenPurpose.PASSWORD_RESET,
                AuthToken.used_at.is_(None),
            )
            .order_by(AuthToken.created_at.desc())
            .first()
        )
        if live is not None:
            live.attempts += 1
            if live.attempts >= AuthToken.MAX_ATTEMPTS:
                live.consume()
                logger.warning(
                    "Password reset code for user %s burned after %d failed attempts",
                    user.id, live.attempts,
                )
            db.commit()
        raise invalid

    if not row.is_usable:
        raise invalid

    user.hashed_password = User.get_password_hash(payload.new_password)
    row.consume()

    # Proving control of the mailbox also verifies it. A user who never clicked
    # the verification link but can complete a reset has demonstrated exactly
    # what verification asks for, and leaving them unverified would nag them
    # about an address they just proved they own.
    if not user.is_email_verified:
        user.is_email_verified = True
        user.email_verified_at = datetime.now(timezone.utc)

    db.commit()

    # A password reset is how someone recovers a *compromised* account, so
    # every existing session has to die with the old password — otherwise the
    # attacker who prompted the reset keeps their access.
    try:
        revoke_user_sessions(user.email)
    except Exception as e:
        # Best effort: Redis may be disabled. The password is already changed,
        # which is the part the user asked for, so this must not 500.
        logger.error("Failed to revoke sessions for %s after reset: %s", user.email, e)

    logger.info("Password reset completed for user %s", user.id)
    return {"message": "Password updated. You can sign in with your new password."}
