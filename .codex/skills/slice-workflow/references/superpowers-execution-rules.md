# Superpowers Execution Rules Reference

Load this file when the selected slice needs platform-plan Superpowers execution-rule detail, frontend presentation quality checks, API/OpenAPI route checks, or log/audit requirements. Keep the stop rules, Git rules, TDD rules, and verification rules in `SKILL.md` authoritative.

## Independent Plans Or Batches

These require independent implementation plans or independent execution batches:

- First pass for data models and enums.
- First pass for OpenAPI and frontend client generation strategy.
- First pass for Run lifecycle state machine.
- First pass for Narrative Feed top-level entry semantics.
- First pass for DeliveryChannel and final approval blocking semantics.
- First pass for `PlatformRuntimeSettings` and run snapshot semantics.
- First pass for `PromptAsset` Schema, built-in prompt asset directory, and PromptRenderer consumption boundary.
- First pass for LangGraph runtime and `deterministic test runtime` interface boundary.
- First pass for tool confirmation and human approval boundary.
- First pass for tool risk classification and execution gate.

If a selected slice appears to cross one of these boundaries and the current task does not isolate it, use the Source Trace Conflict Gate in `SKILL.md`.

## Writing-Plans Overrides

When using `superpowers:writing-plans`, apply this repository's execution rules over the generic skill template:

- Save plans to `docs/plans/implementation/<task-id>-<task-name>.md`, not `docs/superpowers/plans/`.
- The plan header must name `superpowers:executing-plans` as the execution skill. Do not recommend `superpowers:subagent-driven-development`.
- Do not offer the generic execution choice between subagent-driven and inline execution; this repository uses main-agent inline execution with `superpowers:executing-plans`.
- Do not include commit steps, commit commands, Git worktree setup, branch finishing, PR creation, merge, tag, or branch cleanup steps.
- Replace any generic "frequent commits" instruction with verified checkpoints and commit approval requests.
- If the implementation plan needs a final Git step, write it as "prepare a commit approval request with `git-delivery-workflow` after fresh verification"; do not write `git add` or `git commit` commands.
- Keep the writing-plans requirement for concrete file paths, concrete test code, concrete implementation code, exact commands, expected failure output, expected passing output, and self-review.

## Implementation Plan Checklist

Each implementation plan must include:

- File list with exact create, modify, and test paths.
- TDD red-green steps.
- Concrete failing test code.
- Concrete implementation code.
- Exact run commands.
- Expected failure output and expected passing output.
- Completion verification checklist.

## API And OpenAPI Checks

For `backend/app/api/routes/*` changes, the implementation plan must include local API tests and `/api/openapi.json` assertions for:

- Path.
- Method.
- Request schema.
- Response schema.
- Major error responses.

## Log & Audit Integration

For user command interfaces, run lifecycle changes, runtime nodes, model calls, tool calls, workspace writes, `bash`, Git delivery, remote delivery, configuration changes, or security-sensitive failures, the implementation plan must include `Log & Audit Integration`:

- Runtime log category, audit action, associated objects, and failure result.
- `request_id`, `trace_id`, `correlation_id`, `span_id`, and `parent_span_id` generation or inheritance.
- Sensitive field redaction, blocking, summarization, and payload size limits.
- Behavior when log write, audit write, or `log.db` indexing fails.
- Tests proving logs do not replace domain objects, domain events, Narrative Feed, Inspector, or product state truth.

## Frontend Design Gate

Use `impeccable` for these frontend quality-gate slices:

- `F2.3-F2.6`
- `F3.3-F3.7`
- `F4.1-F4.4`
- `F4.3a`
- `F5.1-F5.2b`
- `H4.2`
- `F0.1`
- `V6.2`, `V6.3`, `V6.6`, `V6.7`, `V6.8`

Use it for pure API client, mock fixture, or state merge slices only when visible UI is introduced.

The implementation plan for applicable frontend display slices must include `Frontend Design Gate`:

- Tone source and inherited project tone.
- Default tone when no reference exists: quiet, professional, high-information-density workspace UI.
- Reference boundary: what is adopted and what is not copied.
- Reconfirmation conditions.
- Pre-implementation information hierarchy, layout, state, interaction path, and responsive strategy.
- Post-implementation accessibility, responsive, overflow, contrast, focus, and visual anti-pattern review.
- Pre-delivery hardening for empty, loading, error, disabled, long text, history, and edge states.
- Reported findings, handled items, remaining risks, and verification evidence.

The main agent must establish or inherit the project tone before `F0.1` or the first visible frontend slice. If the user provided no reference, record the default workspace tone and continue; do not block implementation for missing style input.
