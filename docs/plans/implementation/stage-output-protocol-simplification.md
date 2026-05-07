# Stage Output Protocol Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans as fallback only when subagent context cannot be bounded. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make stage model outputs simple and stage-specific so structured-output repair is exceptional rather than the normal path.

**Architecture:** Keep the internal `AgentDecision` model as the runtime handoff object, but stop exposing the full shared decision union to ordinary stage calls. Add a stage-specific response schema, deterministic normalization that wraps obvious stage artifacts into `submit_stage_artifact`, constrained repair that cannot change the intended decision semantics, and semantic gates for Solution Design and Code Generation.

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI backend runtime, existing pytest suite, LangChain provider adapter contracts.

---

## Source Trace

- `docs/specs/function-one-product-overview-v1.md` requires `Solution Design` to output an executable implementation plan that downstream stages can read.
- `docs/specs/function-one-backend-engine-design-v1.md` requires stage agent output to be parsed as `AgentDecision` or an equivalent structured decision protocol, with runtime-owned tool execution, artifact persistence, and structured repair.
- `docs/specs/function-one-backend-engine-design-v1.md` also allows structured-output repair as a traceable internal model call, but does not require ordinary stage calls to expose repair as a model-selectable business decision.
- `AGENTS.md` active workflow allows main-based stabilization and permits `slice-workflow` as execution discipline without acceleration claim updates.

## Files

- Modify: `backend/app/runtime/agent_decision.py`
- Modify: `backend/app/runtime/stage_agent.py`
- Modify: `backend/app/services/runtime_dispatch.py`
- Modify: `backend/app/prompts/assets/runtime/runtime_instructions.md`
- Modify: `backend/app/prompts/assets/repairs/structured_output_repair.md`
- Modify: `backend/tests/runtime/test_agent_decision_parser.py`
- Modify: `backend/tests/runtime/test_stage_agent_runtime.py`
- Modify: `backend/tests/services/test_runtime_execution_service.py`
- Modify: `docs/plans/implementation/stage-output-protocol-simplification.md`

## Log & Audit Integration

This slice changes model-call response schema and parser failure handling. It does not add a new log category, audit action, database object, or product projection. Existing `model_call_trace`, `decision_trace`, `structured_output_repair_trace`, `stage_agent_failed`, `tool_trace`, and LangSmith tracing remain the observable surfaces. Tests must prove deterministic normalization does not write `structured_output_repair_trace`, and true repair still uses `model_call_type = structured_output_repair`.

## Task 1: Stage-Specific Schema And Parser Normalization

- [ ] **Step 1: Write failing parser tests**

Add tests in `backend/tests/runtime/test_agent_decision_parser.py`:

```python
def test_stage_response_schema_uses_submit_artifact_protocol_without_repair_union() -> None:
    from backend.app.runtime.agent_decision import stage_response_schema

    schema = stage_response_schema(artifact_type="SolutionDesignArtifact")

    assert schema["title"] == "StageResponse"
    assert schema["properties"]["artifact_type"]["const"] == "SolutionDesignArtifact"
    assert "decision_type" not in schema["required"]
    assert "repair_structured_output" not in str(schema)
    assert set(schema["properties"]["artifact_payload"]["required"]) >= {
        "technical_plan",
        "implementation_plan",
        "impacted_files",
        "requirement_refs",
        "evidence_refs",
    }
```

```python
def test_parser_wraps_bare_stage_artifact_payload_as_submit_decision() -> None:
    from backend.app.runtime.agent_decision import AgentDecisionParser, AgentDecisionType

    payload = {
        "technical_plan": "Update the homepage heading text only.",
        "implementation_plan": [
            "Edit frontend/src/pages/HomePage.tsx heading from Make delivery work traceable. to Make delivery work."
        ],
        "impacted_files": ["frontend/src/pages/HomePage.tsx"],
        "api_design": "No API changes.",
        "data_flow_design": "No data-flow changes.",
        "risks": ["Text-only change risk is limited to homepage copy."],
        "test_strategy": ["Inspect the file and run the frontend build if available."],
        "validation_report": "Plan is scoped to the user requested homepage copy change.",
        "requirement_refs": ["message://run-1/user/1"],
        "evidence_refs": ["stage-process://stage-run-1/model-call/1"],
    }

    decision = AgentDecisionParser().parse_model_result(
        model_result(structured_output=payload),
        context_envelope=context_envelope(stage_type=StageType.SOLUTION_DESIGN),
        stage_contract=stage_contract(
            allowed_tools=[],
            output_contract="SolutionDesignArtifact",
            structured_artifact_required="SolutionDesignArtifact",
        ),
    )

    assert decision.decision_type is AgentDecisionType.SUBMIT_STAGE_ARTIFACT
    assert decision.stage_artifact is not None
    assert decision.stage_artifact.artifact_type == "SolutionDesignArtifact"
    assert decision.stage_artifact.artifact_payload["impacted_files"] == [
        "frontend/src/pages/HomePage.tsx"
    ]
```

