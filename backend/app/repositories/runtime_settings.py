from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.db.models.control import PlatformRuntimeSettingsModel


RUNTIME_SETTINGS_ID = "platform-runtime-settings"


class RuntimeSettingsRepositoryError(RuntimeError):
    pass


class RuntimeSettingsVersionConflict(RuntimeSettingsRepositoryError):
    pass


class PlatformRuntimeSettingsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_current(self) -> PlatformRuntimeSettingsModel | None:
        try:
            return self._session.get(PlatformRuntimeSettingsModel, RUNTIME_SETTINGS_ID)
        except SQLAlchemyError as exc:
            raise RuntimeSettingsRepositoryError(
                "PlatformRuntimeSettings storage is unavailable."
            ) from exc

    def save_new_version(
        self,
        model: PlatformRuntimeSettingsModel,
        *,
        expected_config_version: str | None = None,
    ) -> PlatformRuntimeSettingsModel:
        try:
            if expected_config_version is not None:
                return self._conditional_update(model, expected_config_version)
            self._session.add(model)
            self._session.flush()
            return model
        except SQLAlchemyError as exc:
            raise RuntimeSettingsRepositoryError(
                "PlatformRuntimeSettings storage is unavailable."
            ) from exc

    def _conditional_update(
        self,
        model: PlatformRuntimeSettingsModel,
        expected_config_version: str,
    ) -> PlatformRuntimeSettingsModel:
        values = self._model_values(model)
        with self._session.no_autoflush:
            result = self._session.execute(
                update(PlatformRuntimeSettingsModel)
                .where(
                    PlatformRuntimeSettingsModel.settings_id == model.settings_id,
                    PlatformRuntimeSettingsModel.config_version
                    == expected_config_version,
                )
                .values(**values)
            )
        if result.rowcount != 1:
            raise RuntimeSettingsVersionConflict(
                "PlatformRuntimeSettings expected_config_version does not match "
                "the current version."
            )
        self._session.expire(model)
        refreshed = self._session.get(PlatformRuntimeSettingsModel, model.settings_id)
        if refreshed is None:
            raise RuntimeSettingsRepositoryError(
                "PlatformRuntimeSettings storage is unavailable."
            )
        return refreshed

    def _model_values(self, model: PlatformRuntimeSettingsModel) -> dict[str, Any]:
        return {
            "config_version": model.config_version,
            "schema_version": model.schema_version,
            "hard_limits_version": model.hard_limits_version,
            "agent_limits": dict(model.agent_limits),
            "provider_call_policy": dict(model.provider_call_policy),
            "internal_model_bindings": dict(model.internal_model_bindings),
            "context_limits": dict(model.context_limits),
            "log_policy": dict(model.log_policy),
            "created_by_actor_id": model.created_by_actor_id,
            "updated_by_actor_id": model.updated_by_actor_id,
            "last_audit_log_id": model.last_audit_log_id,
            "last_trace_id": model.last_trace_id,
            "updated_at": self._required_datetime(model.updated_at),
        }

    @staticmethod
    def _required_datetime(value: datetime | None) -> datetime:
        if value is None:
            raise RuntimeSettingsRepositoryError(
                "PlatformRuntimeSettings updated_at is required."
            )
        return value


__all__ = [
    "PlatformRuntimeSettingsRepository",
    "RUNTIME_SETTINGS_ID",
    "RuntimeSettingsRepositoryError",
    "RuntimeSettingsVersionConflict",
]
