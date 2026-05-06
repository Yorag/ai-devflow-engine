# Stage Agent Prompt Assets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current one-sentence stage agent seed prompts with production-grade, stage-specific prompt assets and render stage prompt fragments as traceable PromptRenderer sections without creating a second source of truth for stage contracts, tools, or output schemas.

**Architecture:** Add versioned `stage_prompt_fragment` assets under `backend/app/prompts/assets/stages/`, register them through existing `PromptRegistry`, and render the current stage fragment between `stage_contract` and `agent_role_prompt`. Keep stage responsibilities, allowed tools, response schemas, approvals, delivery routing, and tool descriptions sourced from existing runtime contracts. Expand `agent_role_seed.*` prompt bodies so system template defaults become useful role guidance while remaining low-authority editable prompt text.

**Tech Stack:** Python 3.11+, Pydantic v2 prompt schemas, existing `PromptRegistry` / `PromptRenderer`, pytest through `uv run --no-sync python -m pytest`.

---

## Source Trace

- `docs/specs/function-one-backend-engine-design-v1.md` requires built-in prompt assets to be backend-owned, versioned, tracked by `prompt_id` / `prompt_version`, and rendered by `PromptRenderer` without leaking metadata into model-visible text.
- `docs/specs/function-one-backend-engine-design-v1.md` fixes the prompt authority order as `runtime_instructions` > `stage_contract` > `agent_role_prompt`, with user messages, repository content, tool output, and prior model output treated as untrusted context.
- `docs/specs/function-one-backend-engine-design-v1.md` requires stage completion semantics, evidence requirements, failure return format, and self-check requirements to derive from `stage_contract` and formal output schemas, not from a parallel prompt truth table.
- `docs/plans/function-one-platform/06-langgraph-provider-context-stage-agent.md` A4.8c/A4.8d define `PromptRegistry` and `PromptRenderer` boundaries; A4.8d previously noted that `PromptType.STAGE_PROMPT_FRAGMENT` exists but was intentionally not implemented in that slice.
- `AGENTS.md` current working agreement says main-based stabilization is active and acceleration lane mode is not active. Therefore acceleration claim/store gates, lane worker status, and coordination-store writes are not applicable for this user-approved branch work.
- `references/superpowers-execution-rules.md` is referenced by `slice-workflow` but is absent in this checkout. The plan applies the available `slice-workflow`, `git-delivery-workflow`, `writing-plans`, `subagent-driven-development`, `test-driven-development`, `requesting-code-review`, and `verification-before-completion` rules directly.

## Scope

In scope:

- Add six built-in `stage_prompt_fragment` assets:
  - `stage_prompt_fragment.requirement_analysis`
  - `stage_prompt_fragment.solution_design`
  - `stage_prompt_fragment.code_generation`
  - `stage_prompt_fragment.test_generation_execution`
  - `stage_prompt_fragment.code_review`
  - `stage_prompt_fragment.delivery_integration`
- Expand role seed prompt bodies for:
  - `agent_role_seed.requirement_analyst`
  - `agent_role_seed.solution_designer`
  - `agent_role_seed.code_generator`
  - `agent_role_seed.test_runner`
  - `agent_role_seed.code_reviewer`
- Update `PromptRegistry` definitions so stage fragments are required built-in assets and stage-scoped.
- Update `PromptRenderer` to render exactly one current-stage fragment as a `stage_prompt_fragment` section after `stage_contract` and before `agent_role_prompt`.
- Add focused tests for asset loading, stage scoping, renderer section order, metadata prompt refs, and no metadata leakage.
- Update this implementation plan with actual red/green evidence.

Out of scope:

- No changes to `GraphDefinition.stage_contracts`, `stage_allowed_tools`, `ToolRegistry`, approval semantics, delivery routing, output schemas, API routes, frontend, configuration packages, provider adapters, or coordination store.
- No spec document edits.
- No platform-plan or split-plan final status updates.