```python
def test_parser_moves_legacy_top_level_artifact_fields_into_payload() -> None:
    from backend.app.runtime.agent_decision import AgentDecisionParser, AgentDecisionType

    decision = AgentDecisionParser().parse_model_result(
        model_result(
            structured_output={
                "decision_type": "submit_stage_artifact",
                "artifact_type": "CodeGenerationArtifact",
                "changeset_ref": "changeset://run-1/code-generation/1",
                "changed_files": ["frontend/src/pages/HomePage.tsx"],
                "diff_refs": ["diff://run-1/code-generation/1"],
                "file_edit_trace_refs": ["file_edit_trace:run-1:call-edit-1:frontend/src/pages/HomePage.tsx"],
                "implementation_notes": "Updated homepage heading text.",
                "requirement_refs": ["message://run-1/user/1"],
                "solution_refs": ["stage-artifact://solution-design/output"],
                "evidence_refs": ["file_edit_trace:run-1:call-edit-1:frontend/src/pages/HomePage.tsx"],
            }
        ),
        context_envelope=context_envelope(),
        stage_contract=stage_contract(),
    )

    assert decision.decision_type is AgentDecisionType.SUBMIT_STAGE_ARTIFACT
    assert decision.stage_artifact is not None
    assert decision.stage_artifact.artifact_payload["changed_files"] == [
        "frontend/src/pages/HomePage.tsx"
    ]
```

- [ ] **Step 2: Run parser tests and verify RED**

Run:

```powershell
uv run python -m pytest backend/tests/runtime/test_agent_decision_parser.py::test_stage_response_schema_uses_submit_artifact_protocol_without_repair_union backend/tests/runtime/test_agent_decision_parser.py::test_parser_wraps_bare_stage_artifact_payload_as_submit_decision backend/tests/runtime/test_agent_decision_parser.py::test_parser_moves_legacy_top_level_artifact_fields_into_payload -q
```

Expected: tests fail because `stage_response_schema` does not exist and bare / legacy artifact outputs are not normalized.

- [ ] **Step 3: Implement minimal schema and deterministic normalization**

In `backend/app/runtime/agent_decision.py`:

- Add `stage_response_schema(artifact_type, allowed_decision_types=None)` that exposes a flat submit-artifact shape plus only stage-valid control decisions.
- Keep `agent_decision_response_schema()` for internal repair compatibility and legacy tests.
- Add deterministic normalization before `_structured_decision_type()`:
  - bare known artifact payload becomes `decision_type=submit_stage_artifact`, `artifact_type=<stage contract artifact>`, `artifact_payload=<bare payload>`, and `evidence_refs` from payload or model-call ref fallback;
  - legacy top-level artifact fields move into `artifact_payload`;
  - `artifact_payload` wrappers are unwrapped only when `artifact_type` matches the current stage contract;
  - known aliases are normalized only when the mapping is unambiguous.

- [ ] **Step 4: Run parser tests and verify GREEN**

Run the same focused parser command. Expected: all three tests pass.

## Task 2: Remove Repair From Normal Stage Calls And Constrain Repair

- [ ] **Step 1: Write failing runtime tests**

Add tests in `backend/tests/runtime/test_stage_agent_runtime.py`:

```python
def test_stage_agent_normalizes_bare_stage_artifact_without_repair_call() -> None:
    runtime = build_runtime(
        provider_results=[
            model_result(
                structured_output={
                    "changeset_ref": "changeset://run-1/code-generation/1",
                    "changed_files": ["frontend/src/pages/HomePage.tsx"],
                    "diff_refs": ["diff://run-1/code-generation/1"],
                    "file_edit_trace_refs": ["file_edit_trace:run-1:call-edit-1:frontend/src/pages/HomePage.tsx"],
                    "implementation_notes": "Updated homepage heading text.",
                    "requirement_refs": ["message://run-1/user/1"],
                    "solution_refs": ["stage-artifact://solution-design/output"],
                }
            )
        ],
        allowed_tools=[],
        available_tools=(),
    )

    result = runtime.run_stage(invocation())

    assert result.status is StageStatus.COMPLETED
    assert len(runtime.provider_adapter.calls) == 1
    assert "structured_output_repair_trace" not in runtime.artifact_store.process
```

