# AL04-QA-E2E-V6.3-HARNESS Worker Evidence Report

## Claim

| Field | Value |
| --- | --- |
| Claim | `AL04-QA-E2E-V6.3-HARNESS` |
| Lane | `AL04` |
| Task | `A4.3a` |
| Branch | `feat/al-tools-deterministic-delivery` |
| Coordination Base | `c7b5877` |
| Evidence result | `reported` |
| Expected committed ingest result | `implemented` |
| Implementation plan | `docs/plans/implementation/a4.3a-deterministic-e2e-advancement-harness.md` |

Worker HEAD is not declared by this worker report. The main coordination session reads branch HEAD during ingest.

## Gate Summary

- Current branch: `feat/al-tools-deterministic-delivery`
- Active claim status at worker start: `claimed`
- Claim branch matched the current branch.
- Platform task status: A4.3a `[ ]`
- Split-plan task status: A4.3a `[ ]`
- Owner boundary target: test-owned deterministic runtime advancement harness in AL04 scope.
- No coordination store, acceleration execution plan, platform-plan final status, or split-plan final status is updated by this worker branch.

## Scope Outcome

- Added `backend.app.testing.create_e2e_test_app()` as a test-only app factory that wraps the normal `create_app()` and registers the harness outside `/api`.
- Added a hidden `/__test__/runtime/runs/{runId}/advance` command route with `include_in_schema=False`.
- Kept default `create_app()` and production API router unchanged.
- Implemented `DeterministicRuntimeAdvancementHarness` to:
  - open real control/runtime/event/log sessions from the app database manager;
  - rebuild `RuntimeExecutionContext` from persisted `PipelineRun`, current `StageRun`, provider snapshots, model binding snapshots, and `GraphThreadRef`;
  - configure the existing `DeterministicRuntimeEngine` for solution-design approval and code-generation high-risk tool confirmation;
  - call `DeterministicRuntimeEngine.run_next()` instead of fabricating run state, projection payloads, SSE payloads, or events;
  - return stable ids and refs needed by browser E2E while product state remains sourced from normal workspace/timeline/SSE APIs.
- Added focused E2E coverage proving:
  - default app route isolation and OpenAPI isolation;
  - normal `POST /api/sessions/{sessionId}/messages` starts the persisted run;
  - harness advancement reaches `waiting_approval`;
  - normal approval API emits `approval_result`;
  - harness advancement continues the same run to `waiting_tool_confirmation`;
  - workspace, timeline, and bounded SSE expose real approval and tool-confirmation facts;
  - tool confirmation remains distinct from approval and contains no `approval_id`;
  - missing and blocked advancement errors return stable error envelopes;
  - app-state runtime/checkpoint port fallback matches existing route helper semantics when `h45_*` ports are present but `None`.

## Changed Files

- `backend/app/testing/__init__.py`
- `backend/app/testing/e2e_runtime.py`
- `backend/tests/e2e/test_deterministic_runtime_advancement_harness.py`
- `docs/plans/implementation/a4.3a-deterministic-e2e-advancement-harness.md`
- `docs/plans/acceleration/reports/AL04-QA-E2E-V6.3-HARNESS.md`

## TDD Evidence

Initial RED:

```text
uv run pytest backend/tests/e2e/test_deterministic_runtime_advancement_harness.py::test_default_app_does_not_register_deterministic_advancement_harness -v
Exit code: 1
Key output: ModuleNotFoundError: No module named 'backend.app.testing'
```

Initial GREEN:

```text
uv run pytest backend/tests/e2e/test_deterministic_runtime_advancement_harness.py -v
Exit code: 0
Key output: 3 passed
```

Review-fix RED:

```text
uv run pytest backend/tests/e2e/test_deterministic_runtime_advancement_harness.py -v
Exit code: 1
Key output: test_e2e_harness_falls_back_to_h41_ports_when_h45_ports_are_none FAILED
Failure: AttributeError: 'NoneType' object has no attribute 'save_checkpoint'
```

