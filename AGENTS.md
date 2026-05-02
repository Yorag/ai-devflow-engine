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

5. Prefer correction over patching before implementation.
When a project area or feature has not been formally implemented, revise planning and specification documents directly for coherent structure, wording, and semantics instead of layering patch-style notes, provided the revision does not change approved functional intent.

## Local Environment And Verification

1. Backend Python commands must prefer the repository-local uv environment.
Use `uv run <command>` by default. The repo-local virtual environment interpreter such as `.\.venv\Scripts\python` is an acceptable fallback when `uv run` is not suitable. Do not run backend verification through a global Python interpreter.

2. Do not install Python packages globally.
Backend dependencies must be declared in `pyproject.toml` and installed into the repo-local environment through `uv sync` by default, or an equivalent local virtual environment command when uv is not suitable.

3. Frontend dependencies are isolated under `frontend/`.
Use `npm --prefix frontend ...` for install, dev, build, and test commands.

4. E2E dependencies are isolated under `e2e/`.
Use `npm --prefix e2e ...` for Playwright commands once `e2e/package.json` exists.

5. Agents may run existing test, lint, build, collect-only, and read-only verification commands when needed.
Installing or upgrading dependencies, modifying lock files, running migrations, changing environment files, deleting or moving files, or executing unknown commands requires explicit user approval.

6. Do not rely on undeclared local packages or manually installed tools as project truth.
If a command requires a dependency, the dependency must be declared in the appropriate project manifest before that command becomes part of the normal verification path.

## Library Documentation Usage

1. Treat Context7 MCP as the preferred usage manual for library APIs when current local knowledge may be stale.

2. LangChain and LangGraph require current documentation checks when implementation, debugging, or review depends on API details.
Existing AI knowledge may reflect LangChain/LangGraph `0.3.x` conventions, while LangChain `1.0+` reorganized major APIs and prior import paths, constructors, and helper functions may no longer apply.

3. When LangChain or LangGraph code reports an API error, import error, type mismatch, missing function, or unclear usage pattern, query Context7 MCP before relying on memory or applying compatibility patches.

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

## Active Execution Workflow

- The active function one execution coordinator is:
  `docs/plans/function-one-acceleration-execution-plan.md`
- The archived delivery branch table is:
  `docs/archive/function-one-delivery-branch-plan-legacy.md`
- Do not use the archived Delivery Branch Plan as an active scheduling source.
- Use the repo-local skill `acceleration-workflow` for main-session lane coordination, ready claim discovery, worker launch prompts, progress ingest, and integration checkpoints.
- Use `slice-workflow` only for an assigned acceleration claim in a lane worker branch.
- Worker branches must not update the central Claim Ledger, `function-one-platform-plan.md`, or split-plan final task status. Those final status updates happen only in the main coordination session after an integration checkpoint.
- Acceleration lane branches merge to `integration/function-one-acceleration` first. Do not merge an acceleration lane directly to `main` unless the user explicitly abandons acceleration mode and approves a different integration strategy.
