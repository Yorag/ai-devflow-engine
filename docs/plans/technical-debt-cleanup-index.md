# Technical Debt Cleanup Index

## Purpose

This index tracks technical debt found in task implementation plans and worker evidence reports. It is the entry point for main-based stabilization work after acceleration lane mode was retired.

This document is not a specification and does not replace `docs/specs/*`, `docs/plans/function-one-platform-plan.md`, or split-plan task details. It records cleanup candidates, verification gaps, and resolved-by-later-slice notes so future work can proceed in small batches on `main`.

## Scope

Sources scanned for the initial index:

- `docs/plans/implementation/*.md`
- `docs/plans/acceleration/reports/*.md`
- `docs/plans/function-one-platform-plan.md`
- `docs/plans/function-one-platform/*.md`

Search themes:

- residual limitation or risk
- mock-first or `mock_ready`
- owner blocker or owner conflict
- verification not rerun
- partial / compatibility / legacy behavior
- review findings that remained outside the original task scope

Status values:

- `open`: needs cleanup or an explicit design decision.
- `needs-verification`: may already be covered by later work, but needs current-code verification before closing.
- `resolved-by-verification`: current `main` verification closed the cleanup item without additional code changes.
- `resolved-by-later-slice`: historical debt that later evidence says is resolved.
- `accepted-boundary`: current phase accepts the documented boundary; reopen when the listed production gate is crossed.
- `defer`: accepted low-risk maintenance item for later batches.

Priority values:

- `P0`: production safety, data integrity, security, audit, or delivery trust.
- `P1`: user-visible workflow, display solidification, state consistency, or major maintainability risk.
- `P2`: focused coverage gap, hardening, or documented compatibility limitation.
- `P3`: cleanup-only readability, naming, or historical-doc hygiene.

## Batch Plan

| Batch | Goal | Entry criteria | Exit criteria |
| --- | --- | --- | --- |
| Batch 1 | Verify high-impact backend consistency and command-boundary debt | `P0` / `P1` items with production-path impact | Current code either has regression coverage or a focused cleanup task is created |
| Batch 2 | Close user-visible projection and E2E verification debt | `P1` / `P2` UI, projection, SSE, Playwright, or OpenAPI items | Focused tests pass and stale mock-first blockers are marked resolved |
| Batch 3 | Harden persistence, migration, and multi-worker assumptions | `P1` / `P2` infrastructure items | Accepted production boundary is explicit and tested |
| Batch 4 | Consolidate minor helper extraction and doc hygiene | `P2` / `P3` maintenance items | Low-risk improvements land without changing product semantics |

## Debt Items

