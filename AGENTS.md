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

## Frontend Skill Usage

1. For frontend UI/UX design, implementation, review, polish, or hardening work, Codex agents may use the global `impeccable` skill as an auxiliary design quality tool.

2. Impeccable output must not override product semantics, stage semantics, backend API contracts, projection contracts, event semantics, or test requirements. Frontend work remains governed by the current split specifications and verified by the repository's normal test and review commands.

## Current Working Agreement

- Archived reference documents only:
  `docs/archive/function-one-design-v1.md`
  `docs/archive/function-one-design-v2.md`
- The current feature one split specification set under review is:
  `docs/specs/function-one-product-overview-v1.md`
  `docs/specs/frontend-workspace-global-design-v1.md`
  `docs/specs/function-one-backend-engine-design-v1.md`
- When the current split specifications overlap, resolve by:
  product boundary and stage boundary: `docs/specs/function-one-product-overview-v1.md`
  frontend interaction and presentation semantics: `docs/specs/frontend-workspace-global-design-v1.md`
  backend domain model, API contract, projection contract, and event semantics: `docs/specs/function-one-backend-engine-design-v1.md`
- Do not reintroduce archived feature one semantics. In the current split specs, `Solution Validation` is internal to `Solution Design`, `Rollback / Retry` is a runtime control node, `approval_request` / `approval_result` / `delivery_result` are top-level Narrative Feed entries, and the first `new_requirement` auto-starts a `PipelineRun`.
- The user must review and approve any spec document in the current feature one split specification set before any commit related to those specs.
