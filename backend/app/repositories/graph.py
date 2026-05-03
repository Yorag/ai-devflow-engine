from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.api.error_codes import ErrorCode
from backend.app.db.models.graph import GraphDefinitionModel, GraphThreadModel
from backend.app.domain.graph_definition import GraphDefinition


class GraphRepositoryError(RuntimeError):
    def __init__(
        self,
        message: str = "Graph storage is unavailable.",
        *,
        error_code: ErrorCode = ErrorCode.CONFIG_STORAGE_UNAVAILABLE,
    ) -> None:
        self.error_code = error_code
        self.message = message
        super().__init__(message)


class GraphRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save_definition(self, definition: GraphDefinition) -> GraphDefinitionModel:
        payload = definition.model_dump(mode="json")
        try:
            model = GraphDefinitionModel(
                graph_definition_id=definition.graph_definition_id,
                run_id=definition.run_id,
                template_snapshot_ref=definition.template_snapshot_ref,
                graph_version=definition.graph_version,
                stage_nodes=payload["stage_nodes"],
                stage_contracts=payload["stage_contracts"],
                interrupt_policy=payload["interrupt_policy"],
                retry_policy=payload["retry_policy"],
                delivery_routing_policy=payload["delivery_routing_policy"],
                schema_version=definition.schema_version,
                created_at=definition.created_at,
            )
            self._session.add(model)
            self._session.flush()
            return model
        except SQLAlchemyError as exc:
            raise GraphRepositoryError() from exc

    def save_thread(
        self,
        *,
        thread_id: str,
        run_id: str,
        graph_definition_id: str,
        current_node_key: str,
        created_at,
    ) -> GraphThreadModel:
        try:
            model = GraphThreadModel(
                graph_thread_id=thread_id,
                run_id=run_id,
                graph_definition_id=graph_definition_id,
                checkpoint_namespace=f"{run_id}-main",
                current_node_key=current_node_key,
                current_interrupt_id=None,
                status="running",
                last_checkpoint_ref=None,
                created_at=created_at,
                updated_at=created_at,
            )
            self._session.add(model)
            self._session.flush()
            return model
        except SQLAlchemyError as exc:
            raise GraphRepositoryError() from exc


__all__ = [
    "GraphRepository",
    "GraphRepositoryError",
]
