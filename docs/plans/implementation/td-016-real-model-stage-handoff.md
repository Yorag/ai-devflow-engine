# TD-016 Real-Model Stage Handoff Cleanup Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` for implementation tasks with disjoint write sets, or `superpowers:executing-plans` for inline execution when task boundaries are coupled. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the real-model feature-one chain execute a simple repository website text change through the formal stage artifacts instead of stage-local exploratory behavior.

**Architecture:** Treat `SolutionDesignArtifact.implementation_plan` as the single executable handoff contract for downstream stages. Code generation, test generation/execution, and review consume the persisted plan, requirement artifact, and tool evidence through Context Management; they do not reconstruct their own task plan or rely on demo-specific runtime rewrites. Workspace tools, risk classification, bash allowlisting, and prompt guidance share one verification-command policy.

**Tech Stack:** Python 3.12, FastAPI runtime services, LangGraph stage runner, Pydantic artifacts, repository-local `uv`, pytest, existing workspace tools.

---

## Source Trace

- Debt item: `TD-016` in `docs/plans/technical-debt-cleanup-index.md`.
- Product source: `docs/specs/function-one-product-overview-v1.md` section 7 states `Solution Design` must output an executable task plan for `Code Generation`, `Test Generation & Execution`, and `Code Review`.
- Backend source: `docs/specs/function-one-backend-engine-design-v1.md` sections around `SolutionDesignArtifact`, `CodeGenerationArtifact`, and `TestGenerationExecutionArtifact` require downstream stages to read `SolutionDesignArtifact.implementation_plan`.
- Platform source: `docs/plans/function-one-platform/06-langgraph-provider-context-stage-agent.md` states downstream stages must proceed by stable implementation-plan task ids, order, and dependencies.
- Regression source: `docs/plans/function-one-platform/09-regression-hardening-and-logs.md` states regression hardening must return to the owning slice when earlier stage/tool/runtime semantics are missing, instead of covering gaps with temporary semantics.
- Debug evidence: 2026-05-07 live-model smoke runs for the homepage heading change repeatedly drifted in `code_generation` and `test_generation_execution`, with test-stage package discovery and bash/grep policy mismatches after solution design completed.

## Boundaries

This is a main-based stabilization cleanup. It is not a split-spec rewrite and it does not re-enable acceleration lane mode.

Allowed write sets are split by task below. Do not modify current split specifications under `docs/specs/`. Do not update coordination store, lock files, dependency manifests, migrations, environment files, or archived design docs.

Do not directly apply `stash@{0}: wip/mixed-live-model-chain-patches-before-td016`. That stash contains both reusable foundations and rejected demo-specific fallback logic. Recover individual hunks only after reading the task instructions and tests.

Rejected patterns:

- Hardcoded parsing of Chinese `把 <h1>... 改成 <h1>...` inside `StageAgentRuntime`.
- Runtime-created implementation plans that silently replace missing `SolutionDesignArtifact.implementation_plan`.
- Prompt instructions that mention only `homepage`, `landing page`, or `frontend/src` as global recovery policy.
- Risk classifier allowing commands that `BashTool` cannot execute.
- Test stage narrowing that forces all verification through bash after any source read.

## File Map

- Modify: `backend/app/context/source_resolver.py`
  - Read prior stage `output_snapshot` artifacts as structured stage outputs.
  - Surface `SolutionDesignArtifact.implementation_plan` task ids, target files/modules, verification commands, and dependency order to downstream stages.
- Modify: `backend/app/context/builder.py`
  - Pass user message sources and prior artifact sources into `ContextSourceResolver`.
- Modify: `backend/app/services/runtime_dispatch.py`
  - Build a real workspace tool registry for production stage execution.
  - Pass user messages and refreshed stage artifacts into each stage runner.
- Modify: `backend/app/workspace/manager.py`
  - Create a safe project snapshot in each run workspace from git-tracked project files or a credential-denylisted fallback.
- Modify/Create: `backend/app/workspace/verification_policy.py`
  - Centralize verification command classification for bash allowlist and risk classifier.
- Modify: `backend/app/workspace/bash.py`
  - Use `VerificationCommandPolicy` for verification commands instead of maintaining a divergent shell allowlist.
