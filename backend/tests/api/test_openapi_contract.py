from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.app.core.config import EnvironmentSettings
from backend.app.main import create_app


REPO_ROOT = Path(__file__).resolve().parents[3]

EXPECTED_CORE_ROUTE_METHODS: dict[str, set[str]] = {
    "/api/health": {"get"},
    "/api/projects": {"get", "post"},
    "/api/projects/{projectId}": {"delete"},
    "/api/projects/{projectId}/configuration-package/export": {"get"},
    "/api/projects/{projectId}/configuration-package/import": {"post"},
    "/api/projects/{projectId}/delivery-channel": {"get", "put"},
    "/api/projects/{projectId}/delivery-channel/validate": {"post"},
    "/api/projects/{projectId}/sessions": {"get", "post"},
    "/api/providers": {"get", "post"},
    "/api/providers/{providerId}": {"delete", "get", "patch"},
    "/api/pipeline-templates": {"get", "post"},
    "/api/pipeline-templates/{templateId}": {"delete", "get", "patch"},
    "/api/pipeline-templates/{templateId}/save-as": {"post"},
    "/api/runtime-settings": {"get", "put"},
    "/api/sessions/{sessionId}": {"delete", "get", "patch"},
    "/api/sessions/{sessionId}/template": {"put"},
    "/api/sessions/{sessionId}/messages": {"post"},
    "/api/sessions/{sessionId}/runs": {"post"},
    "/api/sessions/{sessionId}/workspace": {"get"},
    "/api/sessions/{sessionId}/events/stream": {"get"},
    "/api/approvals/{approvalId}/approve": {"post"},
    "/api/approvals/{approvalId}/reject": {"post"},
    "/api/runs/{runId}": {"get"},
    "/api/runs/{runId}/timeline": {"get"},
    "/api/runs/{runId}/pause": {"post"},
    "/api/runs/{runId}/resume": {"post"},
    "/api/runs/{runId}/terminate": {"post"},
    "/api/runs/{runId}/logs": {"get"},
    "/api/stages/{stageRunId}/inspector": {"get"},
    "/api/stages/{stageRunId}/logs": {"get"},
    "/api/control-records/{controlRecordId}": {"get"},
    "/api/tool-confirmations/{toolConfirmationId}": {"get"},
    "/api/tool-confirmations/{toolConfirmationId}/allow": {"post"},
    "/api/tool-confirmations/{toolConfirmationId}/deny": {"post"},
    "/api/delivery-records/{deliveryRecordId}": {"get"},
    "/api/preview-targets/{previewTargetId}": {"get"},
    "/api/audit-logs": {"get"},
}

EXPECTED_CORE_SCHEMAS = {
    "ProjectRead",
    "ProjectCreateRequest",
    "SessionRead",
    "SessionWorkspaceProjection",
    "RunTimelineProjection",
    "RunCommandResponse",
    "ApprovalCommandResponse",
    "ToolConfirmationCommandResponse",
    "ToolConfirmationInspectorProjection",
    "DeliveryResultDetailProjection",
    "PreviewTarget",
    "RunLogQueryResponse",
    "AuditLogQueryResponse",
    "ErrorResponse",
}

EXPECTED_EVENT_PAYLOAD_SCHEMAS = {
    "SessionRead",
    "MessageFeedEntry",
    "RunSummaryProjection",
    "ExecutionNodeProjection",
    "ApprovalRequestFeedEntry",
    "ApprovalResultFeedEntry",
    "ControlItemFeedEntry",
    "ToolConfirmationFeedEntry",
    "DeliveryResultFeedEntry",
    "SystemStatusFeedEntry",
    "SessionStatus",
    "StageType",
}


def _client(tmp_path: Path) -> TestClient:
    project_root = tmp_path / "project-root"
    project_root.mkdir()
    app = create_app(
        EnvironmentSettings(
            platform_runtime_root=tmp_path / "runtime",
            default_project_root=project_root,
        )
    )
    return TestClient(app)