```python
def test_parser_error_without_repairable_intent_fails_instead_of_asking_repair_to_decide() -> None:
    runtime = build_runtime(
        provider_results=[model_result(structured_output={"decision_type": "not-a-decision"})],
    )

    result = runtime.run_stage(invocation())

    assert result.status is StageStatus.FAILED
    assert len(runtime.provider_adapter.calls) == 1
    assert "structured_output_repair_trace" not in runtime.artifact_store.process
    assert runtime.artifact_store.process["stage_agent_failed"]["reason"] == "invalid_structured_output"
```

Update the existing structured repair tests so ordinary `_base_response_schema` and dispatcher `_response_schema` do not include `repair_structured_output`.

- [ ] **Step 2: Run runtime tests and verify RED**

Run:

```powershell
uv run python -m pytest backend/tests/runtime/test_stage_agent_runtime.py::test_stage_agent_normalizes_bare_stage_artifact_without_repair_call backend/tests/runtime/test_stage_agent_runtime.py::test_parser_error_without_repairable_intent_fails_instead_of_asking_repair_to_decide backend/tests/services/test_runtime_execution_service.py::test_dispatch_started_run_default_dispatcher_drives_until_approval_checkpoint -q
```

Expected: tests fail because parser errors still enter repair and normal schemas still expose repair.

- [ ] **Step 3: Implement normal schema routing and repair guard**

In `backend/app/runtime/stage_agent.py` and `backend/app/services/runtime_dispatch.py`:

- Use `stage_response_schema()` for normal stage execution.
- Remove `REPAIR_STRUCTURED_OUTPUT` from `_base_response_schema_decision_types()`.
- Keep `_structured_output_repair_response_schema()` internal and non-recursive.
- Change `_repair_from_parser_error()` so only repairable structural errors with an inferred original action can enter repair. Missing or invalid `decision_type` without a recoverable artifact intent fails immediately.
- When repair runs, pass a schema restricted to the original intended decision. Repair must not convert an apparent submit artifact into `fail_stage`.

- [ ] **Step 4: Run runtime tests and verify GREEN**

Run the same focused runtime command. Expected: all selected tests pass.

## Task 3: Semantic Gates For Solution Design And Code Generation

- [ ] **Step 1: Write failing semantic tests**

Add tests in `backend/tests/runtime/test_stage_agent_runtime.py`:

```python
def test_solution_design_rejects_unrelated_generic_plan_before_code_generation() -> None:
    runtime = build_runtime(
        provider_results=[
            model_result(
                structured_output={
                    "decision_type": "submit_stage_artifact",
                    "artifact_type": "SolutionDesignArtifact",
                    "artifact_payload": {
                        "technical_plan": "Extend the data processing pipeline with a validation stage.",
                        "implementation_plan": ["Create src/pipeline/validator.py"],
                        "impacted_files": ["src/pipeline/orchestrator.py", "src/pipeline/validator.py"],
                        "api_design": "No API changes.",
                        "data_flow_design": "Add validator data flow.",
                        "risks": ["Pipeline validation may reject records."],
                        "test_strategy": ["Add tests/test_validator.py"],
                        "validation_report": "Generic data validation plan.",
                        "requirement_refs": ["REQ-PIPE-101"],
                        "evidence_refs": ["stage-process://stage-run-1/model-call/1"],
                    },
                    "evidence_refs": ["stage-process://stage-run-1/model-call/1"],
                }
            )
        ],
        allowed_tools=[],
        available_tools=(),
        stage_type=StageType.SOLUTION_DESIGN,
        structured_artifact_required="SolutionDesignArtifact",
        task_objective="项目的官网主页面帮我把Make delivery work traceable.改成Make delivery work",
    )

    result = runtime.run_stage(invocation(stage_type=StageType.SOLUTION_DESIGN))

    assert result.status is StageStatus.FAILED
    assert runtime.artifact_store.complete_calls == []
    assert runtime.artifact_store.process["stage_agent_failed"]["reason"] == "stage_semantic_gate_failed"
```