- Modify: `backend/app/tools/risk.py`
  - Use `VerificationCommandPolicy` for read-only verification command classification.
- Modify: `backend/app/runtime/agent_decision.py`
  - Add stage-specific response schema narrowing without permissive artifact shorthands that hide missing fields.
- Modify: `backend/app/runtime/stage_agent.py`
  - Validate downstream artifact evidence generically.
  - Reject missing side-effect evidence with structured repair.
  - Do not mutate tool inputs from user-message regexes.
- Modify: `backend/app/prompts/assets/stages/solution_design.md`
  - Require executable `implementation_plan` with stable task ids, target files/modules, verification commands, dependencies, and risk handling.
- Modify: `backend/app/prompts/assets/stages/code_generation.md`
  - Require execution of implementation-plan tasks and artifact evidence from successful edit tools.
- Modify: `backend/app/prompts/assets/stages/test_generation_execution.md`
  - Require execution of plan verification commands or explicit test-gap reporting tied to task ids.
- Modify: `backend/app/prompts/assets/stages/code_review.md`
  - Require review against implementation-plan task ids, code evidence, and test evidence.
- Test: `backend/tests/context/test_context_source_resolver.py`
- Test: `backend/tests/runtime/test_agent_decision_parser.py`
- Test: `backend/tests/runtime/test_stage_agent_runtime.py`
- Test: `backend/tests/services/test_runtime_execution_service.py`
- Test: `backend/tests/tools/test_tool_risk_classifier.py`
- Test: `backend/tests/workspace/test_workspace_bash.py`
- Test: `backend/tests/workspace/test_workspace_manager.py`
- Create: `backend/tests/e2e/test_real_model_stage_handoff_smoke.py`
- Modify: `docs/plans/technical-debt-cleanup-index.md`
- Modify: `docs/plans/implementation/td-016-real-model-stage-handoff.md`

## Task 1: Context Handoff Uses Persisted Stage Outputs

**Files:**
- Modify: `backend/app/context/source_resolver.py`
- Modify: `backend/app/context/builder.py`
- Test: `backend/tests/context/test_context_source_resolver.py`

- [x] **Step 1: Add failing context resolver tests**

Add tests that create `StageArtifactModel` objects with `process.output_snapshot` for `RequirementAnalysisArtifact`, `SolutionDesignArtifact`, and `CodeGenerationArtifact`.

Assertions:

```python
blocks = ContextSourceResolver().resolve_stage_inputs(
    session_id="session-1",
    run_id="run-1",
    stage_run_id="stage-run-code",
    stage_type=StageType.CODE_GENERATION,
    stage_artifacts=(requirement_artifact, solution_artifact),
    user_messages=(),
    allowed_context_run_ids=("run-1",),
    built_at=NOW,
)

summaries = "\n".join(block.summary for block in blocks)
assert "plan_id=plan-1" in summaries
assert "task_id=task-homepage-copy" in summaries
assert "target_files=frontend/src/pages/HomePage.tsx" in summaries
assert "verification_commands=npm --prefix frontend run build" in summaries
assert "RequirementAnalysisArtifact" in summaries
```

Add a second test for `StageType.TEST_GENERATION_EXECUTION` asserting it receives `SolutionDesignArtifact.implementation_plan` and `CodeGenerationArtifact.file_edit_trace_refs`.

- [x] **Step 2: Verify RED**

Run:

```powershell
uv run python -m pytest backend/tests/context/test_context_source_resolver.py::test_code_generation_receives_solution_plan_from_output_snapshot backend/tests/context/test_context_source_resolver.py::test_test_execution_receives_plan_and_code_generation_output -q
```

Expected: fail because current resolver reads `process.solution_design_artifact` only and does not surface prior structured outputs from `output_snapshot`.

- [x] **Step 3: Implement structured output extraction**

Update `ContextSourceResolver` so it:

- Parses `process["output_snapshot"]` when `output_snapshot["artifact_type"]` is one of the structured artifacts.
- Keeps existing `process["solution_design_artifact"]` support for deterministic historical fixtures.
- Emits trusted input blocks for prior structured artifacts by stage:
  - `code_generation`: `RequirementAnalysisArtifact`, `SolutionDesignArtifact`
  - `test_generation_execution`: `RequirementAnalysisArtifact`, `SolutionDesignArtifact`, `CodeGenerationArtifact`
  - `code_review`: `RequirementAnalysisArtifact`, `SolutionDesignArtifact`, `CodeGenerationArtifact`, `TestGenerationExecutionArtifact`
  - `delivery_integration`: code, test, and review outputs
- Summarizes implementation-plan task ids, target files/modules, verification commands, dependencies, and risks without including raw model prompt text.

- [x] **Step 4: Verify GREEN**

Run:

```powershell
uv run python -m pytest backend/tests/context/test_context_source_resolver.py -q
```

Expected: all context source resolver tests pass.

## Task 2: Production Runtime Uses Real Workspace Tools Safely

**Files:**
- Modify: `backend/app/workspace/manager.py`
- Modify: `backend/app/services/runtime_dispatch.py`
- Test: `backend/tests/workspace/test_workspace_manager.py`
- Test: `backend/tests/services/test_runtime_execution_service.py`

- [x] **Step 1: Add failing workspace snapshot tests**

Add `test_create_for_run_copies_git_tracked_project_files_without_credentials`:

```python
(project_root / "frontend/src/pages").mkdir(parents=True)
(project_root / "frontend/src/pages/HomePage.tsx").write_text("export const title = 'old';\n", encoding="utf-8")
(project_root / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
(project_root / ".npmrc").write_text("//registry.example/:_authToken=secret\n", encoding="utf-8")
(project_root / "secrets").mkdir()
(project_root / "secrets/token.txt").write_text("secret\n", encoding="utf-8")

workspace = manager.create_for_run(...)

assert (workspace.root / "frontend/src/pages/HomePage.tsx").is_file()
assert not (workspace.root / ".env").exists()
assert not (workspace.root / ".npmrc").exists()
assert not (workspace.root / "secrets/token.txt").exists()
assert not (workspace.root / ".runtime").exists()
```

Add a runtime dispatch test asserting the default stage runner receives a registry with `read_file`, `glob`, `grep`, `edit_file`, `write_file`, and `bash` for stages that allow them.

- [x] **Step 2: Verify RED**

Run:

```powershell
uv run python -m pytest backend/tests/workspace/test_workspace_manager.py::test_create_for_run_copies_git_tracked_project_files_without_credentials backend/tests/services/test_runtime_execution_service.py::test_default_stage_runner_uses_workspace_tool_registry -q
```

Expected: fail because current workspace creation does not copy project files and production dispatch uses an empty `ToolRegistry`.

- [x] **Step 3: Implement safe project snapshot**

Implement workspace snapshot creation inside `WorkspaceManager.create_for_run()`:

- Prefer git-tracked files from `git ls-files -z` when `default_project_root/.git` exists.
- Fall back to recursive copy with a denylist when git metadata is unavailable.
- Always exclude `.git`, `.runtime`, workspace root, `.venv`, `node_modules`, `dist`, `build`, `coverage`, `__pycache__`.
- Always exclude credential paths: `.env`, `.env.*`, `.npmrc`, `.pypirc`, `.netrc`, `secrets/`, `.ssh/`, `*.pem`, `*.key`, `id_rsa`, `id_ed25519`.
- Copy files with `copy2()` and preserve relative paths.

- [x] **Step 4: Wire production workspace tool registry**

Update `RuntimeExecutionService` factory to:

- Resolve or create the run workspace.
- Build `ToolRegistry` with `FileReadTool`, `GlobTool`, `GrepTool`, `FileWriteTool`, `FileEditTool`, and `BashTool`.
- Pass workspace boundary and audit recorder into `StageAgentRuntime`.

Do not import deterministic runtime or test harness code into this path.

- [x] **Step 5: Verify GREEN**

Run:

```powershell
uv run python -m pytest backend/tests/workspace/test_workspace_manager.py backend/tests/services/test_runtime_execution_service.py -q
```

Expected: workspace and runtime execution service tests pass.

## Task 3: Stage Response Schema And Clarification Boundaries

