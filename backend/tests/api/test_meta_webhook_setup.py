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

The webhook values handed to a customer to paste into their own Meta app.

These were displayed with total confidence whatever they contained. A
deployment whose BACKEND_URL still said localhost showed a localhost callback
URL as if it were ready; the customer pasted it, the handshake never fired, and
nothing in the product suggested the values themselves were the problem.
"""

import pytest

from app.api.channels.meta import _webhook_setup_problems, _is_placeholder


@pytest.fixture
def configured(monkeypatch):
    """A deployment that is actually set up correctly."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "META_WEBHOOK_VERIFY_TOKEN", "b7f2c1a9d4e6", raising=False)
    monkeypatch.setattr(settings, "META_APP_SECRET", "0123456789abcdef0123456789abcdef", raising=False)
    return settings


def test_a_correct_deployment_reports_no_problems(configured):
    assert _webhook_setup_problems("https://chat.example.com") == []


def test_localhost_callback_is_rejected(configured):
    problems = _webhook_setup_problems("http://localhost:8000")
    assert any("localhost" in p for p in problems)


@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0", "::1"])
def test_every_loopback_form_is_rejected(configured, host):
    """Meta has to reach this from the public internet; none of these qualify."""
    base = f"http://[{host}]:8000" if host == "::1" else f"http://{host}:8000"
    assert _webhook_setup_problems(base), f"{host} should have been flagged"


def test_plain_http_is_rejected(configured):
    """Meta refuses non-HTTPS callbacks outright."""
    problems = _webhook_setup_problems("http://chat.example.com")
    assert any("https" in p.lower() for p in problems)


def test_unset_backend_url_is_reported(configured):
    problems = _webhook_setup_problems("")
    assert any("BACKEND_URL" in p for p in problems)


def test_placeholder_verify_token_is_reported(monkeypatch, configured):
    """The .env.example value is non-empty but has never been configured."""
    monkeypatch.setattr(configured, "META_WEBHOOK_VERIFY_TOKEN",
                        "any_random_string_you_choose", raising=False)
    problems = _webhook_setup_problems("https://chat.example.com")
    assert any("placeholder" in p.lower() for p in problems)


def test_missing_verify_token_is_reported(monkeypatch, configured):
    monkeypatch.setattr(configured, "META_WEBHOOK_VERIFY_TOKEN", "", raising=False)
    problems = _webhook_setup_problems("https://chat.example.com")
    assert any("META_WEBHOOK_VERIFY_TOKEN" in p for p in problems)


def test_missing_app_secret_is_reported(monkeypatch, configured):
    """The quietest failure of the three.

    The handshake still succeeds without an app secret, so the connection looks
    healthy — and then every delivered message fails its signature check and is
    dropped, with nothing on screen to explain it.

    Since accounts carry their own app secret, this is no longer a server the
    customer cannot fix: the message has to point at the field in front of them
    rather than at an environment variable they have no access to.
    """
    monkeypatch.setattr(configured, "META_APP_SECRET", "your_meta_app_secret", raising=False)
    problems = _webhook_setup_problems("https://chat.example.com")
    assert any("App secret" in p and "your own Meta app" in p for p in problems)


@pytest.mark.parametrize("value,expected", [
    ("your_meta_app_secret", True),
    ("any_random_string_you_choose", True),
    ("changeme", True),
    ("REPLACE_ME_NOW", True),
    # Reached production and was reported as correctly configured, because the
    # check was a prefix denylist and this prefix was not on it.
    ("PASTE_YOUR_APP_SECRET_HERE", True),
    ("YOUR_APP_SECRET", True),
    ("b7f2c1a9d4e6", False),
    # A real secret that merely starts with similar letters must not be flagged.
    ("yourealsecret123", False),
    # Real secrets are lowercase hex; neither of these is instruction-shaped.
    ("0123456789abcdef0123456789abcdef", False),
    ("A1B2C3D4E5F60718293A4B5C6D7E8F90", False),
])
def test_placeholder_detection(value, expected):
    assert _is_placeholder(value) is expected


def test_app_secret_of_the_wrong_shape_is_reported(monkeypatch, configured):
    """A truncated or mistyped secret fails silently at signature-check time.

    Meta issues exactly 32 hex characters, so the shape is checkable — and
    checking it catches a bad paste that no list of known placeholder words
    ever would.
    """
    monkeypatch.setattr(configured, "META_APP_SECRET", "abc123", raising=False)
    problems = _webhook_setup_problems("https://chat.example.com")
    assert any("32 hexadecimal" in p for p in problems)


def test_a_correctly_shaped_secret_passes(monkeypatch, configured):
    monkeypatch.setattr(configured, "META_APP_SECRET",
                        "0123456789abcdef0123456789abcdef", raising=False)
    assert _webhook_setup_problems("https://chat.example.com") == []
