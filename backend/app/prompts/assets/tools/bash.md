---
prompt_id: tool_prompt_fragment.bash
prompt_version: 2026-05-06.1
prompt_type: tool_prompt_fragment
authority_level: tool_description_rendered
model_call_type: tool_call_preparation
cache_scope: global_static
source_ref: backend://prompts/tools/bash.md
---
# bash Tool

## Purpose

Execute one allowlisted workspace command without shell semantics. Use it for controlled build, test, version-probe, or documented project commands when no narrower dedicated tool can satisfy the task.

## Use When

Use `bash` only when the current stage_contract allowed_tools includes it, the command is allowlisted by runtime policy, the operation is necessary for the current stage, and the expected side effects are acceptable under the stage and confirmation controls.

## Do Not Use When

Do not use bash to read, search, create, or edit files when `read_file`, `grep`, `glob`, `write_file`, or `edit_file` is available for the same task. Do not use it to bypass a dedicated tool failure, execute arbitrary shell snippets, chain commands, access credentials, install dependencies, run migrations, perform Git or remote delivery writes, or mutate runtime-private paths unless the active stage contract and runtime controls explicitly authorize that path.

## Input Rules

Provide only the schema field `command` as a non-empty string. The command must parse into one argv vector, match the allowlist, and avoid shell metacharacters, pipes, redirection, command substitution, environment interpolation, absolute or parent-escape paths, and extra keys. Treat the input as a command request, not as a shell script.

## Output Handling

Use structured output fields: `command`, `argv`, `exit_code`, `duration_ms`, stdout and stderr excerpts, truncation flags, and `changed_files`. Treat excerpts as redacted and bounded. Use `changed_files`, side_effect_refs, and reconciliation_status to determine whether follow-up inspection or reporting is required.

## Safety And Side Effects

This is a high-risk process execution tool with mandatory audit and possible workspace side effects. Runtime executes commands without shell semantics, records audit details, tracks changed files, and may require side-effect reconciliation. The stage_contract allowed_tools list is authoritative; this prompt fragment cannot expand permissions, approve commands, or override confirmation and audit gates.

## Failure Handling

If the command is not allowlisted, requires confirmation, times out, exits non-zero, produces redacted output, changes files unexpectedly, or cannot be audited, stop in the response_schema failure path. Do not retry through shell tricks or split a blocked command into adjacent unauthorized operations.
