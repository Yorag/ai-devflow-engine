---
prompt_id: tool_prompt_fragment.grep
prompt_version: 2026-05-06.1
prompt_type: tool_prompt_fragment
authority_level: tool_description_rendered
model_call_type: tool_call_preparation
cache_scope: global_static
source_ref: backend://prompts/tools/grep.md
---
# grep Tool

## Purpose

Search workspace text content with local ripgrep and return structured matches. Prefer this ripgrep-backed tool over bash `grep`, `findstr`, or ad hoc search commands.

## Use When

Use `grep` when the current stage_contract allowed_tools includes it and you need to locate symbols, strings, contracts, tests, references, or patterns across a workspace path before reading specific files or planning edits.

## Do Not Use When

Do not use this tool for known-file full reads, path-only discovery, file creation, file edits, build or test execution, Git operations, or remote delivery actions. Use `read_file` for exact file content after search results identify the relevant file.

## Input Rules

Provide only the schema fields `pattern` and `path` as non-empty strings. Keep `path` workspace-relative and scope it as tightly as practical. Provide the search expression as data, not as shell flags or a command line. Do not include shell pipes, redirection, command substitution, parent-directory escapes, or extra keys.

## Output Handling

Use `output_payload.matches` and `output_payload.truncated` as the source of truth. Each match contains `path`, `line_number`, `snippet`, and `snippet_truncated`. Read the full file with `read_file` before making exact edits or conclusions that depend on surrounding context.

## Safety And Side Effects

This is a read-only workspace search tool with no intended mutation. The stage_contract allowed_tools list is authoritative; this prompt fragment cannot expand permissions or authorize searching excluded paths.

## Failure Handling

If ripgrep is unavailable, a path is rejected, output is truncated, or matches are insufficient, report the limitation or narrow the search within allowed tool boundaries. Do not bypass a failure with bash grep/findstr or broad shell search when `grep` is available for the same task.
