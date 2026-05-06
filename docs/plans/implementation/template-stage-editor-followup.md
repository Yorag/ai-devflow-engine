# Template Stage Editor Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development when a task can be safely isolated; otherwise use focused inline TDD with explicit review checkpoints. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish the draft template editor so provider-missing states are readable, stage editing saves the whole template, stage cards avoid duplicate machine names, and the draft Composer remains usable while unsaved template edits are only advisory.

**Architecture:** Keep the change in the existing frontend template slice. `template-state.ts` owns provider availability messages and dirty-template advisory copy. `TemplateEditor` renders only user-facing stage labels, disables provider selection when no provider is configured, and saves the full template draft. `WorkspaceShell` stops pre-blocking the draft Composer for provider availability and lets backend run-start validation remain authoritative.

**Tech Stack:** React, TypeScript, TanStack Query, Vitest, Testing Library, existing REST API clients.

---

## Source Trace

- Branch gate: current branch `feat/template-stage-editor`, worktree clean after commit `87ddcba fix(composer): compact workspace input bar`.
- Acceleration claim/store: N/A for this stabilization follow-up; active AGENTS.md says acceleration lane mode is historical and `slice-workflow` may be used as single-task discipline without coordination-store updates.
- `references/superpowers-execution-rules.md`: missing in this worktree, so this plan uses AGENTS.md, the current split specs, and existing implementation documents as source.
- Frontend spec:
  - `docs/specs/frontend-workspace-global-design-v1.md` lines around `13.1`: draft sessions show template selection and Composer immediately.
  - Same section still says dirty templates should require save/discard before direct start. The latest user request changes product behavior to advisory only: sending uses the currently bound template, unsaved draft edits are not included.
  - `16` usability requirements say model/provider dropdowns show only configured enabled providers and do not treat unconfigured builtin providers as defaults.
- Backend spec:
  - `POST /api/sessions/{sessionId}/messages` with `new_requirement` starts from current `selected_template_id`; backend rejects missing or disabled Provider at run start.
  - `PipelineTemplateWriteRequest` persists full `stage_role_bindings`, not a partial stage fragment.
- Existing plan:
  - `docs/plans/implementation/template-stage-editor.md` originally used `Save stage` and only replaced the active stage binding. This follow-up supersedes that UI copy and save behavior: the editor remains stage-scoped for editing, but the action saves the whole template draft.

## Frontend Design Gate

- Product UI, restrained style.
- Remove implementation identifiers from user-facing surfaces.
- Prefer explicit disabled states and short status messages over leaking provider ids.
- Keep Composer as the primary draft input, available in the same workspace while template configuration is advisory.

## Files

- Modify: `frontend/src/features/templates/template-state.ts`
- Modify: `frontend/src/features/templates/TemplateEditor.tsx`
- Modify: `frontend/src/features/templates/TemplateEmptyState.tsx`
- Modify: `frontend/src/features/templates/__tests__/TemplateEditor.test.tsx`
- Modify: `frontend/src/features/templates/__tests__/TemplateSelector.test.tsx`
- Modify: `frontend/src/features/composer/Composer.tsx`
- Modify: `frontend/src/features/composer/__tests__/Composer.test.tsx`
- Modify: `frontend/src/features/workspace/WorkspaceShell.tsx`
- Modify: `frontend/src/features/workspace/__tests__/WorkspaceShell.test.tsx`
- Modify: `frontend/src/styles/global.css`

## Task 1: Provider Availability Copy And Select State

**Files:**
- Modify: `frontend/src/features/templates/template-state.ts`
- Modify: `frontend/src/features/templates/TemplateEditor.tsx`
- Test: `frontend/src/features/templates/__tests__/TemplateEditor.test.tsx`

- [x] **Step 1: Write failing tests**

Add tests that render a draft template with `providers={[]}` and assert:
- The guard says `No provider configured`.
- The provider select is disabled.
- The select does not expose `provider-deepseek` or `provider-volcengine` in visible text.

