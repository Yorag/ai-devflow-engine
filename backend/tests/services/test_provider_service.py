from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.app.api.error_codes import ErrorCode
from backend.app.db.base import DatabaseRole
from backend.app.db.models.control import ControlBase, ProviderModel
from backend.app.db.session import DatabaseManager
from backend.app.domain.enums import ProviderProtocolType, ProviderSource
from backend.app.domain.trace_context import TraceContext
from backend.app.schemas.observability import AuditActorType, AuditResult
from backend.app.schemas.provider import ProviderWriteRequest


NOW = datetime(2026, 5, 2, 13, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 5, 2, 13, 5, 0, tzinfo=UTC)


class RecordingAuditService:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record_command_result(self, **kwargs: Any) -> object:
        self.records.append({"method": "record_command_result", **kwargs})
        return object()

    def record_rejected_command(self, **kwargs: Any) -> object:
        self.records.append(
            {
                "method": "record_rejected_command",
                "result": AuditResult.REJECTED,
                **kwargs,
            }
        )
        return object()


class FailingAuditService:
    def record_command_result(self, **kwargs: Any) -> object:
        raise RuntimeError("audit ledger unavailable")

    def record_rejected_command(self, **kwargs: Any) -> object:
        raise RuntimeError("audit ledger unavailable")


def build_trace() -> TraceContext:
    return TraceContext(
        request_id="request-provider-command",
        trace_id="trace-provider-command",
        correlation_id="correlation-provider-command",
        span_id="span-provider-command",
        parent_span_id=None,
        created_at=NOW,
    )


