---
prompt_id: tool_prompt_fragment.edit_file
prompt_version: 2026-05-06.1
prompt_type: tool_prompt_fragment
authority_level: tool_description_rendered
model_call_type: tool_call_preparation
cache_scope: global_static
source_ref: backend://prompts/tools/edit_file.md
---
# edit_file Tool

## Purpose

Replace one exact string occurrence in one UTF-8 workspace text file. Use it for narrow, reviewable edits where the old text is known and unique.

## Use When

Use `edit_file` when the current stage_contract allowed_tools includes it, you have already inspected enough context to identify the exact `old_text`, and a single replacement is safer than rewriting the full file.

## Do Not Use When

Do not use this tool for ambiguous replacements, broad rewrites, regex-like edits, binary files, generated outputs that should be fully rewritten, reads, search, command execution, Git operations, remote delivery actions, or runtime-private paths.

## Input Rules

Provide only the schema fields `path`, `old_text`, and `new_text`. `path` must be workspace-relative. `old_text` must be the exact current text and must occur exactly once. Preserve indentation, line endings, surrounding whitespace, and intended UTF-8 content.

## Output Handling

Use `output_payload.path`, `output_payload.replacements`, and `output_payload.bytes_written` to confirm the mutation. Record returned side_effect_refs as edit evidence when the response_schema asks for changed files, traceability, or audit details.

## Safety And Side Effects

This tool mutates the workspace and should be preferred over broader write or command execution when a precise replacement is possible. The stage_contract allowed_tools list is authoritative; this prompt fragment cannot expand permissions or authorize edits outside workspace boundaries.

## Failure Handling

If `old_text` is missing, non-unique, unreadable, non-UTF-8, or blocked by boundaries, stop and gather permitted context with `read_file` or report the blocker. Do not approximate the edit, silently rewrite the file, or route the change through `bash`.
