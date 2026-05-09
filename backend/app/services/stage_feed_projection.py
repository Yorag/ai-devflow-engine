from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
from typing import Any

from sqlalchemy.orm import Session

from backend.app.db.models.runtime import (
    PipelineRunModel,
    StageArtifactModel,
    StageRunModel,
)
from backend.app.domain.enums import StageType
from backend.app.schemas import common
from backend.app.schemas.feed import ExecutionNodeProjection, StageItemProjection


@dataclass(frozen=True, slots=True)
class _OrderedStageItem:
    iteration_index: int
    phase_index: int
    record_index: int
    item: StageItemProjection


def stage_progress_items(
    runtime_session: Session,
    *,
    run: PipelineRunModel,
    stage: StageRunModel,
    occurred_at: object,
    artifact_refs: Sequence[str],
) -> list[StageItemProjection]:
    artifact = latest_stage_artifact(
        runtime_session,
        run_id=run.run_id,
        stage_run_id=stage.stage_run_id,
        artifact_refs=artifact_refs,
    )
    if artifact is None or not isinstance(artifact.process, dict):
        return []

    process = dict(artifact.process)
    ordered_items: list[_OrderedStageItem] = []

    for index, record in enumerate(_mapping_records(process.get("model_call_trace")), 1):
        usage = record.get("usage") if isinstance(record.get("usage"), dict) else {}
        ordered_items.append(
            _OrderedStageItem(
                iteration_index=_iteration_index(record, fallback=index),
                phase_index=10,
                record_index=index,
                item=StageItemProjection(
                    item_id=_bounded_id(
                        "item",
                        stage.stage_run_id,
                        "model",
                        str(index),
                    ),
                    type=common.StageItemType.MODEL_CALL,
                    occurred_at=occurred_at,
                    title=_model_call_title(record),
                    summary=_model_call_summary(record),
                    content=None,
                    artifact_refs=_stage_ref_list(
                        record.get("artifact_refs"),
                        fallback=[_first_existing_text(record, ("model_call_ref",))],
                    ),
                    metrics={key: value for key, value in usage.items() if value is not None},
                ),
            )
        )

    for index, record in enumerate(_mapping_records(process.get("decision_trace")), 1):
        ordered_items.append(
            _OrderedStageItem(
                iteration_index=_iteration_index(record, fallback=index),
                phase_index=20,
                record_index=index,
                item=StageItemProjection(
                    item_id=_bounded_id(
                        "item",
                        stage.stage_run_id,
                        "decision",
                        str(index),
                    ),
                    type=common.StageItemType.DECISION,
                    occurred_at=occurred_at,
                    title=_decision_title(record),
                    summary=_decision_summary(record),
                    content=None,
                    artifact_refs=_stage_ref_list(
                        record.get("artifact_refs"),
                        fallback=[_first_existing_text(record, ("trace_ref",))],
                    ),
                    metrics=_compact_metrics(record, ("status", "decision_type")),
                ),
            )
        )

    for index, record in enumerate(
        _mapping_records(process.get("tool_confirmation_trace")),
        1,
    ):
        ordered_items.append(
            _OrderedStageItem(
                iteration_index=_iteration_index(record, fallback=index),
                phase_index=25,
                record_index=index,
                item=StageItemProjection(
                    item_id=_bounded_id(
                        "item",
                        stage.stage_run_id,
                        "tool-confirmation",
                        str(index),
                    ),
                    type=common.StageItemType.TOOL_CONFIRMATION,
                    occurred_at=occurred_at,
                    title=_tool_confirmation_title(record),
                    summary=_tool_confirmation_summary(record),
                    content=None,
                    artifact_refs=_stage_ref_list(
                        record.get("artifact_refs"),
                        fallback=[_first_existing_text(record, ("tool_confirmation_ref",))],
                    ),
                    metrics=_compact_metrics(record, ("status", "tool_name")),
                ),
            )
        )

    for index, record in enumerate(_mapping_records(process.get("tool_trace")), 1):
        ordered_items.append(
            _OrderedStageItem(
                iteration_index=_iteration_index(record, fallback=index),
                phase_index=30,
                record_index=index,
                item=StageItemProjection(
                    item_id=_bounded_id(
                        "item",
                        stage.stage_run_id,
                        "tool",
                        str(index),
                    ),
                    type=common.StageItemType.TOOL_CALL,
                    occurred_at=occurred_at,
                    title=_tool_title(record),
                    summary=_tool_summary(record),
                    content=_tool_content(record),
                    artifact_refs=_stage_ref_list(record.get("artifact_refs")),
                    metrics=_compact_metrics(record, ("status", "call_id", "tool_name")),
                ),
            )
        )

    for index, record in enumerate(
        _mapping_records(process.get("structured_output_repair_trace")),
        1,
    ):
        ordered_items.append(
            _OrderedStageItem(
                iteration_index=_iteration_index(record, fallback=index),
                phase_index=35,
                record_index=index,
                item=StageItemProjection(
                    item_id=_bounded_id(
                        "item",
                        stage.stage_run_id,
                        "repair",
                        str(index),
                    ),
                    type=common.StageItemType.CONTEXT,
                    occurred_at=occurred_at,
                    title="Repair structured output",
                    summary=_structured_repair_summary(record),
                    content=_structured_repair_content(record),
                    artifact_refs=_stage_ref_list(
                        record.get("artifact_refs"),
                        fallback=[_first_existing_text(record, ("invalid_output_ref",))],
                    ),
                    metrics=_compact_metrics(record, ("iteration_index",)),
                ),
            )
        )

    for index, record in enumerate(
        (
            *_mapping_records(process.get("change_set")),
            *_mapping_records(process.get("change_sets")),
        ),
        1,
    ):
        refs = _stage_ref_list(record.get("diff_refs"))
        ordered_items.append(
            _OrderedStageItem(
                iteration_index=10_000,
                phase_index=10,
                record_index=index,
                item=StageItemProjection(
                    item_id=_bounded_id(
                        "item",
                        stage.stage_run_id,
                        "diff",
                        str(index),
                    ),
                    type=common.StageItemType.DIFF_PREVIEW,
                    occurred_at=occurred_at,
                    title="Diff preview",
                    summary=_change_set_summary(record),
                    content=_change_set_content(record),
                    artifact_refs=refs,
                    metrics=_compact_metrics(record, ("change_set_id",)),
                ),
            )
        )

    output_records = _mapping_records(process.get("output_snapshot"))
    if output_records:
        output = output_records[-1]
        ordered_items.append(
            _OrderedStageItem(
                iteration_index=10_000,
                phase_index=20,
                record_index=1,
                item=StageItemProjection(
                    item_id=_bounded_id("item", stage.stage_run_id, "result"),
                    type=common.StageItemType.RESULT,
                    occurred_at=occurred_at,
                    title="Stage result",
                    summary=_result_summary(output, stage.stage_type),
                    content=_result_content(output),
                    artifact_refs=[
                        artifact.artifact_id,
                        *_stage_ref_list(process.get("output_refs")),
                    ],
                    metrics=dict(artifact.metrics) if isinstance(artifact.metrics, dict) else {},
                ),
            )
        )

    return [
        ordered.item
        for ordered in sorted(
            ordered_items,
            key=lambda item: (
                item.iteration_index,
                item.phase_index,
                item.record_index,
                item.item.item_id,
            ),
        )
    ]


