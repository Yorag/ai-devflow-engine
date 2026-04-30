---
name: slice-workflow
description: Use when asked to execute, continue, plan, or choose one task from this repository's one-slice-at-a-time platform implementation plan under docs/plans/function-one-platform-plan.md.
---

# Slice Workflow

## Overview

Run one platform-plan implementation slice through the repository's required gates. This skill adapts generic Superpowers execution to this repository's platform-plan execution rules, Git rules, split specs, and frontend quality gate.

## Core Rule

Execute exactly one implementation slice per invocation. Do not continue into the next slice unless the user explicitly starts another slice after the current one is verified and reported.

## When Not To Use

- Do not use for ordinary ad hoc features, bug fixes, or reviews outside `docs/plans/function-one-platform-plan.md`.
- Do not use to execute multiple slices in one invocation.
- Do not bypass dependency, status, branch, or source-trace gates because the user named a task id.
- Do not use generic Superpowers defaults that create worktrees, commits, PRs, merges, tags, branch cleanup, or subagent handoffs for this plan.
- Do not use `impeccable` to change product semantics, stage semantics, backend APIs, projection fields, event payloads, or test requirements.

## Required Sources

Read the smallest necessary set, but treat these as the source of truth:

- `AGENTS.md`
- `docs/plans/function-one-platform-plan.md`
- `docs/plans/function-one-platform/*.md`
- `docs/specs/function-one-product-overview-v1.md`
- `docs/specs/frontend-workspace-global-design-v1.md`
- `docs/specs/function-one-backend-engine-design-v1.md`

Do not reintroduce archived feature-one semantics. Use archived docs only when the user explicitly asks for historical comparison.

When split specs overlap, resolve by the repository agreement:

| Topic | Source |
| --- | --- |
| Product and stage boundary | `function-one-product-overview-v1.md` |
| Frontend interaction and presentation semantics | `frontend-workspace-global-design-v1.md` |
| Backend domain model, API, projection, and events | `function-one-backend-engine-design-v1.md` |

## Required Sub-Skills

- **REQUIRED SUB-SKILL:** Use `git-delivery-workflow` for branch and commit gates.
- **REQUIRED SUB-SKILL:** Use `superpowers:writing-plans` before touching implementation code.
- **REQUIRED SUB-SKILL:** Use `superpowers:executing-plans` to execute the written implementation plan.
- **REQUIRED SUB-SKILL:** Use `superpowers:test-driven-development` for each production-code, behavior, test-target, or refactor change.
- **REQUIRED SUB-SKILL:** Use `superpowers:requesting-code-review` after the slice or implementation batch.
- **REQUIRED SUB-SKILL:** Use `superpowers:verification-before-completion` before any completion, fixed, passing, commit-ready, or PR-ready claim.
- **CONDITIONAL SUB-SKILL:** Use `impeccable` for frontend quality-gate slices listed in the platform plan.

## Workflow

1. Announce this skill and the immediate gate being entered.
2. Run the `git-delivery-workflow` branch gate as read-only inspection.
3. Select exactly one eligible slice whose dependencies are complete and whose own status is not complete.
4. Resolve scope from the platform plan and split-plan task details, then run the pre-plan Source Trace Conflict Gate.
5. Use `superpowers:writing-plans` to create or update one implementation plan under `docs/plans/implementation/`.
6. Review the implementation plan before execution.
7. Use `superpowers:executing-plans` as the outer execution process in the main agent session.
8. Inside that execution flow, use `superpowers:test-driven-development` for every subtask that changes production code, behavior, test targets, or refactor structure.
9. Run the code review checkpoint with `superpowers:requesting-code-review`.
10. Run fresh verification with `superpowers:verification-before-completion`.
11. Update task tracking in the platform plan and split plan.
12. If a commit is appropriate, prepare a commit approval request only.

## Git Gate

Use `git-delivery-workflow` branch gate as read-only inspection before planning work. It must answer whether the worktree is clean or mixed, what the current branch objective is, whether this slice continues that objective, whether unrelated user work is present, and what the next Git action is.

Do not run Git write actions proactively. This includes branch creation, branch switching, commits, merges, tags, rebases, worktrees, pushes, PR creation, or branch cleanup. If a Git write action is needed, prepare the request and wait for explicit user approval.

Do not revert user changes. If unrelated edits exist, leave them alone. If they block the selected slice, stop and ask how to separate the work.

If generic Superpowers instructions mention `using-git-worktrees`, `commit`, `finishing-a-development-branch`, `merge`, `PR`, or branch cleanup, replace those steps with the repository flow:

- Generate a verified checkpoint.
- Report changed files and verification evidence.
- Use `git-delivery-workflow` for the relevant gate.
- Ask for explicit approval before any Git write action.

## Slice Selection

If the user names a task id, use that task id. Otherwise identify the next dependency-satisfied incomplete task from:

