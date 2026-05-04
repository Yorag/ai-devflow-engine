# QA-V6.1 Worker Evidence Report

## Claim

| Field | Value |
| --- | --- |
| Claim | `QA-V6.1` |
| Lane | `QA` |
| Task | `V6.1` |
| Branch | `test/al-regression-hardening` |
| Coordination Base | `a2fabbf` |
| Evidence report | `docs/plans/acceleration/reports/QA-V6.1.md` |
| Local result | `reported` |
| Expected ingest result after checkpoint commit | `implemented` |
| Implementation plan | `docs/plans/implementation/v6.1-backend-full-api-flow.md` |

Worker HEAD is intentionally not declared here. The main coordination session reads the branch head during ingest.

## Gate Summary

Read-only worker gate passed for `QA-V6.1`:

```text
Command: uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py worker-start --json
Exit code: 0
Key output: branch test/al-regression-hardening, claim QA-V6.1, task V6.1, lane QA, status claimed, coordination_base a2fabbf
```

```text
Command: uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py validate-worker --claim QA-V6.1 --branch test/al-regression-hardening --status claimed --status reported --json
Exit code: 0
Key output: claim QA-V6.1 validated on branch test/al-regression-hardening with status claimed
```

Platform and split-plan task status remained `[ ]`. No coordination store, checkpoint snapshot, `docs/plans/function-one-acceleration-execution-plan.md`, `docs/plans/function-one-platform-plan.md`, or split-plan final status was updated.

## Scope

Implemented only `V6.1`: backend full API flow regression coverage.

Changed files:

- `backend/tests/e2e/test_full_api_flow.py`
- `docs/plans/implementation/v6.1-backend-full-api-flow.md`
- `docs/plans/acceleration/reports/QA-V6.1.md`

The slice adds no production route, schema, service, runtime, frontend, dependency, lock, migration, environment, coordination, platform-plan, or split-plan final status changes.

## Implemented Coverage

- New Session creation through `POST /api/projects/project-default/sessions`.
- First `new_requirement` through `POST /api/sessions/{sessionId}/messages`, verifying automatic `PipelineRun` startup and first `requirement_analysis` stage.
- Deterministic runtime advancement in-process through `DeterministicRuntimeEngine.run_next()` because no public runtime-advance API exists.
- Public approval and tool-confirmation commands through API routes.
- Public workspace, timeline, stage Inspector, ToolConfirmationInspectorProjection, and DeliveryRecord detail queries.
- Successful path from new requirement through all deterministic business stages to `delivery_result`.
- Top-level Narrative Feed and timeline entries for `approval_request`, `approval_result`, `tool_confirmation`, and `delivery_result`.
- Tool confirmation allow and deny command paths, including follow-up fields for denial.
- ToolConfirmationInspectorProjection identity, status, input risk fields, process trace refs, tool result refs, output result status, and output tool result refs.
- DeliveryRecord detail for demo delivery mode, succeeded status, delivery process record, and `no_git_actions == True`.
- Generic delivery stage Inspector identity/status/output/artifact refs without injecting delivery-process-only evidence into that stage projection.
- Provider retry and circuit breaker evidence reaching stage Inspector from artifact process refs and provider-call event records.

## TDD Evidence

Initial RED:

```text
Command: uv run pytest backend/tests/e2e/test_full_api_flow.py -v
Key output: initial command reported the new test file was missing.
```

Flow assertion RED after the first test implementation:

```text
Command: uv run pytest backend/tests/e2e/test_full_api_flow.py -v
Key output: 1 failed, 1 passed because delivery process evidence was being asserted through fixture-seeded delivery stage Inspector data.
```

GREEN:

```text
Command: uv run pytest backend/tests/e2e/test_full_api_flow.py -v
Exit code: 0
Key output: 2 passed in 2.35s
```

Post-review cleanup GREEN:

```text
Command: uv run pytest backend/tests/e2e/test_full_api_flow.py -v
Exit code: 0
Key output: 2 passed in 2.37s
```

## Review

Spec and plan review initially found one Important issue:

- Delivery process and `no_git_actions` assertions were tied to fixture-seeded delivery stage Inspector evidence. That blurred the contract between generic stage Inspector and DeliveryRecord detail projection.

Fix applied:

- Removed delivery stage Inspector trace seeding.
- Asserted delivery process and `no_git_actions` through `GET /api/delivery-records/{deliveryRecordId}`.
- Kept `GET /api/stages/{deliveryStageRunId}/inspector` assertions to generic stage identity, status, output ref, and artifact refs.

Spec re-review found no Critical or Important findings.

Code quality review initially reported only Minor findings. The cleanup addressed them by:

- Returning the control session explicitly from `_build_engine()` instead of writing a private attribute onto the engine.
- Checking deterministic stage coverage by `StageType` membership and completed status instead of relying on tied `started_at` ordering.
- Strengthening ToolConfirmationInspectorProjection allow and deny assertions for risk, process, and output fields.

Final read-only review with `gpt-5.5` `xhigh` found no Critical, Important, or Minor findings.

## Verification

Focused slice verification:

```text
Command: uv run pytest backend/tests/e2e/test_full_api_flow.py -v
Exit code: 0
Key output: 2 passed in 2.37s
```

Impacted API/projection/runtime regression:

```text
Command: uv run pytest backend/tests/api/test_session_message_api.py backend/tests/api/test_tool_confirmation_api.py backend/tests/api/test_query_api.py backend/tests/e2e/test_deterministic_run_flow.py -v
Exit code: 0
Key output: 37 passed in 22.03s
```

Full backend suite:

```text
Command: uv run pytest -q
Exit code: 0
Key output: 1279 passed, 3 warnings in 341.04s
Warnings: three existing LangChain adapter warnings about temperature being passed through model_kwargs.
```

Pre-commit focused rerun after evidence documentation update:

```text
Command: uv run pytest backend/tests/e2e/test_full_api_flow.py -v
Exit code: 0
Key output: 2 passed in 4.26s
```

Compile check:

```text
Command: uv run python -m compileall backend/tests/e2e/test_full_api_flow.py
Exit code: 0
Key output: Compiling 'backend/tests/e2e/test_full_api_flow.py'...
```

Only implementation/evidence documentation was updated after the full backend suite. No code, test, dependency, config, lock, or runtime behavior file was changed after the full-suite verification run.

## Owner Conflict

- Mock-first status: not mock-first; implemented against existing backend runtime, projection, delivery, and command APIs.
- Owner conflict: none observed. The slice is QA-owned regression coverage and does not modify another lane owner's production entry points.
- Real provider / remote delivery: not used. The test uses deterministic runtime and demo delivery only.
- Product truth: assertions use domain models, events, Narrative Feed, Inspector, and DeliveryRecord projections; `.runtime/logs` and log tables are not used as authoritative product state.

## Commit Readiness

The local worker result is `reported`. After the checkpoint commit contains the implementation plan, E2E test, and this evidence report, the main coordination session can ingest `QA-V6.1` as `implemented`.