Add a second test with a configured provider that does not match the template binding and assert:
- The guard says `This template references unavailable providers.`
- The current unavailable option does not show the raw provider id.
- The configured provider remains selectable.

- [x] **Step 2: Verify RED**

Run:

```bash
npm --prefix frontend run test -- --run src/features/templates/__tests__/TemplateEditor.test.tsx
```

Expected: failure because the current UI lists raw provider ids and leaves the no-provider select value tied to the missing id.

- [x] **Step 3: Implement provider availability helpers**

In `template-state.ts`, make no-enabled-provider a distinct state:

```ts
export function hasConfiguredTemplateProviders(providers: ProviderRead[]): boolean {
  return availableTemplateProviders(providers).length > 0;
}

export function unavailableProviderMessage(providerIds: string[]): string {
  return providerIds.length > 0
    ? "This template references unavailable providers."
    : "No provider configured.";
}
```

Keep `unavailableTemplateProviderIds` returning missing ids only when at least one provider is configured.

- [x] **Step 4: Implement disabled no-provider select**

In `TemplateEditor.tsx`, disable the provider `<select>` when `providerOptions.length === 0`, render only `No provider configured`, and render a generic `Unavailable provider` option when a binding points to a missing provider while configured alternatives exist.

- [x] **Step 5: Verify GREEN**

Run the same focused command and expect all TemplateEditor tests to pass.

## Task 2: Whole Template Save Semantics And Button Copy

**Files:**
- Modify: `frontend/src/features/templates/TemplateEmptyState.tsx`
- Modify: `frontend/src/features/templates/TemplateEditor.tsx`
- Test: `frontend/src/features/templates/__tests__/TemplateEditor.test.tsx`
- Test: `frontend/src/features/workspace/__tests__/WorkspaceShell.test.tsx`

- [x] **Step 1: Write failing tests**

Update save tests so the button is `Save template`, not `Save stage`.

Add a test that edits Requirement Analysis, switches to Solution Design, edits it, clicks `Save template`, and asserts both edited bindings are present in the full saved `stage_role_bindings` payload.

- [x] **Step 2: Verify RED**

Run:

```bash
npm --prefix frontend run test -- --run src/features/templates/__tests__/TemplateEditor.test.tsx src/features/workspace/__tests__/WorkspaceShell.test.tsx
```

Expected: failure because the button is still `Save stage` and `TemplateEmptyState` currently saves only the active stage.

- [x] **Step 3: Save the full draft**

Change editor callbacks to `onSaveAs()` and `onOverwrite()` without a `stageType` argument. In `TemplateEmptyState`, remove active-stage filtering and pass the current `draft` directly to save-as or overwrite. Keep role ids and stage types from the draft.

- [x] **Step 4: Verify GREEN**

Run the same focused command and expect the updated save tests to pass.

## Task 3: Remove Duplicate Stage Machine Name

**Files:**
- Modify: `frontend/src/features/templates/TemplateEditor.tsx`
- Modify: `frontend/src/styles/global.css`
- Test: `frontend/src/features/templates/__tests__/TemplateEditor.test.tsx`

- [x] **Step 1: Write failing test**

Assert the active stage card contains `Requirement Analysis` but does not contain `requirement_analysis`.

- [x] **Step 2: Verify RED**

Run:

```bash
npm --prefix frontend run test -- --run src/features/templates/__tests__/TemplateEditor.test.tsx
```

Expected: failure because the stage card currently renders the snake_case `stage_type` on the right.

- [x] **Step 3: Remove machine-name span**

Delete the right-side `stage_type` text from `TemplateEditor.tsx`. Keep tabs as the stage switcher and keep CSS layout stable.

- [x] **Step 4: Verify GREEN**

Run the same focused command and expect the test to pass.

## Task 4: Draft Composer Is Advisory, Not Blocked By Template Editor State

