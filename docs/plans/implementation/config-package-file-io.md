# Configuration Package File IO Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Fallback to `superpowers:executing-plans` only if subagent execution cannot be bounded to the allowed files. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace placeholder configuration package import/export actions with real project-scoped JSON download and upload interactions.

**Architecture:** `ConfigurationPackageSettings` remains the only UI owner for file IO. Export calls the existing API, serializes the returned package as stable pretty JSON, creates a temporary Blob URL, and triggers a browser download. Import uses a hidden `.json` file input, reads the selected File with `File.text()`, parses JSON, sends the parsed package to the existing import API, and refreshes DeliveryChannel, Provider, and PipelineTemplate queries after a successful API response.

**Tech Stack:** React 18, TypeScript, TanStack Query, Testing Library, Vitest, browser Blob/File APIs. No new dependencies.

---

## Source Trace

- User request: implement real JSON file interaction for existing `/configuration-package/export` and `/configuration-package/import` APIs.
- Platform plan: `docs/plans/function-one-platform/02-control-plane-and-workspace-shell.md` F2.4 requires the settings import/export page to call the F2.1 configuration package client, show import summaries, affected objects and field errors, and refresh DeliveryChannel, Provider and template data after import.
- Backend spec: `docs/specs/function-one-backend-engine-design-v1.md` section `2.2.4 ConfigurationPackage` defines project-scoped user-visible configuration packages and explicitly excludes platform runtime settings, real secrets, prompt assets, snapshots, logs and audit bodies.
- API contract is already implemented and must not change: `frontend/src/api/configuration-package.ts` calls `GET /api/projects/{projectId}/configuration-package/export` and `POST /api/projects/{projectId}/configuration-package/import`.

Acceleration claim/store, lane ownership, coordination DB and integration checkpoint gates are N/A for this main-based stabilization slice.

## Execution Notes

- TDD tests were added before implementation for Blob JSON download, local JSON file upload, invalid JSON parsing, missing project, invalid file type, visible `Upload JSON` trigger, API field errors and query invalidation behavior.
- Initial focused RED/GREEN verification was blocked because `frontend/node_modules` was absent. After dependencies were restored, the focused settings command passed.
- Spec compliance review found one Important issue: empty MIME files without `.json` extension could bypass the invalid file type guard. The implementation now requires the selected filename to end in `.json`, and the invalid-file test uses an empty MIME `.txt` file to cover that case.
- Code quality review found no Critical or Important issues. Minor coverage gaps for the visible upload button and field-error/no-refresh path were addressed with focused tests. The earlier Blob fallback and empty-MIME validation comments are no longer applicable after implementation changes.
- Final verification after dependencies were restored:
  - `npm --prefix frontend run test -- --run src/features/settings/__tests__/SettingsBoundary.test.tsx src/features/settings/__tests__/SettingsModal.test.tsx`: 2 files passed, 27 tests passed.
  - `npm --prefix frontend run test -- --run`: 29 files passed, 256 tests passed.
  - `npm --prefix frontend run build`: TypeScript and Vite build passed.
  - The Vitest runs print jsdom `Not implemented: navigation to another Document` messages from simulated anchor downloads, but both commands exit 0.

## Files

- Modify: `frontend/src/features/settings/ConfigurationPackageSettings.tsx`
- Modify: `frontend/src/features/settings/__tests__/SettingsBoundary.test.tsx`
- Modify: `frontend/src/features/settings/__tests__/SettingsModal.test.tsx`
- Modify: `frontend/src/api/__tests__/client.test.ts`
- Modify: `frontend/src/styles/global.css`
- Modify: `docs/plans/implementation/config-package-file-io.md`

Do not modify backend API contracts, configuration package schema, lock files, package manifests, or template editing pages.

## Frontend Design Gate

Project register: product UI. The settings dialog is a task surface used by developers or operators while configuring a project, usually on a desktop workstation where clarity and predictable controls matter more than visual novelty.