def build_manager(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(
        _database_paths={role: tmp_path / f"{role.value}.db" for role in DatabaseRole},
        _database_urls={
            role: f"sqlite:///{(tmp_path / f'{role.value}.db').as_posix()}"
            for role in DatabaseRole
        },
    )
    ControlBase.metadata.create_all(manager.engine(DatabaseRole.CONTROL))
    return manager


def provider_request(
    *,
    display_name: str | None = "Team compatible model",
    protocol_type: ProviderProtocolType | None = None,
    base_url: str = "https://provider.example.test/v1",
    api_key_ref: str | None = "env:AI_DEVFLOW_CREDENTIAL_TEAM_PROVIDER_API_KEY",
    default_model_id: str = "team-chat",
    supported_model_ids: list[str] | None = None,
    runtime_capabilities: list[dict[str, Any]] | None = None,
) -> ProviderWriteRequest:
    model_ids = supported_model_ids or ["team-chat", "team-reasoner"]
    return ProviderWriteRequest(
        display_name=display_name,
        protocol_type=protocol_type,
        base_url=base_url,
        api_key_ref=api_key_ref,
        default_model_id=default_model_id,
        supported_model_ids=model_ids,
        runtime_capabilities=runtime_capabilities
        or [
            {
                "model_id": "team-chat",
                "max_output_tokens": 8192,
                "supports_tool_calling": True,
                "supports_structured_output": True,
                "supports_native_reasoning": False,
            },
            {"model_id": "team-reasoner"},
        ],
    )


def action_records(audit: RecordingAuditService, action: str) -> list[dict[str, Any]]:
    return [record for record in audit.records if record["action"] == action]


def test_create_custom_provider_defaults_capabilities_and_audits(
    tmp_path: Path,
) -> None:
    from backend.app.services.providers import ProviderService

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        service = ProviderService(session, audit_service=audit, now=lambda: NOW)
        provider = service.create_custom_provider(
            provider_request(),
            trace_context=build_trace(),
        )
        saved = session.get(ProviderModel, provider.provider_id)

    assert saved is not None
    assert provider.provider_id.startswith("provider-custom-")
    assert saved.provider_source is ProviderSource.CUSTOM
    assert saved.protocol_type is ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE
    assert saved.display_name == "Team compatible model"
    assert saved.default_model_id == "team-chat"
    assert saved.supported_model_ids == ["team-chat", "team-reasoner"]
    by_model = {item["model_id"]: item for item in saved.runtime_capabilities}
    assert by_model["team-chat"]["max_output_tokens"] == 8192
    assert by_model["team-chat"]["supports_tool_calling"] is True
    assert by_model["team-reasoner"]["context_window_tokens"] == 128000
    assert by_model["team-reasoner"]["max_output_tokens"] == 4096
    assert by_model["team-reasoner"]["supports_structured_output"] is False

    records = action_records(audit, "provider.create_custom")
    assert len(records) == 1
    record = records[0]
    assert record["method"] == "record_command_result"
    assert record["actor_type"] is AuditActorType.USER
    assert record["actor_id"] == "api-user"
    assert record["target_type"] == "provider"
    assert record["target_id"] == provider.provider_id
    assert record["result"] is AuditResult.SUCCEEDED
    assert record["metadata"]["provider_id"] == provider.provider_id
    assert record["metadata"]["provider_source"] == "custom"
    assert record["metadata"]["protocol_type"] == "openai_completions_compatible"
    assert record["metadata"]["api_key_ref"] == (
        "env:AI_DEVFLOW_CREDENTIAL_TEAM_PROVIDER_API_KEY"
    )
    assert "display_name" not in record["metadata"]
    assert "base_url" not in record["metadata"]
    assert "old_api_key_ref" not in record["metadata"]
    assert "new_api_key_ref" not in record["metadata"]
    assert "api_key_ref_changed" not in record["metadata"]
    assert record["metadata"]["ref_transition"] == {
        "changed": True,
        "before_ref": None,
        "after_ref": "env:AI_DEVFLOW_CREDENTIAL_TEAM_PROVIDER_API_KEY",
    }
    assert record["metadata"]["runtime_capability_flags"] == [
        {
            "model_id": "team-chat",
            "supports_tool_calling": True,
            "supports_structured_output": True,
            "supports_native_reasoning": False,
        },
        {
            "model_id": "team-reasoner",
            "supports_tool_calling": False,
            "supports_structured_output": False,
            "supports_native_reasoning": False,
        },
    ]
    assert "raw-secret" not in str(record["metadata"])


def test_patch_builtin_provider_runtime_config_preserves_identity_and_audits(
    tmp_path: Path,
) -> None:
    from backend.app.services.providers import ProviderService

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        service = ProviderService(session, audit_service=audit, now=lambda: NOW)
        service.seed_builtin_providers(trace_context=build_trace())
        updated = ProviderService(
            session,
            audit_service=audit,
            now=lambda: LATER,
        ).patch_builtin_provider_runtime_config(
            "provider-deepseek",
            provider_request(
                display_name=None,
                base_url="https://api.deepseek.example/v1",
                api_key_ref="env:DEEPSEEK_ROTATED_API_KEY",
                default_model_id="deepseek-reasoner",
                supported_model_ids=["deepseek-chat", "deepseek-reasoner"],
                runtime_capabilities=[
                    {"model_id": "deepseek-chat"},
                    {
                        "model_id": "deepseek-reasoner",
                        "supports_native_reasoning": True,
                    },
                ],
            ),
            trace_context=build_trace(),
        )

    assert updated.provider_id == "provider-deepseek"
    assert updated.provider_source is ProviderSource.BUILTIN
    assert updated.display_name == "DeepSeek"
    assert updated.protocol_type is ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE
    assert updated.base_url == "https://api.deepseek.example/v1"
    assert updated.api_key_ref == "env:DEEPSEEK_ROTATED_API_KEY"
    assert updated.default_model_id == "deepseek-reasoner"
    records = action_records(audit, "provider.patch_builtin_runtime_config")
    assert len(records) == 1
    assert records[0]["metadata"]["ref_transition"] == {
        "changed": True,
        "before_ref": "env:DEEPSEEK_API_KEY",
        "after_ref": "env:DEEPSEEK_ROTATED_API_KEY",
    }


def test_patch_custom_provider_updates_display_name_and_runtime_config(
    tmp_path: Path,
) -> None:
    from backend.app.services.providers import ProviderService

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        created = ProviderService(
            session,
            audit_service=audit,
            now=lambda: NOW,
        ).create_custom_provider(
            provider_request(),
            trace_context=build_trace(),
        )
        patched = ProviderService(
            session,
            audit_service=audit,
            now=lambda: LATER,
        ).patch_custom_provider(
            created.provider_id,
            provider_request(
                display_name="Renamed custom provider",
                base_url="https://provider.example.test/renamed",
                default_model_id="team-chat",
                supported_model_ids=["team-chat"],
                runtime_capabilities=[{"model_id": "team-chat"}],
            ),
            trace_context=build_trace(),
        )

    assert patched.provider_id == created.provider_id
    assert patched.display_name == "Renamed custom provider"
    assert patched.supported_model_ids == ["team-chat"]
    assert patched.updated_at == LATER
    assert action_records(audit, "provider.patch_custom")


def test_builtin_identity_mutation_is_rejected_and_audited(tmp_path: Path) -> None:
    from backend.app.services.providers import ProviderService, ProviderServiceError

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        service = ProviderService(session, audit_service=audit, now=lambda: NOW)
        service.seed_builtin_providers(trace_context=build_trace())
        before = session.get(ProviderModel, "provider-deepseek")
        assert before is not None

        with pytest.raises(ProviderServiceError) as error:
            service.patch_builtin_provider_runtime_config(
                "provider-deepseek",
                provider_request(
                    display_name="Renamed DeepSeek",
                    protocol_type=ProviderProtocolType.VOLCENGINE_NATIVE,
                ),
                trace_context=build_trace(),
            )
        after = session.get(ProviderModel, "provider-deepseek")

    assert error.value.error_code is ErrorCode.VALIDATION_ERROR
    assert error.value.status_code == 409
    assert error.value.message == "Built-in Provider identity fields cannot be modified."
    assert after is not None
    assert after.display_name == before.display_name
    records = action_records(audit, "provider.patch_builtin_runtime_config.rejected")
    assert len(records) == 1
    assert records[0]["result"] is AuditResult.REJECTED


def test_invalid_custom_provider_config_is_rejected_without_saving(
    tmp_path: Path,
) -> None:
    from backend.app.services.providers import ProviderService, ProviderServiceError

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        service = ProviderService(session, audit_service=audit, now=lambda: NOW)
        with pytest.raises(ProviderServiceError) as error:
            service.create_custom_provider(
                provider_request(
                    display_name=None,
                    api_key_ref="raw-secret-value",
                ),
                trace_context=build_trace(),
            )
        saved_count = session.query(ProviderModel).count()

    assert error.value.error_code is ErrorCode.CONFIG_INVALID_VALUE
    assert error.value.status_code == 422
    assert error.value.message == "Custom Provider display_name is required."
    assert saved_count == 0
    records = action_records(audit, "provider.create_custom.rejected")
    assert len(records) == 1
    assert "raw-secret-value" not in str(records[0]["metadata"])


@pytest.mark.parametrize(
    ("request_kwargs", "message"),
    [
        (
            {
                "protocol_type": ProviderProtocolType.VOLCENGINE_NATIVE,
            },
            "Custom Provider protocol_type must be openai_completions_compatible.",
        ),
        (
            {
                "default_model_id": "missing-model",
            },
            "Provider default_model_id must be in supported_model_ids.",
        ),
        (
            {
                "runtime_capabilities": [{"model_id": "team-chat"}],
            },
            "Provider runtime_capabilities must cover supported_model_ids.",
        ),
        (
            {
                "runtime_capabilities": [
                    {"model_id": "team-chat"},
                    {"model_id": "team-chat"},
                    {"model_id": "team-reasoner"},
                ],
            },
            "Provider runtime_capabilities must not contain duplicate model ids.",
        ),
        (
            {
                "runtime_capabilities": [
                    {"model_id": "team-chat"},
                    {"model_id": "team-reasoner"},
                    {"model_id": "unsupported-model"},
                ],
            },
            "Provider runtime_capabilities must only reference supported_model_ids.",
        ),
        (
            {
                "api_key_ref": "env:PATH",
            },
            "Provider api_key_ref must use an env: credential reference.",
        ),
    ],
)
def test_invalid_custom_provider_values_are_rejected_without_saving(
    tmp_path: Path,
    request_kwargs: dict[str, Any],
    message: str,
) -> None:
    from backend.app.services.providers import ProviderService, ProviderServiceError

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        service = ProviderService(session, audit_service=audit, now=lambda: NOW)
        with pytest.raises(ProviderServiceError) as error:
            service.create_custom_provider(
                provider_request(**request_kwargs),
                trace_context=build_trace(),
            )
        saved_count = session.query(ProviderModel).count()

    assert error.value.error_code is ErrorCode.CONFIG_INVALID_VALUE
    assert error.value.status_code == 422
    assert error.value.message == message
    assert saved_count == 0
    assert action_records(audit, "provider.create_custom.rejected")


def test_provider_service_respects_injected_credential_env_prefixes(
    tmp_path: Path,
) -> None:
    from backend.app.services.providers import ProviderService, ProviderServiceError

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        service = ProviderService(
            session,
            audit_service=audit,
            now=lambda: NOW,
            credential_env_prefixes=("TEAM_PROVIDER_",),
        )
        created = service.create_custom_provider(
            provider_request(api_key_ref="env:TEAM_PROVIDER_API_KEY"),
            trace_context=build_trace(),
        )
        with pytest.raises(ProviderServiceError):
            service.create_custom_provider(
                provider_request(api_key_ref="env:AI_DEVFLOW_CREDENTIAL_TEAM_KEY"),
                trace_context=build_trace(),
            )

    assert created.api_key_ref == "env:TEAM_PROVIDER_API_KEY"


def test_missing_provider_patch_returns_not_found_and_audits(tmp_path: Path) -> None:
    from backend.app.services.providers import ProviderService, ProviderServiceError

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        with pytest.raises(ProviderServiceError) as error:
            ProviderService(
                session,
                audit_service=audit,
                now=lambda: NOW,
            ).patch_provider(
                "provider-missing",
                provider_request(),
                trace_context=build_trace(),
            )

    assert error.value.error_code is ErrorCode.NOT_FOUND
    assert error.value.status_code == 404
    assert error.value.message == "Provider was not found."
    assert action_records(audit, "provider.patch.rejected")


def test_provider_write_rolls_back_when_success_audit_fails(tmp_path: Path) -> None:
    from backend.app.services.providers import ProviderService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        with pytest.raises(RuntimeError, match="audit ledger unavailable"):
            ProviderService(
                session,
                audit_service=FailingAuditService(),
                now=lambda: NOW,
            ).create_custom_provider(
                provider_request(),
                trace_context=build_trace(),
            )
        assert session.query(ProviderModel).count() == 0

        audit = RecordingAuditService()
        service = ProviderService(session, audit_service=audit, now=lambda: NOW)
        service.seed_builtin_providers(trace_context=build_trace())
        before = session.get(ProviderModel, "provider-deepseek")
        assert before is not None
        old_base_url = before.base_url

        with pytest.raises(RuntimeError, match="audit ledger unavailable"):
            ProviderService(
                session,
                audit_service=FailingAuditService(),
                now=lambda: LATER,
            ).patch_builtin_provider_runtime_config(
                "provider-deepseek",
                provider_request(
                    display_name=None,
                    base_url="https://should-not-persist.test",
                    supported_model_ids=["team-chat"],
                    runtime_capabilities=[{"model_id": "team-chat"}],
                ),
                trace_context=build_trace(),
            )
        after = session.get(ProviderModel, "provider-deepseek")

    assert after is not None
    assert after.base_url == old_base_url


def test_custom_provider_patch_rolls_back_when_success_audit_fails(
    tmp_path: Path,
) -> None:
    from backend.app.services.providers import ProviderService

    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        created = ProviderService(
            session,
            audit_service=RecordingAuditService(),
            now=lambda: NOW,
        ).create_custom_provider(
            provider_request(),
            trace_context=build_trace(),
        )
        old_display_name = created.display_name
        old_base_url = created.base_url

        with pytest.raises(RuntimeError, match="audit ledger unavailable"):
            ProviderService(
                session,
                audit_service=FailingAuditService(),
                now=lambda: LATER,
            ).patch_custom_provider(
                created.provider_id,
                provider_request(
                    display_name="Should not persist",
                    base_url="https://should-not-persist.test",
                ),
                trace_context=build_trace(),
            )
        after = session.get(ProviderModel, created.provider_id)

    assert after is not None
    assert after.display_name == old_display_name
    assert after.base_url == old_base_url


def test_provider_patch_audit_blocks_preexisting_unsafe_api_key_ref(
    tmp_path: Path,
) -> None:
    from backend.app.services.providers import ProviderService

    audit = RecordingAuditService()
    manager = build_manager(tmp_path)

    with manager.session(DatabaseRole.CONTROL) as session:
        provider = ProviderModel(
            provider_id="provider-custom-legacy",
            display_name="Legacy custom provider",
            provider_source=ProviderSource.CUSTOM,
            protocol_type=ProviderProtocolType.OPENAI_COMPLETIONS_COMPATIBLE,
            base_url="https://provider.example.test/v1",
            api_key_ref="raw-legacy-secret",
            default_model_id="legacy-chat",
            supported_model_ids=["legacy-chat"],
            runtime_capabilities=[
                {
                    "model_id": "legacy-chat",
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
        session.add(provider)
        session.commit()

        ProviderService(
            session,
            audit_service=audit,
            now=lambda: LATER,
        ).patch_custom_provider(
            provider.provider_id,
            provider_request(
                display_name="Legacy custom provider",
                api_key_ref="env:AI_DEVFLOW_CREDENTIAL_REPAIRED_PROVIDER",
                default_model_id="legacy-chat",
                supported_model_ids=["legacy-chat"],
                runtime_capabilities=[{"model_id": "legacy-chat"}],
            ),
            trace_context=build_trace(),
        )

    records = action_records(audit, "provider.patch_custom")
    assert len(records) == 1
    metadata = records[0]["metadata"]
    assert metadata["api_key_ref"] == "env:AI_DEVFLOW_CREDENTIAL_REPAIRED_PROVIDER"
    assert metadata["ref_transition"] == {
        "changed": True,
        "before_ref": "[blocked:api_key_ref]",
        "after_ref": "env:AI_DEVFLOW_CREDENTIAL_REPAIRED_PROVIDER",
    }
    assert "raw-legacy-secret" not in str(metadata)
