# Prompt Engineering Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Use `superpowers:executing-plans` only if task boundaries cannot be safely delegated. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current thin prompt fragments with an industrial prompt asset system that includes Claude-Code-style runtime discipline, tool usage policy, per-tool prompt fragments, repair/compression rules, stage guidance, and role seeds.

**Architecture:** Keep provider tool schemas concise and stable, and render rich tool instructions through prompt assets. Add a `tool_prompt_fragment` prompt type, load `backend/app/prompts/assets/tools/*.md` as first-class assets, and include only the fragments for `available_tools` allowed by the current stage contract. Prompt content remains governed by `PromptRegistry`, `PromptRenderer`, `ToolRegistry`, and stage `allowed_tools`.

**Tech Stack:** Python, Pydantic, pytest, existing prompt asset registry/renderer, existing tool protocol/registry.

---

## Scope And Boundaries

This is a prompt-engineering implementation slice, not a split-spec edit. Do not modify the current split specification set under `docs/specs/`. Do not update acceleration coordination store, platform plan final statuses, or split plan final statuses.

Claude Code design ideas applied here:

- Static runtime prompt has clear authority, task execution, tool usage, tone, output, safety, and failure sections.
- Tools have concise bindable function descriptions plus separate rich model-visible usage guidance.
- Detailed tool guidance explains purpose, when to use, when not to use, input semantics, safety boundaries, side effects, and output handling.
- Repair/compression prompts preserve facts and authority instead of rewriting intent.
- Built-in agent/role prompts are focused on mission, workflow, quality gates, escalation, and style without overriding higher-authority contracts.

## Files

- Modify: `backend/app/schemas/prompts.py`
- Modify: `backend/app/prompts/definitions.py`
- Modify: `backend/app/prompts/registry.py`
- Modify: `backend/app/prompts/renderer.py`
- Modify: `backend/app/prompts/assets/runtime/runtime_instructions.md`
- Modify: `backend/app/prompts/assets/tools/tool_usage_common.md`
- Create: `backend/app/prompts/assets/tools/read_file.md`
- Create: `backend/app/prompts/assets/tools/glob.md`
- Create: `backend/app/prompts/assets/tools/grep.md`
- Create: `backend/app/prompts/assets/tools/write_file.md`
- Create: `backend/app/prompts/assets/tools/edit_file.md`
- Create: `backend/app/prompts/assets/tools/bash.md`
- Create: `backend/app/prompts/assets/tools/read_delivery_snapshot.md`
- Create: `backend/app/prompts/assets/tools/prepare_branch.md`
- Create: `backend/app/prompts/assets/tools/create_commit.md`
- Create: `backend/app/prompts/assets/tools/push_branch.md`
- Create: `backend/app/prompts/assets/tools/create_code_review_request.md`
- Modify: `backend/app/prompts/assets/compression/compression_context.md`
- Modify: `backend/app/prompts/assets/repairs/structured_output_repair.md`
- Modify: `backend/app/prompts/assets/stages/*.md`
- Modify: `backend/app/prompts/assets/roles/*.md`
- Modify tests: `backend/tests/schemas/test_prompt_asset_schemas.py`
- Modify tests: `backend/tests/prompts/test_prompt_asset_loading.py`
- Modify tests: `backend/tests/prompts/test_prompt_registry.py`
- Modify tests: `backend/tests/prompts/test_prompt_renderer.py`
- Modify tests: `backend/tests/prompts/test_prompt_renderer_manifest_metadata.py`
- Modify tests: `backend/tests/tools/test_tool_protocol_registry.py`

## Log And Audit Integration

This slice changes model-call prompt assembly and model-visible tool instructions. It does not introduce new runtime log categories, audit actions, trace identifiers, tool execution side effects, workspace writes by the product runtime, Git delivery behavior, remote delivery behavior, or configuration writes. Existing prompt render metadata must still preserve prompt refs, render hash, section order, tool schema version, and source refs. Tests must prove rich tool prompt refs enter metadata without replacing tool execution audit records.

## Task 1: Add Tool Prompt Fragment Contract

**Files:**
- Modify: `backend/app/schemas/prompts.py`
- Modify: `backend/app/prompts/definitions.py`
- Modify: `backend/app/prompts/registry.py`
- Test: `backend/tests/schemas/test_prompt_asset_schemas.py`
- Test: `backend/tests/prompts/test_prompt_asset_loading.py`
- Test: `backend/tests/prompts/test_prompt_registry.py`

