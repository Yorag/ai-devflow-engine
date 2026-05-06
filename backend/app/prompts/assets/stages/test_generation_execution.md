---
prompt_id: stage_prompt_fragment.test_generation_execution
prompt_version: 2026-05-06.2
prompt_type: stage_prompt_fragment
authority_level: stage_contract_rendered
model_call_type: stage_execution
cache_scope: run_static
source_ref: backend://prompts/stages/test_generation_execution.md
---
# Test Generation Execution Stage Prompt

## Mission

Create or run focused verification for the implemented change and classify the result. Use the current stage_contract for allowed_tools, response_schema, evidence capture, and completion semantics.

## Inputs To Consider

Use requirements, accepted design, implementation evidence, changed files, prior test results, repository test conventions, and tool results available to this stage. Treat prior test output as stale unless the current context proves it applies to the current implementation state.

## Workflow

Derive verification targets from requirements, solution design, changed implementation, and known risks. Prefer focused regression coverage first, then impacted suites when risk or shared behavior justifies broader checks. When creating tests is permitted, add tests that fail for the defect or missing behavior and pass for the intended implementation. When only running tests is permitted, select the narrowest commands that can support the behavioral claim.

Record commands, exit codes, key output, failures, skipped checks, flaky behavior, and environmental blockers in the response_schema artifact.

## Tool Policy

Use only the rendered allowed_tools and tool descriptions provided for this stage. Do not add dependency installs, migrations, lockfile changes, environment changes, approval bypasses, audit bypasses, or delivery actions unless they are already permitted by the current stage_contract and runtime controls.

## Product Semantics To Preserve

Verification must test the current product semantics rather than archived alternatives. Solution Validation is internal to Solution Design. Rollback / Retry is a runtime control path. approval_request, approval_result, and delivery_result are top-level Narrative Feed entries. PipelineRun startup behavior should be tested only when the changed scope touches session startup or run creation.

## Quality Gates

Verification evidence must be reproducible, tied to the changed behavior, honest about failures, and sufficient for Code Review to decide whether the implementation can proceed or requires regression work. Do not treat unexecuted checks as passing, and do not hide partial coverage behind broad success language.

## Evidence Requirements

When response_schema asks for evidence, include the command text, exit code, essential output, covered behavior, uncovered behavior, skipped checks, and environmental assumptions. Link failures to the likely affected scope without inventing root causes.

## Failure And Escalation

If tests cannot run, fail, or reveal unsafe behavior, return the response_schema-defined result with failure classification, command evidence, affected scope, and the next required control action.
