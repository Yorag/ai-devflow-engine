# Function One Platform Acceptance Checklist

## Release Candidate Summary

This Release Candidate Acceptance Checklist consolidates feature-one platform V1 acceptance evidence. It does not replace the current split specifications:

- `docs/specs/function-one-product-overview-v1.md`
- `docs/specs/frontend-workspace-global-design-v1.md`
- `docs/specs/function-one-backend-engine-design-v1.md`

| Field | Value |
| --- | --- |
| Release candidate branch | `test/qa-release-candidate` |
| Worker HEAD | `5591217` |
| Integration checkpoint | `integration/function-one-acceleration` merge `0852082` |
| Scope | Feature-one V1 regression, projection, E2E, error, configuration, observability, and acceptance evidence consolidation |
| Prerequisite gate | Contract, E2E, error, configuration, and observability QA evidence exists; any retained risk is recorded below |
| Sign-off status | Integrated after V6.7 worker verification, checkpoint verification, and release-candidate checklist review |

## Scope And Sources

Primary sources:

- Product and stage boundary: `docs/specs/function-one-product-overview-v1.md`
- Frontend interaction and presentation semantics: `docs/specs/frontend-workspace-global-design-v1.md`
- Backend domain model, API contract, projection contract, and event semantics: `docs/specs/function-one-backend-engine-design-v1.md`
- Execution slice: `docs/plans/function-one-platform/09-regression-hardening-and-logs.md#v67`
- Implementation plan: `docs/plans/implementation/v6.7-regression-release-candidate.md`

This checklist records acceptance coverage only. It does not introduce new stage semantics, projection fields, SSE payloads, log/audit truth sources, frontend interactions, or delivery behavior.

## Spec Acceptance Matrix

| Source | Acceptance Area | Release Candidate Evidence |
| --- | --- | --- |
| Product spec section 12 and immutable principles 14-15 | Project/session defaults, first requirement startup, fixed stage flow, approvals, tool confirmation, runtime controls, delivery completion, history, no long-term memory | `QA-V6.1`, `QA-E2E-V6.2-FINAL`, `QA-E2E-V6.3-LIVE`, `QA-CONFIG-V6.8`, V6.7 lifecycle regression |
| Frontend spec sections 10, 12, 13, 15, 18 | Single workspace, Narrative Feed, Inspector, Run Switcher, Composer states, historical replay, responsive and accessibility behavior | `QA-E2E-V6.2-FINAL`, `QA-E2E-V6.3-LIVE`, `QA-ERROR-V6.6`, `QA-CONFIG-V6.8`, V6.7 frontend design gate audit |
| Backend spec sections 8, 11, 12, 15 | REST/OpenAPI, SSE, run/stage state machine, EventStore, projections, deterministic runtime, delivery, log/audit | `QA-V6.1`, `QA-V6.4`, `QA-V6.5`, `QA-ERROR-V6.6`, `QA-CONFIG-V6.8`, `QA-OBS-L6.1`, `QA-OBS-L6.2`, V6.7 projection regression |

## Product Acceptance

| Item | Coverage |
| --- | --- |
| Default project/session | `QA-V6.1`, `QA-E2E-V6.2-FINAL`, `QA-CONFIG-V6.8` |
| First `new_requirement` auto-starts first `PipelineRun` | `QA-V6.1`, V6.7 lifecycle regression |
| Six-stage flow | `QA-V6.1`, V6.7 lifecycle regression |
| Clarification | `QA-E2E-V6.2-FINAL`, `QA-E2E-V6.3-LIVE` |
| Solution and code-review approvals | `QA-V6.1`, `QA-E2E-V6.2-FINAL`, `QA-E2E-V6.3-LIVE` |
| High-risk tool confirmation | `QA-V6.1`, `QA-E2E-V6.3-LIVE` |
| Pause/resume/terminate/rerun | `QA-E2E-V6.3-LIVE`, `QA-ERROR-V6.6` |
| Demo delivery | `QA-V6.1`, `QA-E2E-V6.2-FINAL`, V6.7 lifecycle regression |
| Git auto delivery | `QA-CONFIG-V6.8`, `QA-OBS-L6.2`, existing delivery tool regressions referenced by observability evidence |
| History management | `QA-CONFIG-V6.8`, V6.7 history replay regression |
| No long-term memory | `QA-CONFIG-V6.8`, V6.7 history replay regression |
| Configuration boundaries | `QA-CONFIG-V6.8` |