Inherited tone: restrained, professional workspace UI with dense but readable settings content. Use existing `settings-section`, `settings-actions`, `settings-result`, `settings-inline-error`, and `workspace-button` vocabulary. Do not add decorative cards, marketing copy, gradients, or new color themes.

Interaction strategy:
- Primary mental model is `Download JSON` and `Upload JSON`.
- Export is a direct command button; it does not display raw package data as the main outcome.
- Import uses a standard file picker and never asks for or implies arbitrary local path access.
- No project selected, invalid file type, JSON parse failure, API field errors, loading, success and no-changed-object states all stay inside the import/export panel.
- Hidden file input remains keyboard reachable through the visible Upload JSON button and has an accessible label.

Post-implementation review checklist:
- Buttons have stable labels, disabled states and no text overflow.
- Long project names, file names, field names and object ids wrap without layout breakage.
- Error copy names the problem without exposing internal backend fields beyond returned field errors.
- The panel remains usable on narrow settings dialog widths using wrapping action rows and compact result sections.

## Task 1: Export Downloads API JSON

**Files:**
- Modify: `frontend/src/features/settings/__tests__/SettingsModal.test.tsx`
- Modify: `frontend/src/features/settings/ConfigurationPackageSettings.tsx`

- [ ] **Step 1: Write the failing export download test**

Add a test near the existing configuration package settings tests in `SettingsModal.test.tsx`:

```tsx
it("downloads exported configuration packages as stable JSON files", async () => {
  const project = createSettingsProject();
  const exportedPackage: ConfigurationPackageExport = {
    export_id: "export-file-test",
    exported_at: "2026-05-06T11:22:33.000Z",
    package_schema_version: "function-one-config-v1",
    scope: { scope_type: "project", project_id: project.project_id },
    providers: [],
    delivery_channels: [],
    pipeline_templates: [],
  };
  const createObjectUrl = vi.fn(() => "blob:config-export");
  const revokeObjectUrl = vi.fn();
  const clickSpy = vi.fn();
  const originalCreateElement = document.createElement.bind(document);

  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: createObjectUrl,
    revokeObjectURL: revokeObjectUrl,
  });
  vi.spyOn(document, "createElement").mockImplementation((tagName) => {
    const element = originalCreateElement(tagName);

    if (tagName.toLowerCase() === "a") {
      vi.spyOn(element, "click").mockImplementation(clickSpy);
    }

    return element;
  });

  renderSettingsModalWithRequest(project, async (input) => {
    const path = normalizePath(input);

    if (path.endsWith("/configuration-package/export")) {
      return jsonResponse(exportedPackage);
    }

    if (path.endsWith("/delivery-channel")) {
      return jsonResponse(createDeliveryChannel(project.project_id));
    }

    return jsonResponse([]);
  });

  const dialog = screen.getByRole("dialog", { name: "Settings" });
  fireEvent.click(within(dialog).getByRole("tab", { name: "导入导出" }));
  fireEvent.click(await within(dialog).findByRole("button", { name: "Download JSON" }));

  await waitFor(() => {
    expect(createObjectUrl).toHaveBeenCalledTimes(1);
  });
  const blob = createObjectUrl.mock.calls[0][0] as Blob;
  await expect(blob.text()).resolves.toBe(`${JSON.stringify(exportedPackage, null, 2)}\n`);
  expect(blob.type).toBe("application/json");
  expect(clickSpy).toHaveBeenCalledTimes(1);
  expect(revokeObjectUrl).toHaveBeenCalledWith("blob:config-export");
  expect(await within(dialog).findByText(/Downloaded function-one-config-Settings-Test-Project-/u)).toBeTruthy();
});
```

- [ ] **Step 2: Run the focused test to verify RED**

Run:

```powershell
npm --prefix frontend run test -- --run src/features/settings/__tests__/SettingsModal.test.tsx
```

Expected: FAIL because the visible button is still `Export configuration package`, no Blob URL is created, and no download click occurs.

- [ ] **Step 3: Implement minimal export file download**