Review-fix GREEN:

```text
uv run pytest backend/tests/e2e/test_deterministic_runtime_advancement_harness.py -v
Exit code: 0
Key output: 4 passed
```

## Review Result

Spec / plan compliance review:

- Result: no Critical or Important findings.
- Minor findings:
  - default app route isolation test could be stronger;
  - service-internal commits mean full post-service atomic rollback is not independently proven by the harness.
- Action:
  - strengthened route isolation with direct route-table assertion and malformed-body 404 check;
  - documented remaining rollback boundary risk below.

Code quality / test sufficiency review:

- Initial review found Important issues:
  - app-state port fallback returned `None` when `h45_*` attributes existed but were set to `None`;
  - default-app isolation assertion could false-pass if a hidden route was registered;
  - stable error test checked only `error_code`.
- Fixes:
  - matched existing route helper fallback semantics: `h45_*` -> `h41_*` -> in-memory port;
  - added route-table and malformed-body isolation assertions;
  - added stable `message`, `request_id`, and `correlation_id` assertions.
- Re-review result: no Critical, Important, or Minor findings remain in the scoped re-review.

## Verification

Focused harness verification:

```text
uv run pytest backend/tests/e2e/test_deterministic_runtime_advancement_harness.py -v
Exit code: 0
Key output: 4 passed in 4.83s
```

Impacted full API flow regression:

```text
uv run pytest backend/tests/e2e/test_full_api_flow.py -v
Exit code: 0
Key output: 2 passed in 2.54s
```

OpenAPI regression:

```text
uv run pytest backend/tests/api/test_openapi_contract.py -v
Exit code: 0
Key output: 2 passed in 1.76s
```

Human-loop command regression:

```text
uv run pytest backend/tests/api/test_pause_resume_api.py backend/tests/api/test_approval_api.py backend/tests/api/test_tool_confirmation_api.py -v
Exit code: 0
Key output: 30 passed in 18.80s
```

Full backend suite:

```text
uv run pytest -q
Exit code: 0
Key output: 1329 passed, 3 warnings in 457.16s (0:07:37)
Warnings: existing backend/tests/providers/test_langchain_adapter.py UserWarning about explicit temperature parameters passed through model_kwargs.
```

Post-full-suite tracking-only updates:

- After the final full backend suite passed, only `docs/plans/implementation/a4.3a-deterministic-e2e-advancement-harness.md` and this evidence report were updated with verification evidence.
- No code, test, configuration, dependency manifest, lockfile, or runtime-behavior artifact changed after the full suite.

## Owner Conflict Check

No owner conflict was introduced.

- AL04 deterministic runtime was consumed through its public `DeterministicRuntimeEngine` API.
- AL03 approval and tool-confirmation semantics were consumed through existing services and normal API routes; AL03 service files were not modified.
- Production API route modules and `build_api_router()` were not modified.
- Frontend and Playwright files were not modified.
- Shared coordination store, acceleration execution plan, platform-plan final status, and split-plan final status were not modified.

## Remaining Risk

- The harness rolls back opened sessions for precondition failures and runtime errors it handles directly. Existing `ApprovalService` and `ToolConfirmationService` perform their own commits during interrupt creation, so a synthetic failure injected after those service calls would not be fully atomic at the harness layer. This follows existing service behavior and is not used to fabricate product state.
- SSE assertions prove that normal bounded stream output includes approval and tool-confirmation event types. They do not parse every SSE frame payload field; workspace and timeline assertions cover the product projection fields required by this slice.
- `uv run ruff check ...` was attempted by the implementer as an extra style check, but `ruff` is not available in the local uv environment. No dependencies or manifests were changed.

## Commit Readiness

Local result is `reported`. After a checkpoint commit containing code, tests, implementation plan, and this evidence report, the main coordination session can ingest this claim as `implemented`.