**Files:**
- Modify: `backend/app/runtime/agent_decision.py`
- Modify: `backend/app/services/runtime_dispatch.py`
- Test: `backend/tests/runtime/test_agent_decision_parser.py`
- Test: `backend/tests/services/test_runtime_execution_service.py`

- [x] **Step 1: Add failing parser schema tests**

Add tests proving:

- `agent_decision_response_schema(artifact_type="CodeGenerationArtifact")` requires CodeGeneration artifact fields inside `artifact_payload`.
- `agent_decision_response_schema(allowed_decision_types=(AgentDecisionType.SUBMIT_STAGE_ARTIFACT, AgentDecisionType.FAIL_STAGE))` does not include `request_clarification`.
- `request_clarification` is rejected for stage contracts without `clarification_allowed` or `can_request_clarification`.

- [x] **Step 2: Verify RED**

Run:

```powershell
uv run python -m pytest backend/tests/runtime/test_agent_decision_parser.py::test_response_schema_can_be_limited_to_current_artifact_type backend/tests/runtime/test_agent_decision_parser.py::test_response_schema_can_remove_clarification_for_downstream_stages backend/tests/runtime/test_agent_decision_parser.py::test_parser_rejects_structured_clarification_when_stage_disallows_it -q
```

Expected: fail until schema narrowing and structured clarification validation are implemented.

- [x] **Step 3: Implement schema narrowing**

Update `agent_decision_response_schema()` to accept:

```python
def agent_decision_response_schema(
    *,
    artifact_type: str | None = None,
    allowed_decision_types: Sequence[AgentDecisionType | str] | None = None,
) -> JsonObject:
    ...
```

Use existing `_ARTIFACT_REQUIRED_FIELDS` for artifact-specific `artifact_payload` schemas. Do not add permissive artifact shorthand normalization that turns missing `decision_type` outputs into accepted artifacts.

- [x] **Step 4: Wire stage-specific schema in runtime dispatch**

Update `_RuntimeDispatchStageRunner` so:

- `Requirement Analysis` may request clarification.
- `Solution Design`, `Code Generation`, `Test Generation & Execution`, `Code Review`, and `Delivery Integration` only expose decision types allowed by their stage contracts.
- `structured_artifact_required` from `GraphDefinition.stage_contracts` drives the artifact type passed to `agent_decision_response_schema()`.

- [x] **Step 5: Verify GREEN**

Run:

```powershell
uv run python -m pytest backend/tests/runtime/test_agent_decision_parser.py backend/tests/services/test_runtime_execution_service.py -q
```

Expected: parser and runtime dispatch tests pass.

## Task 4: Generic Evidence Enforcement In Stage Agent

**Files:**
- Modify: `backend/app/runtime/stage_agent.py`
- Test: `backend/tests/runtime/test_stage_agent_runtime.py`

- [x] **Step 1: Add failing evidence tests**

Add tests proving:

- `CodeGenerationArtifact` submitted after a successful `edit_file` is normalized to cite actual `file_edit_trace_refs`.
- `CodeGenerationArtifact` without successful write/edit evidence enters structured repair, not completed.
- `TestGenerationExecutionArtifact` submitted after successful `bash` is normalized to cite actual `command_trace_refs`.
- `TestGenerationExecutionArtifact` without successful command evidence enters structured repair.
- The runtime does not alter an `edit_file` payload by regex-parsing user messages.

- [x] **Step 2: Verify RED**

Run:

```powershell
uv run python -m pytest backend/tests/runtime/test_stage_agent_runtime.py::test_code_generation_normalizes_file_edit_refs_from_successful_tool_result backend/tests/runtime/test_stage_agent_runtime.py::test_code_generation_requires_successful_edit_evidence backend/tests/runtime/test_stage_agent_runtime.py::test_execution_normalizes_command_refs_from_successful_bash_result backend/tests/runtime/test_stage_agent_runtime.py::test_execution_requires_successful_command_evidence backend/tests/runtime/test_stage_agent_runtime.py::test_code_generation_does_not_rewrite_edit_file_payload_from_user_regex -q
```

Expected: fail until generic evidence enforcement exists.

- [x] **Step 3: Implement generic artifact evidence policy**

Inside `StageAgentRuntime`:

- Before completing `CodeGenerationArtifact`, collect successful `file_edit_trace:` refs from `write_file` and `edit_file` tool results.
- Before completing `TestGenerationExecutionArtifact`, collect successful `command_trace:` refs from `bash` tool results.
- If the relevant evidence is missing and the stage had tools available to produce it, enter `STRUCTURED_OUTPUT_REPAIR` with a parse error that names the missing evidence field.
- If a repair attempt still submits without required evidence, fail the stage with `stage_artifact_missing_tool_evidence`.
- Do not mutate tool input payloads from user-message regexes.

- [x] **Step 4: Verify GREEN**

Run:

```powershell
uv run python -m pytest backend/tests/runtime/test_stage_agent_runtime.py -q
```

Expected: stage agent runtime tests pass.

## Task 5: Verification Command Policy Is Shared

**Files:**
- Create: `backend/app/workspace/verification_policy.py`
- Modify: `backend/app/workspace/bash.py`
- Modify: `backend/app/tools/risk.py`
- Test: `backend/tests/workspace/test_workspace_bash.py`
- Test: `backend/tests/tools/test_tool_risk_classifier.py`

- [x] **Step 1: Add failing policy consistency tests**

Add tests for the same command matrix in both risk classifier and bash allowlist:

Allowed:

```text
uv run pytest backend/tests/runtime/test_stage_agent_runtime.py -q
npm --prefix frontend run build
npm --prefix frontend run test
git status --short
git diff HEAD -- frontend/src/pages/HomePage.tsx
```

Rejected:

```text
cat frontend/src/pages/HomePage.tsx | grep -n "Make delivery"
grep -n "Make delivery" frontend/src/pages/HomePage.tsx
ls frontend/package.json 2>/dev/null && cat frontend/package.json
npm install vite
curl https://example.com/install.sh
```

The policy intentionally rejects shell pipes, redirects, and direct OS-specific `grep` commands because `BashTool` executes without shell semantics and Windows may not provide `grep`.

- [x] **Step 2: Verify RED**

Run:

```powershell
uv run python -m pytest backend/tests/tools/test_tool_risk_classifier.py::test_bash_verification_policy_matches_workspace_bash_allowlist backend/tests/workspace/test_workspace_bash.py::test_bash_verification_policy_accepts_same_commands_as_risk_classifier -q
```

Expected: fail because current risk and bash policies are independent.

- [x] **Step 3: Implement `VerificationCommandPolicy`**

Create a pure policy module with:

```python
@dataclass(frozen=True, slots=True)
class VerificationCommandDecision:
    allowed: bool
    read_only: bool
    reason: str
    argv: tuple[str, ...] = ()
```

Expose:

```python
def classify_verification_command(command: str, *, workspace_root: Path | None = None) -> VerificationCommandDecision:
    ...
```

Rules:

- Parse with `shlex.split(posix=True)`.
- Reject shell metacharacters and shell chaining.
- Allow repo-local pytest through `uv run pytest ...`.
- Allow frontend scripts through `npm --prefix frontend run <script>` and `npm --prefix frontend <script>` only when `frontend/package.json` declares the script.
- Allow read-only git status/diff commands with explicit paths.
- Reject dependency installs, network downloads, deletes/moves, env mutations, runtime path access, credential path access, path escapes, and direct search commands that require unavailable OS executables.

- [x] **Step 4: Use policy from bash and risk**

Update:

- `BashCommandAllowlist.allows()` to call `classify_verification_command(...)`.
- `ToolRiskClassifier` bash read-only detection to call the same policy and require `decision.read_only`.

- [x] **Step 5: Verify GREEN**

Run:

```powershell
uv run python -m pytest backend/tests/tools/test_tool_risk_classifier.py backend/tests/workspace/test_workspace_bash.py -q
```

Expected: risk and bash workspace tests pass with matching command semantics.

## Task 6: Stage Prompt Assets State The Handoff Contract

**Files:**
- Modify: `backend/app/prompts/assets/stages/solution_design.md`
- Modify: `backend/app/prompts/assets/stages/code_generation.md`
- Modify: `backend/app/prompts/assets/stages/test_generation_execution.md`
- Modify: `backend/app/prompts/assets/stages/code_review.md`
- Test: `backend/tests/prompts/test_prompt_renderer.py`