## Prompt Design Rules

All stage fragments and role seeds must follow these rules:

- Use ASCII text.
- No `prompt_id`, `prompt_version`, `source_ref`, content hash, or front matter appears in model-visible body text.
- Do not instruct the model to modify `allowed_tools`, stage contracts, approvals, delivery routing, audit policy, or response schemas.
- Do not duplicate exact allowed tool lists. The actual tool list remains rendered dynamically from `stage_contract` and `ToolRegistry`.
- Stage fragments may describe how to use the already-rendered contract: read the current contract, respect `allowed_tools`, submit only the required structured artifact, record evidence, and stop on unsafe or impossible states.
- Role seeds may describe role discipline, workflow, quality standards, and output preferences, but remain low-authority `agent_role_prompt` content.
- Role seeds must not repeat the runtime/contract/schema section names or define output/failure mechanics. Those details stay in higher-authority rendered sections and current stage fragments.

## Files

- Modify: `backend/app/prompts/definitions.py`
- Modify: `backend/app/prompts/renderer.py`
- Modify: `backend/app/prompts/assets/runtime/runtime_instructions.md`
- Modify: `backend/app/prompts/assets/roles/requirement_analyst.md`
- Modify: `backend/app/prompts/assets/roles/solution_designer.md`
- Modify: `backend/app/prompts/assets/roles/code_generator.md`
- Modify: `backend/app/prompts/assets/roles/test_runner.md`
- Modify: `backend/app/prompts/assets/roles/code_reviewer.md`
- Create: `backend/app/prompts/assets/stages/requirement_analysis.md`
- Create: `backend/app/prompts/assets/stages/solution_design.md`
- Create: `backend/app/prompts/assets/stages/code_generation.md`
- Create: `backend/app/prompts/assets/stages/test_generation_execution.md`
- Create: `backend/app/prompts/assets/stages/code_review.md`
- Create: `backend/app/prompts/assets/stages/delivery_integration.md`
- Modify: `backend/tests/prompts/test_prompt_asset_loading.py`
- Modify: `backend/tests/prompts/test_prompt_renderer.py`
- Modify: `backend/tests/prompts/test_agent_role_seed_assets.py`

## Task 1: Register Stage Prompt Fragment Assets

**Files:**
- Modify: `backend/app/prompts/definitions.py`
- Create: `backend/app/prompts/assets/stages/*.md`
- Test: `backend/tests/prompts/test_prompt_asset_loading.py`

- [ ] **Step 1: Write failing registry tests**

Add tests that load built-in assets and assert:

```python
def test_builtin_stage_prompt_fragments_are_required_and_stage_scoped() -> None:
    from backend.app.domain.enums import StageType
    from backend.app.prompts.registry import PromptRegistry
    from backend.app.schemas.prompts import (
        ModelCallType,
        PromptAuthorityLevel,
        PromptCacheScope,
        PromptType,
    )

    registry = PromptRegistry.load_builtin_assets()

    expected = {
        "stage_prompt_fragment.requirement_analysis": StageType.REQUIREMENT_ANALYSIS,
        "stage_prompt_fragment.solution_design": StageType.SOLUTION_DESIGN,
        "stage_prompt_fragment.code_generation": StageType.CODE_GENERATION,
        "stage_prompt_fragment.test_generation_execution": StageType.TEST_GENERATION_EXECUTION,
        "stage_prompt_fragment.code_review": StageType.CODE_REVIEW,
        "stage_prompt_fragment.delivery_integration": StageType.DELIVERY_INTEGRATION,
    }
    for prompt_id, stage_type in expected.items():
        asset = registry.get(prompt_id)
        assert asset.prompt_type is PromptType.STAGE_PROMPT_FRAGMENT
        assert asset.authority_level is PromptAuthorityLevel.STAGE_CONTRACT_RENDERED
        assert asset.model_call_type is ModelCallType.STAGE_EXECUTION
        assert asset.cache_scope is PromptCacheScope.RUN_STATIC
        assert asset.applies_to_stage_types == [stage_type]
        assert asset.sections[0].body.startswith("# ")
        assert "prompt_id:" not in asset.sections[0].body
        assert "allowed_tools" in asset.sections[0].body
        assert "response_schema" in asset.sections[0].body
```

