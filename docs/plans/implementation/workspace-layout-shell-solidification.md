# Workspace Layout Shell Solidification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Fallback to `superpowers:executing-plans` only if subagent boundaries cannot be kept precise. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Solidify the workspace shell so the closed Inspector consumes no layout or DOM space, the middle workspace content centers consistently, and session cards keep inline rename and delete controls usable with long names.

**Architecture:** Keep the existing three-region workspace composition, but make the Inspector region conditional. The shell uses explicit closed/open layout classes, and the middle column owns a shared centered content width token that template empty state, Narrative Feed, Run Switcher, and Composer inherit. Session list actions remain shell-level affordances: rename is inline display editing backed by the existing session rename API, delete remains disabled and visually protected.

**Tech Stack:** React, TypeScript, TanStack Query, Vitest, Testing Library, CSS grid/flex.

---

## Scope And Source Trace

- User task: workspace layout and sidebar/inspector display solidification.
- Branch gate: worktree clean, current branch `fix/workspace-layout-shell`, current slice matches branch objective, next Git action after verification is commit gate.
- Acceleration claim/store steps: N/A by user instruction and current stabilization workflow.
- Governing frontend spec: `docs/specs/frontend-workspace-global-design-v1.md`.
  - Section 6 defines left `Project + Session Sidebar`, middle `Narrative Workspace`, right `Inspector`, with Inspector default closed and opened on detail actions.
  - Section 8.2 defines template configuration as Narrative Feed empty content, not a separate main region.
  - Section 9 defines Composer as the middle-column input/control entry.
  - Section 12 defines Inspector as an on-demand detail region that does not replace Narrative Feed or own primary actions.
- Impeccable product design gate:
  - Register: product UI.
  - Context script status: `.agents/skills/impeccable/scripts/load-context.mjs` missing and no root `PRODUCT.md`/`DESIGN.md` found, so use default workspace register.
  - Baseline tone: quiet, professional, high-information-density workspace UI.
  - Layout strategy: predictable shell grid, no decorative motion, no new marketing/hero patterns, stable icon/button dimensions, long text protected through truncation and `min-width: 0`.

## Files

- Modify: `frontend/src/features/workspace/WorkspaceShell.tsx`
- Modify: `frontend/src/features/workspace/SessionList.tsx`
- Modify: `frontend/src/features/workspace/ProjectSidebar.tsx`
- Modify: `frontend/src/mocks/handlers.ts`
- Modify: `frontend/src/features/inspector/InspectorPanel.tsx`
- Modify: `frontend/src/features/workspace/__tests__/WorkspaceShell.test.tsx`
- Modify: `frontend/src/pages/__tests__/ConsolePage.test.tsx`
- Modify: `frontend/src/features/workspace/__tests__/ProjectSessionHistory.test.tsx`
- Modify: `frontend/src/features/inspector/__tests__/InspectorPanel.test.tsx`
- Modify: `frontend/src/styles/global.css`
- Modify: `docs/plans/implementation/workspace-layout-shell-solidification.md`

Do not modify backend code, template editing save semantics, configuration import/export logic, or backend session auto-naming logic.

## Task 1: Inspector Closed DOM And Shell Classes

**Files:**
- Modify: `frontend/src/features/inspector/__tests__/InspectorPanel.test.tsx`
- Modify: `frontend/src/features/workspace/__tests__/WorkspaceShell.test.tsx`
- Modify: `frontend/src/features/inspector/InspectorPanel.tsx`
- Modify: `frontend/src/features/workspace/WorkspaceShell.tsx`

- [x] **Step 1: Write failing Inspector closed test**

In `InspectorPanel.test.tsx`, replace closed-state assertions with:

```tsx
it("does not render the Inspector region while closed", () => {
  renderWithAppProviders(
    <InspectorPanel
      isOpen={false}
      target={null}
      onClose={() => undefined}
      request={mockApiRequestOptions}
    />,
  );

  expect(screen.queryByRole("complementary", { name: "Inspector" })).toBeNull();
  expect(screen.queryByText("Inspector closed")).toBeNull();
});
```

Also update close-related tests to assert the Inspector complementary region disappears after closing.

Run:

```powershell
npm --prefix frontend run test -- --run src/features/inspector/__tests__/InspectorPanel.test.tsx
```

