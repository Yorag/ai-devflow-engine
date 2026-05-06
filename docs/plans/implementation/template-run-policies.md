# Template Run Policies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Repository override: do not push, merge, rebase, update coordination store, or mark platform/split tasks complete.

**Goal:** Make system templates behaviorally distinct, expose richer common template runtime configuration, and freeze a template-level high-risk tool confirmation bypass policy onto runs started from that template.

**Architecture:** Template editable fields remain explicit scalar contract fields, not an open policy blob. `PipelineTemplateModel` stores template defaults, `TemplateSnapshot` freezes them at run start, `RuntimeLimitSnapshot` applies template runtime limits within platform/hard limits, and `GraphDefinition.stage_contracts[*].runtime_limits` carries the run policy into stage execution. `ToolExecutionGate` consumes a run policy flag that only suppresses high-risk confirmation waits; it does not bypass blocked risks, tool allow-lists, schema validation, workspace boundaries, audit intent, or tool result logging.

**Tech Stack:** Python 3.11+, FastAPI/Pydantic v2, SQLAlchemy, pytest via repo-local Python; React/TypeScript/Vitest under `frontend/`.

---

## Source Trace

- User scope:
  - Do not implement second-step review strategy changes.
  - Make the three system templates meaningfully different.
  - Add more common template configuration than auto-regression and max retry count.
  - Add a template-level default-off "tool use bypass" switch. A run started from that template skips all later high-risk tool confirmation waits.
- Current split specs still describe high-risk tool confirmation as mandatory. This plan treats the user clarification as the accepted product override for this branch and does not edit split specs because current split specs require user review before commit.
- Frontend quality gate: this changes visible template editor controls, so use the existing quiet, dense workspace UI pattern and the global `impeccable` product guidance. Project `PRODUCT.md` / `DESIGN.md` context is unavailable in this worktree.

## Scope

Implement exactly this slice:

- Add template fields:
  - `max_react_iterations_per_stage`
  - `max_tool_calls_per_stage`
  - `skip_high_risk_tool_confirmations`
- Persist and expose those fields through template APIs and configuration packages.
- Differentiate the three system templates through descriptions and runtime defaults.
- Freeze the new fields in `TemplateSnapshot`.
- Apply template runtime limits in `RuntimeLimitSnapshotBuilder`, bounded by current platform settings and hard limits.
- Carry the skip policy into graph stage runtime limits and stage-agent tool execution context.
- Suppress high-risk confirmation waits in `ToolExecutionGate` only when the run policy is true.
- Update deterministic tool-confirmation interrupt emission to honor the same graph/runtime policy when present.
- Update frontend types, draft state, template editor controls, save payloads, mocks, and focused tests.

Do not modify:

- Current split specification documents.
- Acceleration coordination store or final platform/split task statuses.
- Dependency manifests or lock files.
- Second-step review strategy semantics.

## File List

