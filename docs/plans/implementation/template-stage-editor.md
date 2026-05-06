# Template Stage Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` where task boundaries are precise. Fallback to `superpowers:executing-plans` only when the edit set is too tightly coupled to delegate safely. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify the draft-session template surface into compact template selection plus stage-scoped editing, then persist the saved template and bind it to the draft session before the first requirement starts.

**Architecture:** Keep the draft template UI inside the Narrative Feed empty state and keep Composer fixed below it. `TemplateSelector` becomes a compact template switcher. `TemplateEditor` owns one selected stage at a time, derives `stage_type` from the active fixed-stage tab, hides stage role selection, and edits only that stage binding plus template-level retry settings and user-template name. `WorkspaceShell` owns real template save/patch/delete/session-binding requests, refetches query data, and lets the template panel disappear naturally once Composer starts the run.

**Tech Stack:** React 18, TypeScript, TanStack Query, Vitest, Testing Library, existing frontend API clients, existing global CSS.

---

## Slice And Gate State

- Branch gate: current branch `feat/template-stage-editor`, worktree clean before planning, HEAD matches `origin/main` at `09f6f8f`. This task continues the branch objective.
- Active workflow: main-based stabilization and display solidification. Acceleration claim/store/lane worker gates are N/A per `AGENTS.md`.
- Selected slice id: `template-stage-editor`.
- Implementation plan path: `docs/plans/implementation/template-stage-editor.md`.
- Backend contract decision: no backend change required. Existing frontend clients expose `saveAsPipelineTemplate`, `patchPipelineTemplate`, `deletePipelineTemplate`, and `updateSessionTemplate`.
- Commit gate: use `git-delivery-workflow` after implementation, review, and fresh verification. Do not commit draft spec documents. This implementation plan is not a current split spec and can be committed with the implementation checkpoint if verified.

## Source Trace

- Frontend template semantics: `docs/specs/frontend-workspace-global-design-v1.md`, section `8.2` and section `13.1`.
  - Blank session template content belongs inside Narrative Feed empty content, not a separate page.
  - Template selection and editing coexist with Composer.
  - Fixed core stages and approval checkpoints are not editable.
  - System templates can be selected and saved as user templates; user templates can be overwritten, saved as new, or deleted.
  - After the first message starts a run, the template configuration area leaves the main workspace.
- Backend template and session contract: `docs/specs/function-one-backend-engine-design-v1.md`, sections `5.1`, `5.2`, and API list around `PUT /api/sessions/{sessionId}/template`.
  - Draft sessions may update `selected_template_id`.
  - `system_template` is immutable except save-as.
  - `user_template` supports overwrite, save-as, and delete.
  - Message append with `new_requirement` starts the first run from the current `selected_template_id`.
- Prior frontend implementation record: `docs/plans/implementation/f2.5-template-empty-state-selector.md`.
  - Template empty state is Narrative Feed content.
  - Template selector must remain compact and product-UI oriented.
- Prior editor implementation record: `docs/plans/implementation/f2.6-template-editor-dirty-guard.md`.
  - Existing editor edits allowed runtime fields and blocks dirty starts.
  - Existing plan intentionally kept persistence local/mock-compatible; this slice replaces that gap with real frontend client calls.
- Backend CRUD implementation record: `docs/plans/implementation/c2.4-user-template-crud.md`.
  - `PipelineTemplateWriteRequest` contains `name`, `description`, `stage_role_bindings`, `auto_regression_enabled`, and `max_auto_regression_retries`.
  - Direct patch/delete of system templates is rejected by backend; frontend must route system changes through save-as.

No Source Trace Conflict Gate blocker was found. The requested stage-scoped UI is a refinement of the existing fixed-stage skeleton semantics and uses already-declared API contracts.

## Frontend Design Gate

