---
prompt_id: tool_prompt_fragment.glob
prompt_version: 2026-05-08.3
prompt_type: tool_prompt_fragment
authority_level: tool_description_rendered
model_call_type: tool_call_preparation
cache_scope: global_static
source_ref: backend://prompts/tools/glob.md
---
# glob Tool

## Purpose

List workspace-relative file paths that match one glob pattern. Use it to discover candidate files before reading, searching, editing, or reporting path evidence.

## Use When

Use `glob` when the current stage_contract allowed_tools includes it and you need deterministic path discovery inside the current run workspace, especially before selecting specific files for `read_file`, `grep`, or targeted edits.

## Do Not Use When

Do not use this tool to read file contents, search text inside files, create or edit files, execute commands, inspect excluded runtime-private paths, or perform Git and delivery operations.

## Input Rules

Provide only the schema field `pattern` as a non-empty string. Use a relative glob pattern scoped to the workspace. Do not pass absolute paths, drive-qualified paths, parent-directory escapes, shell pipelines, command substitutions, or extra keys.

Do not use repository-wide discovery such as `**/*` unless the requirement explicitly asks for a whole-repository inventory. Do not use workspace-wide `**/` patterns such as `**/*.html`, `**/*.tsx`, or `**/package.json` when a product surface or prior artifact provides a narrower path. Prefer patterns that name the inferred product area, file family, or feature surface, for example `frontend/src/**/*.tsx` for a frontend component search. If the requirement provides exact visible text or a symbol, prefer `grep` before `glob`.

Do not use `glob` after grep has already found a relevant source file for the requirement. Glob is only for path discovery when text search cannot identify the target path or when the requirement is path-structure oriented.

## Output Handling

Use `output_payload.matches` as the source of truth. Each returned item has `path` and `path_type`; only file matches are returned. Treat an empty matches list as evidence of no visible file match for that pattern, not proof that the repository lacks related content outside the allowed workspace.

## Safety And Side Effects

This is a read-only workspace discovery tool. The stage_contract allowed_tools list is authoritative; this prompt fragment cannot expand permissions or authorize path access beyond workspace and exclusion boundaries.

## Failure Handling

If a glob pattern is rejected or returns no useful matches, narrow or correct the pattern only within the same allowed tool boundary. Do not fall back to `bash` path enumeration when `glob` is available for the same task.