Also update `seed_required_assets()` in `backend/tests/prompts/test_prompt_asset_loading.py` so temporary asset roots must include the six stage fragments.

- [ ] **Step 2: Run test to verify RED**

Run:

```powershell
uv run --no-sync python -m pytest backend/tests/prompts/test_prompt_asset_loading.py::test_builtin_stage_prompt_fragments_are_required_and_stage_scoped -q
```

Expected before implementation:

```text
FAILED ... PromptAssetNotFoundError: Prompt asset not found: stage_prompt_fragment.requirement_analysis
```

- [ ] **Step 3: Implement registry definitions and assets**

Update `backend/app/prompts/definitions.py` with constants for the six stage fragment prompt ids, add them to `REQUIRED_BUILTIN_PROMPT_IDS`, add a stage-fragment mapping to `applies_to_stage_types_for_prompt_id()`, and add `BuiltinPromptDefinition` entries with relative paths under `stages/`.

Create each stage asset with front matter:

```yaml
prompt_type: stage_prompt_fragment
authority_level: stage_contract_rendered
model_call_type: stage_execution
cache_scope: run_static
source_ref: backend://prompts/stages/<stage>.md
```

Each body must include sections named `Mission`, `Workflow`, `Tool Policy`, `Quality Gates`, and `Failure And Escalation`.

- [ ] **Step 4: Run test to verify GREEN**

Run:

```powershell
uv run --no-sync python -m pytest backend/tests/prompts/test_prompt_asset_loading.py::test_builtin_stage_prompt_fragments_are_required_and_stage_scoped -q
```

Expected:

```text
1 passed
```

## Task 2: Render Current Stage Prompt Fragment

**Files:**
- Modify: `backend/app/prompts/renderer.py`
- Modify: `backend/tests/prompts/test_prompt_renderer.py`

- [ ] **Step 1: Write failing renderer tests**

Update the test registry in `backend/tests/prompts/test_prompt_renderer.py` to include a `stage_prompt_fragment.solution_design` asset. Update `test_render_stage_execution_messages_with_metadata_without_prompt_metadata_in_text()` to assert:

```python
assert "Solution Design Stage Prompt" in result.messages[0].content
assert "Use the current stage_contract" in result.messages[0].content
assert result.section_order == [
    "runtime_instructions",
    "stage_contract",
    "stage_prompt_fragment",
    "agent_role_prompt",
    "task_objective",
    "specified_action",
    "available_tools",
    "response_schema",
]
assert [ref.prompt_id for ref in result.metadata.prompt_refs] == [
    "runtime_instructions",
    "stage_prompt_fragment.solution_design",
    "tool_usage_template",
]
```

Add a focused missing-asset test:

```python
def test_missing_stage_prompt_fragment_returns_structured_renderer_error() -> None:
    from backend.app.prompts.renderer import PromptRenderException, PromptRenderer

    registry = PromptRegistry(
        [
            asset
            for asset in _registry().list_by_type(PromptType.RUNTIME_INSTRUCTIONS)
        ]
    )

    with pytest.raises(PromptRenderException) as exc_info:
        PromptRenderer(registry).render_messages(_request())

    assert exc_info.value.error.code == "prompt_asset_missing"
    assert exc_info.value.error.prompt_id == "stage_prompt_fragment.solution_design"
```

- [ ] **Step 2: Run test to verify RED**

Run:

```powershell
uv run --no-sync python -m pytest backend/tests/prompts/test_prompt_renderer.py::test_render_stage_execution_messages_with_metadata_without_prompt_metadata_in_text -q
```