- Skill: `impeccable`.
- Context load result: repo root has no `PRODUCT.md` or `DESIGN.md`. Register is product UI, inferred from authenticated workspace/tool surface. Use the established project baseline: quiet, professional, high information density.
- Physical scene: a developer is starting a local delivery session from a desktop workspace, scanning a small number of templates, editing one stage binding, then immediately typing the first requirement in Composer.
- Information hierarchy:
  - Top: compact template selector and selected template identity.
  - Next: fixed-stage segmented control with six stable stages.
  - Current focus: one stage editor only.
  - Footer action: `Save stage`, with `Save as user template` semantics for system templates and overwrite semantics for user templates.
- Layout:
  - No landing page, hero, card wall, or independent template management page.
  - Use tabs/segmented control for the six fixed stages.
  - Avoid nested cards. Keep stage editor in one compact panel.
  - Keep Composer visible and usable for draft sessions unless blocked by template/provider state.
- Interaction:
  - Template switch means editing a different template and resets active stage to the first fixed stage.
  - Stage switch within the same template means editing another binding in the same draft.
  - Stage role select is removed. The active stage decides `stage_type`; `role_id` remains the existing binding value in the saved payload and is not exposed in UI text.
  - System template name is read-only.
  - User template name supports inline rename and is included when patching the user template.
  - Save completes by saving/patching the full template payload, then binding the resulting template id to the current draft session.
- Responsive and accessibility checks:
  - Tabs are keyboard reachable buttons with selected state.
  - Inputs have labels and error/status text.
  - Long template names, provider names, and prompts wrap.
  - Buttons have stable widths and disabled/loading states.
  - No viewport-scaled font sizes, negative letter spacing, side-stripe accents, gradient text, glass styling, decorative orbs, or nested cards.

## Files

- Modify: `frontend/src/features/templates/TemplateEmptyState.tsx`
- Modify: `frontend/src/features/templates/TemplateEditor.tsx`
- Modify: `frontend/src/features/templates/TemplateSelector.tsx`
- Modify: `frontend/src/features/templates/template-state.ts`
- Modify: `frontend/src/features/templates/__tests__/TemplateEditor.test.tsx`
- Modify: `frontend/src/features/templates/__tests__/TemplateSelector.test.tsx`
- Modify: `frontend/src/features/workspace/WorkspaceShell.tsx`
- Modify: `frontend/src/features/workspace/__tests__/WorkspaceShell.test.tsx`
- Modify: `frontend/src/api/templates.ts` only if exported helper naming needs alignment; no backend contract change.
- Modify: `frontend/src/api/sessions.ts` only if existing update helper needs call-site typing; no backend contract change.
- Modify: `frontend/src/styles/global.css`
- Modify: `docs/plans/implementation/template-stage-editor.md`

Do not modify backend files, dependency manifests, lock files, environment files, database migrations, current split specs, acceleration coordination store, platform plan final statuses, or archived specs.

## Behavior Details

- Fixed stage order:
  - `requirement_analysis`
  - `solution_design`
  - `code_generation`
  - `test_generation_execution`
  - `code_review`
  - `delivery_integration`
- Template selector:
  - Compact row/list of templates.
  - Switching template calls `updateSessionTemplate` for draft sessions and changes the editor template.
  - Stage tab state resets when template id changes.
- Editor:
  - Shows only the active stage binding.
  - Displays the active stage label, while retaining the original `role_id` in data only.
  - Removes user-visible role select and role id text.
  - Provider and system prompt remain editable for the active stage.
  - Auto regression settings remain visible as template-level runtime settings.
  - `Save stage` builds a full `PipelineTemplateWriteRequest` from the latest template baseline plus the active stage draft.
  - Other `stage_role_bindings` remain byte-for-byte equal to the baseline for that save.
- Save behavior:
  - For `system_template`, call `saveAsPipelineTemplate(sourceTemplateId, payload)`, then `updateSessionTemplate(sessionId, { template_id: saved.template_id })`.
  - For `user_template`, call `patchPipelineTemplate(templateId, payload)`, then `updateSessionTemplate(sessionId, { template_id: patched.template_id })`.
  - On success, refetch templates, sessions, and session workspace.
  - On failure, keep editor visible and show the error.
