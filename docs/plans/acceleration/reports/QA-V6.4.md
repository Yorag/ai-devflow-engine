# QA-V6.4 Worker Evidence Report

## Claim

| Field | Value |
| --- | --- |
| Claim | `QA-V6.4` |
| Lane | `QA` |
| Task | `V6.4` |
| Branch | `test/al-regression-hardening` |
| Coordination Base | `2e682ec` |
| Evidence report | `docs/plans/acceleration/reports/QA-V6.4.md` |
| Local result | `reported` |
| Expected ingest result after checkpoint commit | `implemented` |
| Implementation plan | `docs/plans/implementation/v6.4-openapi-route-coverage.md` |

Worker HEAD is intentionally not declared here. The main coordination session reads the branch head during ingest.

## Gate Summary

Read-only worker gate passed for `QA-V6.4` on the resumed Q3.2a baseline:

```text
Command: uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py worker-start --json
Exit code: 0
Key output: branch test/al-regression-hardening, claim QA-V6.4, task V6.4, lane QA, status claimed, coordination_base 2e682ec, branch_head 2e682ec, target_head 2e682ec
```

```text
Command: uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py validate-worker --claim QA-V6.4 --branch test/al-regression-hardening --status claimed --status reported --json
Exit code: 0
Key output: claim QA-V6.4 validated on branch test/al-regression-hardening with status claimed and coordination_base 2e682ec
```

No coordination store, checkpoint snapshot, `docs/plans/function-one-acceleration-execution-plan.md`, `docs/plans/function-one-platform-plan.md`, or split-plan final status was updated.

## Scope

Implemented only `V6.4`: OpenAPI core route coverage.

Changed files:

- `backend/tests/api/test_openapi_contract.py`
- `docs/api/function-one-openapi-notes.md`
- `README.md`
- `docs/plans/implementation/v6.4-openapi-route-coverage.md`
- `docs/plans/acceleration/reports/QA-V6.4.md`

The slice adds no production route, schema, service, runtime, frontend, dependency, lock, migration, environment, coordination, platform-plan, or split-plan final status changes.

## Implemented Coverage

- `GET /api/openapi.json` returns the current machine-readable OpenAPI document.
- `GET /api/docs` returns readable HTML documentation referencing `/api/openapi.json`.
- Global route coverage asserts core Function One path/method presence across project, session, provider, template, runtime settings, approval, run lifecycle, query, inspector, delivery, preview target, tool confirmation, log, audit, and SSE route groups.
- Tool confirmation command/detail routes assert request schemas, response schemas, and main error responses.
- Approval command routes assert request schemas, response schemas, and main error responses.
- Q3.2a run summary route `GET /api/runs/{runId}` asserts `RunStatusSummaryProjection`, `runId` parameter, and main error responses.
- Run/stage log and audit log routes assert query parameters, response schemas, and main error responses; audit coverage includes `stage_run_id` and `correlation_id`.
- SSE route asserts `sessionId`, `after`, and `limit` parameters, `text/event-stream` response, and event/feed payload component schemas. The companion note explicitly tracks `session_status_changed` payload fields `session_id`, `status`, `current_run_id`, and `current_stage_type`.
- `docs/api/function-one-openapi-notes.md` records the V6.4 coverage boundary and README links it from the repository map.

## TDD Evidence

Initial RED on the old baseline:

```text
Command: uv run pytest backend/tests/api/test_openapi_contract.py -v
Exit code: 1
Key output: OpenAPI route/schema coverage initially exposed a plan naming error for `PreviewTargetProjection`; docs companion note was missing as expected.
```

Plan correction:

```text
Root cause: existing W5.6 route-local contract and current OpenAPI schema use `PreviewTarget`, not `PreviewTargetProjection`.
Action: corrected the implementation plan and test expectation to `PreviewTarget`.
```

Focused RED after plan correction:

```text
Command: uv run pytest backend/tests/api/test_openapi_contract.py -v
Exit code: 1
Key output: OpenAPI route/schema coverage passed; remaining failure was `test_openapi_companion_note_is_tracked_and_linked` at `assert notes_path.exists()`.
```

Focused GREEN before review fixes:

```text
Command: uv run pytest backend/tests/api/test_openapi_contract.py -v
Exit code: 0
Key output: 2 passed
```

Spec-review RED before Q3.2a:

```text
Command: uv run pytest backend/tests/api/test_openapi_contract.py -v
Exit code: 1
Key output: `test_openapi_document_covers_function_one_core_routes_and_docs` failed with `missing_paths == {'/api/runs/{runId}'}`; companion note test passed.
```