Expected before implementation:

```text
FAILED ... AssertionError ... 'Solution Design Stage Prompt' ...
```

- [ ] **Step 3: Implement renderer support**

Add a helper mapping or imported constants from `backend/app/prompts/definitions.py` so `PromptRenderer` resolves exactly one prompt id for `request.stage_type`. Add `render_stage_prompt_fragment(request)` that returns an asset-backed section:

- `section_id="stage_prompt_fragment"`
- `authority_level=PromptAuthorityLevel.STAGE_CONTRACT_RENDERED`
- `cache_scope=asset.cache_scope`
- `prompt_ref` from the asset

Insert it after `stage_contract` in `render_messages()`. Include `stage_prompt_fragment` in `system_sections`, not `user_sections`.

- [ ] **Step 4: Run renderer tests to verify GREEN**

Run:

```powershell
uv run --no-sync python -m pytest backend/tests/prompts/test_prompt_renderer.py -q
```

Expected:

```text
all tests pass
```

## Task 3: Expand Role Seed And Runtime Prompt Bodies

**Files:**
- Modify: `backend/app/prompts/assets/runtime/runtime_instructions.md`
- Modify: `backend/app/prompts/assets/roles/*.md`
- Modify: `backend/tests/prompts/test_agent_role_seed_assets.py`

- [ ] **Step 1: Write failing role-content tests**

Add assertions to `test_agent_role_seed_assets_parse_front_matter_and_hash_body()`:

```python
body = asset.sections[0].body
assert "## Mission" in body
assert "## Workflow" in body
assert "## Quality Gates" in body
assert "## Failure And Escalation" in body
assert "runtime_instructions" not in body
assert "stage_contract" not in body
assert "response_schema" not in body
assert "stage prompt" not in body.lower()
assert "prompt_id:" not in body
assert "prompt_version:" not in body
```

Add a runtime prompt test in `backend/tests/prompts/test_prompt_asset_loading.py`:

```python
def test_runtime_instructions_define_real_development_boundaries() -> None:
    from backend.app.prompts.registry import PromptRegistry

    asset = PromptRegistry.load_builtin_assets().get("runtime_instructions")
    body = asset.sections[0].body

    assert "Authority Order" in body
    assert "Untrusted Context" in body
    assert "Tool And Side Effect Policy" in body
    assert "No Raw Chain-of-Thought" in body
    assert "response_schema" in body
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
uv run --no-sync python -m pytest backend/tests/prompts/test_agent_role_seed_assets.py::test_agent_role_seed_assets_parse_front_matter_and_hash_body backend/tests/prompts/test_prompt_asset_loading.py::test_runtime_instructions_define_real_development_boundaries -q
```

Expected before prompt expansion and later layering adjustment:

```text
FAILED ... AssertionError ... '## Mission' ...
FAILED ... AssertionError: assert '2026-05-06.1' == '2026-05-06.2'
```

- [ ] **Step 3: Expand prompt bodies**

Update runtime instructions into a multi-section prompt covering platform role, authority order, untrusted context, stage execution discipline, tool and side-effect policy, structured output, evidence, audit, and failure behavior.

Update each role seed with concrete sections. Keep role seed text focused on durable role behavior and avoid repeating the runtime/contract/schema section names:

- `Requirement Analyst`: clarify scope, acceptance criteria, assumptions, non-goals, open questions, source refs.
- `Solution Designer`: read-only design, internal validation, approval-ready artifact, no file edits.
- `Code Generator`: approved-plan implementation only, minimal diffs, changed files, evidence refs, no delivery actions.
- `Test Runner`: tests and verification, command evidence, failure classification, no hidden failures.
- `Code Reviewer`: findings-first review, regression decision, fix requirements, delivery-stage behavior when bound to delivery integration.
- Prompt versions: bump edited role seed assets to `2026-05-06.2` when the layering adjustment removes duplicated contract terms.

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```powershell
uv run --no-sync python -m pytest backend/tests/prompts/test_agent_role_seed_assets.py backend/tests/prompts/test_prompt_asset_loading.py -q
```