- Inline rename:
  - System template name is read-only text.
  - User template name is editable inline and included in the patch payload.
  - Empty trimmed user template name blocks save with a visible field error.
- Post-save panel disappearance:
  - Save binds the saved template to the draft session.
  - The template panel disappears immediately after save and bind.
  - The middle column renders an empty Narrative Feed area while Composer remains ready for the first requirement.
  - After Composer submits `new_requirement`, the session becomes non-draft through the existing workspace store/query flow and continues as Narrative Feed plus Composer.

## Log And Audit Integration

- Frontend-only slice. No new backend log or audit behavior is implemented.
- Template save/patch/delete and session-template binding already use backend command APIs that own audit semantics.
- Frontend tests assert request methods, paths, and payload shape. They do not treat logs or audits as product truth.

## Subagent Execution Plan

Use one implementer subagent only if the controller can provide the exact plan and current file context. The write set is tightly coupled across editor state, shell persistence, mocks, tests, and CSS, so fallback to inline execution is acceptable if subagent context would duplicate or conflict with controller work.

Implementer subagent:
- Model: `gpt-5.5`, reasoning effort `xhigh`.
- Required sub-skill: `superpowers:test-driven-development`.
- Allowed files:
  - `frontend/src/features/templates/TemplateEmptyState.tsx`
  - `frontend/src/features/templates/TemplateEditor.tsx`
  - `frontend/src/features/templates/TemplateSelector.tsx`
  - `frontend/src/features/templates/template-state.ts`
  - `frontend/src/features/templates/__tests__/TemplateEditor.test.tsx`
  - `frontend/src/features/templates/__tests__/TemplateSelector.test.tsx`
  - `frontend/src/features/workspace/WorkspaceShell.tsx`
  - `frontend/src/features/workspace/__tests__/WorkspaceShell.test.tsx`
  - `frontend/src/mocks/handlers.ts`
  - `frontend/src/styles/global.css`
- Allowed commands:
  - `npm --prefix frontend run test -- --run src/features/templates/__tests__/TemplateEditor.test.tsx`
  - `npm --prefix frontend run test -- --run src/features/templates/__tests__/TemplateSelector.test.tsx`
  - `npm --prefix frontend run test -- --run src/features/workspace/__tests__/WorkspaceShell.test.tsx`
  - Read-only inspection commands such as `rg`, `Get-Content`, `git diff --stat`, and `git diff -- frontend/src/...`
- Forbidden:
  - Git write actions.
  - Dependency installation or lock/manifest changes.
  - Backend/API contract changes.
  - Spec document edits.
  - Acceleration coordination store or platform/split final status changes.
  - Workspace shell layout foundation changes unrelated to the template panel.