- [ ] **Step 1: Write failing schema tests**

Add assertions to `test_prompt_asset_read_locks_system_prompt_asset_identity_and_hash`:

```python
assert {prompt_type.value for prompt_type in PromptType} == {
    "runtime_instructions",
    "stage_prompt_fragment",
    "structured_output_repair",
    "compression_prompt",
    "agent_role_seed",
    "tool_usage_template",
    "tool_prompt_fragment",
}
```

Add a new test:

```python
def test_tool_prompt_fragment_uses_tool_description_authority() -> None:
    from backend.app.schemas.prompts import (
        ModelCallType,
        PromptAssetRead,
        PromptAuthorityLevel,
        PromptCacheScope,
        PromptSectionRead,
        PromptType,
    )

    section = PromptSectionRead(
        section_id="tool_prompt_fragment.read_file",
        title="read_file Tool",
        body="# read_file Tool\n\nUse this tool only for workspace text reads.",
        cache_scope=PromptCacheScope.GLOBAL_STATIC,
    )

    asset = PromptAssetRead(
        prompt_id="tool_prompt_fragment.read_file",
        prompt_version="2026-05-06.1",
        prompt_type=PromptType.TOOL_PROMPT_FRAGMENT,
        authority_level=PromptAuthorityLevel.TOOL_DESCRIPTION_RENDERED,
        model_call_type=ModelCallType.TOOL_CALL_PREPARATION,
        cache_scope=PromptCacheScope.GLOBAL_STATIC,
        source_ref="backend://prompts/tools/read_file.md",
        content_hash="a" * 64,
        sections=[section],
    )

    assert asset.prompt_type is PromptType.TOOL_PROMPT_FRAGMENT
```

- [ ] **Step 2: Run schema test and verify RED**

Run:

```powershell
uv run pytest backend/tests/schemas/test_prompt_asset_schemas.py::test_prompt_asset_read_locks_system_prompt_asset_identity_and_hash backend/tests/schemas/test_prompt_asset_schemas.py::test_tool_prompt_fragment_uses_tool_description_authority -q
```

Expected: FAIL because `PromptType.TOOL_PROMPT_FRAGMENT` does not exist and enum set lacks `tool_prompt_fragment`.

- [ ] **Step 3: Implement schema contract**

Add to `PromptType` in `backend/app/schemas/prompts.py`:

```python
TOOL_PROMPT_FRAGMENT = "tool_prompt_fragment"
```

Add expected mappings:

```python
PromptType.TOOL_PROMPT_FRAGMENT: PromptAuthorityLevel.TOOL_DESCRIPTION_RENDERED,
PromptType.TOOL_PROMPT_FRAGMENT: ModelCallType.TOOL_CALL_PREPARATION,
```

- [ ] **Step 4: Add failing registry-loading tests**

In `backend/tests/prompts/test_prompt_asset_loading.py`, update `seed_required_assets` to create one sample tool fragment:

```python
write_asset(
    root,
    "tools/read_file.md",
    valid_asset(
        prompt_id="tool_prompt_fragment.read_file",
        prompt_version="2026-05-06.1",
        prompt_type="tool_prompt_fragment",
        authority_level="tool_description_rendered",
        model_call_type="tool_call_preparation",
        cache_scope="global_static",
        source_ref="backend://prompts/tools/read_file.md",
        body="# read_file Tool\n\nUse read_file for workspace text reads.",
    ),
)
```

Add a new builtin test:

```python
def test_builtin_tool_prompt_fragments_are_registered_and_stage_scoped() -> None:
    from backend.app.prompts.registry import PromptRegistry
    from backend.app.schemas.prompts import PromptType

    registry = PromptRegistry.load_builtin_assets()
    assets = registry.list_by_type(PromptType.TOOL_PROMPT_FRAGMENT)

    assert [asset.prompt_id for asset in assets] == [
        "tool_prompt_fragment.bash",
        "tool_prompt_fragment.create_code_review_request",
        "tool_prompt_fragment.create_commit",
        "tool_prompt_fragment.edit_file",
        "tool_prompt_fragment.glob",
        "tool_prompt_fragment.grep",
        "tool_prompt_fragment.prepare_branch",
        "tool_prompt_fragment.push_branch",
        "tool_prompt_fragment.read_delivery_snapshot",
        "tool_prompt_fragment.read_file",
        "tool_prompt_fragment.write_file",
    ]
    assert all(asset.sections[0].body.startswith("# ") for asset in assets)
```

