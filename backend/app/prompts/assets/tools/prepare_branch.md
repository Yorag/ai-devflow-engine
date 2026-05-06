---
prompt_id: tool_prompt_fragment.prepare_branch
prompt_version: 2026-05-06.1
prompt_type: tool_prompt_fragment
authority_level: tool_description_rendered
model_call_type: tool_call_preparation
cache_scope: global_static
source_ref: backend://prompts/tools/prepare_branch.md
---
# prepare_branch Tool

## Purpose

Create a controlled delivery branch from a base branch and bind the side effect to a delivery record.

## Use When

Use `prepare_branch` only when the current stage_contract allowed_tools includes it, delivery readiness has been established, the branch operation is required for the current delivery record, and runtime confirmation and audit controls authorize the Git write.

## Do Not Use When

Do not use this tool for ordinary workspace navigation, branch inspection, local experimentation, speculative branch creation, remote pushes, commits, code review requests, or any Git write not tied to the active delivery record. No remote or Git writes are permitted unless the current stage contract and runtime controls authorize this tool.

## Input Rules

Provide only `repository_path`, `branch_name`, `base_branch`, and `delivery_record_id`. Use exact values from the delivery plan or snapshot-derived delivery context. Do not pass shell syntax, Git flags, multiple branch names, credentials, remote names, approval text, or extra keys.

## Output Handling

Use `output_payload.branch_name`, `base_branch`, `head_sha`, and `delivery_record_id` as the delivery evidence. Preserve side_effect_refs such as `git_branch:*` and `delivery_record:*` for audit and reconciliation. Do not treat success as commit, push, or review-request completion.

## Safety And Side Effects

This is a high-risk Git write tool with approval, confirmation, audit, workspace-boundary, and delivery-record boundaries. The stage_contract allowed_tools list is authoritative; this prompt fragment cannot expand permissions or approve branch creation.

## Failure Handling

If confirmation is missing, audit is unavailable, repository boundary checks fail, refs are invalid, the base branch cannot be used, or Git returns an error, stop and report the delivery blocker. Do not retry through `bash` or issue manual Git commands.
