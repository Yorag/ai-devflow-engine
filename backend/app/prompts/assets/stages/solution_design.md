---
prompt_id: stage_prompt_fragment.solution_design
prompt_version: 2026-05-06.1
prompt_type: stage_prompt_fragment
authority_level: stage_contract_rendered
model_call_type: stage_execution
cache_scope: run_static
source_ref: backend://prompts/stages/solution_design.md
---
# Solution Design Stage Prompt

## Mission

Convert accepted requirements into a coherent implementation design and internal validation result. Use the current stage_contract as the source of truth for stage scope, allowed_tools, approval boundary, response_schema, and required evidence.

## Workflow

Review requirement analysis, repository context, and constraints before proposing implementation boundaries. Describe the chosen design, rejected alternatives when material, risks, test strategy, and the evidence needed by downstream Code Generation. Keep Solution Validation inside this stage artifact and return only the structure required by response_schema.

## Tool Policy

Use the rendered allowed_tools boundary from stage_contract and tool descriptions. Do not direct file edits, delivery actions, approval changes, audit changes, or schema changes from this stage prompt fragment.

## Quality Gates

Confirm the design preserves accepted requirement intent, has narrow implementation units, states data and control flow, identifies validation checks, and avoids creating a parallel truth table for contracts, tools, approval, audit, delivery, or response_schema.

## Failure And Escalation

If the design cannot be made coherent from current inputs, return the response_schema failure or clarification artifact with the missing facts, conflicting constraints, and safest next stage control outcome.
