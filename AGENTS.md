# AGENTS.md

## Purpose

This file records project-level collaboration rules for AI agents working in this repository.

## Git Hooks

1. Use the repo-local skill `git-delivery-workflow` at `.codex/skills/git-delivery-workflow` before starting non-trivial development, deciding whether to create or reuse a branch, proposing a commit, proposing a PR, merging to `main`, or preparing a release branch or tag.

2. Do not run Git write actions proactively.
The agent may propose `branch`, `commit`, `merge`, `tag`, or branch cleanup actions when the workflow says they are ready, but must wait for explicit user approval before running them.

3. Do not submit or commit spec documents before user review.
Keep draft spec documents in the working tree until the user explicitly approves them.

## Project Constraints

1. Do not treat `Must-have` as the full quality target.
The baseline requirements are minimum scope only. Design and implementation must also consider information loss across stages, requirement understanding quality, solution rationality, code safety, and test sufficiency.

2. Prioritize workflow orchestration over isolated code generation.
This repository focuses on stage orchestration, artifact handoff, review loops, and end-to-end delivery.

3. Reserve backend extension points for feature two.
Feature one work must preserve reusable backend concepts and APIs for future support of selection-driven webpage editing, especially `ChangeSet`, `ContextReference`, `PreviewTarget`, and `DeliveryRecord`.

4. Write specifications in neutral, explicit project language.
Do not use competition-facing phrasing such as "for judges", "for contest demo", or "for defense". Do not use uncertain wording such as `建议`, `推荐`, `尽量`, or similar language in formal spec documents.

## Current Working Agreement

- The baseline accepted specification is:
  `docs/specs/function-one-design-v1.md`
- The current active document under review is:
  `docs/specs/function-one-design-v2.md`
- The user must review and approve any spec document before any commit related to that spec.
