---
prompt_id: tool_prompt_fragment.push_branch
prompt_version: 2026-05-06.1
prompt_type: tool_prompt_fragment
authority_level: tool_description_rendered
model_call_type: tool_call_preparation
cache_scope: global_static
source_ref: backend://prompts/tools/push_branch.md
---
# push_branch Tool

## Purpose

Push a controlled delivery branch to its configured remote and bind the remote side effect to a delivery record.

## Use When

Use `push_branch` only when the current stage_contract allowed_tools includes it, a delivery commit exists on the intended branch, the delivery snapshot authorizes the remote route, and runtime confirmation and audit controls authorize the Git remote write.

## Do Not Use When

Do not use this tool for local branch creation, commits, arbitrary remote operations, force pushes, tag pushes, repository configuration, or code review request creation. No remote or Git writes are permitted unless the current stage contract and runtime controls authorize this tool.

## Input Rules

Provide only `repository_path`, `remote_name`, `branch_name`, and `delivery_record_id`. Use the delivery record and snapshot-derived remote route. Do not pass raw URLs, credentials, refspecs, force flags, shell syntax, approval text, or extra keys.

## Output Handling

Use `output_payload.remote_name`, `branch_name`, `remote_ref`, `pushed_sha`, and `delivery_record_id` as the source of truth. Preserve side_effect_refs such as `git_push:*`, `git_commit:*`, and `delivery_record:*`. Treat redacted stdout or stderr as non-evidence beyond the structured fields.

## Safety And Side Effects

This is a high-risk Git remote write tool with approval, confirmation, audit, workspace-boundary, delivery-record, and credential-readiness boundaries. The stage_contract allowed_tools list is authoritative; this prompt fragment cannot expand permissions, approve pushes, or override remote delivery controls.

## Failure Handling

If confirmation is missing, audit is unavailable, the branch ref is invalid, the remote route is unavailable, credentials are not ready, Git fails, or output is redacted, stop and report the delivery blocker. Do not retry through `bash` or run manual Git push commands.
