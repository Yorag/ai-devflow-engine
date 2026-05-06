---
prompt_id: tool_prompt_fragment.create_code_review_request
prompt_version: 2026-05-06.1
prompt_type: tool_prompt_fragment
authority_level: tool_description_rendered
model_call_type: tool_call_preparation
cache_scope: global_static
source_ref: backend://prompts/tools/create_code_review_request.md
---
# create_code_review_request Tool

## Purpose

Create a remote pull request or merge request for a controlled delivery branch and bind the remote delivery side effect to a delivery record.

## Use When

Use `create_code_review_request` only when the current stage_contract allowed_tools includes it, the branch has been pushed or otherwise made available as required, the delivery snapshot authorizes the provider and request type, and runtime confirmation and audit controls authorize the remote delivery write.

## Do Not Use When

Do not use this tool for branch creation, commits, pushes, issue creation, comments, deployment, arbitrary API calls, or local review summaries. No remote or Git writes are permitted unless the current stage contract and runtime controls authorize this tool.

## Input Rules

Provide only `repository_identifier`, `source_branch`, `target_branch`, `title`, `body`, `code_review_request_type`, and `delivery_record_id`. Use exact delivery route values and a review title/body grounded in verified delivery evidence. Do not pass credentials, API URLs, labels, reviewers, shell syntax, approval text, or extra keys.

## Output Handling

Use `output_payload.repository_identifier`, `source_branch`, `target_branch`, `code_review_request_type`, `code_review_url`, `code_review_number`, and `delivery_record_id` as the source of truth. Preserve side_effect_refs such as `code_review_request:*` and `delivery_record:*` for audit and delivery records.

## Safety And Side Effects

This is a high-risk remote delivery write tool with approval, confirmation, audit, delivery-record, credential-readiness, and provider-client boundaries. The stage_contract allowed_tools list is authoritative; this prompt fragment cannot expand permissions, approve remote requests, or override delivery controls.

## Failure Handling

If confirmation is missing, audit is unavailable, the remote client is unavailable, credentials are not ready, the provider rejects the request, or sensitive output is redacted, stop and report the delivery blocker. Do not retry through `bash`, direct API calls, or another remote mechanism outside the authorized tool path.