- Modify: `backend/app/db/models/control.py`
- Modify: `backend/app/db/session.py`
- Modify: `backend/app/schemas/template.py`
- Modify: `backend/app/schemas/configuration_package.py`
- Modify: `backend/app/api/routes/templates.py`
- Modify: `backend/app/services/templates.py`
- Modify: `backend/app/services/configuration_packages.py`
- Modify: `backend/app/domain/template_snapshot.py`
- Modify: `backend/app/domain/runtime_limit_snapshot.py`
- Modify: `backend/app/services/graph_compiler.py`
- Modify: `backend/app/runtime/stage_agent.py`
- Modify: `backend/app/runtime/deterministic.py`
- Modify: `backend/app/tools/execution_gate.py`
- Test: `backend/tests/db/test_control_model_boundary.py`
- Test: `backend/tests/schemas/test_control_plane_schemas.py`
- Test: `backend/tests/services/test_template_seed.py`
- Test: `backend/tests/services/test_user_template_service.py`
- Test: `backend/tests/services/test_template_snapshot.py`
- Test: `backend/tests/services/test_runtime_limit_snapshot.py`
- Test: `backend/tests/services/test_graph_compiler.py`
- Test: `backend/tests/services/test_start_first_run.py`
- Test: `backend/tests/tools/test_tool_execution_gate.py`
- Test: `backend/tests/runtime/test_deterministic_interrupts.py`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/features/templates/template-state.ts`
- Modify: `frontend/src/features/templates/TemplateEditor.tsx`
- Modify: `frontend/src/features/workspace/WorkspaceShell.tsx`
- Modify: `frontend/src/mocks/fixtures.ts`
- Modify: `frontend/src/mocks/handlers.ts`
- Test: `frontend/src/features/templates/__tests__/TemplateEditor.test.tsx`
- Test: `frontend/src/features/templates/__tests__/TemplateSelector.test.tsx`
- Test: `frontend/src/features/workspace/__tests__/WorkspaceShell.test.tsx`
- Test: `frontend/src/api/__tests__/client.test.ts`
- Test: `frontend/src/api/__tests__/openapi-compat.test.ts`

## Subagent Execution Boundary

Implementer subagents:

- Model: `gpt-5.5`
- Reasoning effort: `xhigh`
- Must use `superpowers:test-driven-development`: write failing tests, run them red, implement, rerun green.
- Must not run Git write commands, install dependencies, edit lock files, delete/move files, update coordination store, or change split specs.

Planned delegation:

- Frontend implementer owns only `frontend/src/api/types.ts`, `frontend/src/features/templates/*`, `frontend/src/features/workspace/WorkspaceShell.tsx`, `frontend/src/mocks/*`, and the listed frontend tests.
- Main agent owns backend contracts, runtime behavior, implementation plan updates, final review, final verification, and Git gate.
- Reviewers are read-only and check spec/plan compliance first, then code quality/testing/regression risk.

## TDD Tasks

### Task 1: Template Contract And Persistence

**Files:** backend model, schema, API route mapper, template service, configuration package service, DB/schema/template tests.

- [x] Write failing backend tests proving:
  - template read/write schemas require and expose the three new fields with `extra="forbid"`;
  - `PipelineTemplateModel` stores the three fields;
  - save-as and patch persist them and audit metadata contains them;
  - config package import/export round-trips them.
- [x] Run:
  - `C:\Users\lkw\Desktop\github\agent-project\ai-devflow-engine\.venv\Scripts\python.exe -m pytest backend/tests/db/test_control_model_boundary.py backend/tests/schemas/test_control_plane_schemas.py backend/tests/services/test_template_seed.py backend/tests/services/test_user_template_service.py -q`
  - Expected red: assertions fail because fields are missing from schemas/models/service payloads.
- [x] Add SQLAlchemy columns with defaults and SQLite control-schema upgrade backfill:
  - `max_react_iterations_per_stage INTEGER NOT NULL DEFAULT 30`
  - `max_tool_calls_per_stage INTEGER NOT NULL DEFAULT 80`
  - `skip_high_risk_tool_confirmations BOOLEAN NOT NULL DEFAULT 0`
- [x] Add fields to template and configuration package schemas.
- [x] Update route mapping, save-as, patch, seed, audit metadata, config package serialization and import.
- [x] Rerun the focused backend tests until green.

### Task 2: Distinct System Templates

**Files:** `backend/app/services/templates.py`, seed/API tests.

- [x] Write failing tests proving the three system templates have non-empty distinct descriptions and distinct runtime defaults.
- [x] Run:
  - `C:\Users\lkw\Desktop\github\agent-project\ai-devflow-engine\.venv\Scripts\python.exe -m pytest backend/tests/services/test_template_seed.py backend/tests/api/test_template_provider_seed_api.py -q`
  - Expected red: descriptions are `None` and runtime defaults are mostly identical.
- [x] Update `TEMPLATE_SEEDS`:
  - Bugfix: defect isolation/regression focus, conservative limits.
  - Feature: balanced feature delivery, higher tool budget.
  - Refactor: behavior-preserving focus, moderate limits and strict confirmation default.
  - Keep `skip_high_risk_tool_confirmations=False` for all system templates.
- [x] Rerun focused seed/API tests until green.

### Task 3: Run Snapshot And Graph Policy

**Files:** template snapshot, runtime limit snapshot, graph compiler, run-start tests.

- [x] Write failing tests proving:
  - `TemplateSnapshot` freezes the three new template fields;
  - `RuntimeLimitSnapshotBuilder` overrides ReAct and tool-call limits from template after validating against current platform/hard limits;
  - `GraphDefinition.stage_contracts[*].runtime_limits` carries the effective limits and `skip_high_risk_tool_confirmations`;
  - first run startup persists graph/runtime refs that contain these run-start values.
- [x] Run:
  - `C:\Users\lkw\Desktop\github\agent-project\ai-devflow-engine\.venv\Scripts\python.exe -m pytest backend/tests/services/test_template_snapshot.py backend/tests/services/test_runtime_limit_snapshot.py backend/tests/services/test_graph_compiler.py backend/tests/services/test_start_first_run.py -q`
  - Expected red: new snapshot and graph fields are absent.
- [x] Add strict fields and builder validators to `TemplateSnapshot`.
- [x] Extend `RuntimeLimitSnapshotBuilder` with bounded template overrides for ReAct/tool-call limits.
- [x] Add policy propagation in `GraphCompiler._build_stage_contracts`.
- [x] Rerun focused tests until green.

### Task 4: Tool Confirmation Bypass

**Files:** tool execution gate, stage agent runtime, deterministic runtime, tool/runtime tests.

- [x] Write failing tests proving:
  - high-risk tools execute without creating a confirmation request when `skip_high_risk_tool_confirmations=True`;
  - blocked risk stays blocked even when skip is true;
  - normal high-risk path still waits when skip is false;
  - stage agent passes graph runtime policy into `ToolExecutionContext`;
  - deterministic tool-confirmation interrupt is suppressed when the graph runtime policy says skip.
- [x] Run:
  - `C:\Users\lkw\Desktop\github\agent-project\ai-devflow-engine\.venv\Scripts\python.exe -m pytest backend/tests/tools/test_tool_execution_gate.py backend/tests/runtime/test_stage_agent_runtime.py backend/tests/runtime/test_deterministic_interrupts.py -q`
  - Expected red: high-risk tools still enter waiting confirmation.
- [x] Add `skip_high_risk_tool_confirmations: bool = False` to `ToolExecutionContext`.
- [x] Populate it from `stage_contract.runtime_limits` in `StageAgentRuntime.execute_tool_decision`.
- [x] In `_validate_risk_confirmation`, check blocked risk first, then return `None` for high-risk confirmation waits when skip is true.
- [x] Do not create `ToolConfirmationRequestModel` for skipped waits.
- [x] Update deterministic interrupt emission to skip tool-confirmation fixture interrupts when the graph/runtime policy is true.
- [x] Rerun focused tests until green.

### Task 5: Frontend Template Editor

**Files:** frontend types, template state, editor, workspace shell, mocks, frontend tests.

- [x] Write failing frontend tests proving:
  - common template config renders controls for ReAct iterations, tool calls, and high-risk confirmation skip;
  - toggling/saving sends the new fields in payloads;
  - system template selector surfaces distinct descriptions;
  - mocks validate and persist the new fields.
- [x] Run:
  - `npm --prefix frontend run test -- --run src/features/templates/__tests__/TemplateSelector.test.tsx src/features/templates/__tests__/TemplateEditor.test.tsx src/features/workspace/__tests__/WorkspaceShell.test.tsx src/api/__tests__/client.test.ts`
  - Expected red: controls/fields are missing.
- [x] Update TypeScript API types and draft state serialization.
- [x] Add compact editor controls using existing checkbox and number input patterns.
- [x] Update `createTemplateWriteRequest`.
- [x] Update mock fixtures/handlers and API tests.
- [ ] Rerun focused frontend tests until green. Blocked by missing worktree `frontend/node_modules` executables; commands were attempted and failed before test execution.

## Log & Audit Integration

- Template save/patch audit metadata must include the three new configuration fields.
- Run startup audit/log already records `selected_template_id`; product truth for the policy is the frozen template snapshot plus graph/runtime snapshots, not log text.
- Tool confirmation bypass must leave audit intent and tool result logs intact through `ToolExecutionGate`.
- Skipped confirmation must not write `ToolConfirmationRequestModel`, create a graph interrupt, or mutate run/stage/session to `waiting_tool_confirmation`.
- Blocked risks, workspace boundary violations, tool-not-allowed, invalid input schema, audit failures, and tool execution failures keep their current behavior.

## API/OpenAPI Checklist

Template route/schema changes require:

- `PipelineTemplateRead` includes all three new fields.
- `PipelineTemplateWriteRequest` requires all three new fields.
- `/pipeline-templates` list/get/create/patch/save-as response schemas include them.
- OpenAPI compatibility tests cover the new template request/response fields.
- Config package import/export schemas include them.

## Frontend Design Gate

- Baseline: existing product workspace UI, quiet controls, dense layout, no marketing copy.
- Information hierarchy: keep common runtime configuration in the existing global template editor section above stage-specific bindings.
- Controls:
  - number inputs for ReAct iterations and tool-call budget;
  - checkbox/toggle pattern for high-risk confirmation skip;
  - existing auto-regression checkbox and retry input remain.
- Responsive behavior: existing grid should collapse without overflow under narrow widths.
- Accessibility: every new input has a stable label and keeps native keyboard/focus behavior.
- Copy: labels should describe the saved behavior directly; no long in-app explanation blocks.

## Final Verification

Run fresh before any completion claim:

- `C:\Users\lkw\Desktop\github\agent-project\ai-devflow-engine\.venv\Scripts\python.exe -m pytest backend/tests/db/test_control_model_boundary.py backend/tests/schemas/test_control_plane_schemas.py backend/tests/services/test_template_seed.py backend/tests/services/test_user_template_service.py backend/tests/services/test_template_snapshot.py backend/tests/services/test_runtime_limit_snapshot.py backend/tests/services/test_graph_compiler.py backend/tests/services/test_start_first_run.py backend/tests/tools/test_tool_execution_gate.py backend/tests/runtime/test_stage_agent_runtime.py backend/tests/runtime/test_deterministic_interrupts.py backend/tests/api/test_template_api.py backend/tests/api/test_template_provider_seed_api.py backend/tests/api/test_openapi_contract.py backend/tests/api/test_configuration_package_api.py backend/tests/services/test_configuration_package_service.py -q`
- `npm --prefix frontend run test -- --run src/features/templates/__tests__/TemplateSelector.test.tsx src/features/templates/__tests__/TemplateEditor.test.tsx src/features/workspace/__tests__/WorkspaceShell.test.tsx src/features/settings/__tests__/SettingsBoundary.test.tsx src/api/__tests__/client.test.ts src/api/__tests__/openapi-compat.test.ts`
- `npm --prefix frontend run build`

After verification, run `git status --short` and `git diff --stat`. If the diff is one coherent slice and verification is fresh, use `git-delivery-workflow` commit gate.

## Execution Notes

- Backend template contract, distinct system template defaults, run snapshots, graph policy propagation, and tool-confirmation bypass are implemented.
- Existing system template rows are refreshed to the current system defaults without reloading role prompt assets when no templates are missing.
- Frontend template editor types, draft state, controls, save payloads, mock fixtures, mock handlers, and focused tests are updated for the new fields.
- Review follow-up fixed:
  - structured `request_tool_confirmation` now honors `skip_high_risk_tool_confirmations=True` by recording a skipped confirmation trace, executing the carried tool payload through the normal tool gate, and continuing the stage instead of waiting;
  - `GraphCompiler` now rejects drift between template and runtime snapshots for `max_auto_regression_retries`, `max_react_iterations_per_stage`, and `max_tool_calls_per_stage`.
- Fresh backend verification passed:
  `C:\Users\lkw\Desktop\github\agent-project\ai-devflow-engine\.venv\Scripts\python.exe -m pytest backend/tests/db/test_control_model_boundary.py backend/tests/schemas/test_control_plane_schemas.py backend/tests/services/test_template_seed.py backend/tests/services/test_user_template_service.py backend/tests/services/test_template_snapshot.py backend/tests/services/test_runtime_limit_snapshot.py backend/tests/services/test_graph_compiler.py backend/tests/services/test_start_first_run.py backend/tests/tools/test_tool_execution_gate.py backend/tests/runtime/test_stage_agent_runtime.py backend/tests/runtime/test_deterministic_interrupts.py backend/tests/api/test_template_api.py backend/tests/api/test_template_provider_seed_api.py backend/tests/api/test_openapi_contract.py backend/tests/api/test_configuration_package_api.py backend/tests/services/test_configuration_package_service.py -q`
  Result: `186 passed in 30.69s`.
- After user approval to install dependencies, `npm --prefix frontend ci` completed from the existing lockfile with `added 155 packages`, `found 0 vulnerabilities`, and no package manifest or lockfile changes.
- Fresh frontend verification passed:
  `npm --prefix frontend run test -- --run src/features/templates/__tests__/TemplateSelector.test.tsx src/features/templates/__tests__/TemplateEditor.test.tsx src/features/workspace/__tests__/WorkspaceShell.test.tsx src/features/settings/__tests__/SettingsBoundary.test.tsx src/api/__tests__/client.test.ts src/api/__tests__/openapi-compat.test.ts`
  Result: `6 passed (6)`, `87 passed (87)`.
- Fresh frontend build passed:
  `npm --prefix frontend run build`
  Result: `tsc --noEmit && vite build`, `135 modules transformed`, built successfully.
