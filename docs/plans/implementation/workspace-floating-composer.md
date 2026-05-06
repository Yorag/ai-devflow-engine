# Workspace Floating Composer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Fallback to `superpowers:executing-plans` only if subagent boundaries cannot be kept precise. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the session Composer fixed in the middle workspace viewport, like a chat input dock, so it stays usable while the Narrative Feed scrolls.

**Architecture:** `WorkspaceShell` keeps the left sidebar, middle workspace, and optional Inspector grid. The middle column splits scrollable feed content from a viewport-fixed Composer dock. The dock inherits the same centered max-width rail as the feed and template surfaces, while the scrollable content receives bottom padding so feed content is not hidden behind the floating input.

**Tech Stack:** React, TypeScript, Vitest, Testing Library, CSS grid/flex/fixed positioning.

---

## Scope And Source Trace

- User task: "会话页，输入框是悬浮在中栏中央的，不随滚动条下拉、上滑，一直固定在页面窗口的固定位置参考 gemini、chatgpt 聊天框".
- Branch gate: implementation ran on local branch `fix/workspace-layout-shell`; current request continues the same workspace layout shell PR objective. After PR #19 was merged and its remote branch removed, final PR delivery uses a clean branch based on `origin/main` so the review contains only this floating Composer slice.
- Acceleration claim/store: N/A under the current main-based stabilization agreement in `AGENTS.md`.
- `slice-workflow` execution rules loaded from `.codex/skills/slice-workflow/references/superpowers-execution-rules.md`.
- Governing frontend spec: `docs/specs/frontend-workspace-global-design-v1.md`.
  - Section 8 defines the middle column as `Narrative Feed + Composer`.
  - Section 9 states Composer is fixed at the bottom of the middle column and is the unified requirement/clarification entry.
  - Section 15 requires narrow screens to keep the full Narrative Feed and bottom Composer without breaking reading continuity.
  - Acceptance item 27 requires Composer to stay fixed on the session page and serve the current active run.
- Impeccable product design gate:
  - Register: product UI.
  - Context loader status: `.agents/skills/impeccable/scripts/load-context.mjs` missing, so use the inherited default workspace register.
  - Baseline: quiet, professional, high-information-density workspace UI.
  - Layout strategy: no decorative hero/card treatment; preserve the centered middle rail; make the Composer visually available without covering feed content; keep disabled, loading, long-text, and responsive states stable.

## Files

- Modify: `frontend/src/features/workspace/__tests__/WorkspaceShell.test.tsx`
- Modify: `frontend/src/styles/global.css`
- Modify: `docs/plans/implementation/workspace-floating-composer.md`

Current slice note: `WorkspaceShell.tsx` already contained the scroll/dock structure from the preceding workspace layout commit. This slice does not add a new `WorkspaceShell.tsx` diff; it hardens the CSS positioning, mobile shell constraints, and regression coverage around that existing structure.

Do not modify backend code, template editor save semantics, configuration import/export logic, or backend session auto-naming logic.

## Task 1: Fixed Middle Composer Dock

**Files:**
- Modify: `frontend/src/features/workspace/__tests__/WorkspaceShell.test.tsx`
- Modify: `frontend/src/styles/global.css`

- [x] **Step 1: Confirm existing shell structure baseline**

`WorkspaceShell.tsx` already renders a scroll area and a separate Composer dock:

```tsx
<section className="workspace-main" aria-label="Narrative workspace">
  <div className="workspace-main__scroll">
    <div className="workspace-main__content">...</div>
  </div>
  {workspace ? (
    <div className="workspace-main__composer-dock">
      <div className="workspace-main__composer-inner">
        <Composer ... />
      </div>
    </div>
  ) : null}
</section>
```

Existing `WorkspaceShell.test.tsx` layout assertions cover this structure in the Inspector closed and Inspector open cases:

```tsx
const scrollArea = main.querySelector(".workspace-main__scroll");
const dock = main.querySelector(".workspace-main__composer-dock");
expect(scrollArea).toBeTruthy();
expect(dock?.parentElement).toBe(main);
expect(dock?.querySelector(".workspace-main__composer-inner .composer")).toBeTruthy();
expect(scrollArea?.querySelector(".workspace-main__panel--composer")).toBeNull();
```

No new production code is required for this step.

- [x] **Step 2: Add the failing CSS regression test for viewport-fixed behavior**

Add a CSS source regression test to `WorkspaceShell.test.tsx`:

```tsx
it("keeps the Composer dock fixed to the workspace viewport in CSS", () => {
  const cwd = process.cwd();
  const frontendRoot = cwd.endsWith("frontend") ? cwd : join(cwd, "frontend");
  const css = readFileSync(
    join(frontendRoot, "src", "styles", "global.css"),
    "utf8",
  );

  expect(css).toMatch(
    /\.workspace-shell\s*\{[^}]*--workspace-sidebar-width:\s*clamp\(280px,\s*22vw,\s*320px\);[^}]*--workspace-inspector-width:\s*0px;[^}]*height:\s*calc\(100vh\s*-\s*73px\);[^}]*min-height:\s*0;[^}]*grid-template-columns:\s*var\(--workspace-sidebar-width\)\s+minmax\(0,\s*1fr\);/su,
  );
  expect(css).toMatch(
    /\.workspace-shell--inspector-open\s*\{[^}]*--workspace-inspector-width:\s*clamp\(360px,\s*28vw,\s*420px\);[^}]*grid-template-columns:\s*var\(--workspace-sidebar-width\)\s+minmax\(0,\s*1fr\)\s+var\(--workspace-inspector-width\);/su,
  );
  expect(css).toMatch(
    /\.workspace-main__composer-dock\s*\{[^}]*position:\s*fixed;[^}]*left:\s*var\(--workspace-sidebar-width\);[^}]*right:\s*var\(--workspace-inspector-width\);/su,
  );
  expect(css).toMatch(/\.composer\s*\{[^}]*max-height:\s*min\(42vh,\s*260px\);[^}]*overflow:\s*auto;/su);
  expect(css).toMatch(/\.composer\s+textarea\s*\{[^}]*resize:\s*none;/su);
  expect(css).not.toMatch(
    /@media\s*\(max-width:\s*900px\)[\s\S]*\.workspace-shell,\s*\.workspace-shell--inspector-open\s*\{[^}]*height:\s*auto;/u,
  );
  expect(css).not.toMatch(
    /@media\s*\(max-width:\s*900px\)[\s\S]*\.workspace-shell,\s*\.workspace-shell--inspector-open\s*\{[^}]*overflow:\s*visible;/u,
  );
});
```

Run:

```powershell
npm --prefix frontend run test -- --run src/features/workspace/__tests__/WorkspaceShell.test.tsx
```

Expected RED: one failing test because `global.css` still lacks the shell width variables, the dock still uses `position: absolute`, the mobile shell still uses `height: auto` / `overflow: visible`, and the Composer textarea remains vertically resizable.

Actual RED evidence: the command exited 1 with 1 failed test and 39 passed tests. The failure was the expected CSS assertion that `.workspace-shell` did not define the final viewport-bounded rail contract: `--workspace-sidebar-width`, `--workspace-inspector-width`, `height: calc(100vh - 73px)`, `min-height: 0`, and grid columns driven from those variables.

- [x] **Step 3: Implement fixed dock CSS**

In `global.css`, move scroll responsibility to `.workspace-main__scroll`, define the shell column widths as inherited CSS variables, and make the dock viewport-fixed while still occupying only the middle column:

```css
.workspace-shell {
  --workspace-sidebar-width: clamp(280px, 22vw, 320px);
  --workspace-inspector-width: 0px;
  height: calc(100vh - 73px);
  min-height: 0;
  display: grid;
  grid-template-columns: var(--workspace-sidebar-width) minmax(0, 1fr);
  background: oklch(97.6% 0.006 248);
  overflow: hidden;
}

.workspace-shell--inspector-open {
  --workspace-inspector-width: clamp(360px, 28vw, 420px);
  grid-template-columns:
    var(--workspace-sidebar-width) minmax(0, 1fr)
    var(--workspace-inspector-width);
}

.workspace-main {
  position: relative;
  min-height: 0;
  display: grid;
  grid-template-rows: minmax(0, 1fr);
  overflow: hidden;
}

.workspace-main__scroll {
  min-height: 0;
  overflow: auto;
  padding: 24px 24px 300px;
}

.workspace-main__content,
.workspace-main__composer-inner {
  width: min(880px, 100%);
  min-width: 0;
  margin-inline: auto;
}

.workspace-main__content {
  display: grid;
  gap: 18px;
}

.workspace-main__composer-dock {
  position: fixed;
  left: var(--workspace-sidebar-width);
  right: var(--workspace-inspector-width);
  bottom: 0;
  z-index: 8;
  padding: 14px 24px 20px;
  pointer-events: none;
}

.workspace-main__composer-inner {
  pointer-events: auto;
}
```

Constrain Composer height so the bottom reserve stays reliable:

```css
.composer {
  width: 100%;
  max-height: min(42vh, 260px);
  display: grid;
  gap: 12px;
  overflow: auto;
}

.composer textarea {
  width: 100%;
  min-height: 88px;
  max-height: 140px;
  resize: none;
  overflow: auto;
}
```

In narrow screens, remove the sidebar/Inspector offset, keep the shell height bounded to the viewport, and preserve the middle scroll area:

```css
@media (max-width: 900px) {
  .workspace-shell,
  .workspace-shell--inspector-open {
    --workspace-sidebar-width: 0px;
    --workspace-inspector-width: 0px;
    height: calc(100vh - 73px);
    min-height: 0;
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto minmax(0, 1fr);
    overflow: hidden;
  }

  .workspace-sidebar {
    max-height: min(36vh, 280px);
  }

  .workspace-main {
    min-height: 0;
  }

  .workspace-main__scroll {
    padding: 20px 18px 340px;
  }

  .workspace-main__composer-dock {
    padding: 12px 18px 16px;
  }
}
```