def stage_metrics(
    runtime_session: Session,
    *,
    run_id: str | None = None,
    stage_run_id: str | None = None,
    artifact_refs: Sequence[str],
) -> dict[str, Any]:
    artifacts: list[StageArtifactModel] = []
    for artifact_id in _artifact_ids_from_refs(artifact_refs):
        artifact = runtime_session.get(StageArtifactModel, artifact_id)
        if artifact is not None:
            artifacts.append(artifact)
    if not artifacts and run_id is not None and stage_run_id is not None:
        artifact = latest_stage_artifact(
            runtime_session,
            run_id=run_id,
            stage_run_id=stage_run_id,
            artifact_refs=(),
        )
        if artifact is not None:
            artifacts.append(artifact)

    metrics: dict[str, Any] = {}
    for artifact in artifacts:
        if isinstance(artifact.metrics, dict):
            metrics.update(artifact.metrics)
    return metrics


def hydrate_stage_node_from_artifacts(
    runtime_session: Session,
    stage_node: ExecutionNodeProjection,
) -> ExecutionNodeProjection:
    run = runtime_session.get(PipelineRunModel, stage_node.run_id)
    stage = runtime_session.get(StageRunModel, stage_node.stage_run_id)
    if run is None or stage is None or stage.run_id != run.run_id:
        return stage_node

    artifact_refs = _stage_node_artifact_refs(stage_node)
    generated_items = stage_progress_items(
        runtime_session,
        run=run,
        stage=stage,
        occurred_at=stage_node.occurred_at,
        artifact_refs=artifact_refs,
    )
    if not generated_items:
        return stage_node

    provider_items = [item for item in stage_node.items if item.type == "provider_call"]
    metrics = stage_metrics(
        runtime_session,
        run_id=run.run_id,
        stage_run_id=stage.stage_run_id,
        artifact_refs=artifact_refs,
    )
    return stage_node.model_copy(
        update={
            "status": stage.status,
            "attempt_index": stage.attempt_index,
            "started_at": stage.started_at,
            "ended_at": stage.ended_at,
            "summary": stage.summary or stage_node.summary,
            "items": [*provider_items, *generated_items],
            "metrics": metrics or stage_node.metrics,
        }
    )


