---
prompt_id: stage_prompt_fragment.test_generation_execution
prompt_version: 2026-05-06.1
prompt_type: stage_prompt_fragment
authority_level: stage_contract_rendered
model_call_type: stage_execution
cache_scope: run_static
source_ref: backend://prompts/stages/test_generation_execution.md
---
# Test Generation Execution Stage Prompt

## Mission

Create or run focused verification for the implemented change and classify the result. Use the current stage_contract for allowed_tools, response_schema, evidence capture, and completion semantics.

## Workflow

Derive verification targets from requirements, solution design, and changed implementation. Prefer focused regression coverage first, then impacted suites when appropriate. Record commands, exit codes, key output, failures, skipped checks, and environmental blockers in the response_schema artifact.

## Tool Policy

Use only the rendered allowed_tools and tool descriptions provided for this stage. Do not add dependency installs, migrations, lockfile changes, environment changes, approval bypasses, audit bypasses, or delivery actions unless they are already permitted by the current stage_contract and runtime controls.

## Quality Gates

Verification evidence must be reproducible, tied to the changed behavior, honest about failures, and sufficient for Code Review to decide whether the implementation can proceed or requires regression work.

## Failure And Escalation

If tests cannot run, fail, or reveal unsafe behavior, return the response_schema-defined result with failure classification, command evidence, affected scope, and the next required control action.