def _schema_ref(route: dict[str, Any], status_code: str) -> str:
    return route["responses"][status_code]["content"]["application/json"]["schema"][
        "$ref"
    ]


def _request_schema_ref(route: dict[str, Any]) -> str:
    return route["requestBody"]["content"]["application/json"]["schema"]["$ref"]


def _assert_error_refs(route: dict[str, Any], expected_statuses: set[str]) -> None:
    assert expected_statuses <= set(route["responses"])
    for status_code in expected_statuses:
        assert _schema_ref(route, status_code) == "#/components/schemas/ErrorResponse"


def _parameter_names(route: dict[str, Any]) -> set[str]:
    return {parameter["name"] for parameter in route.get("parameters", [])}


def assert_openapi_contains_core_routes(document: dict[str, Any]) -> None:
    paths = document["paths"]
    missing_paths = set(EXPECTED_CORE_ROUTE_METHODS) - set(paths)
    assert missing_paths == set()

    for path, expected_methods in EXPECTED_CORE_ROUTE_METHODS.items():
        available_methods = set(paths[path])
        assert expected_methods <= available_methods, path

    schemas = document["components"]["schemas"]
    missing_schemas = EXPECTED_CORE_SCHEMAS - set(schemas)
    assert missing_schemas == set()

    allow_route = paths["/api/tool-confirmations/{toolConfirmationId}/allow"]["post"]
    deny_route = paths["/api/tool-confirmations/{toolConfirmationId}/deny"]["post"]
    detail_route = paths["/api/tool-confirmations/{toolConfirmationId}"]["get"]
    assert (
        _request_schema_ref(allow_route)
        == "#/components/schemas/ToolConfirmationAllowRequest"
    )
    assert (
        _request_schema_ref(deny_route)
        == "#/components/schemas/ToolConfirmationDenyRequest"
    )
    assert (
        _schema_ref(allow_route, "200")
        == "#/components/schemas/ToolConfirmationCommandResponse"
    )
    assert (
        _schema_ref(deny_route, "200")
        == "#/components/schemas/ToolConfirmationCommandResponse"
    )
    assert (
        _schema_ref(detail_route, "200")
        == "#/components/schemas/ToolConfirmationInspectorProjection"
    )
    _assert_error_refs(allow_route, {"404", "409", "422", "500"})
    _assert_error_refs(deny_route, {"404", "409", "422", "500"})
    _assert_error_refs(detail_route, {"404", "422", "500"})

    approve_route = paths["/api/approvals/{approvalId}/approve"]["post"]
    reject_route = paths["/api/approvals/{approvalId}/reject"]["post"]
    assert (
        _request_schema_ref(approve_route)
        == "#/components/schemas/ApprovalApproveRequest"
    )
    assert (
        _request_schema_ref(reject_route)
        == "#/components/schemas/ApprovalRejectRequest"
    )
    assert (
        _schema_ref(approve_route, "200")
        == "#/components/schemas/ApprovalCommandResponse"
    )
    assert (
        _schema_ref(reject_route, "200")
        == "#/components/schemas/ApprovalCommandResponse"
    )
    _assert_error_refs(approve_route, {"404", "409", "422", "500"})
    _assert_error_refs(reject_route, {"404", "409", "422", "500"})

    run_summary_route = paths["/api/runs/{runId}"]["get"]
    assert (
        _schema_ref(run_summary_route, "200")
        == "#/components/schemas/RunStatusSummaryProjection"
    )
    run_summary_parameters = _parameter_names(run_summary_route)
    assert "runId" in run_summary_parameters
    _assert_error_refs(run_summary_route, {"404", "422", "500"})

    run_logs_route = paths["/api/runs/{runId}/logs"]["get"]
    stage_logs_route = paths["/api/stages/{stageRunId}/logs"]["get"]
    audit_logs_route = paths["/api/audit-logs"]["get"]
    assert _schema_ref(run_logs_route, "200") == "#/components/schemas/RunLogQueryResponse"
    assert (
        _schema_ref(stage_logs_route, "200")
        == "#/components/schemas/RunLogQueryResponse"
    )
    assert (
        _schema_ref(audit_logs_route, "200")
        == "#/components/schemas/AuditLogQueryResponse"
    )
    assert {
        "runId",
        "level",
        "category",
        "source",
        "since",
        "until",
        "cursor",
        "limit",
    } <= _parameter_names(run_logs_route)
    assert {
        "stageRunId",
        "level",
        "category",
        "source",
        "since",
        "until",
        "cursor",
        "limit",
    } <= _parameter_names(stage_logs_route)
    assert {
        "actor_type",
        "action",
        "target_type",
        "target_id",
        "run_id",
        "stage_run_id",
        "correlation_id",
        "result",
        "since",
        "until",
        "cursor",
        "limit",
    } <= _parameter_names(audit_logs_route)
    _assert_error_refs(run_logs_route, {"404", "422", "503"})
    _assert_error_refs(stage_logs_route, {"404", "422", "503"})
    _assert_error_refs(audit_logs_route, {"422", "503"})