RED evidence: `npm --prefix frontend run test -- --run src/features/inspector/__tests__/InspectorPanel.test.tsx src/features/workspace/__tests__/WorkspaceShell.test.tsx src/features/workspace/__tests__/ProjectSessionHistory.test.tsx` exited 1. Inspector tests failed because the closed `<aside aria-label="Inspector">` and `Inspector closed` text still rendered.

- [x] **Step 2: Write failing shell layout class test**

In `WorkspaceShell.test.tsx`, update the default regions test:

```tsx
const shell = screen.getByRole("region", { name: "Workspace shell" });
expect(shell.getAttribute("class")).toContain("workspace-shell--inspector-closed");
expect(shell.getAttribute("class")).not.toContain("workspace-shell--inspector-open");
expect(screen.queryByRole("complementary", { name: "Inspector" })).toBeNull();
expect(screen.queryByText("Inspector closed")).toBeNull();
```

Add an open-state assertion after opening a feed detail:

```tsx
fireEvent.click(await screen.findByRole("button", { name: "Open Add workspace shell" }));
fireEvent.click(await screen.findByRole("button", { name: "Open Solution Design details" }));
const shell = screen.getByRole("region", { name: "Workspace shell" });
expect(shell.getAttribute("class")).toContain("workspace-shell--inspector-open");
expect(shell.getAttribute("class")).not.toContain("workspace-shell--inspector-closed");
expect(await screen.findByRole("complementary", { name: "Inspector" })).toBeTruthy();
```

Run:

```powershell
npm --prefix frontend run test -- --run src/features/workspace/__tests__/WorkspaceShell.test.tsx src/features/inspector/__tests__/InspectorPanel.test.tsx
```

RED evidence: same focused command exited 1. `WorkspaceShell` failed because the closed layout class was missing and the closed Inspector DOM still existed.

- [x] **Step 3: Implement conditional Inspector rendering**

In `InspectorPanel.tsx`, return `null` when closed:

```tsx
if (!isOpen || !target) {
  return null;
}
```

In `WorkspaceShell.tsx`, make the shell class explicit and base the open class on a visible Inspector target:

```tsx
const isInspectorVisible = inspector.isOpen && inspector.target !== null;
const shellClassName = isInspectorVisible
  ? "workspace-shell workspace-shell--inspector-open"
  : "workspace-shell workspace-shell--inspector-closed";
```

Use `className={shellClassName}` and keep `InspectorPanel` mounted so its focus restoration effect can run while returning `null` for the closed state:

```tsx
<InspectorPanel
  isOpen={isInspectorVisible}
  target={inspector.target}
  onClose={inspector.close}
  request={request}
/>
```

GREEN evidence: focused command exited 0 with 3 files passed and 57 tests passed after implementation.

## Task 2: Shared Middle Column Width And Centering

**Files:**
- Modify: `frontend/src/features/workspace/__tests__/WorkspaceShell.test.tsx`
- Modify: `frontend/src/styles/global.css`

- [x] **Step 1: Write failing class and containment tests**

In `WorkspaceShell.test.tsx`, assert the middle column has a centered content wrapper and key middle surfaces use the shared width class:

```tsx
const main = screen.getByRole("region", { name: "Narrative workspace" });
expect(main.getAttribute("class")).toContain("workspace-main");
expect(main.querySelector(".workspace-main__content")).toBeTruthy();
expect(main.querySelector(".workspace-main__panel--template .template-empty-state")).toBeTruthy();
expect(main.querySelector(".workspace-main__panel--composer .composer")).toBeTruthy();
```

For a running session:

```tsx
fireEvent.click(await screen.findByRole("button", { name: "Open Add workspace shell" }));
const main = screen.getByRole("region", { name: "Narrative workspace" });
expect(main.querySelector(".workspace-main__panel--feed .narrative-feed")).toBeTruthy();
expect(main.querySelector(".workspace-main__panel--composer .composer")).toBeTruthy();
```

Run:

```powershell
npm --prefix frontend run test -- --run src/features/workspace/__tests__/WorkspaceShell.test.tsx
```

RED evidence: focused command exited 1. Workspace tests failed because `.workspace-main__content` and shared middle panel wrappers were absent.

- [x] **Step 2: Implement shared classes and CSS**

Wrap the toolbar/feed/composer in `WorkspaceShell.tsx`:

```tsx
<section className="workspace-main" aria-label="Narrative workspace">
  <div className="workspace-main__content">
    ...
  </div>
</section>
```

Add `workspace-main__panel` wrappers in `WorkspaceShell` around the template, feed, empty, and composer surfaces. Do not edit `TemplateEmptyState`, `NarrativeFeed`, or `Composer` for class plumbing in this slice.

In `global.css`, define a single width token and centering rule:

```css
.workspace-main {
  min-height: 0;
  overflow: auto;
  padding: 24px;
}

.workspace-main__content {
  width: min(880px, 100%);
  min-width: 0;
  display: grid;
  gap: 18px;
  margin-inline: auto;
}

.workspace-main__panel,
.template-empty-state,
.narrative-feed__entries,
.narrative-feed__run-groups,
.run-switcher,
.composer {
  width: 100%;
  min-width: 0;
}
```

GREEN evidence: focused command exited 0 after `WorkspaceShell` wrapped toolbar/feed/composer in `.workspace-main__content` and `.workspace-main__panel` containers, and `global.css` moved the shared width to the middle content wrapper.

## Task 3: Inline Session Rename And Protected Delete

**Files:**
- Modify: `frontend/src/features/workspace/__tests__/WorkspaceShell.test.tsx`
- Modify: `frontend/src/features/workspace/__tests__/ProjectSessionHistory.test.tsx`
- Modify: `frontend/src/features/workspace/SessionList.tsx`
- Modify: `frontend/src/styles/global.css`

- [x] **Step 1: Write failing inline rename and truncation tests**

Add a focused `SessionList` test in `WorkspaceShell.test.tsx` or a local describe block that renders `SessionList` directly with a long session name:

```tsx
const longName = "This is a very long session name that should stay on one protected row without pushing delete outside the card";
render(
  <SessionList
    sessions={[{ ...mockSessionWorkspaces["session-running"].session, display_name: longName }]}
    currentSessionId="session-running"
    onSessionChange={() => undefined}
  />,
);

const item = screen.getByRole("article", { name: `Session ${longName}` });
expect(within(item).getByRole("button", { name: `Open ${longName}` })).toBeTruthy();
expect(within(item).getByRole("button", { name: `Rename ${longName}` })).toBeTruthy();
expect(within(item).getByRole("button", { name: `Delete ${longName} blocked by active run` })).toBeTruthy();
expect(item.querySelector(".session-list-item__title-row")).toBeTruthy();
expect(item.querySelector(".session-list-item__name-text")).toBeTruthy();
expect(item.querySelector(".session-list-item__delete")).toBeTruthy();
```

Then click rename and assert the inline edit field appears:

```tsx
fireEvent.click(within(item).getByRole("button", { name: `Rename ${longName}` }));
expect(within(item).getByRole("textbox", { name: `Rename ${longName}` })).toHaveProperty("value", longName);
expect(within(item).getByRole("button", { name: "Save session name" })).toBeTruthy();
expect(within(item).getByRole("button", { name: "Cancel rename" })).toBeTruthy();
```

Update existing shell/history assertions to keep the disabled delete behavior but no longer require a separate visible `Rename` button row.

Run:

```powershell
npm --prefix frontend run test -- --run src/features/workspace/__tests__/WorkspaceShell.test.tsx src/features/workspace/__tests__/ProjectSessionHistory.test.tsx
```

RED evidence: focused command exited 1. The direct `SessionList` test could not find the named session article, title row, name truncation hook, delete hook, or inline rename textbox.

- [x] **Step 2: Implement inline edit UI without backend semantic changes**

In `SessionList.tsx`:

- Add local `editingSessionId` and `draftName` state.
- Keep `onSessionChange` unchanged.
- Do not call backend rename in this slice; this is display solidification. The inline edit can expose save/cancel controls with save disabled when the trimmed name is empty or unchanged.
- Render an accessible title row:

```tsx
<div className="session-list-item__title-row">
  {isEditing ? (
    <label className="session-list-item__rename">
      <span className="sr-only">Rename {session.display_name}</span>
      <input ... />
    </label>
  ) : (
    <button className="session-list-item__open" ...>
      <span className="session-list-item__name-text">{session.display_name}</span>
    </button>
  )}
  <button className="session-list-item__delete" type="button" disabled ...>
    Delete
  </button>
</div>
```