- [x] **Step 4: Run focused green verification**

Run:

```powershell
npm --prefix frontend run test -- --run src/features/workspace/__tests__/WorkspaceShell.test.tsx
```

Expected GREEN: `WorkspaceShell.test.tsx` passes, and the Composer remains queryable as `role="form"` with existing send/pause/resume behavior.

Actual GREEN evidence: after the fixed dock CSS update, `npm --prefix frontend run test -- --run src/features/workspace/__tests__/WorkspaceShell.test.tsx` exited 0 with 1 file passed and 40 tests passed. After code review identified that a desktop `min-height: 520px` could let the fixed dock hide feed content on short viewports, the CSS regression was extended to require `min-height: 0`; temporarily restoring `min-height: 520px` produced the expected RED result with 1 failed test and 39 passed tests, and restoring `min-height: 0` produced GREEN with 1 file passed and 40 tests passed.

## Task 2: Review And Verification

- [x] **Step 1: Two-stage review**

Spec/plan compliance reviewer checks:

- Composer is no longer inside the scroll content flow.
- Composer dock is scoped to the middle column, not the whole browser viewport or sidebar/Inspector.
- The dock keeps the same centered max-width rule as template, feed, and previous Composer layout.
- Narrative Feed/template content gets bottom padding to avoid being hidden behind the floating input.
- No backend, template save, configuration import/export, or session auto-naming changes.

Code quality/testing/regression reviewer checks:

- The dock does not add nested cards.
- Pointer events allow feed scrolling outside the Composer and normal input interaction inside the Composer.
- Mobile breakpoint keeps feed continuity and bottom Composer.
- Existing Composer tests still exercise send, clarification, pause/resume, disabled states, and session-switch reset.

Review results:

- Spec/plan compliance reviewer found a Medium documentation issue: the plan still overstated current-slice `WorkspaceShell.tsx` changes and old structure-split RED evidence. The plan was corrected to treat `WorkspaceShell.tsx` as an existing baseline and to list only the current CSS/test/plan files in scope. The reviewer found no spec compliance issue in the actual floating Composer behavior.
- Code quality/testing/regression reviewer found a Medium short-viewport risk: desktop `.workspace-shell` still had `min-height: 520px` while the dock is fixed to the viewport bottom. The CSS regression test was extended, `.workspace-shell` now uses `min-height: 0`, and focused/impacted/full verification was rerun.

- [x] **Step 2: Run final verification**

Run:

```powershell
npm --prefix frontend run test -- --run src/features/inspector/__tests__/InspectorPanel.test.tsx src/features/workspace/__tests__/WorkspaceShell.test.tsx src/features/workspace/__tests__/ProjectSessionHistory.test.tsx
npm --prefix frontend run test -- --run src/features/workspace/__tests__/WorkspaceShell.test.tsx
npm --prefix frontend run test -- --run
npm --prefix frontend run build
```

Expected:

- Focused workspace shell tests pass.
- Full frontend Vitest suite passes. Existing jsdom navigation warnings may print but must not fail the run.
- `tsc --noEmit && vite build` completes.

Actual verification evidence after review fixes:

- `npm --prefix frontend run test -- --run src/features/inspector/__tests__/InspectorPanel.test.tsx src/features/workspace/__tests__/WorkspaceShell.test.tsx src/features/workspace/__tests__/ProjectSessionHistory.test.tsx` exited 0 with 3 files passed and 59 tests passed.
- `npm --prefix frontend run test -- --run` exited 0 with 30 files passed and 262 tests passed. The run printed existing jsdom `Not implemented: navigation to another Document` warnings after completion.
- `npm --prefix frontend run build` exited 0. It ran `tsc --noEmit && vite build`, transformed 137 modules, and completed the production build with `dist/assets/index-DouVRVYD.css` and `dist/assets/index-DlcxK9Ka.js`.

- [ ] **Step 3: Commit gate**

Use `git-delivery-workflow` commit gate after fresh verification. The checkpoint is commit-ready only if the diff remains limited to the files listed above and verification evidence is fresh.

## Subagent Execution Contract

- Implementer allowed files: only `frontend/src/features/workspace/__tests__/WorkspaceShell.test.tsx`, `frontend/src/styles/global.css`, and this implementation plan.
- Implementer allowed commands: the focused workspace test, full frontend test, frontend build, and read-only file inspection commands.
- Implementer forbidden actions: backend edits, dependency install/upgrade, lockfile edits, config/env edits, migrations, file deletion/move, Git write commands, PR actions, acceleration coordination store updates, platform/split final status updates.
- Implementer must use TDD and report RED/GREEN command outputs with exit codes.
- Reviewers must run in order: spec/plan compliance first, then code quality/testing/regression. Critical or Important findings require fixes and re-review.
