# AL06-QA-E2E-V6.2 Worker Evidence Report

## Claim

| Field | Value |
| --- | --- |
| Claim | `AL06-QA-E2E-V6.2` |
| Lane | `AL06` |
| Task | `V6.2` |
| Branch | `feat/al-frontend-runtime-ui` |
| Coordination Base | `b94e8a5` |
| Evidence report | `docs/plans/acceleration/reports/AL06-QA-E2E-V6.2.md` |
| Local result | `reported` |
| Post-commit ingest expectation | `implemented` after a user-approved checkpoint commit |

Worker HEAD is intentionally not declared here; the main coordination session reads it during ingest.

## Provenance Repair

This report records the AL06 frontend prework that unblocks QA-E2E V6.2 real session creation. The implementation was committed first as `06ae96e feat(workspace): wire new session action`; this evidence report repairs the missing claim provenance so the AL06 branch can pass the acceleration merge gate before an integration checkpoint.

This claim does not mark V6.2 complete. It only removes the frontend owner blocker recorded by the QA-E2E V6.2 worker: the sidebar `New session` action now calls the real create-session API path instead of remaining presentational.

## Scope

Implemented AL06 owner-scope behavior for the workspace sidebar:

- clicking `New session` calls `createSession()` against `POST /api/projects/{projectId}/sessions`
- the action is disabled while creation is in flight or when no project is selected
- successful creation inserts the returned draft session into the project sessions query cache
- the current session switches to the created `session_id`
- project session and created workspace queries are invalidated after creation
- failed creation preserves the current session and renders the existing `ErrorState`
- the mock API handler now supports `POST /api/projects/{projectId}/sessions` with mutable draft session data

No backend API, schema, event payload, final platform plan status, split-plan final status, coordination checkpoint snapshot, dependency manifest, lockfile, or E2E test was changed by this AL06 prework.

## Source Trace

- QA task: `docs/plans/function-one-platform/09-regression-hardening-and-logs.md#v62` requires the user to create a session in the console during the Playwright success path.
- Frontend owner scope: `docs/plans/function-one-acceleration-execution-plan.md` assigns frontend API client runtime-facing additions, workspace store, Feed, Inspector, Composer, Approval, Tool Confirmation, and Delivery UI to AL06.
- API contract: `frontend/src/api/sessions.ts::createSession()` calls `POST /api/projects/{projectId}/sessions`.
- Prior QA blocker: `docs/plans/acceleration/reports/QA-E2E-V6.2.md` recorded that `New session` had no create-session handler, so QA-E2E V6.2 remained `mock_ready`.

## Changed Files

- `docs/plans/implementation/al06-new-session-frontend-prework.md`
- `docs/plans/acceleration/reports/AL06-QA-E2E-V6.2.md`
- `frontend/src/features/workspace/ProjectSidebar.tsx`
- `frontend/src/features/workspace/__tests__/WorkspaceShell.test.tsx`
- `frontend/src/mocks/handlers.ts`

## TDD Evidence

RED command:

```powershell
npm --prefix frontend run test -- --run src/features/workspace/__tests__/WorkspaceShell.test.tsx
```

RED result:

- exit `1`
- the new success/failure tests observed that the `New session` button had no create-session handler, so no created draft session was selected and no failure state was rendered.

GREEN commands:

```powershell
npm --prefix frontend run test -- --run WorkspaceShell
npm --prefix frontend run build
```

GREEN results:

- `WorkspaceShell`: exit `0`, `Test Files 1 passed`, `Tests 31 passed`
- build: exit `0`, TypeScript and Vite production build completed

## Review

Execution path: fallback to direct implementation because this repair is a narrow provenance/evidence fix for an already implemented AL06 worker checkpoint.

Spec and plan compliance review:

- No Critical or Important findings.
- The change consumes the existing `createSession()` frontend API client and does not invent a new route or payload shape.
- The change stays inside AL06 frontend owner scope and does not alter backend contracts or final task status.

Code quality and testing review:

- No Critical or Important findings.
- Success coverage verifies API-backed session creation, session selection, and visible session count update.
- Failure coverage verifies the selected session is preserved and the existing error component is shown.
- Mock handler coverage uses the same route shape as the real client.

Frontend design gate:

- No visual redesign was introduced.
- Existing workspace sidebar layout, button styling, and `ErrorState` presentation are reused.
- The in-flight label keeps the action state visible without changing product semantics.

## Verification

Fresh verification before the original worker commit:

```powershell
npm --prefix frontend run test -- --run WorkspaceShell
```

Exit code: `0`

Key output:

```text
Test Files  1 passed (1)
Tests  31 passed (31)
```

```powershell
npm --prefix frontend run build
```

Exit code: `0`

Key output:

```text
tsc --noEmit && vite build
136 modules transformed
```

After those commands, only this evidence report was added for provenance repair.

## Mock-First Status

Expected ingest result is `implemented`, not `mock_ready`. The AL06 behavior uses the real frontend API client route and verifies the UI behavior against the mock API handler that mirrors `POST /api/projects/{projectId}/sessions`.

V6.2 itself remains open until the QA-E2E worker updates and verifies the Playwright success path on the integration branch.

## Remaining Risks

- This AL06 claim does not run Playwright and does not claim the full V6.2 acceptance path.
- Integration checkpoint still needs to merge `feat/al-frontend-runtime-ui`, run `npm --prefix frontend test`, run `npm --prefix frontend build`, and then let the QA-E2E V6.2 session perform its separate E2E implementation.

## Commit Readiness

Suggested commit message:

```text
docs(acceleration): add AL06 V6.2 evidence
```