Q3.2a baseline sync:

```text
Key output: branch head and integration target are both 2e682ec (`chore(integration): close out AL02 Q3.2a checkpoint`), and generated OpenAPI now contains `GET /api/runs/{runId}` with `RunStatusSummaryProjection`.
```

Focused GREEN after Q3.2a and V6.4 route-specific assertion update:

```text
Command: uv run pytest backend/tests/api/test_openapi_contract.py -v
Exit code: 0
Key output: 2 passed in 1.66s
```

Review-fix RED for `session_status_changed` payload documentation:

```text
Command: uv run pytest backend/tests/api/test_openapi_contract.py -v
Exit code: 1
Key output: route/OpenAPI coverage passed; companion note test failed because `session_status_changed` was missing from `docs/api/function-one-openapi-notes.md`.
```

Focused GREEN after `session_status_changed` payload documentation:

```text
Command: uv run pytest backend/tests/api/test_openapi_contract.py -v
Exit code: 0
Key output: 2 passed in 1.73s
```

Review-fix RED for audit query parameter documentation:

```text
Command: uv run pytest backend/tests/api/test_openapi_contract.py -v
Exit code: 1
Key output: route/OpenAPI coverage passed; companion note test failed because `stage_run_id` was missing from `docs/api/function-one-openapi-notes.md`.
```

Focused GREEN after audit parameter coverage update:

```text
Command: uv run pytest backend/tests/api/test_openapi_contract.py -v
Exit code: 0
Key output: 2 passed in 1.72s
```

Final impacted API/OpenAPI regression:

```text
Command: uv run pytest backend/tests/api/test_openapi_contract.py backend/tests/api/test_approval_api.py backend/tests/api/test_tool_confirmation_api.py backend/tests/api/test_query_api.py backend/tests/api/test_sse_stream.py backend/tests/api/test_audit_log_api.py -v
Exit code: 0
Key output: 54 passed in 34.44s
```

Final backend API suite:

```text
Command: uv run pytest backend/tests/api -q
Exit code: 0
Key output: 166 passed in 112.85s
```

## Review

Initial spec / plan compliance review found two Important issues and one Minor issue:

- Important: V6.4 global route coverage omitted approval command routes.
- Important: V6.4 global route coverage omitted `GET /api/runs/{runId}`, which the backend spec lists as a core query API.
- Minor: implementation plan wording made evidence-report ownership ambiguous.

Fixes applied inside QA scope:

- Added `POST /api/approvals/{approvalId}/approve` and `POST /api/approvals/{approvalId}/reject` to global route coverage.
- Added approval request/response/error schema assertions.
- Added `GET /api/runs/{runId}` to the global route coverage list.
- On the Q3.2a baseline, added `RunStatusSummaryProjection`, `runId` parameter, and main error response assertions for `GET /api/runs/{runId}`.
- Clarified that the main agent updates the worker evidence report.

Resumed spec / plan compliance re-review after Q3.2a found no Critical or Important issues. It recorded one Minor note that new files remain untracked until commit staging, and one residual test gap: the SSE payload shape is asserted through route boundary, component presence, and companion note text because the current SSE route documents `text/event-stream` as a string response.

Code quality / testing / regression review found one Important issue and one Minor issue:

- Important: global audit query coverage omitted `stage_run_id` and `correlation_id`.
- Minor: this report still said spec compliance re-review was pending.

Fixes applied inside QA scope:

- Added `stage_run_id` and `correlation_id` to the `/api/audit-logs` global parameter assertion.
- Added companion note assertions and documentation for `stage_run_id` and `correlation_id`.
- Updated this report with the completed review and verification evidence.

Code quality re-review found no Critical or Important issues remaining. Residual risk is limited to V6.4's intended summary-regression boundary: parameter assertions are name-based subsets, while route-local tests cover deeper OpenAPI parameter location, requiredness, and schema details.

## Owner Conflict

- Mock-first status: not mock-first; implemented against the current integrated FastAPI/OpenAPI output.
- Owner conflict: none remaining on the resumed Q3.2a baseline.
- Previously blocked gap: `GET /api/runs/{runId}` was missing from the old baseline. Q3.2a resolved it before this resumed verification.
- Product truth: assertions use generated FastAPI OpenAPI and route-local schema contracts; runtime logs and audit rows are not used as product truth.

## Commit Readiness

The local worker result is `reported`. After the checkpoint commit contains the implementation plan, OpenAPI regression test, API note, README link, and this evidence report, the main coordination session can ingest `QA-V6.4` as `implemented`.
