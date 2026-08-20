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

The provider accounts the platform pays for, and the machinery that keeps every
tenant using them in step with the operator's current keys.
"""

from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.model_catalog import is_known_provider
from app.core.security import decrypt_api_key, encrypt_api_key
from app.models.ai_config import AIConfig, AIModelType
from app.models.platform_ai import PlatformAIConfig

logger = get_logger(__name__)



def get_config(db: Session) -> PlatformAIConfig:
    """The platform configuration row, created empty if it has never been saved.

    Returning a row rather than None keeps every caller off the `if config is
    None` path; an unconfigured platform is expressed by `is_configured` being
    False, which is the question callers actually want to ask.
    """
    config = db.get(PlatformAIConfig, PlatformAIConfig.SINGLETON_ID)
    if config is None:
        config = PlatformAIConfig(id=PlatformAIConfig.SINGLETON_ID)
        db.add(config)
        db.flush()
    return config


def _resolve(provider: Optional[str], model: Optional[str],
             encrypted: Optional[str]) -> Optional[Tuple[str, str, str]]:
    if not (provider and model and encrypted):
        return None
    return provider.upper(), model, decrypt_api_key(encrypted)


def text_credentials(db: Session) -> Optional[Tuple[str, str, str]]:
    """(provider, model, api_key) for text messages, or None if unconfigured."""
    c = get_config(db)
    return _resolve(c.text_provider, c.text_model, c.text_encrypted_api_key)


def image_credentials(db: Session) -> Optional[Tuple[str, str, str]]:
    """(provider, model, api_key) for messages carrying an image."""
    c = get_config(db)
    return _resolve(c.image_provider, c.image_model, c.image_encrypted_api_key)


def fallback_credentials(db: Session) -> Optional[Tuple[str, str, str]]:
    """(provider, model, api_key) to use when the primary text model is failing.

    The fallback deliberately has no key of its own: it must name one of the two
    providers already configured, and borrows that account. A third set of
    credentials that nothing exercises until an outage is a set of credentials
    nobody notices has expired.
    """
    c = get_config(db)
    if not (c.fallback_enabled and c.fallback_provider and c.fallback_model):
        return None

    provider = c.fallback_provider.upper()
    for configured_provider, encrypted in (
        (c.text_provider, c.text_encrypted_api_key),
        (c.image_provider, c.image_encrypted_api_key),
    ):
        if configured_provider and configured_provider.upper() == provider and encrypted:
            return provider, c.fallback_model, decrypt_api_key(encrypted)

    logger.warning(
        "Fallback provider %s has no configured key; fallback is inert", provider
    )
    return None


class PlatformAIError(ValueError):
    """Raised when a proposed platform configuration could not be served."""


def save_config(db: Session, payload: dict) -> PlatformAIConfig:
    """Write the operator's configuration. Caller commits.

    `payload` carries plaintext keys under `text.api_key` / `image.api_key`, and
    omits them when the operator left the field untouched — the console never
    receives a key back, so it cannot echo one, and treating "absent" as "clear
    it" would wipe working credentials on every unrelated save.
    """
    config = get_config(db)

    text = payload.get("text") or {}
    image = payload.get("image") or {}
    fallback = payload.get("fallback") or {}

    for section, data in (("text", text), ("image", image)):
        provider = data.get("provider")
        if provider and not is_known_provider(provider.upper()):
            raise PlatformAIError(f"Unknown {section} provider: {provider}")

    config.text_provider = text.get("provider") or None
    config.text_model = text.get("model") or None
    if text.get("api_key"):
        config.text_encrypted_api_key = encrypt_api_key(text["api_key"])

    config.image_provider = image.get("provider") or None
    config.image_model = image.get("model") or None
    if image.get("api_key"):
        config.image_encrypted_api_key = encrypt_api_key(image["api_key"])

    # Clearing a provider must clear its key too, or the next save that names a
    # different provider would silently pair it with the old account's secret.
    if not config.text_provider:
        config.text_encrypted_api_key = None
    if not config.image_provider:
        config.image_encrypted_api_key = None

    config.fallback_enabled = bool(fallback.get("enabled"))
    config.fallback_provider = fallback.get("provider") or None
    config.fallback_model = fallback.get("model") or None

    if config.fallback_enabled:
        configured = {p.upper() for p in (config.text_provider, config.image_provider) if p}
        if not config.fallback_provider or config.fallback_provider.upper() not in configured:
            raise PlatformAIError(
                "The fallback must use a provider that is already configured above, "
                "so it borrows a key that is known to work."
            )

    if not config.is_configured:
        # Refusing here rather than at first use: a tenant discovering the
        # platform model is unusable does so mid-conversation with a customer.
        raise PlatformAIError(
            "A text provider, model and API key are required before the platform "
            "model can be offered to tenants."
        )

    return config


def sync_tenant_configs(db: Session) -> int:
    """Re-point every tenant on the platform model at the current credentials.

    Tenant rows store their own copy of the key, which is what every consumer
    already decrypts. Without this, rotating the platform key would leave every
    hosted tenant authenticating with the retired secret — the rotation would
    look successful in the console and break chat everywhere.

    Returns the number of tenants updated. Caller commits.
    """
    credentials = text_credentials(db)
    if credentials is None:
        return 0
    provider, model, api_key = credentials

    rows = db.query(AIConfig).filter(AIConfig.is_platform_managed.is_(True)).all()
    encrypted = encrypt_api_key(api_key)
    for row in rows:
        # The provider moves too: an operator switching the platform from Groq
        # to Gemini changes which client every hosted tenant must be built with.
        row.model_type = AIModelType(provider)
        row.model_name = model
        row.encrypted_api_key = encrypted

    if rows:
        logger.info("Re-pointed %d tenant(s) at the platform model %s", len(rows), model)
    return len(rows)