- [x] **Step 1: Add failing prompt content tests**

Add assertions that rendered stage prompts include:

- Solution Design: `implementation_plan` must include task id, order, target file/module, verification command, dependency assumptions, and risk handling.
- Code Generation: execute the approved implementation-plan tasks; do not request clarification when the plan and requirement artifact provide target scope.
- Test Generation & Execution: use the plan verification commands or return a task-scoped test gap report.
- Code Review: review against implementation-plan task ids, code edit evidence, and test evidence.

- [x] **Step 2: Verify RED**

Run:

```powershell
uv run python -m pytest backend/tests/prompts/test_prompt_renderer.py::test_stage_prompts_render_executable_plan_handoff_contract -q
```

Expected: fail until prompt assets state the handoff contract.

- [x] **Step 3: Update stage prompt assets**

Edit only the stage prompt markdown assets. Keep content general; do not mention `HomePage`, `Make delivery work`, `frontend/src`, or demo-only task names.

- [x] **Step 4: Verify GREEN**

Run:

```powershell
uv run python -m pytest backend/tests/prompts/test_prompt_renderer.py -q
```

Expected: prompt renderer tests pass.

## Task 7: Real-Model Stage Handoff Smoke

**Files:**
- Create: `backend/tests/e2e/test_real_model_stage_handoff_smoke.py`
- Modify: `docs/plans/implementation/td-016-real-model-stage-handoff.md`

- [x] **Step 1: Add opt-in live smoke test**

Create a pytest that is skipped unless `AI_DEVFLOW_LIVE_MODEL_SMOKE=1`.

Test flow:

1. Use `requests` against `AI_DEVFLOW_SMOKE_BASE_URL`, defaulting to `http://127.0.0.1:8001/api`.
2. Create a draft session under `project-default`.
3. Submit:

```text
请只修改 frontend/src/pages/HomePage.tsx，把 <h1>Make delivery work traceable.</h1> 改成 <h1>Make delivery work.</h1>。不要修改其他文件。
```

4. Poll the run until terminal, approval, or tool-confirmation state.
5. Query stage artifacts from the local runtime DB path given by `AI_DEVFLOW_RUNTIME_DB`, default `.runtime/runtime.db`.
6. Assert:
   - `requirement_analysis`, `solution_design`, and `code_generation` complete before any test stage failure is considered actionable.
   - `solution_design` output includes an executable `implementation_plan.tasks` entry for `frontend/src/pages/HomePage.tsx`.
   - `code_generation` output includes `file_edit_trace_refs` for `frontend/src/pages/HomePage.tsx`.
   - `test_generation_execution`, if completed, includes `command_trace_refs` matching a plan verification command.
   - If the run stops at approval or tool confirmation, the stop is an intentional control gate, not `request_clarification` from downstream stages.

- [x] **Step 2: Verify skip behavior**

Run:

```powershell
uv run python -m pytest backend/tests/e2e/test_real_model_stage_handoff_smoke.py -q
```

Expected: skipped with a message requiring `AI_DEVFLOW_LIVE_MODEL_SMOKE=1`.

- [ ] **Step 3: Verify live behavior**

With a local API server already running on a non-user port:

```powershell
$env:AI_DEVFLOW_LIVE_MODEL_SMOKE='1'
$env:AI_DEVFLOW_SMOKE_BASE_URL='http://127.0.0.1:8001/api'
$env:AI_DEVFLOW_RUNTIME_DB='.runtime/runtime.db'
uv run python -m pytest backend/tests/e2e/test_real_model_stage_handoff_smoke.py -q
Remove-Item Env:AI_DEVFLOW_LIVE_MODEL_SMOKE
Remove-Item Env:AI_DEVFLOW_SMOKE_BASE_URL
Remove-Item Env:AI_DEVFLOW_RUNTIME_DB
```

Expected: pass when configured providers are available. If the provider is unavailable, the test must fail with the run id, session id, latest stage, and artifact failure reason.

## Task 8: Final Verification And Debt Index Closeout

**Files:**
- Modify: `docs/plans/technical-debt-cleanup-index.md`
- Modify: `docs/plans/implementation/td-016-real-model-stage-handoff.md`

