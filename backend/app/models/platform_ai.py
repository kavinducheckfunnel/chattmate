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

from sqlalchemy import Boolean, Column, DateTime, Integer, String, func

from app.database import Base


class PlatformAIConfig(Base):
    """The provider accounts the platform itself pays for.

    This backs the managed ``CHATTERMATE`` model type: a tenant may either bring
    their own provider key, or select the platform model and be metered against
    their plan's message allowance. These are the credentials behind that second
    option, so they belong to the operator, not to any organization — nothing
    here is scoped by ``organization_id`` and no tenant-facing endpoint reads it.

    Text and image are separate because they are separately priced and separately
    capped: plans sell "messages per month" and "image requests per month" as
    different allowances, and routing an image to a text-only model fails at the
    provider rather than at our own boundary.

    Stored as a single row (``id == SINGLETON_ID``). A settings table with one
    row is unusual, but the alternative — key/value pairs — loses the column
    types and lets half a configuration be saved: a provider without its model,
    or a model whose key was never set.
    """

    __tablename__ = "platform_ai_config"

    # Fixed: there is one platform, so there is one configuration. Enforced by
    # the service layer, which only ever reads and writes this id.
    SINGLETON_ID = 1

    id = Column(Integer, primary_key=True, default=SINGLETON_ID)

    # Answers messages that arrive without an image. Required for the platform
    # model to be offered at all.
    text_provider = Column(String(32), nullable=True)
    text_model = Column(String(128), nullable=True)
    text_encrypted_api_key = Column(String, nullable=True)

    # Optional. Without it the platform model simply has no image capability,
    # which is a coherent state — the Free plan sells no image allowance either.
    image_provider = Column(String(32), nullable=True)
    image_model = Column(String(128), nullable=True)
    image_encrypted_api_key = Column(String, nullable=True)

    # Used when the primary text provider is failing, so conversations continue
    # through an outage instead of returning errors to end customers.
    fallback_enabled = Column(Boolean, nullable=False, default=False)
    fallback_provider = Column(String(32), nullable=True)
    fallback_model = Column(String(128), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    @property
    def is_configured(self) -> bool:
        """Whether the platform model can actually serve a message.

        Text is the floor: a config with only image credentials cannot answer
        anything, and offering the platform model on that basis would let a
        tenant select a model that fails on their first real conversation.
        """
        return bool(self.text_provider and self.text_model and self.text_encrypted_api_key)

    @property
    def supports_images(self) -> bool:
        return bool(self.image_provider and self.image_model and self.image_encrypted_api_key)

    def to_dict(self) -> dict:
        """Serialised for the operator console.

        API keys are never included, not even masked. A masked key still reveals
        which provider account is in use and how long the secret is; the console
        only needs to know whether one is set.
        """
        return {
            "text": {
                "provider": self.text_provider,
                "model": self.text_model,
                "has_api_key": bool(self.text_encrypted_api_key),
            },
            "image": {
                "provider": self.image_provider,
                "model": self.image_model,
                "has_api_key": bool(self.image_encrypted_api_key),
            },
            "fallback": {
                "enabled": self.fallback_enabled,
                "provider": self.fallback_provider,
                "model": self.fallback_model,
            },
            "is_configured": self.is_configured,
            "supports_images": self.supports_images,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