## Frontend Acceptance

| Item | Coverage |
| --- | --- |
| Single workspace and project/session sidebar | `QA-E2E-V6.2-FINAL`, `QA-CONFIG-V6.8` |
| Template empty state and settings modal | `QA-CONFIG-V6.8` |
| Narrative Feed and Run Switcher | `QA-E2E-V6.2-FINAL`, `QA-E2E-V6.3-LIVE` |
| Composer lifecycle states | `QA-E2E-V6.2-FINAL`, `QA-E2E-V6.3-LIVE`, `QA-ERROR-V6.6` |
| Approval block | `QA-E2E-V6.2-FINAL`, `QA-E2E-V6.3-LIVE`, `QA-ERROR-V6.6` |
| Tool Confirmation block | `QA-E2E-V6.3-LIVE`, `QA-ERROR-V6.6` |
| Provider status | `QA-V6.1`, `QA-E2E-V6.3-LIVE` |
| Inspector and delivery result details | `QA-V6.1`, `QA-E2E-V6.2-FINAL`, `QA-CONFIG-V6.8` |
| Responsive layout, empty/error/history/focus states | `QA-E2E-V6.2-FINAL`, `QA-E2E-V6.3-LIVE`, `QA-ERROR-V6.6`, `QA-CONFIG-V6.8`, V6.7 frontend design gate audit |

## Backend Acceptance

| Item | Coverage |
| --- | --- |
| FastAPI REST and OpenAPI | `QA-V6.4`, `QA-V6.5` |
| SSE | `QA-V6.4`, `QA-E2E-V6.3-LIVE`, V6.7 projection regression |
| Run/stage state machine | `QA-V6.1`, `QA-ERROR-V6.6`, V6.7 lifecycle regression |
| EventStore and projection services | `QA-V6.1`, V6.7 projection regression |
| Inspector | `QA-V6.1`, `QA-E2E-V6.2-FINAL` |
| Deterministic runtime | `QA-V6.1`, `QA-E2E-V6.3-LIVE`, V6.7 lifecycle regression |
| LangGraph boundary | `QA-CONFIG-V6.8` |
| Provider retry/circuit breaker | `QA-V6.1`, `QA-E2E-V6.3-LIVE` |
| ToolProtocol and workspace tools | `QA-OBS-L6.2` impacted workspace and delivery verification |
| DeliveryRecord and git delivery tools | `QA-V6.1`, `QA-OBS-L6.2` |
| Log/audit | `QA-OBS-L6.1`, `QA-OBS-L6.2` |

## Regression Evidence Matrix

| Evidence | Integration Status | Acceptance Role |
| --- | --- | --- |
| `QA-V6.1` | `done` | Backend full API flow and delivery result coverage |
| `QA-E2E-V6.2-FINAL` | `done` | Playwright success path and frontend workspace acceptance |
| `QA-E2E-V6.3-LIVE` | `done` | Live backend-backed manual intervention, SSE, rerun, tool confirmation |
| `QA-V6.4` | `done` | OpenAPI route coverage |
| `QA-V6.5` | `done` | Frontend client/OpenAPI compatibility |
| `QA-ERROR-V6.6` | `done` | Backend and frontend error-state contract regression |
| `QA-CONFIG-V6.8` | `done` | Configuration, snapshot, prompt, settings, and history regression |
| `QA-OBS-L6.1` | `done` | Log rotation, retention, cleanup |
| `QA-OBS-L6.2` | `done` | Log redaction, audit query, runtime log exclusion, audit failure rollback |
| `QA-RELEASE-V6.7` | `done` | Release-candidate lifecycle/projection regression and checklist |

## Full Regression Scenario Coverage

V6.7 verification is recorded by `docs/plans/acceleration/reports/QA-RELEASE-V6.7.md` and the integration checkpoint:

```powershell
uv run --no-sync python -m pytest backend/tests/regression/test_run_lifecycle_regression.py -v
uv run --no-sync python -m pytest backend/tests/regression/test_projection_regression.py -v
uv run --no-sync python -m pytest backend/tests/regression/test_run_lifecycle_regression.py backend/tests/regression/test_projection_regression.py -v
uv run --no-sync python -m pytest backend/tests/regression -v
npm --prefix e2e run test
uv run --no-sync python -m pytest -q
npm --prefix frontend run test -- --run
npm --prefix frontend run build
```

Required scenario assertions:

- Completed deterministic run reaches `Delivery Integration`, writes one `delivery_result`, returns a succeeded `DeliveryRecord`, and marks `PipelineRun.status` as `completed`.
- Completed session rejects a second `new_requirement` with HTTP `409` and `error_code == "validation_error"`.
- Repeated workspace/timeline reads replay stable history without duplicate feed identities or `graph_thread_ref` leakage.
- Duplicate approval result replay creates one `approval_result` projection and keeps the matched `approval_request` approved and non-actionable.
- SSE replay preserves monotonically increasing event ids and does not introduce a second approval payload semantic.

## Frontend Design Gate

Register: product UI.

Context: repository root has no `PRODUCT.md` or `DESIGN.md`; design audit uses the current product/frontend/backend specs, prior QA evidence, and the Impeccable product register. The inherited baseline is a quiet, professional, high-information-density workspace UI.

Findings to verify:

- Empty states remain task-oriented and do not introduce marketing layout.
- Error states use stable backend error contracts, hide sensitive diagnostics, and preserve request/correlation visibility.
- Historical replay keeps completed runs readable and non-actionable.
- Responsive layouts preserve sidebar, Narrative Feed, Composer, approval/tool blocks, Inspector, and delivery details without incoherent overlap.
- Long text wraps within cards, buttons, forms, feed entries, and Inspector panels.
- Focus restoration remains observable after Inspector open and rerun focus transitions.
- Accessibility states include visible focus, disabled state, and semantic button/form behavior.

Retained risk: no new visual implementation is part of V6.7, so this gate is an audit over prior QA evidence and current V6.7 verification rather than a screenshot-driven redesign pass.

Verification commands:

```powershell
npm --prefix e2e run test
npm --prefix frontend run test -- --run
npm --prefix frontend run build
```

## Log And Audit Evidence

| Capability | Evidence |
| --- | --- |
| JSONL writing | `QA-OBS-L6.1`, `QA-OBS-L6.2` |
| `log.db` indexes | `QA-OBS-L6.1`, `QA-OBS-L6.2` |
| Audit records | `QA-OBS-L6.2` |
| TraceContext | `QA-OBS-L6.2`, `QA-V6.1` |
| Run/stage log queries | `QA-OBS-L6.2` |
| Audit queries | `QA-OBS-L6.2` |
| Rotation | `QA-OBS-L6.1` |
| Retention | `QA-OBS-L6.1` |
| Redaction and payload blocking | `QA-OBS-L6.2` |
| `.runtime/logs` exclusion | `QA-OBS-L6.2` |
| Audit failure rollback | `QA-OBS-L6.2` |

Logs and audit rows remain diagnostic and audit stores. Product assertions in V6.7 must use domain models, domain events, Narrative Feed, Inspector, and DeliveryRecord projections, not `RunLogEntry` or `AuditLogEntry`.

## Release Candidate Validation Commands

Focused V6.7 commands:

```powershell
uv run --no-sync python -m pytest backend/tests/regression/test_run_lifecycle_regression.py -v
uv run --no-sync python -m pytest backend/tests/regression/test_projection_regression.py -v
uv run --no-sync python -m pytest backend/tests/regression/test_run_lifecycle_regression.py backend/tests/regression/test_projection_regression.py -v
```

Release candidate commands:

```powershell
uv run --no-sync python -m pytest backend/tests/regression -v
npm --prefix e2e run test
uv run --no-sync python -m pytest -q
npm --prefix frontend run test -- --run
npm --prefix frontend run build
```

Checklist verification:

```powershell
rg -n "Release Candidate Acceptance Checklist|Frontend Design Gate|Log And Audit Evidence|Residual Risks|QA-E2E-V6.3-LIVE|QA-OBS-L6.2" docs/plans/function-one-platform-acceptance-checklist.md
```

## Residual Risks

| Risk | Review Item |
| --- | --- |
| V6.7 introduced a narrow runtime lifecycle fix for completed demo delivery | Reviewer must confirm it does not add `system_status` to completed runs and does not change failed/terminated terminal semantics |
| SSE regression validates replay payload keys and monotonic ids, not browser rendering of those replay frames | E2E command remains required for frontend rendering confidence |
| Full release commands can be environment-sensitive and long running | Integration checkpoint must preserve exact exit codes and outputs for required suites |
| Frontend design gate has no repo `PRODUCT.md` or `DESIGN.md` baseline | Review uses current specs and product-register defaults; no semantic or visual redesign is accepted under V6.7 without separate scope |