```python
def test_code_generation_rejects_missing_file_failure_when_design_identifies_target() -> None:
    design_artifact = SimpleNamespace(
        artifact_type="SolutionDesignArtifact",
        payload={
            "impacted_files": ["frontend/src/pages/HomePage.tsx"],
            "implementation_plan": ["Edit frontend/src/pages/HomePage.tsx heading text."],
        },
        artifact_id="artifact-solution-design",
    )
    runtime = build_runtime(
        provider_results=[
            model_result(
                structured_output={
                    "decision_type": "fail_stage",
                    "failure_reason": "Missing target website file.",
                    "evidence_refs": ["stage-process://stage-run-1/model-call/1"],
                    "incomplete_items": ["implementation"],
                    "user_visible_summary": "Cannot continue because the website file is missing.",
                }
            )
        ],
        stage_artifacts=[design_artifact],
        task_objective="项目的官网主页面帮我把Make delivery work traceable.改成Make delivery work",
    )

    result = runtime.run_stage(invocation())

    assert result.status is StageStatus.FAILED
    assert runtime.artifact_store.process["stage_agent_failed"]["reason"] == "stage_semantic_gate_failed"
```

- [ ] **Step 2: Run semantic tests and verify RED**

Run:

```powershell
uv run python -m pytest backend/tests/runtime/test_stage_agent_runtime.py::test_solution_design_rejects_unrelated_generic_plan_before_code_generation backend/tests/runtime/test_stage_agent_runtime.py::test_code_generation_rejects_missing_file_failure_when_design_identifies_target -q
```

Expected: tests fail because no semantic gate rejects unrelated solution plans or unsupported code-generation failures.

- [ ] **Step 3: Implement semantic validation**

In `backend/app/runtime/stage_agent.py`:

- Before `submit_stage_artifact()`, validate stage artifacts against stage semantics.
- For `SolutionDesignArtifact`:
  - `requirement_refs` must be present and non-empty.
  - `implementation_plan` must be non-empty and actionable.
  - `impacted_files`, `implementation_plan`, or evidence must overlap obvious user target terms when the task objective names a file/domain phrase such as homepage/frontpage/官网.
  - Reject generic pipeline/data-validation plans for a homepage copy objective.
- For `CodeGenerationArtifact`:
  - `changed_files` must stay within solution design `impacted_files` when prior solution artifact provides them.
  - `file_edit_trace_refs` must cite actual edit/write side-effect evidence when edit/write tools are allowed.
- For `fail_stage` during Code Generation:
  - reject “missing file/path” failure claims when prior design or task objective names a target file/source area and no tool evidence supports the missing-file claim.

- [ ] **Step 4: Run semantic tests and verify GREEN**

Run the same semantic command. Expected: both tests pass.

## Task 4: Prompt Alignment And Regression

- [ ] **Step 1: Update prompt tests if needed**

Keep prompt assertions aligned with the new protocol: ordinary runtime instructions should describe a stage response protocol with runtime-owned wrapping, not require every ordinary stage call to return the full `AgentDecision` union.

- [ ] **Step 2: Update prompts**

In prompt assets:

- `runtime_instructions.md`: say ordinary stage calls return the required stage artifact or allowed control response; runtime wraps submit artifacts into internal `AgentDecision`.
- `structured_output_repair.md`: say repair is format-only and must preserve original action, stage, artifact type, status, and business decision.

- [ ] **Step 3: Run prompt/context regression**

Run:

```powershell
uv run python -m pytest backend/tests/prompts/test_prompt_renderer.py backend/tests/context/test_context_envelope_builder.py -q
```

Expected: tests pass with updated assertions or unchanged compatible prompt assertions.

## Task 5: Final Verification And Review

- [x] **Step 1: Run focused runtime suite**

Run:

```powershell
uv run python -m pytest backend/tests/runtime/test_agent_decision_parser.py backend/tests/runtime/test_stage_agent_runtime.py backend/tests/runtime/test_stage_agent_process_records.py backend/tests/services/test_runtime_execution_service.py -q
```

Actual result:

```text
84 passed in 11.61s
```

- [x] **Step 2: Run impacted backend regression**

Run:

```powershell
uv run python -m pytest backend/tests/context backend/tests/prompts backend/tests/providers/test_langchain_adapter.py backend/tests/runtime backend/tests/services/test_runtime_execution_service.py -q
```

Actual result:

```text
350 passed, 3 warnings in 26.45s
```

The warnings are the existing LangChain adapter `temperature` model_kwargs warning in provider tests.

- [x] **Step 3: Review gates**

Use reviewer subagents when available. Reviewer inputs:

- Plan file: `docs/plans/implementation/stage-output-protocol-simplification.md`
- Changed files only.
- Required checks: source trace compliance, no repair-as-normal-path regression, no semantic drift, test coverage sufficiency, no prompt/spec contradiction.

Subagents may only use `gpt-5.5` with `xhigh` reasoning, must not perform Git write operations, must not update platform/split plan final statuses, and must not expand the slice.

Actual review result:

- Spec / protocol review: main-thread review found no Critical or Important findings after the schema evidence_refs compatibility fix.
- Code quality / regression review: main-thread review found no Critical or Important findings after the schema evidence_refs compatibility fix.
- Subagent review note: two reviewer subagent attempts were launched with `gpt-5.5` and `xhigh`, but both timed out without findings and were shut down. Their incomplete work was not used as approval evidence.
- Follow-up applied during review: added `test_stage_response_schema_allows_bare_artifact_evidence_refs` and changed the bare stage artifact schema to allow optional envelope-level `evidence_refs`, preventing strict structured-output rejection of valid bare artifact responses.

- [x] **Step 4: Completion evidence**

Update this plan with actual red/green command results, review findings, verification output, changed-file list, remaining risks, and commit recommendation after fresh verification.

## Completion Evidence

### Red / Green Evidence

- Parser normalization and schema tests:
  - RED: focused parser tests failed before `stage_response_schema` and deterministic wrapping existed.
  - GREEN: `uv run python -m pytest backend/tests/runtime/test_agent_decision_parser.py -q`
  - Result: `30 passed`
- Runtime repair-path tests:
  - RED: invalid or bare stage outputs still entered structured-output repair.
  - GREEN: focused runtime tests passed after normal stage calls used `stage_response_schema()` and parser repair was gated by identifiable decision intent.
- Semantic gate tests:
  - RED: unrelated Solution Design artifacts and unsupported Code Generation missing-file failures were accepted as normal model decisions.
  - GREEN: semantic gate tests passed after adding Solution Design and Code Generation validation.
- Review-discovered schema compatibility test:
  - RED: `uv run python -m pytest backend/tests/runtime/test_agent_decision_parser.py::test_stage_response_schema_allows_bare_artifact_evidence_refs -q` failed with `KeyError: 'evidence_refs'`.
  - GREEN: same command passed after allowing optional bare artifact `evidence_refs`.

### Changed Files

- `backend/app/runtime/agent_decision.py`
- `backend/app/runtime/stage_agent.py`
- `backend/app/services/runtime_dispatch.py`
- `backend/app/prompts/renderer.py`
- `backend/app/prompts/assets/runtime/runtime_instructions.md`
- `backend/app/prompts/assets/repairs/structured_output_repair.md`
- `backend/tests/runtime/test_agent_decision_parser.py`
- `backend/tests/runtime/test_stage_agent_runtime.py`
- `backend/tests/runtime/test_stage_agent_process_records.py`
- `backend/tests/services/test_runtime_execution_service.py`
- `backend/tests/prompts/test_prompt_renderer.py`
- `backend/tests/prompts/test_prompt_asset_loading.py`
- `backend/tests/prompts/test_prompt_renderer_manifest_metadata.py`
- `backend/tests/context/test_context_envelope_builder.py`
- `docs/plans/implementation/stage-output-protocol-simplification.md`

### Final Verification

```powershell
uv run python -m pytest backend/tests/runtime/test_agent_decision_parser.py backend/tests/runtime/test_stage_agent_runtime.py backend/tests/runtime/test_stage_agent_process_records.py backend/tests/services/test_runtime_execution_service.py -q
```

```text
84 passed in 11.61s
```

```powershell
uv run python -m pytest backend/tests/context backend/tests/prompts backend/tests/providers/test_langchain_adapter.py backend/tests/runtime backend/tests/services/test_runtime_execution_service.py -q
```

```text
350 passed, 3 warnings in 26.45s
```

```powershell
git diff --check
```

```text
Only CRLF conversion warnings; no whitespace errors.
```

### Remaining Risks

- The new semantic gates intentionally cover high-signal cases: unrelated Solution Design output, changed files outside Solution Design boundaries, and unsupported missing-file failure claims. They do not replace full semantic validation for every possible requirement category.
- The stage response schema still uses `oneOf` because control decisions remain schema-distinct. The exposed schema is smaller than the previous full `AgentDecision` union and excludes runtime-internal repair from ordinary stage calls.

### Commit Recommendation

This is one coherent stabilization checkpoint. It is suitable for a `fix(runtime)` commit after the user asks to commit or confirms commit closeout.
