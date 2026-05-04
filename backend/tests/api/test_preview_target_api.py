from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.app.db.base import DatabaseRole
from backend.app.db.models.runtime import StageArtifactModel
from backend.tests.api.test_query_api import build_query_api_app
from backend.tests.api.test_startup_publication_visibility import _seed_pending_startup
from backend.tests.projections.test_workspace_projection import NOW


def _preview_target_process() -> dict[str, Any]:
    return {
        "target_type": "preview_snapshot",
        "reference": {
            "reference_id": "ctx-preview-1",
            "reference_kind": "preview_snapshot",
            "source_ref": "preview://run-active/snapshot-1",
            "source_label": "Workspace preview snapshot",
            "path": "src/app.py",
            "version_ref": "workspace-version-1",
            "metadata": {
                "change_set_ref": "changeset://changeset-1",
            },
        },
    }


def _seed_preview_target(
    app,
    *,
    artifact_id: str = "preview-target-1",
    run_id: str = "run-active",
    stage_run_id: str = "stage-active",
    process: Any | None = None,
) -> str:
    with app.state.database_manager.session(DatabaseRole.RUNTIME) as session:
        session.add(
            StageArtifactModel(
                artifact_id=artifact_id,
                run_id=run_id,
                stage_run_id=stage_run_id,
                artifact_type="preview_target",
                payload_ref=f"payload-{artifact_id}",
                process=process if process is not None else _preview_target_process(),
                metrics={},
                created_at=NOW,
            )
        )
        session.commit()
    return artifact_id


def test_get_preview_target_returns_projection_and_unified_not_found(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)
    preview_target_id = _seed_preview_target(app)

    with TestClient(app) as client:
        ok_response = client.get(
            f"/api/preview-targets/{preview_target_id}",
            headers={
                "X-Request-ID": "req-preview-target",
                "X-Correlation-ID": "corr-preview-target",
            },
        )
        missing_response = client.get(
            "/api/preview-targets/preview-target-missing",
            headers={
                "X-Request-ID": "req-preview-target-missing",
                "X-Correlation-ID": "corr-preview-target-missing",
            },
        )

    assert ok_response.status_code == 200
    payload = ok_response.json()
    assert payload["preview_target_id"] == preview_target_id
    assert payload["project_id"] == "project-1"
    assert payload["run_id"] == "run-active"
    assert payload["stage_run_id"] == "stage-active"
    assert payload["target_type"] == "preview_snapshot"
    assert payload["reference"] == {
        "reference_id": "ctx-preview-1",
        "reference_kind": "preview_snapshot",
        "source_ref": "preview://run-active/snapshot-1",
        "source_label": "Workspace preview snapshot",
        "path": "src/app.py",
        "version_ref": "workspace-version-1",
        "metadata": {
            "change_set_ref": "changeset://changeset-1",
        },
    }

    assert missing_response.status_code == 404
    assert missing_response.json() == {
        "error_code": "not_found",
        "message": "Preview target was not found.",
        "request_id": "req-preview-target-missing",
        "correlation_id": "corr-preview-target-missing",
    }


def test_get_preview_target_rejects_unpublished_startup_run(tmp_path: Path) -> None:
    app = build_query_api_app(tmp_path)
    seeded = _seed_pending_startup(app)
    preview_target_id = _seed_preview_target(
        app,
        artifact_id="preview-target-startup-pending",
        run_id=seeded.run_id,
        stage_run_id=seeded.stage_run_id,
        process={
            **_preview_target_process(),
            "reference": {
                **_preview_target_process()["reference"],
                "source_ref": f"preview://{seeded.run_id}/snapshot-1",
            },
        },
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/preview-targets/{preview_target_id}",
            headers={
                "X-Request-ID": "req-preview-target-hidden",
                "X-Correlation-ID": "corr-preview-target-hidden",
            },
        )

    assert response.status_code == 404
    assert response.json() == {
        "error_code": "not_found",
        "message": "Preview target was not found.",
        "request_id": "req-preview-target-hidden",
        "correlation_id": "corr-preview-target-hidden",
    }


def test_get_preview_target_malformed_payload_returns_unified_500(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)
    preview_target_id = _seed_preview_target(
        app,
        artifact_id="preview-target-malformed",
        process={
            "target_type": "preview_snapshot",
            "reference": {
                "reference_id": "ctx-preview-malformed",
                "reference_kind": "not-a-reference-kind",
                "source_ref": "preview://run-active/snapshot-malformed",
                "source_label": "Malformed preview target",
            },
        },
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/preview-targets/{preview_target_id}",
            headers={
                "X-Request-ID": "req-preview-target-malformed",
                "X-Correlation-ID": "corr-preview-target-malformed",
            },
        )

    assert response.status_code == 500
    assert response.json() == {
        "error_code": "internal_error",
        "message": "Preview target is unavailable.",
        "request_id": "req-preview-target-malformed",
        "correlation_id": "corr-preview-target-malformed",
    }


def test_get_preview_target_malformed_process_returns_unified_500(
    tmp_path: Path,
) -> None:
    app = build_query_api_app(tmp_path)
    preview_target_id = _seed_preview_target(
        app,
        artifact_id="preview-target-malformed-process",
        process=["not", "an", "object"],
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/preview-targets/{preview_target_id}",
            headers={
                "X-Request-ID": "req-preview-target-malformed-process",
                "X-Correlation-ID": "corr-preview-target-malformed-process",
            },
        )

    assert response.status_code == 500
    assert response.json() == {
        "error_code": "internal_error",
        "message": "Preview target is unavailable.",
        "request_id": "req-preview-target-malformed-process",
        "correlation_id": "corr-preview-target-malformed-process",
    }


def test_preview_target_route_is_documented_in_openapi(tmp_path: Path) -> None:
    app = build_query_api_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/openapi.json")

    assert response.status_code == 200
    document = response.json()
    paths = document["paths"]
    schemas = document["components"]["schemas"]
    route = paths["/api/preview-targets/{previewTargetId}"]["get"]

    assert set(route["responses"]) == {"200", "404", "422", "500"}
    assert (
        route["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/PreviewTarget"
    )
    for status_code in ("404", "422", "500"):
        assert (
            route["responses"][status_code]["content"]["application/json"]["schema"][
                "$ref"
            ]
            == "#/components/schemas/ErrorResponse"
        )

    preview_target_id_parameter = next(
        parameter
        for parameter in route["parameters"]
        if parameter["name"] == "previewTargetId"
    )
    assert preview_target_id_parameter["in"] == "path"
    assert preview_target_id_parameter["required"] is True
    assert preview_target_id_parameter["schema"]["type"] == "string"

    assert "PreviewTarget" in schemas
    assert "PreviewTargetReference" in schemas
    assert "ErrorResponse" in schemas