- `docs/plans/function-one-platform-plan.md`
- the relevant `docs/plans/function-one-platform/*.md` split plan

Do not select multiple slices. Do not combine boundary-setting tasks with unrelated implementation.

### Task Eligibility

A slice is eligible only when all of these are true:

- The task exists in the platform-plan task table and has a matching split-plan detail section.
- The platform-plan task status is `[ ]` or `[/]`, not `[x]`.
- The split-plan task status is `[ ]` or `[/]`, not `[x]`.
- Every predecessor required by the dependency overview, split-plan detail, or task acceptance criteria is complete.
- The task does not need to be separated as an independent plan or independent batch under `references/superpowers-execution-rules.md`.

During slice selection, read `references/superpowers-execution-rules.md` and check the independent plan/batch list before declaring a task eligible.

When selecting the next slice automatically, scan the platform-plan task table in order and choose the first eligible slice. If no eligible slice is found, stop and report whether all tasks are complete, dependencies are incomplete, or status data is inconsistent.

Stop instead of selecting when:

- The platform-plan status and split-plan status disagree.
- A dependency is not recorded as complete.
- A predecessor is unclear or only implied by wording.
- More than one candidate appears to satisfy the same ordering position because of duplicated task ids or broken anchors.
- The user-specified task id is complete, missing, blocked, or conflicts with the current branch/worktree state.

### Superpowers Execution Rules Reference

Read `references/superpowers-execution-rules.md` during slice selection for independent-plan and independent-batch boundaries. Read it again before writing the implementation plan when the selected slice involves frontend presentation quality, `Log & Audit Integration`, API/OpenAPI route checks, or generic `superpowers:writing-plans` defaults that must be overridden.

## Scope Resolution

Before writing the implementation plan, read the selected split-plan task details: files, target classes/functions, acceptance criteria, tests, dependencies, and status.

The selected split-plan task details are the planning baseline because they are reviewed task-level instructions. Use the current specs as supporting trace sources for unclear or missing detail, not as permission to override reviewed task details.

If the task boundary, implementation detail, product boundary, stage semantics, API contract, projection contract, event semantics, or frontend interaction semantics is unclear, trace back to the three current specs. If the specs resolve the missing detail without contradicting the selected task details, carry that trace into the implementation plan. If the specs are silent, ambiguous, or conflict with the selected task details, stop and report the issue to the user with targeted options.

Prefer correction over patching before implementation when an unimplemented area has unclear planning language. Revise planning/spec wording only when asked or when the current task is explicitly a planning/documentation task; draft spec documents still require user review before commit.

## Source Trace Conflict Gate

Use this gate before writing the implementation plan, and again whenever execution exposes a possible conflict, missing rule, or drift risk between the selected slice, implementation plan, existing code, completed tasks, and current specs.

1. Stop local implementation work for the conflicting point.
2. Treat the selected split-plan task details as the baseline.
3. Trace the disputed behavior to the relevant current spec section, using the source-of-truth table above.
4. If the spec clarifies missing task detail without contradicting the selected task details, carry that trace into the implementation plan.
5. If the spec is silent, ambiguous, or conflicts with the selected task details, platform plan, task dependency order, existing implementation, or completed task records, stop the workflow.
6. Report the conflict to the user with file references, the competing interpretations, affected task ids, and a targeted recommendation.
7. Wait for user direction before changing specs, changing plans, narrowing the slice, or implementing code.

Do not use specs to override reviewed task details. Do not choose a semantic interpretation yourself when task details and trace sources do not resolve it. Do not hide the conflict by adding compatibility glue, temporary aliases, broader tests, or implementation-only patch notes.

## Implementation Plan Requirements

### Writing-Plans Overrides

When using `superpowers:writing-plans`, apply this repository's execution rules over the generic skill template. Load `references/superpowers-execution-rules.md` for the detailed overrides.

Use `superpowers:writing-plans` and save the plan as:

```text
docs/plans/implementation/<task-id>-<task-name>.md
```

The plan must include exact file paths, TDD red-green steps, concrete failing test code, concrete implementation code, exact run commands, expected failure and passing output, and a completion verification checklist. Load `references/superpowers-execution-rules.md` for the full implementation-plan checklist.

The plan must not loosen task boundaries, rewrite approved semantics, omit required acceptance criteria, or use placeholders such as TODO/TBD/fill in later.

For `backend/app/api/routes/*` changes, load `references/superpowers-execution-rules.md` and include the API/OpenAPI checklist in the implementation plan.

For user command interfaces, run lifecycle changes, runtime nodes, model calls, tool calls, workspace writes, `bash`, Git delivery, remote delivery, configuration changes, or security-sensitive failures, include `Log & Audit Integration`; load `references/superpowers-execution-rules.md` and carry the applicable checklist into the implementation plan.

## Plan Review Gate

Before execution, review the written implementation plan against:

- The selected split-plan task.
- The platform-plan Superpowers execution rules.
- The relevant current spec sections.
- Completed predecessor tasks and their recorded semantics.

Stop if the plan has critical gaps, contradictory semantics, dependency uncertainty, missing TDD steps, missing expected outputs, missing API/OpenAPI checks, missing log/audit requirements, or missing frontend design gate for an applicable frontend slice.

## Execution Rules

Use `superpowers:executing-plans` as the outer execution process. Execute in the main agent session; do not use `superpowers:subagent-driven-development` as the implementation method for this repository plan.

For each step that changes production code, behavior, test target, or refactor structure:

1. Write one failing test.
2. Run it and confirm the failure reason is expected.
3. Write the minimal implementation.
4. Run the test and confirm it passes.
5. Refactor only after green, keeping tests green.

Do not replace TDD with tests-after. Do not broaden scope while executing. If verification fails repeatedly, stop and report the actual blocker.

## Code Review Checkpoint

After the slice or execution batch, use `superpowers:requesting-code-review`.

Review in this order:

1. Spec and plan compliance.
2. Code quality.
3. Test sufficiency.
4. Regression risk.

Fix Critical and Important findings before claiming completion. If the review mechanism cannot dispatch a reviewer in the current environment, perform the same two-stage review inline and state that limitation in the final report.

## Frontend Design Gate

In Codex, use `impeccable` as the auxiliary frontend quality tool when a slice involves frontend UI/UX design, implementation, review, polish, hardening, visible interaction states, responsive behavior, accessibility, or visual consistency.

Load `references/superpowers-execution-rules.md` for the explicit task ids and `Frontend Design Gate` checklist. The implementation plan for applicable frontend display slices must include that gate.

The design gate controls presentation quality only. It must not override product semantics, stage semantics, runtime controls, backend APIs, projection fields, event payloads, or test requirements.

The design gate does not replace tests. Completion still requires the relevant component, state, API client, Playwright, or responsive verification commands.

## Verification And Tracking

Use `superpowers:verification-before-completion` before saying work is complete, fixed, passing, checkpoint-ready, commit-ready, or PR-ready.

Fresh verification means:

- Run the full commands needed for the changed scope.
- Read the full output and exit code.
- Report failures honestly.
- Do not extrapolate from stale or partial results.

After verification, update only the allowed tracking locations:

- The corresponding task status in `docs/plans/function-one-platform-plan.md`.
- The corresponding split-plan task status, implementation-plan link, and verification summary.

Status updates must follow these rules:

- Mark `[x]` only after all task acceptance criteria are met and fresh verification supports the claim.
- Use or keep `[/]` only when the slice has verified partial progress but still has open acceptance criteria, failed verification, or unresolved review findings.
- Keep `[ ]` when no verified deliverable for that task was completed.
- Do not mark completion when verification failed, was skipped, or covered only part of the acceptance criteria.
- The split-plan tracking note must include the implementation-plan link, verification commands, key result, and any blocker or remaining scope.

Do not update unrelated task statuses.

## Stop Conditions

Stop and report to the user when:

- The worktree has unrelated changes that make the branch gate unsafe.
- The selected slice depends on an incomplete or unclear predecessor.
- The platform plan and split plan conflict.
- A current spec conflicts with the selected task details or implementation plan.
- Current implementation or completed tasks use a different semantic model.
- The three current specs do not resolve an ambiguity.
- A selected slice, implementation plan, existing code path, or completed task record creates a conflict that requires source tracing.
- Source tracing finds no governing spec section or finds conflicting spec/plan/task semantics.
- A frontend quality suggestion would alter product semantics or API/event contracts.
- Generic Superpowers flow asks for Git writes or branch finishing actions.
- An implementation plan lacks concrete TDD steps, code, commands, or expected output.
- Verification repeatedly fails after focused debugging.

When stopping, include the specific conflict, file references, and targeted recommendation. Do not continue by guessing.

## Completion Report

Report:

- Selected slice id and implementation plan path.
- Changed files.
- TDD red/green evidence, or the N/A reason for documentation-only slices.
- Code review result and fixes.
- Verification commands, exit codes, and key output.
- Tracking updates made.
- Remaining risks or blockers.
- Whether a commit approval request is recommended.

If a commit is recommended, use `git-delivery-workflow` commit gate and ask for approval. Do not commit without explicit user approval.

## Common Mistakes

- Selecting a task without checking both platform-plan and split-plan status.
- Treating `superpowers:executing-plans` as a replacement for `superpowers:test-driven-development`.
- Accepting generic `superpowers:writing-plans` commit, worktree, PR, or subagent steps.
- Using specs to override reviewed task details instead of stopping on conflict.
- Continuing after source tracing finds missing, ambiguous, or conflicting governing trace sources.
- Updating unrelated task statuses after verification.
- Skipping the `impeccable` quality gate for visible frontend work.
- Skipping inline code review when a reviewer cannot be dispatched.
