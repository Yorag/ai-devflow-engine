# Session Auto Title Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Fallback to `superpowers:executing-plans` only when task boundaries cannot be delegated safely. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically persist a useful `Session.display_name` from the first `new_requirement` when the draft session still has the default title.

**Architecture:** The backend owns persistent session naming. `SessionService.start_run_from_new_requirement()` computes a normalized, bounded title only for default-named draft sessions and persists it through first-run publication so append-message responses and later session-list reads show the same value. The frontend only applies overflow-safe display styling to the existing `display_name` field.

**Tech Stack:** FastAPI, SQLAlchemy, pytest through `uv run`, React, Vitest, CSS.

---

## Source Trace

- Product boundary: `docs/specs/function-one-product-overview-v1.md` says the first requirement message auto-starts the first `PipelineRun`, each `Session` carries one requirement chain, and user rename only changes the session display name.
- Backend contract: `docs/specs/function-one-backend-engine-design-v1.md` says `POST /api/sessions/{sessionId}/messages` with `new_requirement` is only valid for `Session.status = draft` and `current_run_id = null`, and the backend creates the first run and first message event in one startup flow.
- Frontend boundary: `docs/specs/frontend-workspace-global-design-v1.md` assigns session list presentation to the left sidebar; persistent naming logic remains backend state.

## Files

- Modify: `backend/app/services/sessions.py`
- Modify: `backend/app/services/runs.py`
- Modify: `backend/app/services/publication_boundary.py`
- No route change: `backend/app/api/routes/sessions.py`
- Test: `backend/tests/api/test_session_message_api.py`
- Test: `backend/tests/api/test_session_api.py`
- Service regression scope: `backend/tests/services/test_start_first_run.py`
- Service regression scope: `backend/tests/services/test_publication_boundary.py`
- Modify for display-only truncation: `frontend/src/features/workspace/SessionList.tsx`
- Test for display-only truncation: `frontend/src/features/workspace/__tests__/ProjectSessionHistory.test.tsx`
- Modify for display-only truncation: `frontend/src/styles/global.css`

## Backend TDD

- [x] **Step 1: Add failing API test for default draft auto-title**

Add a test to `backend/tests/api/test_session_message_api.py`:

```python
def test_new_requirement_auto_titles_default_draft_session_and_list_reflects_name(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path)

    content = (
        "Build   checkout\n\nworkspace history controls with very long trailing detail"
    )
    expected_title = "Build checkout workspace hist..."

    with TestClient(app) as client:
        created = create_draft_session(client)
        response = client.post(
            f"/api/sessions/{created['session_id']}/messages",
            json={"message_type": "new_requirement", "content": content},
        )
        list_response = client.get("/api/projects/project-default/sessions")

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["display_name"] == expected_title

    assert list_response.status_code == 200
    listed = list_response.json()
    assert listed[0]["session_id"] == created["session_id"]
    assert listed[0]["display_name"] == expected_title
```

Run: `uv run python -m pytest backend/tests/api/test_session_message_api.py::test_new_requirement_auto_titles_default_draft_session_and_list_reflects_name -q`

Expected RED: assertion fails because `display_name` is still `Untitled requirement`.

Actual RED evidence:

```text
uv run --extra dev python -m pytest backend/tests/api/test_session_message_api.py::test_new_requirement_auto_titles_default_draft_session_and_list_reflects_name -q
FAILED: expected "Build checkout workspace hist...", got "Untitled requirement"
```

- [x] **Step 2: Add failing API test for renamed session preservation**

Add a test to `backend/tests/api/test_session_message_api.py`:

```python
def test_new_requirement_does_not_auto_title_renamed_session(tmp_path: Path) -> None:
    app = build_app(tmp_path)

    with TestClient(app) as client:
        created = create_draft_session(client)
        rename = client.patch(
            f"/api/sessions/{created['session_id']}",
            json={"display_name": "Manual planning session"},
        )
        assert rename.status_code == 200
        response = client.post(
            f"/api/sessions/{created['session_id']}/messages",
            json={
                "message_type": "new_requirement",
                "content": "This text must not replace a user-selected name.",
            },
        )
        list_response = client.get("/api/projects/project-default/sessions")

    assert response.status_code == 200
    assert response.json()["session"]["display_name"] == "Manual planning session"
    assert list_response.status_code == 200
    assert list_response.json()[0]["display_name"] == "Manual planning session"
```

Run: `uv run python -m pytest backend/tests/api/test_session_message_api.py::test_new_requirement_does_not_auto_title_renamed_session -q`

Expected RED before implementation can pass only if default-only behavior already exists; if it passes because no auto-title exists yet, keep it as a guard and rely on Step 1 for RED.

Actual guard evidence:

```text
uv run --extra dev python -m pytest backend/tests/api/test_session_message_api.py::test_new_requirement_does_not_auto_title_renamed_session -q
1 passed
```

- [x] **Step 3: Add failing API test for `clarification_reply` non-trigger**

Add a test to `backend/tests/api/test_clarification_reply_api.py` if a reusable waiting-clarification fixture exists there; otherwise add a service-level regression around `SessionService.append_clarification_reply()` using a stub `ClarificationService` that returns a message item and does not mutate `display_name`.

Expected behavior: `clarification_reply` response and persisted session keep the existing display name, including `Untitled requirement`.

Run the focused test with `uv run`.

Actual guard evidence:

```text
uv run --extra dev python -m pytest backend/tests/api/test_clarification_reply_api.py::test_clarification_reply_does_not_auto_title_default_named_session -q
1 passed
```

- [x] **Step 4: Implement stable title normalization**

In `backend/app/services/sessions.py`, add a constant and helper:

```python
SESSION_AUTO_TITLE_MAX_LENGTH = 32

def session_auto_title_from_requirement(content: str) -> str:
    normalized = " ".join(content.split())
    if not normalized:
        return DEFAULT_SESSION_DISPLAY_NAME
    if len(normalized) <= SESSION_AUTO_TITLE_MAX_LENGTH:
        return normalized
    return f"{normalized[: SESSION_AUTO_TITLE_MAX_LENGTH - 3].rstrip()}..."
```

Then, in `SessionService.start_run_from_new_requirement()`, before delegating to `RunLifecycleService.start_first_run()`, compute `auto_display_name` only when `model.display_name == DEFAULT_SESSION_DISPLAY_NAME`. Pass that optional title and the expected current default name into `RunLifecycleService.start_first_run()`. `RunLifecycleService` forwards the value into `_commit_first_run_startup()`, and `PublicationBoundaryService.publish_startup_visibility()` applies the title during the same control-DB publication commit that sets `Session.status`, `current_run_id`, and `latest_stage_type`. If startup raises, publication is aborted and the display name is not updated. If a concurrent manual rename changes `display_name` before publication, the expected-current-name guard is evaluated against the current database row during publication and prevents overwrite.

If list ordering depends on `updated_at`, use the same timestamp as the successful startup return to avoid nondeterministic ordering.

- [x] **Step 5: Run backend green checks**

Run focused tests:

```powershell
uv run python -m pytest backend/tests/api/test_session_message_api.py -q
uv run python -m pytest backend/tests/api/test_session_api.py -q
```

If service tests were changed, also run:

```powershell
uv run python -m pytest backend/tests/services/test_start_first_run.py -q
```

Actual GREEN evidence:

```text
uv run python -m pytest backend/tests/api/test_session_message_api.py backend/tests/api/test_session_api.py -q
13 passed

uv run python -m pytest backend/tests/api/test_clarification_reply_api.py -q
5 passed

uv run python -m pytest backend/tests/services/test_start_first_run.py -q
14 passed

uv run python -m pytest backend/tests/services/test_publication_boundary.py -q
6 passed
```

