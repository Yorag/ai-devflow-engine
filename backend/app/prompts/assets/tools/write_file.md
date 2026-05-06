---
prompt_id: tool_prompt_fragment.write_file
prompt_version: 2026-05-06.1
prompt_type: tool_prompt_fragment
authority_level: tool_description_rendered
model_call_type: tool_call_preparation
cache_scope: global_static
source_ref: backend://prompts/tools/write_file.md
---
# write_file Tool

## Purpose

Create or fully overwrite one UTF-8 text file in the current run workspace. Use it when the intended operation is a complete file write rather than an exact in-place replacement.

## Use When

Use `write_file` when the current stage_contract allowed_tools includes it and the stage requires creating a new text artifact, replacing a whole generated file, or writing a complete file body that has been deliberately constructed.

## Do Not Use When

Do not use this tool for small targeted edits to an existing file when `edit_file` can express the change safely. Do not use it for reads, search, path discovery, command execution, dependency installation, migrations, Git operations, remote delivery actions, or runtime-private paths.

## Input Rules

Provide only the schema fields `path` and `content`. Use a workspace-relative `path` and complete UTF-8 `content` for the final intended file body. Do not pass partial patches, shell commands, binary data, absolute paths, parent-directory escapes, or extra keys.

## Output Handling

Use `output_payload.path` and `output_payload.bytes_written` to confirm the write target and byte count. Record the returned side_effect_refs as file-write evidence when the response_schema asks for changed files or audit traceability.

## Safety And Side Effects

This tool mutates the workspace and requires the runtime side-effect path, including audit when enforced by the tool gate. The stage_contract allowed_tools list is authoritative; this prompt fragment cannot expand permissions, approve writes, or authorize overwriting unrelated files.

## Failure Handling

If the write fails because of boundary checks, excluded paths, missing confirmation, audit failure, or filesystem errors, do not retry through `bash` or broaden the target. Report the precise blocker and preserve any returned side-effect or audit references.