Expected:

```text
all tests pass
```

## Task 4: Focused Regression And Documentation Evidence

**Files:**
- Modify: `docs/plans/implementation/prompt-assets-stage-agent-prompts.md`

- [ ] **Step 1: Run focused prompt test suite**

Run:

```powershell
uv run --no-sync python -m pytest backend/tests/prompts/test_prompt_asset_loading.py backend/tests/prompts/test_prompt_registry.py backend/tests/prompts/test_agent_role_seed_assets.py backend/tests/prompts/test_prompt_renderer.py backend/tests/prompts/test_prompt_renderer_manifest_metadata.py -q
```

Expected:

```text
all tests pass
```

- [ ] **Step 2: Run impacted runtime validation tests**

Run:

```powershell
uv run --no-sync python -m pytest backend/tests/runtime/test_prompt_validation.py backend/tests/services/test_template_seed.py -q
```

Expected:

```text
all tests pass
```

- [ ] **Step 3: Update this plan with execution evidence**

Record the RED and GREEN command outputs, reviewer findings, and final verification results in the `Execution Evidence` section below.

## Review Plan

After implementation, run two reviews:

- Spec compliance review: confirm no prompt text overrides stage contracts, allowed tools, approvals, delivery routing, audit semantics, or response schemas; confirm metadata stays outside model-visible text.
- Code quality review: confirm the renderer change is narrow, stage fragment lookup is deterministic, tests are focused, and prompt text does not duplicate dynamic truth sources.

## Verification Commands

Final fresh focused verification:

```powershell
uv run --no-sync python -m pytest backend/tests/prompts/test_prompt_asset_loading.py backend/tests/prompts/test_prompt_registry.py backend/tests/prompts/test_agent_role_seed_assets.py backend/tests/prompts/test_prompt_renderer.py backend/tests/prompts/test_prompt_renderer_manifest_metadata.py backend/tests/runtime/test_prompt_validation.py backend/tests/services/test_template_seed.py backend/tests/context/test_context_envelope_builder.py backend/tests/context/test_context_compression.py backend/tests/regression/test_prompt_asset_boundary_regression.py -q
```

If final verification passes and only this plan is edited afterward to record evidence, do not rerun the full command; instead run:

```powershell
git status --short
git diff --stat
```

## Execution Evidence

Commands used `uv run --no-sync --active ...` with `VIRTUAL_ENV` set to the repository-local parent virtual environment because the worktree-local first run created an empty `.venv` without pytest. The initial plan-shaped command failed before test collection:

```text
Command: uv run --no-sync python -m pytest backend/tests/prompts/test_prompt_asset_loading.py::test_builtin_stage_prompt_fragments_are_required_and_stage_scoped -q
Exit code: 1
Key output: C:\Users\lkw\Desktop\github\agent-project\ai-devflow-engine\.worktrees\stage-agent-prompt-assets\.venv\Scripts\python.exe: No module named pytest
```

Task 1 RED:

```text
Command: uv run --no-sync --active python -m pytest backend/tests/prompts/test_prompt_asset_loading.py::test_builtin_stage_prompt_fragments_are_required_and_stage_scoped -q
Exit code: 1
Key output:
FAILED backend/tests/prompts/test_prompt_asset_loading.py::test_builtin_stage_prompt_fragments_are_required_and_stage_scoped
PromptAssetNotFoundError: Prompt asset not found: stage_prompt_fragment.requirement_analysis
```

Task 1 GREEN:

```text
Command: uv run --no-sync --active python -m pytest backend/tests/prompts/test_prompt_asset_loading.py::test_builtin_stage_prompt_fragments_are_required_and_stage_scoped -q
Exit code: 0
Key output: 1 passed in 0.03s
```

Task 2 RED:

```text
Command: uv run --no-sync --active python -m pytest backend/tests/prompts/test_prompt_renderer.py::test_render_stage_execution_messages_with_metadata_without_prompt_metadata_in_text -q
Exit code: 1
Key output:
FAILED backend/tests/prompts/test_prompt_renderer.py::test_render_stage_execution_messages_with_metadata_without_prompt_metadata_in_text
AssertionError: assert 'Solution Design Stage Prompt' in result.messages[0].content
```

Task 2 GREEN:

```text
Command: uv run --no-sync --active python -m pytest backend/tests/prompts/test_prompt_renderer.py -q
Exit code: 0
Key output: 8 passed in 0.05s
```

Task 3 RED:

```text
Command: uv run --no-sync --active python -m pytest backend/tests/prompts/test_agent_role_seed_assets.py::test_agent_role_seed_assets_parse_front_matter_and_hash_body backend/tests/prompts/test_prompt_asset_loading.py::test_runtime_instructions_define_real_development_boundaries -q
Exit code: 1
Key output:
FAILED backend/tests/prompts/test_agent_role_seed_assets.py::test_agent_role_seed_assets_parse_front_matter_and_hash_body
AssertionError: assert '## Mission' in body
FAILED backend/tests/prompts/test_prompt_asset_loading.py::test_runtime_instructions_define_real_development_boundaries
AssertionError: assert 'Authority Order' in body
```

Task 3 GREEN:

```text
Command: uv run --no-sync --active python -m pytest backend/tests/prompts/test_agent_role_seed_assets.py backend/tests/prompts/test_prompt_asset_loading.py -q
Exit code: 0
Key output: 16 passed in 0.38s
```

Role seed layering adjustment RED:

```text
Command: C:\Users\lkw\Desktop\github\agent-project\ai-devflow-engine\.venv\Scripts\python.exe -m pytest backend/tests/prompts/test_agent_role_seed_assets.py::test_agent_role_seed_assets_parse_front_matter_and_hash_body -q
Exit code: 1
Key output:
FAILED backend/tests/prompts/test_agent_role_seed_assets.py::test_agent_role_seed_assets_parse_front_matter_and_hash_body
AssertionError: assert '2026-05-06.1' == '2026-05-06.2'
```

Role seed layering adjustment GREEN:

```text
Command: C:\Users\lkw\Desktop\github\agent-project\ai-devflow-engine\.venv\Scripts\python.exe -m pytest backend/tests/prompts/test_agent_role_seed_assets.py::test_agent_role_seed_assets_parse_front_matter_and_hash_body -q
Exit code: 0
Key output: 1 passed in 0.08s
```

Reviewer-driven semantic layering RED:

```text
Command: C:\Users\lkw\Desktop\github\agent-project\ai-devflow-engine\.venv\Scripts\python.exe -m pytest backend/tests/prompts/test_agent_role_seed_assets.py::test_agent_role_seed_assets_parse_front_matter_and_hash_body -q
Exit code: 1
Key output:
FAILED backend/tests/prompts/test_agent_role_seed_assets.py::test_agent_role_seed_assets_parse_front_matter_and_hash_body
AssertionError: assert 'permission' not in lowered_body
```

Prompt validation coverage RED:

```text
Command: C:\Users\lkw\Desktop\github\agent-project\ai-devflow-engine\.venv\Scripts\python.exe -m pytest backend/tests/prompts/test_agent_role_seed_assets.py -q
Exit code: 1
Key output:
FAILED backend/tests/prompts/test_agent_role_seed_assets.py::test_agent_role_seed_assets_parse_front_matter_and_hash_body
AssertionError: pattern matched 'output shape'
FAILED backend/tests/prompts/test_agent_role_seed_assets.py::test_agent_role_seed_assets_pass_runtime_prompt_validation
RuntimeLimitSnapshotBuilderError: Current PlatformRuntimeSettings are invalid: agent_limits is missing persisted fields.
```