In `backend/tests/prompts/test_prompt_registry.py`, assert:

```python
tool_fragments = registry.list_by_type(PromptType.TOOL_PROMPT_FRAGMENT)
assert "tool_prompt_fragment.read_file" in {asset.prompt_id for asset in tool_fragments}
```

- [ ] **Step 5: Run registry tests and verify RED**

Run:

```powershell
uv run pytest backend/tests/prompts/test_prompt_asset_loading.py::test_builtin_tool_prompt_fragments_are_registered_and_stage_scoped backend/tests/prompts/test_prompt_registry.py::test_load_builtin_assets_registers_required_prompt_assets -q
```

Expected: FAIL because builtin tool prompt asset ids and files are not defined yet.

- [ ] **Step 6: Implement builtin definitions**

In `backend/app/prompts/definitions.py`, add:

```python
TOOL_PROMPT_FRAGMENT_PROMPT_IDS_BY_TOOL = {
    "bash": "tool_prompt_fragment.bash",
    "create_code_review_request": "tool_prompt_fragment.create_code_review_request",
    "create_commit": "tool_prompt_fragment.create_commit",
    "edit_file": "tool_prompt_fragment.edit_file",
    "glob": "tool_prompt_fragment.glob",
    "grep": "tool_prompt_fragment.grep",
    "prepare_branch": "tool_prompt_fragment.prepare_branch",
    "push_branch": "tool_prompt_fragment.push_branch",
    "read_delivery_snapshot": "tool_prompt_fragment.read_delivery_snapshot",
    "read_file": "tool_prompt_fragment.read_file",
    "write_file": "tool_prompt_fragment.write_file",
}
TOOL_PROMPT_FRAGMENT_PROMPT_IDS = frozenset(
    TOOL_PROMPT_FRAGMENT_PROMPT_IDS_BY_TOOL.values()
)
```

Include `*TOOL_PROMPT_FRAGMENT_PROMPT_IDS` in `REQUIRED_BUILTIN_PROMPT_IDS`.

Add a `TOOL_PROMPT_FRAGMENT_STAGE_TYPES` mapping derived from `stage_allowed_tools()` and update `applies_to_stage_types_for_prompt_id` to return the stages where each tool is allowed. Import `stage_allowed_tools` locally inside the mapping helper or build it after `ALL_STAGE_TYPES` to avoid circular imports.

- [ ] **Step 7: Run schema and registry tests and verify GREEN**

Run:

```powershell
uv run pytest backend/tests/schemas/test_prompt_asset_schemas.py backend/tests/prompts/test_prompt_asset_loading.py backend/tests/prompts/test_prompt_registry.py -q
```

Expected: PASS after tool prompt asset files are added in Task 3.

## Task 2: Render Rich Tool Prompt Fragments

**Files:**
- Modify: `backend/app/prompts/renderer.py`
- Modify: `backend/app/prompts/definitions.py`
- Test: `backend/tests/prompts/test_prompt_renderer.py`
- Test: `backend/tests/prompts/test_prompt_renderer_manifest_metadata.py`
- Test: `backend/tests/tools/test_tool_protocol_registry.py`

- [ ] **Step 1: Write failing renderer tests**

Add `_asset(...)` entries for `tool_prompt_fragment.read_file` and `tool_prompt_fragment.grep` in the renderer test registry:

```python
_asset(
    prompt_id="tool_prompt_fragment.read_file",
    prompt_type=PromptType.TOOL_PROMPT_FRAGMENT,
    authority_level=PromptAuthorityLevel.TOOL_DESCRIPTION_RENDERED,
    model_call_type=ModelCallType.TOOL_CALL_PREPARATION,
    source_ref="backend://prompts/tools/read_file.md",
    body="# read_file Tool\n\nPrefer read_file over bash for workspace text reads.",
)
```

Add assertions to `test_render_stage_execution_messages_with_metadata_without_prompt_metadata_in_text`:

```python
assert "read_file Tool" in result.messages[0].content
assert "Prefer read_file over bash" in result.messages[0].content
assert [ref.prompt_id for ref in result.metadata.prompt_refs] == [
    "runtime_instructions",
    "stage_prompt_fragment.solution_design",
    "tool_usage_template",
    "tool_prompt_fragment.read_file",
]
```

Add a new test:

