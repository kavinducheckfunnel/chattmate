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

Cookie lifetimes, which had drifted away from the comments describing them.

The login handler set the access cookie to `max_age=180  # 30 minutes` — three
minutes — so a browser dropped it almost immediately after signing in. Nothing
asserted the number, and a comment is not a test.
"""

import re
from datetime import timedelta
from pathlib import Path

from jose import jwt

from app.core import security
from app.core.security import (
    ACCESS_COOKIE_MAX_AGE,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_COOKIE_MAX_AGE,
    REFRESH_TOKEN_EXPIRE_DAYS,
    USER_INFO_COOKIE_MAX_AGE,
    create_access_token,
    create_refresh_token,
)

API_SOURCES = (
    Path(__file__).resolve().parents[2] / "app" / "api" / "users.py",
    Path(__file__).resolve().parents[2] / "app" / "api" / "organizations.py",
)


def test_cookie_max_age_matches_token_lifetime():
    """The cookie must not outlive, or fall short of, the token inside it."""
    assert ACCESS_COOKIE_MAX_AGE == ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert REFRESH_COOKIE_MAX_AGE == REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600
    # The SPA reads user_info to know who is signed in; a shorter life would log
    # the UI out while the refresh token could still have revived the session.
    assert USER_INFO_COOKIE_MAX_AGE == REFRESH_COOKIE_MAX_AGE


def test_access_token_outlives_a_working_session():
    """Regression: three minutes is not a session.

    The exact value is a product decision, but anything under an hour means a
    user is refreshing constantly and any hiccup during one of those refreshes
    shows up as a surprise sign-out.
    """
    assert ACCESS_COOKIE_MAX_AGE >= 3600


def test_no_hardcoded_cookie_lifetimes_remain():
    """Literal max_age values are how the comment and the number drifted apart.

    Every set_cookie must derive its lifetime from the constants above, so the
    two cannot disagree again.
    """
    for source in API_SOURCES:
        text = source.read_text()
        literals = re.findall(r"max_age=(\d+)", text)
        assert not literals, f"{source.name} still hardcodes max_age={literals}"


def test_tokens_carry_the_expected_expiry():
    """The lifetime constants must reach the JWT, not just the cookie."""
    payload = {"sub": "user-id", "org": "org-id"}

    access = jwt.decode(
        create_access_token(payload), security.SECRET_KEY, algorithms=[security.ALGORITHM]
    )
    refresh = jwt.decode(
        create_refresh_token(payload), security.SECRET_KEY, algorithms=[security.ALGORITHM]
    )

    lifetime = access["exp"] - refresh["iat"] if "iat" in refresh else None
    # Compare the two expiries against each other rather than wall-clock, which
    # keeps the test stable on a slow machine.
    assert refresh["exp"] > access["exp"]

    expected_gap = timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS) - timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )
    actual_gap = timedelta(seconds=refresh["exp"] - access["exp"])
    assert abs(actual_gap - expected_gap) < timedelta(seconds=5)
    assert lifetime is None or lifetime > 0
