from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.db.models.runtime import (
    ModelBindingSnapshotModel,
    StageRunModel,
    ProviderCallPolicySnapshotModel,
    ProviderSnapshotModel,
    RuntimeLimitSnapshotModel,
)
from backend.app.domain.enums import StageStatus, StageType
from backend.app.domain.provider_call_policy_snapshot import (
    ProviderCallPolicySnapshot,
)
from backend.app.domain.provider_snapshot import (
    ModelBindingSnapshot,
    ProviderSnapshot,
)
from backend.app.domain.runtime_limit_snapshot import RuntimeLimitSnapshot


class RuntimeSnapshotRepositoryError(RuntimeError):
    def __init__(
        self,
        message: str = "Runtime snapshot storage is unavailable.",
        *,
        error_code: ErrorCode = ErrorCode.CONFIG_STORAGE_UNAVAILABLE,
    ) -> None:
        self.error_code = error_code
        self.message = message
        super().__init__(message)


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
            raise RuntimeSnapshotRepositoryError() from exc

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
            raise RuntimeSnapshotRepositoryError() from exc

    def save_runtime_limit_snapshot(
        self,
        snapshot: RuntimeLimitSnapshot,
    ) -> RuntimeLimitSnapshotModel:
        try:
            model = RuntimeLimitSnapshotModel(
                snapshot_id=snapshot.snapshot_id,
                run_id=snapshot.run_id,
                agent_limits=snapshot.agent_limits.model_dump(mode="python"),
                context_limits=snapshot.context_limits.model_dump(mode="python"),
                source_config_version=snapshot.source_config_version,
                hard_limits_version=snapshot.hard_limits_version,
                schema_version=snapshot.schema_version,
                created_at=snapshot.created_at,
            )
            self._session.add(model)
            self._session.flush()
            return model
        except SQLAlchemyError as exc:
            raise RuntimeSnapshotRepositoryError() from exc

    def save_provider_call_policy_snapshot(
        self,
        snapshot: ProviderCallPolicySnapshot,
    ) -> ProviderCallPolicySnapshotModel:
        try:
            model = ProviderCallPolicySnapshotModel(
                snapshot_id=snapshot.snapshot_id,
                run_id=snapshot.run_id,
                provider_call_policy=snapshot.provider_call_policy.model_dump(
                    mode="python"
                ),
                source_config_version=snapshot.source_config_version,
                schema_version=snapshot.schema_version,
                created_at=snapshot.created_at,
            )
            self._session.add(model)
            self._session.flush()
            return model
        except SQLAlchemyError as exc:
            raise RuntimeSnapshotRepositoryError() from exc


class StageRunRepositoryError(RuntimeError):
    def __init__(
        self,
        message: str = "Stage run storage is unavailable.",
        *,
        error_code: ErrorCode = ErrorCode.CONFIG_STORAGE_UNAVAILABLE,
    ) -> None:
        self.error_code = error_code
        self.message = message
        super().__init__(message)


class StageRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_stage_run(
        self,
        *,
        stage_run_id: str,
        run_id: str,
        stage_type: StageType,
        status: StageStatus,
        attempt_index: int,
        graph_node_key: str,
        stage_contract_ref: str,
        input_ref: str | None,
        output_ref: str | None,
        summary: str | None,
        started_at,
        created_at,
        updated_at,
        ended_at=None,
    ) -> StageRunModel:
        try:
            model = StageRunModel(
                stage_run_id=stage_run_id,
                run_id=run_id,
                stage_type=stage_type,
                status=status,
                attempt_index=attempt_index,
                graph_node_key=graph_node_key,
                stage_contract_ref=stage_contract_ref,
                input_ref=input_ref,
                output_ref=output_ref,
                summary=summary,
                started_at=started_at,
                ended_at=ended_at,
                created_at=created_at,
                updated_at=updated_at,
            )
            self._session.add(model)
            self._session.flush()
            return model
        except SQLAlchemyError as exc:
            raise StageRunRepositoryError() from exc

    def get_stage_run(self, stage_run_id: str) -> StageRunModel | None:
        try:
            return self._session.get(StageRunModel, stage_run_id)
        except SQLAlchemyError as exc:
            raise StageRunRepositoryError() from exc

    def save(self, stage_run: StageRunModel) -> StageRunModel:
        try:
            self._session.add(stage_run)
            self._session.flush()
            return stage_run
        except SQLAlchemyError as exc:
            raise StageRunRepositoryError() from exc


__all__ = [
    "RuntimeSnapshotRepository",
    "RuntimeSnapshotRepositoryError",
    "StageRunRepository",
    "StageRunRepositoryError",
]
