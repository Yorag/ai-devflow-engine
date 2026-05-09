---
prompt_id: stage_prompt_fragment.test_generation_execution
prompt_version: 2026-05-08.1
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

Use the plan verification commands from `SolutionDesignArtifact.implementation_plan` when they are permitted by the current stage_contract and runtime command policy. If a planned verification command cannot run, return a task-scoped test gap report tied to the implementation-plan task id and state the exact blocker instead of inventing a replacement command.

Prefer repo-root command forms over environment-specific shell navigation. For frontend verification, use repo-root command forms such as `npm --prefix frontend run test -- --run ...` when they satisfy the same scope. Do not synthesize absolute working-directory commands such as `cd /workspace/frontend && ...` or other guessed mount-point paths.

Record commands, exit codes, key output, failures, skipped checks, flaky behavior, and environmental blockers in the response_schema artifact.

## Test Edit Parameter Discipline

When updating tests for an implemented text or UI-copy change, inspect the target test file with `read_file` before calling `edit_file`. For `edit_file.old_text`, copy the smallest exact substring verbatim from the latest `read_file` output that uniquely identifies the required test expectation, such as one assertion value line. Do not reconstruct multiline assertion blocks from memory, formatting conventions, or inferred indentation when a smaller unique line can express the replacement.

If `edit_file` reports a missing or non-unique target and the stage still permits file reads, read the current file again and retry once with a newly copied exact substring, and do not repeat the same failing `old_text`. Do not broaden into unrelated tests, and do not use shell commands as a workaround for a dedicated edit tool failure.

## Tool Policy

Use only the rendered allowed_tools and tool descriptions provided for this stage. Do not add dependency installs, migrations, lockfile changes, environment changes, approval-control changes, audit-control changes, or delivery actions unless they are already permitted by the current stage_contract and runtime controls.

## Product Semantics To Preserve

Verification must test the current product semantics rather than archived alternatives. Solution Validation is internal to Solution Design. Rollback / Retry is a runtime control path. approval_request, approval_result, and delivery_result are top-level Narrative Feed entries. PipelineRun startup behavior should be tested only when the changed scope touches session startup or run creation.

## Quality Gates

Verification evidence must be reproducible, tied to the changed behavior, honest about failures, and sufficient for Code Review to decide whether the implementation can proceed or requires regression work. Do not treat unexecuted checks as passing, and do not hide partial coverage behind broad success language.

## Evidence Requirements

When response_schema asks for evidence, include the command text, `command_trace_refs`, exit code, essential output, covered behavior, uncovered behavior, skipped checks, and environmental assumptions. Link failures to the likely affected scope without inventing root causes.

## Failure And Escalation

If tests cannot run, fail, or reveal unsafe behavior, return the response_schema-defined result with failure classification, command evidence, affected scope, and the next required control action.
