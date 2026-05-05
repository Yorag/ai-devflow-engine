# QA-E2E-V6.3 Worker Evidence

## Metadata

| Field | Value |
| --- | --- |
| claim_id | QA-E2E-V6.3 |
| lane_id | QA-E2E |
| task_id | V6.3 |
| branch | test/qa-e2e-regression |
| coordination_base | a48ea61 |
| expected_ingest_status | mock_ready |
| local_result | reported |

## Scope

Added the V6.3 Playwright manual-intervention regression spec in the QA-E2E worker worktree. The worker did not write the coordination store, did not update central plan status, and did not update platform or split-plan final status. The local result is `reported`; after a checkpoint commit, the expected ingest result is `mock_ready` because the QA-E2E lane continues to use the mock-first Playwright harness established by V6.2 until full UI-created session coverage is available.

## Changed Files

- `docs/plans/implementation/v6.3-playwright-control-flow.md`
- `docs/plans/acceleration/reports/QA-E2E-V6.3.md`
- `e2e/tests/function-one-control-flow.spec.ts`

## Coverage Summary

- Approval rejection writes an `approval_result` with the submitted reason and a rollback `control_item`.
- Paused approval disables both `Approve` and `Reject`, and resume returns to the same approval checkpoint.
- A controlled approval submit error renders through the existing approval error UI.
- High-risk tool confirmation allow transitions the first confirmation to `Allowed`.
- Paused tool confirmation disables both allow and deny.
- Tool deny renders `Denied`, stable `deny_followup_action` / `deny_followup_summary`, and a failed tail `system_status` without approval rollback semantics.
- Terminate appends a terminal `system_status`.
- Retry creates a new current run at `Requirement Analysis`, moves focus to the new run boundary, and leaves prior approval/tool entries in historical disabled state.
- Browser assertions cover global overflow and a 390px narrow viewport.

## TDD Evidence

```powershell
npm --prefix e2e run test -- function-one-control-flow.spec.ts
```

Initial RED exit code: 1

```text
Running 2 tests using 1 worker
both tests failed with Error: Control flow fixture is not implemented.
```

Review-fix RED exit code: 1

```text
Running 2 tests using 1 worker
revised approval expected paused-submit error but route was unhandled
tool deny expected Tool confirmation denied system_status but none existed
```

Focused GREEN exit code: 0

```text
Running 2 tests using 1 worker
  ok 1 [chromium] tests\function-one-control-flow.spec.ts:83:3 ... covers approval rejection, paused approval, terminate, and rerun focus
  ok 2 [chromium] tests\function-one-control-flow.spec.ts:144:3 ... covers high-risk tool allow, deny, paused disablement, and narrow layout
  2 passed (5.7s)
```

## Review Evidence

- Spec / plan compliance review found Important gaps for rerun semantics, tool-deny `system_status`, historical disabled states, and error-state coverage. These were fixed.
- Code quality review found Important gaps for paused dual-action assertions and terminal/historical run metadata coherence. These were fixed.
- Spec / plan re-review found no remaining Critical or Important issues.
- Code quality / test sufficiency re-review found no remaining Critical or Important issues.

## Verification Commands

```powershell
npm --prefix e2e run test -- function-one-full-flow.spec.ts function-one-control-flow.spec.ts
```

Exit code: 0

```text
Running 3 tests using 2 workers
  ok 1 [chromium] tests\function-one-control-flow.spec.ts:83:3 ... covers approval rejection, paused approval, terminate, and rerun focus
  ok 2 [chromium] tests\function-one-full-flow.spec.ts:83:3 ... completes requirement, clarification, approvals, and delivery result in the console
  ok 3 [chromium] tests\function-one-control-flow.spec.ts:144:3 ... covers high-risk tool allow, deny, paused disablement, and narrow layout
  3 passed (9.5s)
```

## Mock-First Status

This checkpoint uses route-level projection fixtures and the existing Vite frontend, not a live backend. It is suitable for `mock_ready` ingest after checkpoint commit. Final `[x]` status for V6.3 remains a main coordination decision after integration checkpoint validation.

## Owner Conflicts

None. The worker changed only QA-E2E-owned Playwright and evidence files.

## Remaining Risks

- The V6.3 browser regression uses mock projection fixtures. It does not prove live backend orchestration, event persistence, or SSE delivery.
- Full UI-created session coverage remains tied to the known V6.2 owner blocker for `New session` wiring.

## Commit Readiness

Local result is `reported`. The diff is scoped to one QA-E2E claim and has fresh focused/impacted Playwright verification. After a checkpoint commit containing the implementation plan, evidence report, and Playwright spec, the main coordination session can ingest this claim as `mock_ready`.