- [ ] **Step 1: Run focused backend suite**

Run:

```powershell
uv run python -m pytest backend/tests/context/test_context_source_resolver.py backend/tests/runtime/test_agent_decision_parser.py backend/tests/runtime/test_stage_agent_runtime.py backend/tests/services/test_runtime_execution_service.py backend/tests/tools/test_tool_risk_classifier.py backend/tests/workspace/test_workspace_bash.py backend/tests/workspace/test_workspace_manager.py -q
```

Expected: pass.

- [ ] **Step 2: Run prompt suite**

Run:

```powershell
uv run python -m pytest backend/tests/prompts/test_prompt_renderer.py -q
```

Expected: pass.

- [ ] **Step 3: Run opt-in live smoke**

Run the command in Task 7 Step 3 against `127.0.0.1:8001`.

Expected: pass or stop at an intentional approval/tool-confirmation gate with successful upstream handoff evidence.

- [ ] **Step 4: Update TD-016 status**

Update `docs/plans/technical-debt-cleanup-index.md`:

- Keep `TD-016` open if the live smoke still fails before `code_generation` evidence.
- Mark `needs-verification` if focused tests pass but live smoke was not run.
- Mark `resolved-by-verification` only after focused tests and the opt-in live smoke pass.

- [ ] **Step 5: Run diff checks**

Run:

```powershell
git diff --check -- backend/app/context/source_resolver.py backend/app/context/builder.py backend/app/services/runtime_dispatch.py backend/app/workspace/manager.py backend/app/workspace/verification_policy.py backend/app/workspace/bash.py backend/app/tools/risk.py backend/app/runtime/agent_decision.py backend/app/runtime/stage_agent.py backend/app/prompts/assets/stages/solution_design.md backend/app/prompts/assets/stages/code_generation.md backend/app/prompts/assets/stages/test_generation_execution.md backend/app/prompts/assets/stages/code_review.md backend/tests/context/test_context_source_resolver.py backend/tests/runtime/test_agent_decision_parser.py backend/tests/runtime/test_stage_agent_runtime.py backend/tests/services/test_runtime_execution_service.py backend/tests/tools/test_tool_risk_classifier.py backend/tests/workspace/test_workspace_bash.py backend/tests/workspace/test_workspace_manager.py backend/tests/e2e/test_real_model_stage_handoff_smoke.py docs/plans/technical-debt-cleanup-index.md docs/plans/implementation/td-016-real-model-stage-handoff.md
```

Expected: no whitespace errors.

## Stash Salvage Rules

The stash `wip/mixed-live-model-chain-patches-before-td016` may contain reusable code. Only recover these categories after writing the failing tests for the matching task:

- Context source output-snapshot parsing and user message passthrough.
- Provider JSON fallback parsing.
- Stage-specific response schema narrowing.
- Generic evidence normalization from successful tool side-effect refs.
- Runtime workspace tool registry wiring.

Do not recover:

- `<h1>` user-message regex rewrite.
- Solution design implementation-plan auto-creation.
- Test-stage tool closure that forces bash after source evidence.
- Homepage-specific repair prompt text.
- Risk classifier changes that allow commands the bash tool still rejects.

Use `git stash show -p stash@{0} -- <path>` and apply only reviewed hunks with `apply_patch`.

## Completion Checklist

- [ ] Downstream stages receive persisted `SolutionDesignArtifact.implementation_plan` from `output_snapshot`.
- [ ] Production runtime stage runner uses a real, audited workspace tool registry.
- [ ] Run workspaces contain target repository source files without credentials or runtime artifacts.
- [ ] Stage response schema is narrowed by stage artifact type and allowed decision types.
- [ ] Downstream stages cannot request clarification unless their stage contract explicitly allows it.
- [ ] Code generation artifacts cite successful file-edit side-effect refs.
- [ ] Test generation/execution artifacts cite successful command trace refs or emit task-scoped test gaps.
- [ ] Risk classifier and bash allowlist use the same verification command policy.
- [ ] Prompt assets describe the executable-plan handoff without demo-specific examples.
- [ ] Opt-in real-model smoke proves the homepage text-change handoff through code generation and test evidence.