```python
def test_render_tool_usage_includes_only_available_tool_fragments() -> None:
    from backend.app.prompts.renderer import PromptRenderer

    registry = PromptRegistry(
        [
            *_registry().list_by_type(PromptType.RUNTIME_INSTRUCTIONS),
            *_registry().list_by_type(PromptType.STAGE_PROMPT_FRAGMENT),
            *_registry().list_by_type(PromptType.TOOL_USAGE_TEMPLATE),
            _asset(
                prompt_id="tool_prompt_fragment.read_file",
                prompt_type=PromptType.TOOL_PROMPT_FRAGMENT,
                authority_level=PromptAuthorityLevel.TOOL_DESCRIPTION_RENDERED,
                model_call_type=ModelCallType.TOOL_CALL_PREPARATION,
                source_ref="backend://prompts/tools/read_file.md",
                body="# read_file Tool\n\nRead file guidance.",
            ),
            _asset(
                prompt_id="tool_prompt_fragment.grep",
                prompt_type=PromptType.TOOL_PROMPT_FRAGMENT,
                authority_level=PromptAuthorityLevel.TOOL_DESCRIPTION_RENDERED,
                model_call_type=ModelCallType.TOOL_CALL_PREPARATION,
                source_ref="backend://prompts/tools/grep.md",
                body="# grep Tool\n\nSearch guidance.",
            ),
        ]
    )

    result = PromptRenderer(registry).render_messages(_request())
    text = result.messages[0].content

    assert "read_file Tool" in text
    assert "grep Tool" not in text
```

- [ ] **Step 2: Run renderer tests and verify RED**

Run:

```powershell
uv run pytest backend/tests/prompts/test_prompt_renderer.py::test_render_stage_execution_messages_with_metadata_without_prompt_metadata_in_text backend/tests/prompts/test_prompt_renderer.py::test_render_tool_usage_includes_only_available_tool_fragments -q
```

Expected: FAIL because `render_tool_usage` does not resolve or render per-tool assets.

- [ ] **Step 3: Implement renderer inclusion**

In `backend/app/prompts/renderer.py`:

```python
from backend.app.prompts.definitions import (
    ...
    TOOL_PROMPT_FRAGMENT_PROMPT_IDS_BY_TOOL,
)
```

Update `render_tool_usage` to:

```python
tool_prompt_sections = []
tool_prompt_refs = []
for tool in sorted(request.available_tools, key=lambda item: item.name):
    prompt_id = TOOL_PROMPT_FRAGMENT_PROMPT_IDS_BY_TOOL.get(tool.name)
    if prompt_id is None:
        raise PromptRenderException(
            PromptRenderError(
                code="tool_prompt_fragment_missing",
                message=(
                    "No rich prompt fragment is registered for available "
                    f"tool: {tool.name}"
                ),
                stage_type=request.stage_type,
            )
        )
    asset = self._get_asset(prompt_id)
    tool_prompt_sections.append("\n\n".join(section.body for section in asset.sections))
    tool_prompt_refs.append(self._prompt_ref(asset))
```

Because `PromptRenderedSection` currently has only one `prompt_ref`, introduce `depends_on_prompt_refs` only at metadata aggregation time by returning an additional list from helper or by adding a private renderer method that appends tool fragment refs to `metadata.prompt_refs`. The simpler implementation is to add an optional field to `PromptRenderedSection`:

```python
depends_on_prompt_refs: list[PromptVersionRef] = Field(default_factory=list)
```

Then set it on `available_tools`, and update `_result`:

```python
prompt_refs = []
for section in sections:
    if section.prompt_ref is not None:
        prompt_refs.append(section.prompt_ref)
    prompt_refs.extend(section.depends_on_prompt_refs)
```

Render body order:

1. common tool usage template
2. global stage allowed tools statement
3. `## Tool Guidance` with available tool prompt fragments
4. `## Tool Schemas` with stable JSON payload

- [ ] **Step 4: Write failing provider/tool schema stability test**

In `backend/tests/tools/test_tool_protocol_registry.py`, update `test_bindable_description_uses_langchain_compatible_schema` to assert rich prompt content is not in provider binding:

```python
assert "Prefer read_file over bash" not in description.to_langchain_tool_schema()["description"]
```

Expected: PASS after renderer-only implementation. This protects against future regressions that move rich prompts into function schema.

- [ ] **Step 5: Run renderer and metadata tests and verify GREEN**

Run:

```powershell
uv run pytest backend/tests/prompts/test_prompt_renderer.py backend/tests/prompts/test_prompt_renderer_manifest_metadata.py backend/tests/tools/test_tool_protocol_registry.py::test_bindable_description_uses_langchain_compatible_schema -q
```

Expected: PASS, with metadata prompt refs including `tool_usage_template` and every rendered available tool fragment.

## Task 3: Add Industrial Tool Prompt Assets

**Files:**
- Modify: `backend/app/prompts/assets/tools/tool_usage_common.md`
- Create: `backend/app/prompts/assets/tools/read_file.md`
- Create: `backend/app/prompts/assets/tools/glob.md`
- Create: `backend/app/prompts/assets/tools/grep.md`
- Create: `backend/app/prompts/assets/tools/write_file.md`
- Create: `backend/app/prompts/assets/tools/edit_file.md`
- Create: `backend/app/prompts/assets/tools/bash.md`
- Create: `backend/app/prompts/assets/tools/read_delivery_snapshot.md`
- Create: `backend/app/prompts/assets/tools/prepare_branch.md`
- Create: `backend/app/prompts/assets/tools/create_commit.md`
- Create: `backend/app/prompts/assets/tools/push_branch.md`
- Create: `backend/app/prompts/assets/tools/create_code_review_request.md`
- Test: `backend/tests/prompts/test_prompt_asset_loading.py`
- Test: `backend/tests/prompts/test_prompt_renderer.py`

- [ ] **Step 1: Write failing content assertions**

In `test_builtin_tool_prompt_fragments_are_registered_and_stage_scoped`, assert representative Claude-Code-style guidance:

```python
by_id = {asset.prompt_id: asset.sections[0].body for asset in assets}
assert "Prefer this tool over bash" in by_id["tool_prompt_fragment.read_file"]
assert "ripgrep" in by_id["tool_prompt_fragment.grep"]
assert "Do not use bash to read, search, create, or edit files" in by_id["tool_prompt_fragment.bash"]
assert "approval" in by_id["tool_prompt_fragment.create_code_review_request"].lower()
```

- [ ] **Step 2: Run content test and verify RED**

Run:

```powershell
uv run pytest backend/tests/prompts/test_prompt_asset_loading.py::test_builtin_tool_prompt_fragments_are_registered_and_stage_scoped -q
```

Expected: FAIL until the files exist with required content.

- [ ] **Step 3: Add tool prompt assets**

Every tool asset uses:

```yaml
---
prompt_id: tool_prompt_fragment.<tool_name>
prompt_version: 2026-05-06.1
prompt_type: tool_prompt_fragment
authority_level: tool_description_rendered
model_call_type: tool_call_preparation
cache_scope: global_static
source_ref: backend://prompts/tools/<tool_name>.md
---
```

Each body must include:

- Purpose
- Use When
- Do Not Use When
- Input Rules
- Output Handling
- Safety And Side Effects
- Failure Handling

`bash.md` must explicitly say:

```markdown
Do not use bash to read, search, create, or edit files when `read_file`, `grep`, `glob`, `write_file`, or `edit_file` is available for the same task.
```

`grep.md` must explicitly say it uses local ripgrep semantics and should be preferred over bash `grep`, `findstr`, or ad hoc search commands.

- [ ] **Step 4: Run prompt asset loading and renderer tests**

Run:

```powershell
uv run pytest backend/tests/prompts/test_prompt_asset_loading.py backend/tests/prompts/test_prompt_renderer.py -q
```

Expected: PASS.

## Task 4: Expand Runtime, Repair, Compression, Stage, And Role Prompts

**Files:**
- Modify: `backend/app/prompts/assets/runtime/runtime_instructions.md`
- Modify: `backend/app/prompts/assets/compression/compression_context.md`
- Modify: `backend/app/prompts/assets/repairs/structured_output_repair.md`
- Modify: `backend/app/prompts/assets/stages/*.md`
- Modify: `backend/app/prompts/assets/roles/*.md`
- Test: `backend/tests/prompts/test_prompt_asset_loading.py`

- [ ] **Step 1: Write failing content assertions**

Update prompt asset loading tests:

```python
def test_runtime_instructions_cover_claude_code_style_sections() -> None:
    from backend.app.prompts.registry import PromptRegistry

    body = PromptRegistry.load_builtin_assets().get("runtime_instructions").sections[0].body
    for required in [
        "System Identity",
        "Doing Tasks",
        "Using Tools",
        "Tone And Style",
        "Output Efficiency",
        "No Raw Chain-of-Thought",
    ]:
        assert required in body
```