Reviewer-driven layering and validation GREEN:

```text
Command: C:\Users\lkw\Desktop\github\agent-project\ai-devflow-engine\.venv\Scripts\python.exe -m pytest backend/tests/prompts/test_agent_role_seed_assets.py -q
Exit code: 0
Key output: 5 passed in 0.17s
```

Layering regression scan and impacted validation:

```text
Command: rg -n "runtime_instructions|stage_contract|response_schema|stage prompt|2026-05-06\.1" backend\app\prompts\assets\roles backend\tests\prompts\test_agent_role_seed_assets.py
Exit code: 0
Key output: only negative assertions in backend/tests/prompts/test_agent_role_seed_assets.py matched; no role asset body matched.

Command: C:\Users\lkw\Desktop\github\agent-project\ai-devflow-engine\.venv\Scripts\python.exe -m pytest backend/tests/prompts/test_agent_role_seed_assets.py backend/tests/services/test_template_seed.py backend/tests/runtime/test_prompt_validation.py -q
Exit code: 0
Key output: 33 passed in 1.10s
```

Final semantic layering scan and verification:

```text
Command: rg -n "runtime_instructions|stage_contract|response_schema|stage prompt|stage contract|response schema|schema-defined|structured output|output contract|output format|output schema|output shape|permission|approval|audit|delivery control|runtime state|confirmation boundary|2026-05-06\.1" backend\app\prompts\assets\roles backend\tests\prompts\test_agent_role_seed_assets.py
Exit code: 0
Key output: only forbidden-pattern definitions and negative assertions in backend/tests/prompts/test_agent_role_seed_assets.py matched; no role asset body matched.

Command: C:\Users\lkw\Desktop\github\agent-project\ai-devflow-engine\.venv\Scripts\python.exe -m pytest backend/tests/prompts/test_prompt_asset_loading.py backend/tests/prompts/test_prompt_registry.py backend/tests/prompts/test_agent_role_seed_assets.py backend/tests/prompts/test_prompt_renderer.py backend/tests/prompts/test_prompt_renderer_manifest_metadata.py backend/tests/runtime/test_prompt_validation.py backend/tests/services/test_template_seed.py backend/tests/context/test_context_envelope_builder.py backend/tests/context/test_context_compression.py backend/tests/regression/test_prompt_asset_boundary_regression.py -q
Exit code: 0
Key output: 84 passed in 1.38s

Command: git diff --check
Exit code: 0
Key output: no whitespace errors; Windows autocrlf warnings only.
```

Focused prompt suite:

```text
Command: uv run --no-sync --active python -m pytest backend/tests/prompts/test_prompt_asset_loading.py backend/tests/prompts/test_prompt_registry.py backend/tests/prompts/test_agent_role_seed_assets.py backend/tests/prompts/test_prompt_renderer.py backend/tests/prompts/test_prompt_renderer_manifest_metadata.py -q
Exit code: 1
Key output:
FAILED backend/tests/prompts/test_prompt_renderer_manifest_metadata.py::test_renderer_metadata_round_trips_into_context_manifest_system_prompt_override
PromptRenderException: Prompt asset not found: stage_prompt_fragment.solution_design
```

Manifest fixture fix:

```text
Command: uv run --no-sync --active python -m pytest backend/tests/prompts/test_prompt_asset_loading.py backend/tests/prompts/test_prompt_registry.py backend/tests/prompts/test_agent_role_seed_assets.py backend/tests/prompts/test_prompt_renderer.py backend/tests/prompts/test_prompt_renderer_manifest_metadata.py -q
Exit code: 0
Key output: 29 passed in 0.53s
```

Impacted runtime validation:

```text
Command: uv run --no-sync --active python -m pytest backend/tests/runtime/test_prompt_validation.py backend/tests/services/test_template_seed.py -q
Exit code: 0
Key output: 29 passed in 0.72s
```