In `ConfigurationPackageSettings.tsx`:
- Add `isExporting`, `statusMessage` and `errorMessage` state.
- Add `buildConfigurationPackageFileName(project)` that returns `function-one-config-<sanitized-name-or-id>-<YYYYMMDD-HHmmss>.json`.
- Use project name when present, otherwise project id. Sanitize to alphanumeric, dot, underscore and hyphen; collapse other characters to `-`; trim leading/trailing hyphens; fallback to `project`.
- Add `downloadJsonFile(fileName, data)` that creates `new Blob([JSON.stringify(data, null, 2), "\n"], { type: "application/json" })`, calls `URL.createObjectURL`, clicks a temporary `<a download={fileName}>`, and revokes the object URL.
- Change the export button label to `Download JSON`.
- If no project is selected, show `Select a project before downloading JSON.` and do not call the API.
- After success, keep the existing export summary and show `Downloaded <fileName>.`

- [ ] **Step 4: Run focused test to verify GREEN**

Run:

```powershell
npm --prefix frontend run test -- --run src/features/settings/__tests__/SettingsModal.test.tsx
```

Expected: PASS for the new export test and existing settings tests, except later tests may still need label updates from `Export configuration package` to `Download JSON`.

## Task 2: Import Reads Local JSON File

**Files:**
- Modify: `frontend/src/features/settings/__tests__/SettingsModal.test.tsx`
- Modify: `frontend/src/features/settings/ConfigurationPackageSettings.tsx`
- Modify: `frontend/src/styles/global.css`

- [ ] **Step 1: Write the failing upload test**

Add a test near `invalidates project configuration queries after successful package import`:

```tsx
it("uploads a selected JSON configuration package file to the import API", async () => {
  const project = createSettingsProject();
  const importCalls: unknown[] = [];
  const packageBody = {
    package_schema_version: "function-one-config-v1",
    scope: { scope_type: "project", project_id: project.project_id },
    providers: [],
    delivery_channels: [],
    pipeline_templates: [],
  };

  renderSettingsModalWithRequest(project, async (input, init) => {
    const path = normalizePath(input);

    if (path.endsWith("/configuration-package/import")) {
      importCalls.push(JSON.parse(String(init?.body)));
      return jsonResponse({
        package_id: "uploaded-import",
        summary: "Uploaded configuration package.",
        changed_objects: [
          {
            object_type: "provider",
            object_id: "provider-uploaded",
            action: "updated",
          },
        ],
      } satisfies ConfigurationPackageImportResult);
    }

    if (path.endsWith("/delivery-channel")) {
      return jsonResponse(createDeliveryChannel(project.project_id));
    }

    return jsonResponse([]);
  });

  const dialog = screen.getByRole("dialog", { name: "Settings" });
  fireEvent.click(within(dialog).getByRole("tab", { name: "导入导出" }));
  const fileInput = within(dialog).getByLabelText("Configuration package JSON file");
  const file = new File([JSON.stringify(packageBody)], "config-package.json", {
    type: "application/json",
  });

  fireEvent.change(fileInput, { target: { files: [file] } });

  expect(await within(dialog).findByText("Uploaded configuration package.")).toBeTruthy();
  expect(within(dialog).getByText(/provider-uploaded/u)).toBeTruthy();
  expect(importCalls).toEqual([packageBody]);
});
```

- [ ] **Step 2: Run focused test to verify RED**

Run:

```powershell
npm --prefix frontend run test -- --run src/features/settings/__tests__/SettingsModal.test.tsx
```

Expected: FAIL because there is no file input, current import sends a hard-coded empty package, and no selected file is read.

- [ ] **Step 3: Implement JSON file upload**

