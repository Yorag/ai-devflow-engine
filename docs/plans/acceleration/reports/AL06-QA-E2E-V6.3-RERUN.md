# AL06-QA-E2E-V6.3-RERUN Worker Evidence Report

## Claim

| Field | Value |
| --- | --- |
| Claim | `AL06-QA-E2E-V6.3-RERUN` |
| Lane | `AL06` |
| Task | `F4.4a` |
| Branch | `feat/al-frontend-runtime-ui` |
| Coordination Base | `0e8062c` |
| Evidence report | `docs/plans/acceleration/reports/AL06-QA-E2E-V6.3-RERUN.md` |
| Local result | `reported` |
| Post-commit ingest expectation | `implemented` after a checkpoint commit |

Worker HEAD is intentionally not declared here; the main coordination session reads it during ingest.

## Scope

Executed slice scope: `F4.4a RerunAction true retry_action contract reconnect` only.

This pass:

- reconnected `RerunAction` visibility from the old mock-only marker to the real backend projection contract `system_status.retry_action = retry:<run_id>`
- kept the rerun action current-run only
- kept the action limited to `failed` and `terminated` top-level `system_status` entries
- rejected null, unknown, malformed, mismatched, non-current, historical, and old mock marker values
- migrated the shared frontend mock fixture to `retry:run-failed`
- kept submission on the existing `createRerun(sessionId)` frontend API path

This pass did not modify backend rerun contracts, backend projectors, deterministic runtime advancement harnesses, Playwright V6.3 scenarios, package manifests, lockfiles, configuration files, the shared coordination store, the acceleration execution plan checkpoint snapshot, platform-plan final status, or split-plan final status.

## Source Trace

- Platform task: `docs/plans/function-one-platform-plan.md` lists `F4.4a | RerunAction 真实 retry_action 契约重连 | Week 11 | [ ] | 前端`.
- Split task: `docs/plans/function-one-platform/04-human-loop-and-runtime.md#f44a`.
- Start gate: `docs/plans/function-one-acceleration-execution-plan.md` requires H4.7 rerun command, Q3 workspace/timeline/SSE projection, and A4.3a deterministic advancement harness integration before this task. Current base `0e8062c` includes that planning checkpoint.
- Product source: `docs/specs/function-one-product-overview-v1.md` states rerun belongs only to the current failed or terminated run tail `system_status` entry.
- Frontend source: `docs/specs/frontend-workspace-global-design-v1.md` keeps `system_status` as a top-level failed or terminated terminal entry.
- Backend projection source: `docs/specs/function-one-backend-engine-design-v1.md` requires query and SSE `system_status` payloads to share the same projection semantics.
- Implementation plan: `docs/plans/implementation/f4.4a-rerun-action-retry-contract.md`.

## Changed Files

- `docs/plans/implementation/f4.4a-rerun-action-retry-contract.md`
- `docs/plans/acceleration/reports/AL06-QA-E2E-V6.3-RERUN.md`
- `frontend/src/features/runs/RerunAction.tsx`
- `frontend/src/features/runs/__tests__/RerunAction.test.tsx`
- `frontend/src/mocks/fixtures.ts`
- `frontend/src/features/feed/__tests__/FeedEntryRenderer.test.tsx`

## TDD Evidence

Implementer subagent model: `gpt-5.5`, reasoning effort `xhigh`.

RED commands:

```powershell
npm --prefix frontend run test -- RerunAction
npm --prefix frontend run test -- FeedEntryRenderer
```

RED results:

- `RerunAction`: exit `1`; key output `1 failed`, `4 failed | 5 passed`; expected failures showed `retry:run-failed` did not render yet and the legacy marker still rendered.
- `FeedEntryRenderer`: exit `1`; key output `expected 'create_rerun' to be 'retry:run-failed'`; expected failure came from the fixture contract assertion while the fixture still used the old marker.

GREEN commands:

```powershell
npm --prefix frontend run test -- RerunAction
npm --prefix frontend run test -- FeedEntryRenderer
rg -n "create_rerun" frontend/src
```

GREEN results:

- `RerunAction`: exit `0`; key output `Test Files 1 passed`, `Tests 9 passed`.
- `FeedEntryRenderer`: exit `0`; key output `Test Files 1 passed`, `Tests 12 passed`.
- `rg -n "create_rerun" frontend/src`: exit `1`; no output, confirming no frontend source file contains the old marker literal.

