from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, ProviderModel
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import ProviderProtocolType, ProviderSource
from backend.app.domain.trace_context import TraceContext
from backend.app.schemas.observability import AuditActorType, AuditResult


NOW = datetime(2026, 5, 2, 10, 11, 12, tzinfo=UTC)


class RecordingAuditService:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record_command_result(self, **kwargs: Any) -> object:
        self.records.append(kwargs)
        return object()


class FailingAuditService:
    def record_command_result(self, **kwargs: Any) -> object:
        raise RuntimeError("audit ledger unavailable")


class FailsOnSecondAuditService:
    def __init__(self) -> None:
        self.committed_records: list[dict[str, Any]] = []

    def record_command_result(self, **kwargs: Any) -> object:
        if self.committed_records:
            raise RuntimeError("audit ledger unavailable")
        self.committed_records.append(kwargs)
        return object()


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-provider-seed",
        trace_id="trace-provider-seed",
        correlation_id="correlation-provider-seed",
        span_id="span-provider-seed",
        parent_span_id=None,
        created_at=NOW,
    )


def build_manager(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(
        _database_paths={
            role: tmp_path / f"{role.value}.db"
            for role in DatabaseRole
        },
        _database_urls={
            role: f"sqlite:///{(tmp_path / f'{role.value}.db').as_posix()}"
            for role in DatabaseRole
        },
    )
    ControlBase.metadata.create_all(manager.engine(DatabaseRole.CONTROL))
    return manager


def test_apply_model_capability_defaults_fills_missing_runtime_fields() -> None:
    from backend.app.services.providers import ProviderService

    capabilities = ProviderService.apply_model_capability_defaults(
        [{"model_id": "model-a"}]
    )

    assert capabilities == [
        {
            "model_id": "model-a",
            "context_window_tokens": 128000,
            "max_output_tokens": 4096,
            "supports_tool_calling": False,
            "supports_structured_output": False,
            "supports_native_reasoning": False,
        }
    ]


def test_seed_builtin_providers_creates_formal_provider_rows_and_audit(
    tmp_path: Path,
) -> None:
    from backend.app.services.providers import ProviderService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        providers = ProviderService(
            session,
            audit_service=audit,
            now=lambda: NOW,
        ).seed_builtin_providers(trace_context=build_trace())

    assert [provider.provider_id for provider in providers] == [
        "provider-volcengine",
        "provider-deepseek",
    ]
    assert [provider.display_name for provider in providers] == ["火山引擎", "DeepSeek"]
    assert providers[0].provider_source is ProviderSource.BUILTIN
    assert providers[0].protocol_type is ProviderProtocolType.VOLCENGINE_NATIVE
    assert providers[0].base_url == "https://ark.cn-beijing.volces.com/api/v3"
    assert providers[0].api_key_ref is None
    assert providers[0].default_model_id == "doubao-seed-1-6"
    assert providers[0].supported_model_ids == ["doubao-seed-1-6"]
    assert providers[0].is_configured is False
    assert providers[0].is_enabled is True
    assert providers[1].provider_source is ProviderSource.BUILTIN
    assert providers[1].protocol_type is ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE
    assert providers[1].base_url == "https://api.deepseek.com"
    assert providers[1].api_key_ref is None
    assert providers[1].default_model_id == "deepseek-chat"
    assert providers[1].supported_model_ids == [
        "deepseek-chat",
        "deepseek-reasoner",
    ]
    assert providers[1].is_configured is False
    assert providers[1].is_enabled is True
    assert "OpenAI Completions compatible" not in {
        provider.display_name for provider in providers
    }
    assert all(provider.created_at == NOW for provider in providers)
    assert len(audit.records) == 1
    assert {record["action"] for record in audit.records} == {"provider.seed_builtin"}
    assert {record["target_type"] for record in audit.records} == {"provider"}
    assert {record["target_id"] for record in audit.records} == {"builtin-provider-seed"}
    assert {record["actor_type"] for record in audit.records} == {
        AuditActorType.SYSTEM
    }
    assert {record["actor_id"] for record in audit.records} == {"control-plane-seed"}
    assert {record["result"] for record in audit.records} == {AuditResult.SUCCEEDED}
    assert audit.records[0]["metadata"]["provider_ids"] == [
        "provider-volcengine",
        "provider-deepseek",
    ]
    assert all("VOLCENGINE_API_KEY_VALUE" not in str(record) for record in audit.records)
    assert all("DEEPSEEK_API_KEY_VALUE" not in str(record) for record in audit.records)


def test_builtin_provider_runtime_capabilities_are_per_model(
    tmp_path: Path,
) -> None:
    from backend.app.services.providers import ProviderService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        providers = ProviderService(
            session,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        ).seed_builtin_providers(trace_context=build_trace())

    capabilities_by_provider = {
        provider.provider_id: {
            capability["model_id"]: capability
            for capability in provider.runtime_capabilities
        }
        for provider in providers
    }

    volcengine = capabilities_by_provider["provider-volcengine"]["doubao-seed-1-6"]
    assert volcengine["context_window_tokens"] == 128000
    assert volcengine["max_output_tokens"] == 8192
    assert volcengine["supports_tool_calling"] is True
    assert volcengine["supports_structured_output"] is True
    assert volcengine["supports_native_reasoning"] is False

    deepseek_reasoner = capabilities_by_provider["provider-deepseek"][
        "deepseek-reasoner"
    ]
    assert deepseek_reasoner["context_window_tokens"] == 128000
    assert deepseek_reasoner["max_output_tokens"] == 8192
    assert deepseek_reasoner["supports_tool_calling"] is False
    assert deepseek_reasoner["supports_structured_output"] is False
    assert deepseek_reasoner["supports_native_reasoning"] is True


def test_seed_builtin_providers_is_idempotent_and_returns_ordered_rows(
    tmp_path: Path,
) -> None:
    from backend.app.services.providers import ProviderService

    manager = build_manager(tmp_path)
    audit = RecordingAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        service = ProviderService(
            session,
            audit_service=audit,
            now=lambda: NOW,
        )
        first = service.seed_builtin_providers(trace_context=build_trace())
        second = service.seed_builtin_providers(trace_context=build_trace())
        saved_count = session.query(ProviderModel).count()

    assert saved_count == 2
    assert [provider.provider_id for provider in second] == [
        provider.provider_id for provider in first
    ]
    assert len(audit.records) == 1


def test_list_providers_returns_configured_rows_without_unadded_builtin_rows(
    tmp_path: Path,
) -> None:
    from backend.app.services.providers import ProviderService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        session.add(
            ProviderModel(
                provider_id="provider-custom",
                display_name="Custom Provider",
                provider_source=ProviderSource.CUSTOM,
                protocol_type=ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE,
                base_url="https://example.test",
                api_key_ref="env:CUSTOM_PROVIDER_API_KEY",
                default_model_id="custom-chat",
                supported_model_ids=["custom-chat"],
                is_configured=True,
                is_enabled=True,
                runtime_capabilities=[
                    {
                        "model_id": "custom-chat",
                        "context_window_tokens": 128000,
                        "max_output_tokens": 4096,
                        "supports_tool_calling": False,
                        "supports_structured_output": False,
                        "supports_native_reasoning": False,
                    }
                ],
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()

        providers = ProviderService(
            session,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        ).list_providers(trace_context=build_trace())

    assert [provider.provider_id for provider in providers] == ["provider-custom"]


def test_provider_seed_uses_single_batch_audit_to_avoid_partial_success(
    tmp_path: Path,
) -> None:
    from backend.app.services.providers import ProviderService

    manager = build_manager(tmp_path)
    audit = FailsOnSecondAuditService()

    with manager.session(DatabaseRole.CONTROL) as session:
        service = ProviderService(
            session,
            audit_service=audit,
            now=lambda: NOW,
        )
        providers = service.seed_builtin_providers(trace_context=build_trace())

        saved_providers = session.query(ProviderModel).all()

    saved_ids = {provider.provider_id for provider in saved_providers}
    assert saved_ids == {"provider-volcengine", "provider-deepseek"}
    assert [provider.provider_id for provider in providers] == [
        "provider-volcengine",
        "provider-deepseek",
    ]
    assert len(audit.committed_records) == 1
    assert audit.committed_records[0]["target_id"] == "builtin-provider-seed"


def test_provider_seed_audit_failure_does_not_leave_partial_control_rows(
    tmp_path: Path,
) -> None:
    from backend.app.services.providers import ProviderService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        service = ProviderService(
            session,
            audit_service=FailingAuditService(),
            now=lambda: NOW,
        )
        with pytest.raises(RuntimeError, match="audit ledger unavailable"):
            service.seed_builtin_providers(trace_context=build_trace())

        saved_providers = session.query(ProviderModel).all()

    assert saved_providers == []
