---
prompt_id: tool_prompt_fragment.create_commit
prompt_version: 2026-05-06.1
prompt_type: tool_prompt_fragment
authority_level: tool_description_rendered
model_call_type: tool_call_preparation
cache_scope: global_static
source_ref: backend://prompts/tools/create_commit.md
---
# create_commit Tool

## Purpose

Stage eligible workspace changes and create a controlled delivery commit tied to a delivery record.

## Use When

Use `create_commit` only when the current stage_contract allowed_tools includes it, the delivery branch is prepared, the intended changes are verified and coherent, and runtime confirmation and audit controls authorize the Git write.

## Do Not Use When

Do not use this tool for speculative commits, unrelated worktree cleanup, runtime log capture, branch creation, pushing, code review request creation, or any commit not tied to the active delivery record. No remote or Git writes are permitted unless the current stage contract and runtime controls authorize this tool.

## Input Rules

Provide only `repository_path`, `commit_message`, and `delivery_record_id`. The commit message must describe the approved delivery changes and must not contain secrets, shell syntax, or unreviewed instructions. Do not pass file lists, Git flags, credentials, approval text, or extra keys.

## Output Handling

Use `output_payload.commit_sha`, `changed_files`, and `delivery_record_id` as the source of truth. Preserve side_effect_refs such as `git_commit:*` and `delivery_record:*` for downstream delivery evidence. Do not treat success as proof that the branch was pushed or a review request exists.

## Safety And Side Effects

This is a high-risk Git write tool with approval, confirmation, audit, workspace-boundary, and delivery-record boundaries. Runtime may exclude private runtime logs and record changed files. The stage_contract allowed_tools list is authoritative; this prompt fragment cannot expand permissions or approve commits.

## Failure Handling

If confirmation is missing, audit is unavailable, there are no eligible changes, workspace checks fail, Git fails, or changed files differ from expected scope, stop and report the blocker. Do not retry through `bash`, manually stage files, or create a different commit outside the delivery tool path.