| ID | Priority | Status | Source | Summary | Suggested cleanup | Verification target | Batch |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TD-001 | P0 | resolved-by-verification | `docs/plans/implementation/r3.2-start-first-run.md`; `docs/plans/acceleration/reports/AL01-R3.2a.md` | R3.2 recorded a residual multi-store commit limitation: late failures across runtime/control/event/graph stores can leave partial product truth. Current `main` now has publication-boundary coverage and partial-startup cleanup coverage for externally visible first-run startup. | No code cleanup in Batch 1. Keep the focused regression command as the guard; reopen only if publication-boundary or startup cleanup tests regress. | `uv run python -m pytest backend/tests/services/test_start_first_run.py backend/tests/services/test_publication_boundary.py backend/tests/services/test_rerun_command_projection.py -q` | Batch 1 |
| TD-002 | P0 | accepted-boundary | `docs/plans/acceleration/reports/AL03-H4.1.md`; `docs/plans/implementation/td-002-clarification-command-boundary.md` | Clarification command evidence records residual architecture risk. Current tests verify required audit failures block runtime create/resume side effects and runtime resume failure rolls back uncommitted domain/event changes. Current stabilization accepts this boundary because the default command path is in-process and does not claim durable external-runtime atomicity. | Reopen before multi-worker command processing, external runtime side effects, crash recovery claims, or formal cross-SQLite production data-integrity claims. The reopened implementation must add a durable outbox, idempotent runtime command contract, or recovery/reconciliation process record. | `uv run python -m pytest backend/tests/services/test_clarification_flow.py backend/tests/services/test_runtime_orchestration_boundary.py backend/tests/schemas/test_run_feed_event_schemas.py -q` | Batch 1 |
| TD-003 | P1 | open | `docs/plans/acceleration/reports/AL03-H4.1.md`; `docs/specs/function-one-backend-engine-design-v1.md`; `docs/plans/implementation/td-003-clarification-status-boundary.md` | Clarification backend still has partial model/spec drift. The `ClarificationRecord.status` surface is now explicit as a derived model property from persisted `answer` / `answered_at`, avoiding a schema change before the migration baseline exists. Rich Requirement Analysis metadata is still not schema-owned on `ClarificationRecord`; current implementation only has `payload_ref` and later `StageArtifact` process capacity. | Keep rich metadata open until the source-of-truth decision and TD-013 migration baseline are settled. Next action: either approve `StageArtifact.process` / `payload_ref` as the owner for rich metadata, or add model fields with migration and regression coverage. | `uv run python -m pytest backend/tests/db/test_runtime_model_boundary.py backend/tests/services/test_clarification_flow.py -q` | Batch 1 |
| TD-004 | P1 | open | `docs/plans/acceleration/reports/AL01-E3.1.md` | EventStore sequence uniqueness is process-local; cross-process or multi-worker uniqueness still needs a durable database constraint or transactional allocator. | If production can run multiple workers, add durable sequencing. If not, document the single-writer deployment constraint and add a regression guard for the current allocator behavior. | `uv run python -m pytest backend/tests/events/test_event_store.py -q` | Batch 3 |
| TD-005 | P2 | open | `docs/plans/acceleration/reports/AL01-E3.1.md` | `ProjectLoaded` is known but unmapped for session SSE projection until project-level projection semantics are specified. | Either define project-level projection semantics or explicitly document that `ProjectLoaded` is not a session feed/SSE event in V1. | `uv run python -m pytest backend/tests/events/test_event_store.py backend/tests/api/test_events_api.py -q` | Batch 4 |
| TD-006 | P2 | open | `docs/plans/acceleration/reports/AL01-C2.9b.md` | Project removal API coverage lacks a real pending-startup blocked-path request and forced runtime-barrier acquisition failure path. | Add focused API/service tests if current fixtures can express these cases without production changes. | `uv run python -m pytest backend/tests/services/test_project_service.py backend/tests/api/test_project_api.py -q` | Batch 2 |
| TD-007 | P2 | open | `docs/plans/acceleration/reports/AL02-Q3.3.md` | Inspector projection reads generic `StageArtifactModel.process` payloads because typed per-stage artifact persistence does not exist; future AL02 extraction may need a shared artifact decoding helper. | Defer until another projection repeats the decoding pattern. If duplication exists now, extract a small helper with focused tests. | `uv run python -m pytest backend/tests/services/test_stage_inspector_projection.py backend/tests/services/test_control_item_inspector_projection.py -q` | Batch 4 |
| TD-008 | P2 | open | `docs/plans/acceleration/reports/AL02-Q3.4.md` | Malformed `control_item` event payload handling is covered indirectly by defensive parsing, but lacks dedicated focused regression coverage. | Add focused malformed-payload tests for control item detail projection. | `uv run python -m pytest backend/tests/services/test_control_item_inspector_projection.py -q` | Batch 2 |
| TD-009 | P2 | open | `docs/plans/acceleration/reports/AL03-H4.5.md` | Timeline endpoint is not explicitly asserted for paused/resumed status replay in the H4.5 focused API tests. | Add a timeline API regression for pause/resume replay if not already covered in later V6.3 live E2E. | `uv run python -m pytest backend/tests/services/test_pause_resume.py backend/tests/api/test_run_timeline_api.py -q` | Batch 2 |
| TD-010 | P2 | resolved-by-verification | `docs/plans/implementation/v6.3-playwright-control-flow-live.md`; `docs/plans/acceleration/reports/QA-E2E-V6.3-LIVE.md`; `docs/plans/acceleration/reports/QA-RELEASE-V6.7.md` | V6.3 live backend E2E originally could not rerun backend harness locally because repo-local pytest was missing in that worker environment. Current `main` can run the deterministic backend harness through repo-local `uv`. | No cleanup action unless this harness regresses. Keep live-backend default coverage decision under TD-011. | `uv run python -m pytest backend/tests/e2e/test_deterministic_runtime_advancement_harness.py -q` | Batch 2 |
| TD-011 | P2 | open | `docs/plans/acceleration/reports/QA-E2E-V6.3-LIVE.md`; `docs/plans/acceleration/reports/QA-RELEASE-V6.7.md` | Default E2E skips opt-in live backend tests; route-fixture E2E passes, but live backend coverage requires `E2E_LIVE_BACKEND=1`. | Decide whether release/display verification must include live backend E2E by default. If yes, add a stable script or documented command. | `$env:E2E_LIVE_BACKEND='1'; npm --prefix e2e run test -- function-one-control-flow-live.spec.ts` | Batch 2 |
| TD-012 | P2 | open | `docs/plans/acceleration/reports/QA-E2E-V6.3-LIVE.md` | Live backend E2E uses `.runtime/e2e-live`; interrupted local runs can leave test sessions. | Add unique runtime-root support or cleanup behavior for live E2E runs. | `npm --prefix e2e run test -- function-one-control-flow-live.spec.ts` with live mode when enabled | Batch 4 |
| TD-013 | P1 | open | `docs/plans/implementation/runtime-settings-internal-bindings-backfill.md` | Internal model bindings backfill notes that Alembic migration baseline remains a separate follow-up because the control-schema revision chain was not valid at the time. Current probe found no migration scripts under `backend/alembic/versions` and Alembic reports no current revision or head. | Create a migration-baseline cleanup task before production data migration claims or before adding new runtime schema columns for TD-003. | `uv run alembic -c backend/alembic.ini current`; `uv run alembic -c backend/alembic.ini heads` | Batch 3 |
| TD-014 | P2 | resolved-by-later-slice | `docs/plans/acceleration/reports/QA-E2E-V6.2.md`; `docs/plans/acceleration/reports/QA-E2E-V6.2-FINAL.md`; `docs/plans/acceleration/reports/AL06-QA-E2E-V6.2.md` | V6.2 originally remained `mock_ready` because `New session` had no create-session handler. AL06 and QA-E2E finalization later verified UI-created draft session flow. | No cleanup action unless current tests regress. Keep as historical resolved debt. | `npm --prefix e2e run test -- function-one-full-flow.spec.ts` | Batch 2 |
| TD-015 | P2 | resolved-by-later-slice | `docs/plans/acceleration/reports/QA-E2E-V6.3.md`; `docs/plans/acceleration/reports/QA-E2E-V6.3-LIVE.md`; `docs/plans/acceleration/reports/QA-RELEASE-V6.7.md` | V6.3 was initially route-fixture `mock_ready`; later live backend-backed Playwright coverage passed and release evidence reports E2E success with live tests opt-in. | No immediate cleanup action; only decide whether live mode should become part of default release verification. | `npm --prefix e2e run test`; optional live command in TD-011 | Batch 2 |