## Frontend Display TDD

- [x] **Step 6: Add failing long-name display test**

In `frontend/src/features/workspace/__tests__/ProjectSessionHistory.test.tsx`, render a workspace with an intentionally long `display_name`, find the open-session button by accessible name, and assert its label span has the truncation class.

Run: `npm --prefix frontend run test -- --run src/features/workspace/__tests__/ProjectSessionHistory.test.tsx`

Expected RED: class assertion fails.

Actual RED attempt:

```text
npm --prefix frontend run test -- --run src/features/workspace/__tests__/ProjectSessionHistory.test.tsx
Exit 1: 'vitest' is not recognized as an internal or external command
```

The test was added, but local frontend dependencies are missing, so the test runner could not execute the intended assertion failure without dependency installation.

- [x] **Step 7: Implement display-only truncation**

In `frontend/src/features/workspace/SessionList.tsx`, add a class to the existing display-name span:

```tsx
<span className="session-list-item__title">{session.display_name}</span>
```

In `frontend/src/styles/global.css`, apply single-line truncation for the title while retaining full accessible names on the button:

```css
.session-list-item__title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
```

Do not derive, truncate, or persist any session name in frontend code.

Implemented as display-only class and CSS ellipsis. Frontend verification remains blocked until `frontend/node_modules` is installed from `frontend/package-lock.json`.

## Review And Verification

- [x] **Step 8: Review compliance**

Review against the user requirements:

- Default draft + first `new_requirement` updates `display_name`.
- Renamed sessions are not overwritten.
- Normalization removes newlines and repeated whitespace.
- Maximum length is explicit and stable.
- `clarification_reply` does not trigger naming.
- API response and list read show the persisted `display_name`.
- Frontend only displays the backend-provided name safely.

Review evidence:

- Requirements/spec reviewer: no blocking findings. Low documentation mismatch fixed in this file.
- Code-quality reviewer: medium transaction finding fixed by moving auto-title into the first-run publication commit; stale identity-map rename race fixed with a database-row conditional update and a publication boundary regression; low stale checklist finding fixed by this status update.

- [x] **Step 9: Required fresh verification**

Run:

```powershell
uv run python -m pytest backend/tests/api/test_session_message_api.py backend/tests/api/test_session_api.py -q
npm --prefix frontend run test -- --run src/features/workspace/__tests__/ProjectSessionHistory.test.tsx
npm --prefix frontend run build
```

If service tests were changed, include their focused `uv run` command.

Completed backend verification:

```text
uv run python -m pytest backend/tests/api/test_session_message_api.py backend/tests/api/test_session_api.py -q
13 passed

uv run python -m pytest backend/tests/api/test_clarification_reply_api.py -q
5 passed

uv run python -m pytest backend/tests/services/test_start_first_run.py -q
14 passed

uv run python -m pytest backend/tests/services/test_publication_boundary.py -q
6 passed
```

Blocked frontend verification:

```text
npm --prefix frontend run test -- --run src/features/workspace/__tests__/ProjectSessionHistory.test.tsx
Initial exit 1: 'vitest' is not recognized as an internal or external command

npm --prefix frontend run build
Initial exit 1: 'tsc' is not recognized as an internal or external command
```

Root cause: `frontend/node_modules/.bin/vitest.cmd`, `tsc`, and `vite` were absent. `frontend/package-lock.json` exists. The user approved `npm --prefix frontend ci`, which installed declared dependencies without manifest changes.

Completed frontend verification:

```text
npm --prefix frontend run test -- --run src/features/workspace/__tests__/ProjectSessionHistory.test.tsx
1 test file passed, 4 tests passed

npm --prefix frontend run build
tsc --noEmit and vite build succeeded
```

- [ ] **Step 10: Commit gate**

After fresh verification, use `git-delivery-workflow` commit gate. Confirm no current split spec document is part of the commit unless separately approved by the user.
