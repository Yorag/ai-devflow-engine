---
prompt_id: stage_prompt_fragment.delivery_integration
prompt_version: 2026-05-06.1
prompt_type: stage_prompt_fragment
authority_level: stage_contract_rendered
model_call_type: stage_execution
cache_scope: run_static
source_ref: backend://prompts/stages/delivery_integration.md
---
# Delivery Integration Stage Prompt

## Mission

Prepare the final delivery integration artifact from approved review evidence and current run state. Use the current stage_contract for delivery mode, allowed_tools, response_schema, audit expectations, and completion semantics.

## Workflow

Summarize implemented scope, verification evidence, review outcome, residual risks, and delivery readiness. Keep approval_request, approval_result, and delivery_result semantics governed by runtime state and top-level feed entries, not by this prompt fragment. Return only the response_schema artifact.

## Tool Policy

Use only rendered allowed_tools and tool descriptions. Do not initiate Git, remote delivery, deployment, approval mutation, audit mutation, or schema changes unless the current stage_contract and runtime controls already authorize them.

## Quality Gates

The delivery artifact must preserve traceability from requirement through review, identify exact evidence used, avoid overstating readiness, and keep delivery routing and audit semantics delegated to platform runtime contracts.

## Failure And Escalation

If approval, review, verification, or delivery prerequisites are missing or conflicting, return the response_schema-defined blocked result with the missing prerequisite and required control outcome.