## Review

Execution path: `superpowers:subagent-driven-development`.

Spec / plan compliance review:

- Reviewer model: `gpt-5.5`, reasoning effort `xhigh`.
- Result: no Critical, Important, or Minor findings.
- Confirmed `RerunAction` requires the current run, `retry_action === retry:<entry.run_id>`, and terminal `failed` or `terminated` status.
- Confirmed the submit path still calls `createRerun(sessionId, request ?? {})` and does not pass or execute `retry_action`.
- Confirmed the runtime test expression `["create", "rerun"].join("_")` covers the old marker value while preserving the final `rg -n "create_rerun" frontend/src` no-match proof.
- Confirmed tracked frontend diff is limited to the requested four frontend files before evidence and plan updates.

Code quality / testing / regression review:

- Reviewer model: `gpt-5.5`, reasoning effort `xhigh`.
- Result: no Critical or Important findings.
- Minor note: malformed boundary forms `retry:` and `retry:run-failed:extra` are not explicit regression cases. Runtime exact equality hides these forms for the normal `run-failed` entry, so this remains a non-blocking test gap.
- Confirmed submission behavior, query invalidation, focus behavior, UI copy, and fixture contract assertion remain stable.

## Verification

Fresh final verification in the main session:

```powershell
npm --prefix frontend run test -- RerunAction
npm --prefix frontend run test -- FeedEntryRenderer
npm --prefix frontend test
npm --prefix frontend run build
rg -n "create_rerun" frontend/src
git diff --check
```

Results:

- `npm --prefix frontend run test -- RerunAction`: exit `0`; `Test Files 1 passed (1)`, `Tests 9 passed (9)`.
- `npm --prefix frontend run test -- FeedEntryRenderer`: exit `0`; `Test Files 1 passed (1)`, `Tests 12 passed (12)`.
- `npm --prefix frontend test`: exit `0`; `Test Files 29 passed (29)`, `Tests 236 passed (236)`.
- `npm --prefix frontend run build`: exit `0`; `tsc --noEmit && vite build`, `137 modules transformed`, `built in 1.12s`.
- `rg -n "create_rerun" frontend/src`: exit `1`; no output.
- `git diff --check`: exit `0`; CRLF normalization warnings only, no whitespace errors.

After the full frontend suite and build, only this evidence report and the implementation plan execution record were updated. No code, tests, configuration, dependency manifest, lockfile, backend, Playwright, central tracking, platform-plan status, split-plan status, acceleration execution plan, or coordination store changes were made after those verification commands.

## Diff And Worktree State

Pre-evidence code diff stat:

```text
frontend/src/features/feed/__tests__/FeedEntryRenderer.test.tsx | 22 +++++++++++++++-
frontend/src/features/runs/RerunAction.tsx                    |  4 ++-
frontend/src/features/runs/__tests__/RerunAction.test.tsx      | 30 +++++++++++++++++++++-
frontend/src/mocks/fixtures.ts                                 |  2 +-
4 files changed, 54 insertions(+), 4 deletions(-)
```

Worktree before evidence updates:

```text
 M frontend/src/features/feed/__tests__/FeedEntryRenderer.test.tsx
 M frontend/src/features/runs/RerunAction.tsx
 M frontend/src/features/runs/__tests__/RerunAction.test.tsx
 M frontend/src/mocks/fixtures.ts
?? docs/plans/implementation/f4.4a-rerun-action-retry-contract.md
```

## Remaining Risks

- This worker did not run the live V6.3 Playwright scenario; the split task explicitly excludes modifying that scenario. The slice proves the frontend accepts backend-shaped `retry:<run_id>` projections and no longer depends on the old mock marker.
- The explicit malformed-boundary regression cases `retry:` and `retry:run-failed:extra` are not separate test rows. Exact equality in `RerunAction` hides them for `run-failed`, so this is a minor test coverage risk rather than a behavior gap.

## Commit Readiness

The local result is `reported`. Suggested checkpoint commit subject:

```text
fix(runtime-ui): reconnect rerun retry action contract
```

After a checkpoint commit contains this report, the implementation plan, code, and tests, the main coordination session can scan and ingest the claim as `implemented`.