**Files:**
- Modify: `frontend/src/features/composer/Composer.tsx`
- Modify: `frontend/src/features/composer/__tests__/Composer.test.tsx`
- Modify: `frontend/src/features/workspace/WorkspaceShell.tsx`
- Modify: `frontend/src/features/workspace/__tests__/WorkspaceShell.test.tsx`

- [x] **Step 1: Write failing tests**

Update workspace tests so empty provider configuration keeps the template warning visible but the draft Composer input is enabled. Type a requirement and assert the send button enables.

Add a test that edits a template prompt without saving, types a requirement, submits it, and asserts the message body is still `new_requirement`; no template save request is made.

- [x] **Step 2: Verify RED**

Run:

```bash
npm --prefix frontend run test -- --run src/features/composer/__tests__/Composer.test.tsx src/features/workspace/__tests__/WorkspaceShell.test.tsx
```

Expected: failure because `WorkspaceShell` still passes `startBlockedReason` to Composer and `Composer` disables draft input when providers are unavailable.

- [x] **Step 3: Remove frontend start pre-block**

Remove `startBlockedReason` from `Composer` props and from `WorkspaceShell`. Keep backend run-start validation as the source of truth for missing Provider rejection. Keep the template editor guard visible as advisory/configuration feedback.

- [x] **Step 4: Verify GREEN**

Run the same focused command and expect Composer and WorkspaceShell tests to pass.

## Final Verification

Run:

```bash
npm --prefix frontend run test -- --run src/features/templates/__tests__/TemplateEditor.test.tsx src/features/templates/__tests__/TemplateSelector.test.tsx src/features/composer/__tests__/Composer.test.tsx src/features/workspace/__tests__/WorkspaceShell.test.tsx
npm --prefix frontend run test -- --run
npm --prefix frontend run build
git diff --check
```

Expected:
- Focused tests pass.
- Full Vitest suite exits `0`.
- Build exits `0`.
- `git diff --check` exits `0`.

## Execution Notes

- TDD RED was observed with the focused frontend command before production edits; failures covered raw provider-id leakage, old `Save stage` copy, stage-only payload saves, duplicate `stage_type` text, and Composer pre-blocking.
- Focused GREEN after implementation:

```bash
npm --prefix frontend run test -- --run src/features/templates/__tests__/TemplateEditor.test.tsx src/features/templates/__tests__/TemplateSelector.test.tsx src/features/composer/__tests__/Composer.test.tsx src/features/workspace/__tests__/WorkspaceShell.test.tsx
```

Result: 4 test files passed, 80 tests passed.

- Model dropdown scope: current frontend and API contracts do not expose per-stage `model_id`. `StageRoleBinding` contains `stage_type`, `role_id`, `system_prompt`, and `provider_id`; provider records own `default_model_id` and supported model lists. This follow-up therefore disables the existing provider selector when no provider is configured and does not add a non-persistent model selector. A persistent per-stage model dropdown requires a backend contract change.

- Review:
  - Spec compliance reviewer found no issues.
  - Code quality reviewer subagent timed out; main session performed an inline code quality check over provider availability, full-template payload preservation, Composer send path, stale imports, and provider API projection behavior.

- Final verification:

```bash
npm --prefix frontend run test -- --run src/features/templates/__tests__/TemplateEditor.test.tsx src/features/templates/__tests__/TemplateSelector.test.tsx src/features/composer/__tests__/Composer.test.tsx src/features/workspace/__tests__/WorkspaceShell.test.tsx
npm --prefix frontend run test -- --run
npm --prefix frontend run build
git diff --check
```

Results:
- Focused frontend suite: 4 files passed, 80 tests passed.
- Full frontend suite: 30 files passed, 273 tests passed. Vitest emitted existing jsdom `Not implemented: navigation to another Document` stderr lines without failures.
- Frontend build: `tsc --noEmit && vite build` exited 0.
- Diff whitespace check: exited 0.