Add repair/compression assertions:

```python
def test_repair_and_compression_prompts_preserve_authority_and_facts() -> None:
    from backend.app.prompts.registry import PromptRegistry

    registry = PromptRegistry.load_builtin_assets()
    repair = registry.get("structured_output_repair").sections[0].body
    compression = registry.get("compression_prompt").sections[0].body

    assert "Do not reinterpret" in repair
    assert "Do not invent missing facts" in repair
    assert "approved decisions" in compression
    assert "tool results" in compression
    assert "open blockers" in compression
```

- [ ] **Step 2: Run content tests and verify RED**

Run:

```powershell
uv run pytest backend/tests/prompts/test_prompt_asset_loading.py::test_runtime_instructions_cover_claude_code_style_sections backend/tests/prompts/test_prompt_asset_loading.py::test_repair_and_compression_prompts_preserve_authority_and_facts -q
```

Expected: FAIL because several section names and preservation rules are missing.

- [ ] **Step 3: Expand prompt assets**

Update runtime prompt with industrial sections:

- System Identity
- Authority Order
- Untrusted Context
- Doing Tasks
- Stage Execution Discipline
- Using Tools
- Tool And Side Effect Policy
- Tone And Style
- Output Efficiency
- Structured Output
- Evidence And Audit
- Failure Behavior

Update repair prompt with:

- Repair Objective
- Immutable Inputs
- Allowed Repairs
- Prohibited Repairs
- Schema Compliance
- Failure Handling

Update compression prompt with:

- Compression Objective
- Must Preserve
- Must Drop Or Condense
- Authority And Trust
- Output Rules
- Failure Handling

Update stage and role prompts to include consistent, concrete sections without changing stage semantics. Preserve current prompt ids, source refs, and existing prompt_version values in this slice unless Worker A updates the tests and schema contract in the same verified change.

Role prompt bodies have an additional validation boundary in `backend/tests/prompts/test_agent_role_seed_assets.py`: avoid control-boundary phrases such as `runtime_instructions`, `stage_contract`, `response_schema`, `stage prompt`, `schema-defined`, `structured output`, `output schema`, `permissions`, `approvals`, `audit`, `delivery controls`, `runtime states`, and `confirmation boundary`.

- [ ] **Step 4: Run content tests and verify GREEN**

Run:

```powershell
uv run pytest backend/tests/prompts/test_prompt_asset_loading.py -q
```

Expected: PASS.

## Task 5: Full Prompt/Tool Verification And Review

**Files:**
- All files changed above

- [ ] **Step 1: Run focused prompt/tool suite**

Run:

```powershell
uv run pytest backend/tests/prompts backend/tests/schemas/test_prompt_asset_schemas.py backend/tests/tools/test_tool_protocol_registry.py backend/tests/providers/test_langchain_adapter.py -q
```

Expected: PASS.

- [ ] **Step 2: Run impacted context/runtime suite**

Run:

```powershell
uv run pytest backend/tests/context backend/tests/runtime/test_stage_agent_runtime.py backend/tests/runtime/test_agent_decision_parser.py -q
```

Expected: PASS.

- [ ] **Step 3: Code review checkpoint**

Dispatch reviewers or run inline review if reviewers are unavailable:

- Spec/plan compliance: verify prompt refs, authority levels, stage boundaries, allowed tool filtering, and no split-spec edits.
- Code quality/testing/regression: verify metadata ordering, schema compatibility, provider binding stability, and prompt content is not hidden in function schema.

Critical or Important findings must be fixed and re-reviewed.

- [ ] **Step 4: Final verification-before-completion**

Run:

```powershell
git status --short
git diff --stat
uv run pytest backend/tests/prompts backend/tests/schemas/test_prompt_asset_schemas.py backend/tests/tools/test_tool_protocol_registry.py backend/tests/providers/test_langchain_adapter.py backend/tests/context backend/tests/runtime/test_stage_agent_runtime.py backend/tests/runtime/test_agent_decision_parser.py -q
```

Expected: git status shows only this slice's files; pytest exits 0.

- [ ] **Step 5: Commit gate**

After fresh verification, use `git-delivery-workflow` commit gate. Commit only if the diff is one coherent verified checkpoint and contains no draft split-spec changes.

## Subagent Execution Checklist