def latest_stage_artifact(
    runtime_session: Session,
    *,
    run_id: str,
    stage_run_id: str,
    artifact_refs: Sequence[str],
) -> StageArtifactModel | None:
    for artifact_id in reversed(tuple(_artifact_ids_from_refs(artifact_refs))):
        artifact = runtime_session.get(StageArtifactModel, artifact_id)
        if (
            artifact is not None
            and artifact.run_id == run_id
            and artifact.stage_run_id == stage_run_id
        ):
            return artifact
    return (
        runtime_session.query(StageArtifactModel)
        .filter(
            StageArtifactModel.run_id == run_id,
            StageArtifactModel.stage_run_id == stage_run_id,
        )
        .order_by(
            StageArtifactModel.created_at.desc(),
            StageArtifactModel.artifact_id.desc(),
        )
        .first()
    )


def _mapping_records(value: object) -> tuple[dict[str, Any], ...]:
    if isinstance(value, Mapping):
        return (dict(value),)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return tuple(dict(item) for item in value if isinstance(item, Mapping))
    return ()


def _iteration_index(record: dict[str, Any], *, fallback: int) -> int:
    value = record.get("iteration_index")
    return value if isinstance(value, int) and value > 0 else fallback


def _model_call_summary(record: dict[str, Any]) -> str:
    display_summary = _optional_text(record.get("display_summary"))
    if display_summary:
        return display_summary
    output_summary = record.get("output_summary")
    if isinstance(output_summary, Mapping):
        excerpt = _optional_text(output_summary.get("excerpt"))
        if excerpt:
            return excerpt
    provider = _optional_text(record.get("provider_id")) or "provider"
    model = _optional_text(record.get("model_id")) or "model"
    call_type = _optional_text(record.get("model_call_type")) or "stage call"
    return f"{provider} {model} handled {call_type}."


def _model_call_title(record: dict[str, Any]) -> str:
    model = _optional_text(record.get("model_id")) or "model"
    return f"Call {model}"


def _decision_title(record: dict[str, Any]) -> str:
    decision_type = _optional_text(record.get("decision_type")) or _optional_text(
        record.get("decision")
    )
    if decision_type:
        return _decision_action(decision_type)
    status = _optional_text(record.get("status"))
    return f"Decision {status}" if status else "Decision"


def _decision_summary(record: dict[str, Any]) -> str:
    message = _optional_text(record.get("safe_message")) or _optional_text(
        record.get("reason")
    )
    decision_type = _optional_text(record.get("decision_type")) or _optional_text(
        record.get("decision")
    )
    status = _optional_text(record.get("status"))
    if message:
        return message
    if decision_type:
        action = _decision_action(decision_type)
        return f"{action} ({status or 'recorded'})."
    return "Model decision is available."


def _decision_action(decision_type: str) -> str:
    actions = {
        "request_tool_call": "Request tool call",
        "request_tool_confirmation": "Request tool confirmation",
        "submit_stage_artifact": "Submit stage result",
        "request_clarification": "Ask for clarification",
        "retry_with_revised_plan": "Retry with revised plan",
        "repair_structured_output": "Repair structured output",
        "fail_stage": "Fail stage",
    }
    return actions.get(decision_type, _humanize_key(decision_type))


def _tool_confirmation_title(record: dict[str, Any]) -> str:
    tool_name = _optional_text(record.get("tool_name")) or "tool"
    return f"Confirm {_tool_action(tool_name).lower()}"


def _tool_confirmation_summary(record: dict[str, Any]) -> str:
    status = _optional_text(record.get("status")) or "pending"
    safe_details = record.get("safe_details")
    if isinstance(safe_details, Mapping):
        detail = _optional_text(safe_details.get("summary")) or _optional_text(
            safe_details.get("message")
        )
        if detail:
            return detail
    return f"Tool confirmation is {status}."


