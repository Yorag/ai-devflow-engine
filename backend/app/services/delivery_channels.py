from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.app.db.models.control import DeliveryChannelModel
from backend.app.domain.enums import (
    CredentialStatus,
    DeliveryMode,
    DeliveryReadinessStatus,
)


DEFAULT_PROJECT_ID = "project-default"
DEFAULT_DELIVERY_CHANNEL_ID = "delivery-default"


def _default_channel_id(project_id: str) -> str:
    if project_id == DEFAULT_PROJECT_ID:
        return DEFAULT_DELIVERY_CHANNEL_ID
    digest = hashlib.sha256(project_id.encode("utf-8")).hexdigest()
    return f"delivery-{digest[:24]}"


class DeliveryChannelService:
    def __init__(
        self,
        session: Session,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._now = now or (lambda: datetime.now(UTC))

    def ensure_default_channel(self, project_id: str) -> DeliveryChannelModel:
        delivery_channel_id = _default_channel_id(project_id)
        existing = self._session.get(DeliveryChannelModel, delivery_channel_id)
        if existing is not None:
            return existing

        timestamp = self._now()
        channel = DeliveryChannelModel(
            delivery_channel_id=delivery_channel_id,
            project_id=project_id,
            delivery_mode=DeliveryMode.DEMO_DELIVERY,
            scm_provider_type=None,
            repository_identifier=None,
            default_branch=None,
            code_review_request_type=None,
            credential_ref=None,
            credential_status=CredentialStatus.READY,
            readiness_status=DeliveryReadinessStatus.READY,
            readiness_message=None,
            last_validated_at=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._session.add(channel)
        self._session.flush()
        return channel


__all__ = [
    "DEFAULT_DELIVERY_CHANNEL_ID",
    "DEFAULT_PROJECT_ID",
    "DeliveryChannelService",
]