- Required report:
  - `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, `BLOCKED`, or `APPROVAL_REQUIRED`.
  - RED command, exit code, and expected failure excerpt.
  - GREEN command, exit code, and pass summary.
  - Files changed.
  - Design gate concerns.

Reviewer subagents:
- Spec compliance reviewer first: verify source trace, fixed-stage semantics, system/user template boundaries, save and session binding behavior, post-save/run-start panel disappearance, and no backend overreach.
- Code quality reviewer second: verify state boundaries, payload construction, async error/loading states, tests, accessibility, responsive CSS, and regression risk.
- Reviewer commands are read-only unless explicitly asked. Critical or Important findings must be fixed and re-reviewed.

## TDD Tasks

### Task 1: Stage Tabs And Current-Stage Editor

**Files:**
- Modify: `frontend/src/features/templates/__tests__/TemplateEditor.test.tsx`
- Modify: `frontend/src/features/templates/TemplateEditor.tsx`
- Modify: `frontend/src/features/templates/template-state.ts`

- [ ] **Step 1: Add failing tests**

Add tests proving six fixed stage tabs exist, only one stage editor is visible, stage switches preserve template identity, and there is no role select.

```tsx
it("renders fixed stage tabs and only edits the selected stage", () => {
  const workspace = mockSessionWorkspaces["session-draft"];

  renderWithAppProviders(
    <TemplateEmptyState
      session={workspace.session}
      templates={mockPipelineTemplates}
      providers={mockProviderList}
      selectedTemplateId="template-feature"
      onTemplateChange={() => undefined}
    />,
  );

  const editor = screen.getByRole("region", { name: "Template editor" });
  expect(within(editor).getAllByRole("tab")).toHaveLength(6);
  expect(within(editor).getByRole("tab", { name: "Requirement Analysis" })).toHaveProperty("ariaSelected", "true");
  expect(within(editor).getByLabelText("Requirement Analysis system prompt")).toHaveProperty(
    "value",
    "Analyze the requirement and ask clarifying questions when needed.",
  );
  expect(within(editor).queryByLabelText("Solution Design system prompt")).toBeNull();

  fireEvent.click(within(editor).getByRole("tab", { name: "Solution Design" }));

  expect(within(editor).getByRole("tab", { name: "Solution Design" })).toHaveProperty("ariaSelected", "true");
  expect(within(editor).getByLabelText("Solution Design system prompt")).toHaveProperty(
    "value",
    "Design a bounded implementation plan.",
  );
  expect(within(editor).queryByLabelText("Requirement Analysis system prompt")).toBeNull();
});