def _tool_title(record: dict[str, Any]) -> str:
    tool_name = _optional_text(record.get("tool_name")) or "runtime tool"
    parameter_parts = _tool_parameter_parts(tool_name, record)
    if parameter_parts:
        return " ".join((tool_name, *parameter_parts))
    return tool_name


def _tool_summary(record: dict[str, Any]) -> str | None:
    safe_details = record.get("safe_details")
    if isinstance(safe_details, Mapping):
        detail = _optional_text(safe_details.get("summary")) or _optional_text(
            safe_details.get("message")
        )
        if detail:
            return _bounded_text(detail, limit=500)
    status = _optional_text(record.get("status"))
    if status and status != "succeeded":
        output_preview = _optional_text(record.get("output_preview"))
        if output_preview:
            return _bounded_text(output_preview, limit=500)
        return f"{status}."
    return None


def _tool_content(record: dict[str, Any]) -> str | None:
    lines: list[str] = []
    title = _tool_title(record)
    lines.append(title)
    output_summary = _tool_output_summary(record)
    if output_summary:
        lines.append(f"Output summary: {output_summary}")
    return "\n".join(dict.fromkeys(lines)) or None


def _tool_parameter_parts(tool_name: str, record: dict[str, Any]) -> list[str]:
    input_summary = record.get("input_payload_summary")
    if not isinstance(input_summary, Mapping):
        return []

    key_order_by_tool = {
        "bash": ("command", "cwd"),
        "grep": ("pattern", "path"),
        "glob": ("pattern", "path"),
        "read_file": ("path", "offset", "limit", "max_chars"),
        "read_workspace": ("path", "offset", "limit", "max_chars"),
        "write_file": ("path",),
        "edit_file": ("path",),
    }
    key_order = key_order_by_tool.get(
        tool_name,
        ("path", "pattern", "glob", "query", "command", "argv", "cwd", "target"),
    )

    parts: list[str] = []
    for key in key_order:
        value = input_summary.get(key)
        display = _display_parameter_value(value)
        if display is not None:
            parts.append(f"{key}={display}")
    return parts