def assert_openapi_contains_event_stream_schema(document: dict[str, Any]) -> None:
    stream_route = document["paths"]["/api/sessions/{sessionId}/events/stream"]["get"]
    assert {"sessionId", "after", "limit"} <= _parameter_names(stream_route)
    assert (
        stream_route["responses"]["200"]["content"]["text/event-stream"]["schema"][
            "type"
        ]
        == "string"
    )
    assert _schema_ref(stream_route, "422") == "#/components/schemas/ErrorResponse"

    schemas = document["components"]["schemas"]
    missing_event_schemas = EXPECTED_EVENT_PAYLOAD_SCHEMAS - set(schemas)
    assert missing_event_schemas == set()


def test_openapi_document_covers_function_one_core_routes_and_docs(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        openapi_response = client.get("/api/openapi.json")
        docs_response = client.get("/api/docs")

    assert openapi_response.status_code == 200
    document = openapi_response.json()
    assert document["info"]["title"] == "AI DevFlow Engine API"
    assert document["openapi"].startswith("3.")
    assert_openapi_contains_core_routes(document)
    assert_openapi_contains_event_stream_schema(document)

    assert docs_response.status_code == 200
    assert "text/html" in docs_response.headers["content-type"]
    assert "/api/openapi.json" in docs_response.text


def test_openapi_companion_note_is_tracked_and_linked() -> None:
    notes_path = REPO_ROOT / "docs" / "api" / "function-one-openapi-notes.md"
    readme_path = REPO_ROOT / "README.md"

    assert notes_path.exists()
    notes = notes_path.read_text(encoding="utf-8")
    assert "# Function One OpenAPI Notes" in notes
    for required_text in (
        "/api/openapi.json",
        "/api/docs",
        "/api/sessions/{sessionId}/events/stream",
        "SessionRead",
        "RunSummaryProjection",
        "ControlItemFeedEntry",
        "SystemStatusFeedEntry",
        "SessionStatus",
        "StageType",
        "session_status_changed",
        "session_id",
        "status",
        "current_run_id",
        "current_stage_type",
        "stage_run_id",
        "correlation_id",
        "/api/tool-confirmations/{toolConfirmationId}/allow",
        "/api/tool-confirmations/{toolConfirmationId}/deny",
        "RunStatusSummaryProjection",
        "/api/runs/{runId}/logs",
        "/api/stages/{stageRunId}/logs",
        "/api/audit-logs",
        "V6.4 is a global coverage regression",
    ):
        assert required_text in notes

    readme = readme_path.read_text(encoding="utf-8")
    assert "docs/api/function-one-openapi-notes.md" in readme