Use implementer subagents for disjoint work where possible:

- Worker A owns schema/definitions/renderer/tests for `tool_prompt_fragment`. Allowed files: `backend/app/schemas/prompts.py`, `backend/app/prompts/definitions.py`, `backend/app/prompts/renderer.py`, prompt/schema/renderer tests. No prompt content assets except test fixtures.
- Worker B owns tool prompt asset content. Allowed files: `backend/app/prompts/assets/tools/*.md`, relevant content assertions.
- Worker C owns runtime/repair/compression/stage/role prompt content. Allowed files: prompt asset markdown files and prompt asset loading content assertions.

Subagents must not run Git write operations, update coordination store, modify split specs, install dependencies, modify lock files, run migrations, or expand beyond assigned files. Each implementer must report RED command, GREEN command, changed files, and concerns.

## Fallback Conditions

Use inline execution only if subagents cannot safely apply patches in the isolated worktree or if task dependencies become too coupled to review independently. Inline fallback must still follow TDD red-green steps and two-stage review.

## Execution Record 2026-05-06

Status: implemented in worktree `.worktrees/refactor-prompt-engineering-overhaul` on branch `refactor/prompt-engineering-overhaul`.

Implemented changes:

- Added `tool_prompt_fragment` as a first-class prompt type with fixed authority, model-call type, and cache scope validation.
- Registered per-tool prompt assets for every current built-in tool and derived their stage applicability from `stage_allowed_tools()`.
- Rendered only current `available_tools` rich tool fragments, retained concise provider function schemas, and failed closed for missing or duplicate available tool bindings.
- Expanded runtime, repair, compression, stage, role, global tool-use, and per-tool prompt assets with industrial sections modeled after Claude Code style.
- Bumped `prompt_version` for every modified existing prompt asset body so persisted `PromptVersionRef` values do not silently point at changed text.
- Updated prompt, schema, context, and tool tests to cover prompt loading, rendering metadata, stage scoping, cache scopes, fail-closed tool fragments, duplicate tool names, provider schema separation, and role prompt control-term boundaries.

Review results:

- Spec/plan compliance review found no Critical issues. Important issue about future/custom tool behavior was accepted as an intentional industrial fail-closed contract; this plan was corrected to match the implementation.
- Code/regression review found no Critical issues. Important issue about prompt body edits without version bumps was fixed by bumping all modified existing prompt assets.
- Minor findings fixed: rendered `## Tool Guidance` / `## Tool Schemas` headings, explicit provider-schema assertion that rich prompt text stays out of `ToolBindableDescription.to_langchain_tool_schema()`, and duplicate available-tool rejection.

Verification run:

- `uv sync --extra dev` exited 0 after user approval and installed the declared local dev test dependencies into the worktree environment.
- `uv run python -m pytest backend/tests/prompts backend/tests/schemas/test_prompt_asset_schemas.py backend/tests/tools/test_tool_protocol_registry.py backend/tests/providers/test_langchain_adapter.py -q` exited 0: 84 passed, 3 warnings.
- `uv run python -m pytest backend/tests/context backend/tests/runtime/test_stage_agent_runtime.py backend/tests/runtime/test_agent_decision_parser.py -q` exited 0: 72 passed.
- `uv run python -m compileall -q backend/app/prompts backend/app/schemas/prompts.py backend/app/context backend/tests/prompts backend/tests/schemas backend/tests/context backend/tests/tools/test_tool_protocol_registry.py` exited 0.
- Direct prompt render smoke exited 0 and verified rich fragments render only for current tools, metadata prompt refs include `tool_usage_template` plus per-tool fragments, and tool headings render as markdown subsections.
- Direct tool content smoke exited 0 and verified all 11 tool prompt fragments contain Purpose, Use When, Do Not Use When, Input Rules, Output Handling, Safety And Side Effects, and Failure Handling sections.
- Direct non-tool prompt content smoke exited 0 and verified runtime, repair, and compression industrial sections and preservation rules.
- Direct cache contract smoke exited 0 and verified prompt-type cache-scope mismatches are rejected.
- Direct missing-fragment smoke exited 0 and verified unknown available tools fail with `tool_prompt_fragment_missing`.
- Direct duplicate-tool smoke exited 0 and verified duplicate available tool names fail with `duplicate_available_tool`.
- Direct role forbidden-term scan exited 0.
- `git diff --check` exited 0 with only CRLF conversion warnings.