## Investigation Notes

### 2026-05-06 Current-Main Probe

- TD-001 verification passed: `uv run python -m pytest backend/tests/services/test_start_first_run.py backend/tests/services/test_publication_boundary.py backend/tests/services/test_rerun_command_projection.py -q` returned `28 passed`.
- TD-002 / TD-003 focused verification passed for existing behavior: `uv run python -m pytest backend/tests/services/test_clarification_flow.py backend/tests/services/test_runtime_orchestration_boundary.py backend/tests/schemas/test_run_feed_event_schemas.py -q` returned `24 passed`.
- TD-010 verification passed: `uv run python -m pytest backend/tests/e2e/test_deterministic_runtime_advancement_harness.py -q` returned `4 passed`.
- TD-013 remains open: `uv run alembic -c backend/alembic.ini current --verbose` listed configured database URLs with empty current revisions, `uv run alembic -c backend/alembic.ini heads --verbose` printed no heads, and `backend/alembic/versions` contains no migration source files.

## Next Recommended Cleanup Slice

Continue Batch 1 with the remaining design decisions:

1. Close the remaining TD-003 rich metadata decision by choosing whether `ClarificationRecord` gets schema-owned metadata fields, or whether rich clarification metadata is owned by `StageArtifact.process` and referenced through `payload_ref`.
2. Defer runtime schema-column work until TD-013 has a migration baseline, unless the cleanup slice deliberately includes both the model change and the baseline migration.
3. Treat TD-002 as closed for the current display-solidification phase, but reopen it before multi-worker or external-runtime production claims.

Reason: these items sit on production backend consistency and command semantics. They are more important than minor projection helper extraction or doc cleanup.

## Notes

- `docs/plans/function-one-platform-plan.md` currently marks all function-one tasks `[x]`; this index therefore treats unfinished-looking implementation notes as possible residual debt, not task status truth.
- Many implementation documents include RED failures and review findings that were fixed inside the same slice. Those are not listed unless a remaining risk, follow-up, or later verification gap is explicitly recorded.
- Before editing code for any item, re-read the cited source document and current tests. Some entries may close through verification alone.