In `ConfigurationPackageSettings.tsx`:
- Add `useRef<HTMLInputElement | null>()` for the hidden file input.
- Change the import button label to `Upload JSON`; clicking it opens `fileInputRef.current?.click()`.
- Render a visually hidden `<input type="file" accept="application/json,.json" aria-label="Configuration package JSON file">`.
- Add `handleImportFileChange(event)`:
  - If no project, show `Select a project before uploading JSON.` and reset the input value.
  - If no file, show `Choose a JSON file before uploading.`.
  - If the selected file name does not end in `.json`, show `Choose a .json configuration package file.` and do not call import API. Treat MIME type only as picker metadata; do not let an empty or `application/json` MIME type bypass the `.json` extension rule.
  - Read text with `await file.text()`.
  - Parse with `JSON.parse`; on parse failure show `JSON parse failed: <message>` and do not call import API.
  - Pass the parsed value as `ConfigurationPackageImportRequest` to `importProjectConfigurationPackage`.
  - Set `importResult`.
  - Invalidate `apiQueryKeys.projectDeliveryChannel(project.project_id)`, `apiQueryKeys.providers`, and `apiQueryKeys.pipelineTemplates` with `refetchType: "all"`.
  - Reset the input value so selecting the same file again fires `change`.
- Keep field errors and changed objects visible after the import API response.

- [ ] **Step 4: Add compact file IO styles**

In `global.css`, add small styles for a hidden file input, status rows and changed object list:

```css
.settings-file-input {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  white-space: nowrap;
}

.settings-result__list {
  display: grid;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.settings-result__list li {
  min-width: 0;
  color: var(--text-muted);
  font-size: 0.82rem;
  line-height: 1.45;
  overflow-wrap: anywhere;
}
```

- [ ] **Step 5: Run focused test to verify GREEN**

Run:

```powershell
npm --prefix frontend run test -- --run src/features/settings/__tests__/SettingsModal.test.tsx
```

Expected: PASS after updating existing tests to use `Download JSON` and `Upload JSON` labels.

## Task 3: Error States and Boundary Coverage

**Files:**
- Modify: `frontend/src/features/settings/__tests__/SettingsModal.test.tsx`
- Modify: `frontend/src/features/settings/__tests__/SettingsBoundary.test.tsx`
- Modify: `frontend/src/api/__tests__/client.test.ts`
- Modify: `frontend/src/features/settings/ConfigurationPackageSettings.tsx`

- [ ] **Step 1: Write failing invalid JSON test**

Add:

```tsx
it("shows a JSON parse error and does not call import for invalid JSON files", async () => {
  const project = createSettingsProject();
  const importFetcher = vi.fn(async () =>
    jsonResponse({ summary: "Should not import." }),
  );

  renderSettingsModalWithRequest(project, async (input, init) => {
    const path = normalizePath(input);

    if (path.endsWith("/configuration-package/import")) {
      return importFetcher(input, init);
    }

    if (path.endsWith("/delivery-channel")) {
      return jsonResponse(createDeliveryChannel(project.project_id));
    }

    return jsonResponse([]);
  });

  const dialog = screen.getByRole("dialog", { name: "Settings" });
  fireEvent.click(within(dialog).getByRole("tab", { name: "导入导出" }));
  const fileInput = within(dialog).getByLabelText("Configuration package JSON file");
  const file = new File(["{ invalid json"], "config-package.json", {
    type: "application/json",
  });

  fireEvent.change(fileInput, { target: { files: [file] } });

  expect(await within(dialog).findByText(/JSON parse failed:/u)).toBeTruthy();
  expect(importFetcher).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Write failing no project and invalid file tests**

Add component-level tests:

```tsx
it("shows project selection and file type errors before using package APIs", async () => {
  const fetcher = vi.fn(async () => jsonResponse({}));

  render(
    <QueryClientProvider client={createQueryClient()}>
      <ConfigurationPackageSettings project={null} request={{ fetcher }} />
    </QueryClientProvider>,
  );

  fireEvent.click(screen.getByRole("button", { name: "Download JSON" }));
  expect(await screen.findByText("Select a project before downloading JSON.")).toBeTruthy();
  expect(fetcher).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: "Upload JSON" }));
  const fileInput = screen.getByLabelText("Configuration package JSON file");
  fireEvent.change(fileInput, {
    target: {
      files: [
        new File(["{}"], "config-package.txt", {
          type: "text/plain",
        }),
      ],
    },
  });

  expect(await screen.findByText("Select a project before uploading JSON.")).toBeTruthy();
  expect(fetcher).not.toHaveBeenCalled();
});

