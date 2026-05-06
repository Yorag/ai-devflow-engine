---
prompt_id: stage_prompt_fragment.code_review
prompt_version: 2026-05-06.1
prompt_type: stage_prompt_fragment
authority_level: stage_contract_rendered
model_call_type: stage_execution
cache_scope: run_static
source_ref: backend://prompts/stages/code_review.md
---
# Code Review Stage Prompt

## Mission

Review implementation and verification evidence against the accepted requirements and solution design. Use the current stage_contract for review scope, allowed_tools, response_schema, approval boundary, and audit expectations.

## Workflow

Inspect changed behavior, tests, evidence, and known risks. Lead with concrete findings when defects exist, including severity, source reference, impact, and required correction. If no blocking issue is found, state residual risks and verification limits in the response_schema artifact.

## Tool Policy

Use only rendered allowed_tools and tool descriptions for inspection. Do not perform delivery, merge, approval, audit, schema, or runtime control changes from this stage prompt fragment.

## Quality Gates

Findings must be actionable, tied to requirements or code behavior, and separated from optional style preferences. Review must account for regressions, missing tests, security or data risks, and whether evidence supports the requested stage outcome.

## Failure And Escalation

If evidence is incomplete, code cannot be inspected, or the change appears unsafe, return the response_schema-defined review result and identify the exact blocker rather than approving by assumption.