it("does not expose a stage role select while retaining the bound role id", () => {
  const workspace = mockSessionWorkspaces["session-draft"];

  renderWithAppProviders(
    <TemplateEmptyState
      session={workspace.session}
      templates={mockPipelineTemplates}
      providers={mockProviderList}
      selectedTemplateId="template-feature"
      onTemplateChange={() => undefined}
    />,
  );

  const editor = screen.getByRole("region", { name: "Template editor" });
  expect(within(editor).queryByLabelText(/ role$/u)).toBeNull();
  expect(within(editor).queryByText("role-requirement-analyst")).toBeNull();
});
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
npm --prefix frontend run test -- --run src/features/templates/__tests__/TemplateEditor.test.tsx
```

Expected: exit code `1`; failure shows no `tab` role or missing stage-specific label, and the existing role select is still present.

- [ ] **Step 3: Implement stage tab state**

Implementation requirements:
- Add `activeStageType` state in `TemplateEditor`.
- Reset active stage to `template.fixed_stage_sequence[0]` when `template.template_id` changes.
- Render `role="tablist"` with one button per fixed stage and `aria-selected`.
- Derive the current binding by `activeStageType`.
- Remove the role `<select>`.
- Render `role_id` as read-only text or metadata.
- Rename prompt/provider labels to display labels such as `Requirement Analysis system prompt`.

- [ ] **Step 4: Verify GREEN**

Run the same focused command. Expected exit code `0` for the new tests and existing editor tests after compatibility updates.

### Task 2: System/User Template Name Semantics

**Files:**
- Modify: `frontend/src/features/templates/__tests__/TemplateEditor.test.tsx`
- Modify: `frontend/src/features/templates/TemplateEditor.tsx`
- Modify: `frontend/src/features/templates/template-state.ts`

- [ ] **Step 1: Add failing tests**

Add tests for read-only system name and inline user-template rename.

```tsx
it("shows system template names as read-only and supports inline rename for user templates", () => {
  const workspace = mockSessionWorkspaces["session-draft"];
  const userTemplate = {
    ...mockPipelineTemplates[1],
    template_id: "template-user-existing",
    name: "Team feature flow",
    template_source: "user_template" as const,
    base_template_id: "template-feature",
  };
  const savedTemplates: string[] = [];

  renderWithAppProviders(
    <TemplateEmptyState
      session={workspace.session}
      templates={mockPipelineTemplates}
      providers={mockProviderList}
      selectedTemplateId="template-feature"
      onTemplateChange={() => undefined}
    />,
  );

  expect(screen.getByText("新功能开发流程")).toBeTruthy();
  expect(screen.queryByLabelText("Template name")).toBeNull();

  cleanup();

  renderWithAppProviders(
    <TemplateEmptyState
      session={workspace.session}
      templates={[...mockPipelineTemplates, userTemplate]}
      providers={mockProviderList}
      selectedTemplateId="template-user-existing"
      onTemplateChange={() => undefined}
      onTemplateOverwrite={(template) => savedTemplates.push(template.name)}
    />,
  );

  const nameInput = screen.getByLabelText("Template name");
  expect(nameInput).toHaveProperty("value", "Team feature flow");
  fireEvent.change(nameInput, { target: { value: "Checkout feature flow" } });
  fireEvent.change(screen.getByLabelText("Requirement Analysis system prompt"), {
    target: { value: "Clarify checkout requirements." },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save stage" }));

  expect(savedTemplates).toEqual(["Checkout feature flow"]);
});
```

- [ ] **Step 2: Verify RED**

Run focused editor tests. Expected failure: no `Template name` inline input for user template or no `Save stage` button.

- [ ] **Step 3: Implement name draft support**

Implementation requirements:
- Extend `TemplateDraftState` to include `name` and optional `description`.
- Update `createTemplateDraft`, dirty serialization, and payload construction.
- System templates show read-only name text.
- User templates show labeled text input `Template name`.
- Empty trimmed user-template name blocks save and displays an alert.

- [ ] **Step 4: Verify GREEN**

Run focused editor tests. Expected exit code `0`.

### Task 3: Save Stage Payload And API Persistence

**Files:**
- Modify: `frontend/src/features/templates/__tests__/TemplateEditor.test.tsx`
- Modify: `frontend/src/features/workspace/__tests__/WorkspaceShell.test.tsx`
- Modify: `frontend/src/features/templates/TemplateEmptyState.tsx`
- Modify: `frontend/src/features/templates/TemplateEditor.tsx`
- Modify: `frontend/src/features/workspace/WorkspaceShell.tsx`
- Modify: `frontend/src/mocks/handlers.ts`

- [ ] **Step 1: Add failing component payload test**

Add a test that changes the active stage and asserts only that binding changes in the saved full payload.

```tsx
it("Save stage replaces only the current stage binding and preserves other bindings", () => {
  const workspace = mockSessionWorkspaces["session-draft"];
  let savedTemplate: PipelineTemplateRead | null = null;

  renderWithAppProviders(
    <TemplateEmptyState
      session={workspace.session}
      templates={mockPipelineTemplates}
      providers={mockProviderList}
      selectedTemplateId="template-feature"
      onTemplateChange={() => undefined}
      onTemplateSaveAs={(template) => {
        savedTemplate = template;
      }}
    />,
  );

  const original = mockPipelineTemplates.find((template) => template.template_id === "template-feature")!;
  fireEvent.click(screen.getByRole("tab", { name: "Solution Design" }));
  fireEvent.change(screen.getByLabelText("Solution Design system prompt"), {
    target: { value: "Design only the approved checkout solution." },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save stage" }));

  expect(savedTemplate?.stage_role_bindings).toEqual(
    original.stage_role_bindings.map((binding) =>
      binding.stage_type === "solution_design"
        ? { ...binding, system_prompt: "Design only the approved checkout solution." }
        : binding,
    ),
  );
});
```

- [ ] **Step 2: Add failing shell API test**

Add a `WorkspaceShell` test with a custom fetcher:
- `POST /api/pipeline-templates/template-feature/save-as` captures full payload and returns a persisted user template.
- `PUT /api/sessions/session-draft/template` captures the saved template id.
- The test clicks `Save stage` from a system template, then asserts:
  - POST path/method called.
  - `stage_role_bindings` contains all six bindings.
  - Only active stage prompt changed.
  - session template binding uses returned user template id.

- [ ] **Step 3: Verify RED**

Run:

```powershell
npm --prefix frontend run test -- --run src/features/templates/__tests__/TemplateEditor.test.tsx src/features/workspace/__tests__/WorkspaceShell.test.tsx
```

Expected: exit code `1`; save is still local and does not call API from `WorkspaceShell`.

- [ ] **Step 4: Implement save handlers**

Implementation requirements:
- `TemplateEditor` exposes one primary button labeled `Save stage`.
- `TemplateEmptyState` receives async callbacks for save-as and overwrite and passes the resulting template back into local UI state.
- `WorkspaceShell` imports `saveAsPipelineTemplate`, `patchPipelineTemplate`, and `updateSessionTemplate`.
- Build `PipelineTemplateWriteRequest` including `name`, `description`, full `stage_role_bindings`, `auto_regression_enabled`, and `max_auto_regression_retries`.
- For system templates, call save-as, then bind saved template id to the draft session.
- For user templates, call patch, then bind patched template id to the draft session.
- Refetch `templatesQuery`, `sessionsQuery`, and `sessionWorkspaceQuery` after success.
- Surface save errors via `ErrorState` or an inline editor error.
- Update mock handlers to support template create/save-as/patch/delete and session binding to newly persisted user templates.

- [ ] **Step 5: Verify GREEN**

Run the focused component and shell tests. Expected exit code `0`.

### Task 4: Post-Save And Composer Readiness Flow

**Files:**
- Modify: `frontend/src/features/workspace/__tests__/WorkspaceShell.test.tsx`
- Modify: `frontend/src/features/workspace/WorkspaceShell.tsx`

- [ ] **Step 1: Add failing workflow test**

Add a test that saves a stage and asserts the template panel disappears while Composer stays ready for the first requirement.

```tsx
it("hides the template panel after saving and binding while Composer stays ready", async () => {
  renderWithAppProviders(
    <ConsolePage request={{ fetcher: createMockApiFetcher() }} />,
  );

  const editor = await screen.findByRole("region", { name: "Template editor" });
  fireEvent.change(within(editor).getByLabelText("Requirement Analysis system prompt"), {
    target: { value: "Clarify saved requirements before implementation." },
  });
  fireEvent.click(within(editor).getByRole("button", { name: "Save stage" }));

  await waitFor(() => {
    expect(screen.queryByRole("region", { name: "Template editor" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Template empty state" })).toBeNull();
  });
  expect(screen.getByRole("form", { name: "Composer" })).toBeTruthy();
  expect(screen.getByLabelText("当前输入")).toHaveProperty("disabled", false);
});
```

- [ ] **Step 2: Verify RED or existing behavior gap**

Run focused shell test. Expected failure if save does not persist/bind or if WorkspaceShell still forces the draft template panel after save.

- [ ] **Step 3: Implement/refine flow**

Implementation requirements:
- Ensure template save uses the same busy flag as template switch to prevent concurrent selector changes.
- Ensure Composer send after save relies on current session/workspace refetch and does not show stale draft template panel.
- Do not alter workspace shell layout foundation.

- [ ] **Step 4: Verify GREEN**

Run focused shell tests. Expected exit code `0`.

### Task 5: Compact Styling And Selector Cleanup

**Files:**
- Modify: `frontend/src/features/templates/__tests__/TemplateSelector.test.tsx`
- Modify: `frontend/src/features/templates/TemplateSelector.tsx`
- Modify: `frontend/src/styles/global.css`

- [ ] **Step 1: Add style/class and visible-copy tests**

Update selector/editor tests to assert:
- selector has compact class hooks,
- no stage role select text is visible,
- `Save stage` is the primary save label,
- fixed stage summary does not render as a large duplicated list when tabs are present.

- [ ] **Step 2: Verify RED**

Run selector/editor tests. Expected failure until markup/classes are updated.

- [ ] **Step 3: Implement CSS**

Implementation requirements:
- Convert `.template-selector__options` to compact responsive list/segmented rows.
- Add `.template-stage-tabs`, `.template-stage-tab`, `.template-stage-current`, `.template-editor__identity`, `.template-editor__status`, and `.template-editor__error` styles.
- Remove or reduce heavy selected template summary layout so tabs carry the fixed-stage skeleton.
- Preserve existing workspace shell and Composer dock CSS.
- Keep UI restrained: tinted neutrals, one accent for selection/action, semantic warning/error colors.

- [ ] **Step 4: Verify GREEN**

Run selector/editor focused tests. Expected exit code `0`.

## Review Plan

After implementation:
- Run a spec compliance review against this plan, `frontend-workspace-global-design-v1.md` section `8.2` and `13.1`, backend engine sections `5.1`, `5.2`, and API list, plus changed files.
- Run a code quality review against state management, async save flow, query refetches, tests, accessibility, CSS responsiveness, and overreach.
- Fix Critical and Important findings, then re-review those findings.

## Review Results

- Spec compliance review found no Critical issues.
- Fixed Important issue: user-template delete was local-only in the shell path. `WorkspaceShell` now calls `deletePipelineTemplate`, refetches template/session/workspace queries, and tests assert the DELETE request before fallback selection.
- Accepted user-requested spec drift: the current split spec still describes user-template save-as and stage role selection in the template editor, while this task explicitly requires user-template `Save stage` overwrite and removal of user-visible stage role UI.
- Accepted user-requested spec drift: the current split spec says the blank-session template area leaves after the first message starts a run, while this task explicitly requires the template panel to disappear after save and session binding. The split spec set should be reviewed before these semantics are treated as final spec truth.
- Code-quality reviewer did not return before timeout; an inline code-quality pass was completed over the changed files, followed by fresh focused tests, full frontend tests, and build.

## Final Verification

Fresh verification commands:

```powershell
npm --prefix frontend run test -- --run src/features/templates/__tests__/TemplateEditor.test.tsx src/features/templates/__tests__/TemplateSelector.test.tsx src/features/workspace/__tests__/WorkspaceShell.test.tsx
npm --prefix frontend run test -- --run
npm --prefix frontend run build
```

Expected:
- All commands exit `0`.
- Focused command includes the new stage tabs, hidden role select, inline rename, save-stage payload, and post-start panel disappearance tests.
- Full suite exits with no failing tests.
- Build completes `tsc --noEmit && vite build`.

Latest results:
- `npm --prefix frontend run test -- --run src/features/templates/__tests__/TemplateEditor.test.tsx src/features/templates/__tests__/TemplateSelector.test.tsx src/features/workspace/__tests__/WorkspaceShell.test.tsx`: exit `0`, 3 files and 67 tests passed.
- `npm --prefix frontend run test -- --run`: exit `0`, 30 files and 269 tests passed. JSDOM printed existing `Not implemented: navigation to another Document` messages without failing tests.
- `npm --prefix frontend run build`: exit `0`, `tsc --noEmit && vite build` completed.

## Completion Checklist

- [x] Draft page keeps only compact template selection, current template stage editor, and Composer.
- [x] Six fixed stages render as tabs/segmented control.
- [x] Only the selected stage binding editor is visible.
- [x] No user-visible stage role dropdown remains.
- [x] `role_id` is retained in saved full `stage_role_bindings`.
- [x] `Save stage` saves a complete template payload and changes only the current stage binding.
- [x] System template name is read-only.
- [x] User template name supports inline rename.
- [x] System template save uses save-as user template.
- [x] User template save patches/overwrites the current user template.
- [x] Saved template is bound to the current draft session.
- [x] After save and session binding, template panel disappears and Composer remains the active input surface.
- [x] No backend, dependency, lockfile, migration, split spec, archived spec, coordination store, or workspace shell layout foundation changes.
- [x] `impeccable` frontend design gate has been applied and reviewed.
- [x] TDD red/green evidence recorded in final report.
- [x] Review findings resolved or explicitly reported.
- [x] Final verification commands run fresh and results reported.
- [x] `git-delivery-workflow` commit gate run after verification if the diff is coherent.
