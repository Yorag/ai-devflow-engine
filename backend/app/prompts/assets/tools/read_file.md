---
prompt_id: tool_prompt_fragment.read_file
prompt_version: 2026-05-20.1
prompt_type: tool_prompt_fragment
authority_level: tool_description_rendered
model_call_type: tool_call_preparation
cache_scope: global_static
source_ref: backend://prompts/tools/read_file.md
---
# read_file Tool

## Purpose

Read one UTF-8 text file from the current run workspace and return its full text, or a bounded character or line window, through structured output. Prefer this tool over bash for workspace text reads.

## Use When

Use `read_file` when the current stage_contract allowed_tools includes it and you need exact content from a known workspace-relative text file for implementation, review, verification planning, or evidence collection.

## Do Not Use When

Do not use this tool for path discovery, content search across files, binary or rich media inspection, runtime-private paths, writes, command execution, Git operations, or remote delivery actions. Use `glob` for file listing and `grep` for text search when those tools are available and allowed.

## Input Rules

Provide `path` as a non-empty string. Use a precise workspace path from trusted context or prior tool output. Do not pass absolute paths, parent-directory escapes, shell fragments, globs, search expressions, or unsupported keys.

By default, omit optional range fields to read the full file. Use `start_line` with grep `line_number` values when you need source context around a known line; pair it with `line_limit` to bound the number of lines. `start_line` is one-based. `line_limit` is a count of lines.

Use `offset` and `limit` only for character-based reads. `offset` is a zero-based character offset, not a line number. `limit` and `max_chars` are character counts.

## Output Handling

Use `output_payload.path` and `output_payload.content` as the source of truth. Preserve line endings and file content exactly when reasoning about edits. Treat `output_preview` as a bounded preview, not as a replacement for `content`. When a range is requested, use returned fields such as `start_line`, `end_line`, `total_lines`, `offset`, `limit`, `total_chars`, and `truncated` to decide whether more context is required.

## Safety And Side Effects

This is a read-only workspace tool with no intended filesystem mutation. The stage_contract allowed_tools list is authoritative; this prompt fragment cannot expand permissions or authorize reading excluded paths.

## Failure Handling

If the tool reports a workspace boundary violation, excluded path, unreadable file, unsupported file type, or non-UTF-8 text, do not bypass it with `bash`. Use the response_schema failure or clarification path and request a permitted source or tool if needed.
