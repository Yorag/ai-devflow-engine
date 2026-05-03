from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.db.models.runtime import (
    ModelBindingSnapshotModel,
    ProviderSnapshotModel,
)
from backend.app.domain.provider_snapshot import (
    ModelBindingSnapshot,
    ProviderSnapshot,
)


class RuntimeSnapshotRepositoryError(RuntimeError):
    pass


class RuntimeSnapshotRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save_provider_snapshot(
        self,
        snapshot: ProviderSnapshot,
    ) -> ProviderSnapshotModel:
        try:
            model = ProviderSnapshotModel(
                snapshot_id=snapshot.snapshot_id,
                run_id=snapshot.run_id,
                provider_id=snapshot.provider_id,
                display_name=snapshot.display_name,
                provider_source=snapshot.provider_source,
                protocol_type=snapshot.protocol_type,
                base_url=snapshot.base_url,
                api_key_ref=snapshot.api_key_ref,
                model_id=snapshot.model_id,
                capabilities=snapshot.capabilities.model_dump(mode="python"),
                source_config_version=snapshot.source_config_version,
                schema_version=snapshot.schema_version,
                created_at=snapshot.created_at,
            )
            self._session.add(model)
            self._session.flush()
            return model
        except SQLAlchemyError as exc:
            raise RuntimeSnapshotRepositoryError(
                "Runtime snapshot storage is unavailable."
            ) from exc

    def save_model_binding_snapshot(
        self,
        snapshot: ModelBindingSnapshot,
    ) -> ModelBindingSnapshotModel:
        try:
            model = ModelBindingSnapshotModel(
                snapshot_id=snapshot.snapshot_id,
                run_id=snapshot.run_id,
                binding_id=snapshot.binding_id,
                binding_type=snapshot.binding_type,
                stage_type=snapshot.stage_type,
                role_id=snapshot.role_id,
                provider_snapshot_id=snapshot.provider_snapshot_id,
                provider_id=snapshot.provider_id,
                model_id=snapshot.model_id,
                capabilities=snapshot.capabilities.model_dump(mode="python"),
                model_parameters=dict(snapshot.model_parameters),
                source_config_version=snapshot.source_config_version,
                schema_version=snapshot.schema_version,
                created_at=snapshot.created_at,
            )
            self._session.add(model)
            self._session.flush()
            return model
        except SQLAlchemyError as exc:
            raise RuntimeSnapshotRepositoryError(
                "Runtime snapshot storage is unavailable."
            ) from exc


__all__ = [
    "RuntimeSnapshotRepository",
    "RuntimeSnapshotRepositoryError",
]