Reviewer-finding fixes:

```text
Command: C:\Users\lkw\Desktop\github\agent-project\ai-devflow-engine\.venv\Scripts\python.exe -m pytest backend/tests/prompts/test_agent_role_seed_assets.py::test_agent_role_seed_assets_parse_front_matter_and_hash_body backend/tests/prompts/test_prompt_asset_loading.py::test_runtime_instructions_define_real_development_boundaries backend/tests/context/test_context_envelope_builder.py backend/tests/context/test_context_compression.py -q
Exit code: 0
Key output: 23 passed in 0.35s
```

Final focused verification:

```text
Command: C:\Users\lkw\Desktop\github\agent-project\ai-devflow-engine\.venv\Scripts\python.exe -m pytest backend/tests/prompts/test_prompt_asset_loading.py backend/tests/prompts/test_prompt_registry.py backend/tests/prompts/test_agent_role_seed_assets.py backend/tests/prompts/test_prompt_renderer.py backend/tests/prompts/test_prompt_renderer_manifest_metadata.py backend/tests/runtime/test_prompt_validation.py backend/tests/services/test_template_seed.py backend/tests/context/test_context_envelope_builder.py backend/tests/context/test_context_compression.py -q
Exit code: 0
Key output: 79 passed in 1.49s
```

Prompt asset boundary regression:

```text
Command: C:\Users\lkw\Desktop\github\agent-project\ai-devflow-engine\.venv\Scripts\python.exe -m pytest backend/tests/regression/test_prompt_asset_boundary_regression.py -q
Exit code: 0
Key output: 4 passed in 0.35s
```

Final focused verification after line-ending normalization:

```text
Command: C:\Users\lkw\Desktop\github\agent-project\ai-devflow-engine\.venv\Scripts\python.exe -m pytest backend/tests/prompts/test_prompt_asset_loading.py backend/tests/prompts/test_prompt_registry.py backend/tests/prompts/test_agent_role_seed_assets.py backend/tests/prompts/test_prompt_renderer.py backend/tests/prompts/test_prompt_renderer_manifest_metadata.py backend/tests/runtime/test_prompt_validation.py backend/tests/services/test_template_seed.py backend/tests/context/test_context_envelope_builder.py backend/tests/context/test_context_compression.py backend/tests/regression/test_prompt_asset_boundary_regression.py -q
Exit code: 0
Key output: 83 passed in 2.17s
```

Full backend suite:

```text
Command: C:\Users\lkw\Desktop\github\agent-project\ai-devflow-engine\.venv\Scripts\python.exe -m pytest backend/tests -q
Exit code: 1
Key output: 1355 passed, 10 failed, 3 warnings in 386.77s
Failure class: pre-existing provider-configuration test fixture blocker. The failed template and E2E paths return "Pipeline template references an unknown Provider." or "Required Provider configuration is unavailable: provider-deepseek, provider-volcengine." No failure references PromptRegistry, PromptRenderer, runtime prompt validation, stage_prompt_fragment assets, or prompt rendering metadata.
```

Review findings after fixes:

```text
Spec compliance re-review: no Critical or Important findings. Previous stale role/runtime versions, response_schema authority ambiguity, and missing custom registry fixtures are closed. Minor finding: this evidence section was stale before this update.
Code quality re-review: no Critical findings. Important commit-hygiene finding: required files under backend/app/prompts/assets/stages/ are untracked and must be included in any commit. Minor findings: line-ending warnings remain; a future parametrized renderer test across all StageType values would add coverage beyond the current asset-loading coverage.
Role-seed layering re-review: no Critical, Important, or Minor prompt-layering findings. Previous Important finding about role seed control-policy duplication is closed.
Role-seed test coverage re-review: previous Important findings are closed. Remaining Minor findings: the role seed version assertion is intentionally coupled for this shared prompt-asset bump, and the semantic forbidden-pattern list may need future maintenance if benign wording changes.
```