- Place rename edit trigger as a quiet inline control beneath or beside the name, not as a separate equal-weight action row.

In `global.css`, protect the name/delete row:

```css
.session-list-item__title-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: start;
  gap: 8px;
  min-width: 0;
}

.session-list-item__open,
.session-list-item__rename,
.session-list-item__rename input,
.session-list-item__name-text {
  min-width: 0;
}

.session-list-item__name-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-list-item__delete {
  width: auto;
  flex: 0 0 auto;
}
```

Review fix evidence: an additional RED test proved inline rename Save was only updating local display state and was not calling the existing session rename client. The fix wires `SessionList` to `renameSession()` through the sidebar request context, updates the project-session query cache in `ProjectSidebar`, and adds the mock `PATCH /api/sessions/{sessionId}` route used by existing frontend fixtures. This changes no backend code and does not alter backend auto-naming.

GREEN evidence: focused command exited 0 after inline rename UI, protected delete placement, long-name truncation CSS, and existing frontend rename API wiring were added.

## Task 4: Final Verification And Review

- [x] **Step 1: Run focused required verification**

```powershell
npm --prefix frontend run test -- --run src/features/inspector/__tests__/InspectorPanel.test.tsx src/features/workspace/__tests__/WorkspaceShell.test.tsx src/features/workspace/__tests__/ProjectSessionHistory.test.tsx
```

Result: exit 0. Vitest reported 3 files passed and 57 tests passed.

- [x] **Step 2: Run full frontend tests**

```powershell
npm --prefix frontend run test -- --run
```

First result: exit 1 because `frontend/src/pages/__tests__/ConsolePage.test.tsx` still expected the removed `Inspector closed` text. The stale assertions were updated to require the closed shell class and no Inspector role/text.

Final result before review fix: exit 0. Vitest reported 29 files passed and 252 tests passed.

Final result after rename persistence review fix: exit 0. Vitest reported 29 files passed and 252 tests passed.

- [x] **Step 3: Run frontend build**

```powershell
npm --prefix frontend run build
```

Result before review fix: exit 0. `tsc --noEmit && vite build` completed; Vite transformed 137 modules and built the production bundle.

Result after rename persistence review fix: exit 0. `tsc --noEmit && vite build` completed; Vite transformed 137 modules and built the production bundle.

- [x] **Step 4: Two-stage review**

Spec/plan compliance review:

- Closed Inspector renders no aside and no closed text.
- Shell exposes closed/open layout classes.
- Middle content uses one centered max-width rule.
- Session list inline rename and delete placement match requested UI.
- No backend, template save, config import/export, or backend auto-naming changes.

Code quality/testing/regression review:

- No new inaccessible controls.
- Escape/close behavior still clears Inspector.
- Long names cannot overflow the sidebar or squeeze delete.
- Tests assert behavior/classes without relying on computed layout unavailable in jsdom.

Result: subagent reviewers were launched but did not return within the wait window, then were closed. Inline spec/plan review found no Critical or Important compliance issues after correcting the plan's wrapper wording. Inline code quality/testing/regression review found one Important issue: inline rename Save was local-only and did not use the existing session rename API. That issue was fixed with a RED test, API wiring through `SessionList`, sidebar query cache update, and mock fixture route coverage. Re-verification passed after the fix.

- [x] **Step 5: Commit gate**

Use `git-delivery-workflow` commit gate after fresh verification. Do not commit specs awaiting review. This implementation plan and UI/test changes form one coherent checkpoint if verification is green.

Result: commit gate is ready to commit one coherent implementation checkpoint. The changed implementation plan is not a formal split spec document and contains this slice's execution evidence.

## Subagent Execution Contract

- Implementer allowed files: only the files listed in this plan.
- Implementer allowed commands: the three `npm --prefix frontend ...` verification commands listed above and read-only inspection commands.
- Implementer forbidden actions: backend edits, dependency install/upgrade, lockfile edits, config/env edits, migration commands, file deletion/move, Git write commands, acceleration coordination store updates, platform/split final status updates.
- Implementer must report RED and GREEN command outputs with exit codes.
- Reviewers must run in order: spec/plan compliance first, then code quality/testing/regression. Critical or Important findings require fixes and re-review.