def _display_parameter_value(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        return _quote_parameter_value(_bounded_text(stripped, limit=180))
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        values = [str(item) for item in value[:8] if str(item)]
        if not values:
            return None
        return _quote_parameter_value(_bounded_text(" ".join(values), limit=180))
    return None


def _quote_parameter_value(value: str) -> str:
    if any(char.isspace() for char in value):
        return f'"{value}"'
    return value


def _tool_output_summary(record: dict[str, Any]) -> str | None:
    tool_name = _optional_text(record.get("tool_name"))
    if tool_name in {"read_file", "read_workspace"}:
        return None
    output_preview = _optional_text(record.get("output_preview"))
    if not output_preview:
        return None
    return _bounded_text(output_preview, limit=1000)


def _structured_repair_summary(record: dict[str, Any]) -> str:
    instruction = _optional_text(record.get("repair_instruction_summary"))
    if instruction:
        return instruction
    parse_error = _optional_text(record.get("parse_error_summary"))
    if parse_error:
        return f"Repair requested after parse error: {parse_error}"
    return "Structured output needed repair before the stage could continue."


def _structured_repair_content(record: dict[str, Any]) -> str | None:
    lines = []
    parse_error = _optional_text(record.get("parse_error_summary"))
    instruction = _optional_text(record.get("repair_instruction_summary"))
    if parse_error:
        lines.append(f"Parse error: {parse_error}")
    if instruction:
        lines.append(f"Repair instruction: {instruction}")
    return "\n".join(lines) or None


def _change_set_summary(record: dict[str, Any]) -> str:
    summary = _optional_text(record.get("summary"))
    if summary:
        return summary
    files = _stage_ref_list(record.get("changed_files"))
    if files:
        return f"{len(files)} file change(s) projected."
    return "Workspace diff preview is available."


def _change_set_content(record: dict[str, Any]) -> str:
    lines: list[str] = []
    files = _stage_ref_list(record.get("changed_files"))
    if files:
        lines.append("Files:")
        lines.extend(files)
    diff_preview = _optional_text(record.get("diff_preview"))
    if diff_preview:
        lines.append("")
        lines.append(diff_preview)
    return "\n".join(lines) or "Diff preview."


def _result_summary(record: dict[str, Any], stage_type: StageType) -> str:
    payload = record.get("artifact_payload")
    if isinstance(payload, Mapping):
        for key in (
            "summary",
            "requirement_summary",
            "design_summary",
            "implementation_summary",
            "review_summary",
            "delivery_summary",
            "risk_summary",
        ):
            value = _optional_text(payload.get(key))
            if value:
                return value
    for key in ("summary", "risk_summary", "failure_summary", "artifact_type"):
        value = _optional_text(record.get(key))
        if value:
            return _humanize_key(value) if key == "artifact_type" else value
    return f"{stage_type.value} produced a stage result."


def _result_content(record: dict[str, Any]) -> str | None:
    lines: list[str] = []
    risk_summary = _optional_text(record.get("risk_summary"))
    failure_summary = _optional_text(record.get("failure_summary"))
    if risk_summary:
        lines.append(risk_summary)
    if failure_summary:
        lines.append(failure_summary)
    payload = record.get("artifact_payload")
    if isinstance(payload, Mapping):
        lines.extend(_result_payload_lines(payload))
    return "\n".join(dict.fromkeys(lines)) or None


def _result_payload_lines(payload: Mapping[str, object]) -> list[str]:
    lines: list[str] = []
    for key in (
        "summary",
        "requirement_summary",
        "design_summary",
        "implementation_summary",
        "review_summary",
        "delivery_summary",
        "implementation_notes",
        "test_execution_result",
        "test_gap_report",
        "review_report",
        "risk_assessment",
    ):
        value = _optional_text(payload.get(key))
        if value:
            lines.append(value)
    for key, label in (
        ("changed_files", "Changed files"),
        ("impacted_files", "Impacted files"),
        ("generated_tests", "Generated tests"),
        ("executed_tests", "Executed tests"),
        ("failed_test_refs", "Failed tests"),
        ("open_questions", "Open questions"),
        ("completed_steps", "Completed steps"),
        ("remaining_steps", "Remaining steps"),
    ):
        values = _string_values(payload.get(key))
        if values:
            lines.append(f"{label}: {', '.join(values[:8])}")
    diff_summary = _diff_summary(payload)
    if diff_summary:
        lines.append(diff_summary)
    return lines


def _diff_summary(payload: Mapping[str, object]) -> str | None:
    value = _optional_text(payload.get("diff_summary"))
    if value:
        return value
    value = _optional_text(payload.get("diff_preview"))
    if value:
        return _bounded_text(value.replace("\n", " "), limit=240)
    return None


def _string_values(value: object) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _stage_node_artifact_refs(stage_node: ExecutionNodeProjection) -> list[str]:
    refs: list[str] = []
    for item in stage_node.items:
        refs.extend(item.artifact_refs)
    return _dedupe_strings(refs)


def _artifact_ids_from_refs(refs: Sequence[str]) -> list[str]:
    return _dedupe_strings(_stage_artifact_id_from_ref(ref) for ref in refs)


def _stage_artifact_id_from_ref(value: str) -> str:
    if not value.startswith("stage-artifact://"):
        return value
    without_scheme = value.removeprefix("stage-artifact://")
    without_fragment = without_scheme.split("#", 1)[0]
    return without_fragment.split("/", 1)[0]


def _compact_metrics(
    record: dict[str, Any],
    keys: Sequence[str],
) -> dict[str, Any]:
    return {key: record[key] for key in keys if record.get(key) is not None}


def _stage_ref_list(
    value: object,
    *,
    fallback: Sequence[str | None] = (),
) -> list[str]:
    if isinstance(value, str):
        values: list[object] = [value]
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        values = list(value)
    else:
        values = list(fallback)
    return [item for item in values if isinstance(item, str) and item.strip()]


def _first_existing_text(
    mapping: dict[str, Any],
    keys: Sequence[str],
) -> str | None:
    for key in keys:
        value = _optional_text(mapping.get(key))
        if value is not None:
            return value
    return None


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped


def _humanize_key(value: str) -> str:
    return value.replace("_", " ").strip().capitalize()


def _bounded_text(value: str, *, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}..."


def _dedupe_strings(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _bounded_id(*parts: str) -> str:
    value = "-".join(part for part in parts if part)
    if len(value) <= 80:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
    return "-".join(parts[:1] + (digest,))


__all__ = [
    "hydrate_stage_node_from_artifacts",
    "latest_stage_artifact",
    "stage_metrics",
    "stage_progress_items",
]
