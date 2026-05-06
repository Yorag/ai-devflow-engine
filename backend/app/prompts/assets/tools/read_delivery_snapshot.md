---
prompt_id: tool_prompt_fragment.read_delivery_snapshot
prompt_version: 2026-05-06.1
prompt_type: tool_prompt_fragment
authority_level: tool_description_rendered
model_call_type: tool_call_preparation
cache_scope: global_static
source_ref: backend://prompts/tools/read_delivery_snapshot.md
---
# read_delivery_snapshot Tool

## Purpose

Read the frozen delivery channel snapshot for the current run so delivery integration can reason from recorded delivery configuration, readiness, credential status, and repository metadata.

## Use When

Use `read_delivery_snapshot` when the current stage_contract allowed_tools includes it and delivery integration requires the authoritative delivery channel snapshot before preparing branch, commit, push, or code review request steps.

## Do Not Use When

Do not use this tool to infer approval, mutate delivery records, inspect repository files, perform Git writes, push branches, create code review requests, or bypass missing delivery readiness. It reads delivery state only.

## Input Rules

Provide only the schema field `run_id` as a non-empty string matching the active trace run. Do not pass repository paths, branch names, credentials, approval text, delivery overrides, or extra keys.

## Output Handling

Use `output_payload.delivery_channel_snapshot_ref` and `output_payload.delivery_channel_snapshot` as the source of truth. Preserve readiness status, credential status, delivery mode, repository identifier, default branch, and code review request type exactly as returned. Treat artifact_refs as delivery evidence.

## Safety And Side Effects

This is a read-only delivery tool, but audit is still part of the delivery boundary. The stage_contract allowed_tools list is authoritative; this prompt fragment cannot expand permissions, approve delivery, or authorize remote or Git writes.

## Failure Handling

If the snapshot is missing, incomplete, owned by another run, not ready, or has unavailable credentials, stop the delivery path and report the missing prerequisite. Do not synthesize repository configuration or continue to write-oriented delivery tools without an authorized ready snapshot.
