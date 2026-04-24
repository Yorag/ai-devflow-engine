# AGENTS.md

## Purpose

This file records project-level collaboration rules for AI agents working in this repository.

## Collaboration Rules

1. Do not create commits proactively.
The agent may recommend a commit when work is ready, but must not run `git commit` unless the user explicitly asks for it.

2. Do not submit or commit spec documents before user review.
When a design/spec document is drafted, keep it in the working tree and ask the user to review it first. Only commit after explicit user approval.

3. Do not treat `Must-have` as the full quality target.
For this project, the minimum赛题 requirements are only the baseline. Design work should also consider information loss across stages, requirement understanding quality, solution rationality, code safety, and test sufficiency.

4. Prioritize workflow orchestration over isolated code generation.
This repository is for an AI-driven delivery flow engine. The core emphasis is stage orchestration, artifact handoff, review loops, and end-to-end delivery, not just code generation.

5. Reserve backend extension points for feature two.
When designing or implementing feature one, preserve reusable backend concepts and APIs for future support of selection-driven webpage editing, especially around `ChangeSet`, `ContextReference`, `PreviewTarget`, and `DeliveryRecord`.

6. Write specifications in neutral project language.
Do not use competition-facing phrasing such as "for judges", "for contest demo", or "for defense" in formal specification documents. Use neutral product and delivery language.

7. Avoid ambiguous wording in specifications.
Do not use uncertain wording such as `建议`, `推荐`, `尽量`, or similar language in formal spec documents. Specs should be written as explicit requirements or clearly labeled future-scope notes.

## Current Working Agreement

- The baseline accepted specification is:
  `docs/specs/function-one-design-v1.md`
- The current active document under review is:
  `docs/specs/function-one-design-v2.md`
- The user must review and approve any spec document before any commit related to that spec.
