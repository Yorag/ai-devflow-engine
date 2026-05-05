# AL06 New Session Frontend Prework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the frontend `New session` sidebar action to the existing session creation API so QA-E2E V6.2 can later exercise real UI session creation.

**Architecture:** Keep the behavior in the AL06 frontend owner scope. `ProjectSidebar` owns the button state and API call, while `WorkspaceShell` continues to own selected project/session state. The mock API handler supports the same `POST /api/projects/{projectId}/sessions` route used by the real client so component tests and local mock runs match the backend contract.

**Tech Stack:** React, TanStack Query, Vitest, Testing Library, existing frontend API client.

---

## Scope

This prework does not update QA-E2E V6.2, coordination store state, platform plan status, split-plan final status, or acceleration checkpoint snapshots.

**Modify:**
- `frontend/src/features/workspace/ProjectSidebar.tsx`
- `frontend/src/features/workspace/__tests__/WorkspaceShell.test.tsx`
- `frontend/src/mocks/handlers.ts`

## Requirements

- Clicking `New session` calls `POST /api/projects/{projectId}/sessions` through `createSession()`.
- The button is disabled while creation is in flight and when no project is selected.
- On success, the created draft session is inserted into the project sessions query cache, the current session switches to the created `session_id`, and the session/workspace queries are refreshed.
- On failure, the current session remains unchanged and the sidebar shows the existing `ErrorState` recovery copy.
- The implementation uses the existing frontend API client, query keys, and workspace styling.

## TDD Record

- [x] Wrote WorkspaceShell tests for successful sidebar session creation and API failure.
- [x] Ran `npm --prefix frontend run test -- --run src/features/workspace/__tests__/WorkspaceShell.test.tsx` and confirmed the new tests failed because `New session` had no handler.
- [x] Implemented `ProjectSidebar` session creation state, query cache update, invalidation, selection switch, and error display.
- [x] Extended `createMockApiFetcher()` with a mutable `POST /api/projects/{projectId}/sessions` route and draft workspace projection.
- [x] Reran the focused WorkspaceShell test file and confirmed it passed.
- [x] Run impacted frontend checks: `npm --prefix frontend run test -- --run WorkspaceShell` and `npm --prefix frontend run build`.