it("rejects non-JSON package files before reading import content", async () => {
  const project = createSettingsProject();
  const importFetcher = vi.fn(async () => jsonResponse({ summary: "Imported." }));

  renderSettingsModalWithRequest(project, async (input, init) => {
    const path = normalizePath(input);

    if (path.endsWith("/configuration-package/import")) {
      return importFetcher(input, init);
    }

    if (path.endsWith("/delivery-channel")) {
      return jsonResponse(createDeliveryChannel(project.project_id));
    }

    return jsonResponse([]);
  });

  const dialog = screen.getByRole("dialog", { name: "Settings" });
  fireEvent.click(within(dialog).getByRole("tab", { name: "导入导出" }));
  fireEvent.change(within(dialog).getByLabelText("Configuration package JSON file"), {
    target: {
      files: [
        new File(["{}"], "config-package.txt", {
          type: "text/plain",
        }),
      ],
    },
  });

  expect(await within(dialog).findByText("Choose a .json configuration package file.")).toBeTruthy();
  expect(importFetcher).not.toHaveBeenCalled();
});
```

- [ ] **Step 3: Update existing boundary and client tests**

Update button labels in `SettingsBoundary.test.tsx`, `SettingsModal.test.tsx`, and `client.test.ts` expectations where they refer to `Export configuration package` or `Import configuration package`. The API client path expectations should continue to assert the canonical GET/POST API paths and should not introduce any browser file IO helper into `frontend/src/api`.

- [ ] **Step 4: Run focused tests to verify RED/GREEN**

Run:

```powershell
npm --prefix frontend run test -- --run src/features/settings/__tests__/SettingsBoundary.test.tsx src/features/settings/__tests__/SettingsModal.test.tsx
```

Expected after implementation: PASS, including invalid JSON, invalid file type, no project, changed objects, field errors, and query invalidation coverage.

## Task 4: Review and Full Verification

**Files:**
- Review all changed files.

- [ ] **Step 1: Spec / plan compliance review**

Reviewer input:
- Requirements in this plan and the user request.
- Diff for `ConfigurationPackageSettings.tsx`, settings tests, client tests, CSS and this plan.

Review questions:
- Does export call the existing API and download the returned JSON as `.json`?
- Is the filename stable and based on project name or id plus `YYYYMMDD-HHmmss`?
- Does import use a file chooser, `File.text()`, `JSON.parse`, and existing import API?
- Does successful import refresh providers, delivery channel and pipeline templates?
- Are changed objects, field errors, parse errors, missing project and invalid file type visible?
- Does UI copy use `Download JSON / Upload JSON` without path-based local file language?
- Are backend API contract, schema, manifests, lockfiles and template editing untouched?

- [ ] **Step 2: Code quality / regression review**

Review questions:
- Are Blob URLs always revoked?
- Is same-file re-upload possible after input reset?
- Are async loading states race-safe enough for this component scope?
- Are test mocks verifying real component behavior rather than only mock behavior?
- Does CSS follow existing settings vocabulary, avoid nested card patterns and preserve narrow layouts?

- [ ] **Step 3: Run required verification**

Run:

```powershell
npm --prefix frontend run test -- --run src/features/settings/__tests__/SettingsBoundary.test.tsx src/features/settings/__tests__/SettingsModal.test.tsx
npm --prefix frontend run test -- --run
npm --prefix frontend run build
```

Expected: all commands exit 0.

- [ ] **Step 4: Commit gate**

After fresh verification, use `git-delivery-workflow` commit gate. This slice can be committed directly if the diff is coherent, contains no spec document from the current split spec set, and verification evidence is fresh.

Proposed commit subject:

```text
fix(settings): use JSON files for config package import
```
