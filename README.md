<div align="center">

# AI DevFlow Engine

### AI-driven engineering workflow engine for requirement-to-delivery pipelines.

![Status](https://img.shields.io/badge/status-V1%20platform%20buildout-0f766e)
![License](https://img.shields.io/badge/license-MIT-111827)
![Runtime](https://img.shields.io/badge/runtime-Python%203.11%2B-3776ab?logo=python&logoColor=white)
![Frontend](https://img.shields.io/badge/frontend-React%20%2B%20Vite-646cff?logo=vite&logoColor=white)
![Orchestration](https://img.shields.io/badge/orchestration-LangGraph-1c3c3c?logo=langchain&logoColor=white)

English | [简体中文](README.zh.md)

</div>

---

AI DevFlow Engine is an AI-driven workflow engine for software delivery. It treats development as a staged pipeline rather than a single chat: requirement understanding, solution design, code change, testing, review, and delivery all become explicit steps.

The project is built around a practical gap in current AI coding tools. Code completion is useful, but teams still need process control: clear requirements, reasonable designs, safe changes, sufficient tests, human approval at quality gates, and delivery records that explain what happened.

AI DevFlow Engine coordinates specialized agents around those stages and preserves the artifacts they produce, so the final delivery can be inspected, corrected, retried, and traced back to the original intent.

<div align="center">
  <img src="assets/agent-delivery-flow.svg" alt="AI DevFlow Engine animated delivery flow" width="960" />
</div>

## Who It Is For

AI DevFlow Engine is designed for teams and builders who want AI to participate in the whole development workflow, not only in code completion.

| Audience | What they need from AI DevFlow Engine |
| --- | --- |
| Product and project owners | A visible path from requirement intent to implementation outcome. |
| Tech leads and reviewers | Structured solution design, risk exposure, review checkpoints, and traceable decisions. |
| Developers | A workflow that carries context from requirement analysis through coding, tests, review, and delivery. |
| AI platform builders | A reusable orchestration model for agent roles, artifacts, tools, runtime control, and delivery records. |

## What It Solves

| Problem | AI DevFlow Engine approach |
| --- | --- |
| Requirements become vague after handoff | Convert natural-language input into structured requirements and acceptance criteria. |
| Solution quality is hard to judge early | Produce a design, implementation plan, impact scope, and validation result before coding. |
| AI-generated code lacks process context | Keep every code change tied to the approved requirement, design, and task plan. |
| Test coverage is easy to skip | Treat test generation, execution, and gap reporting as a formal stage. |
| Reviews happen after context has faded | Preserve artifacts and decisions so review can inspect why the change exists. |
| Delivery is hard to audit | Generate a final delivery record linked to requirement, design, code, tests, and review. |

## Delivery Pipeline

| Stage | Responsibility | Output |
| --- | --- | --- |
| Requirement Analysis | Understand user intent, constraints, and acceptance criteria. | Structured requirement |
| Solution Design | Create the technical approach, implementation plan, and validation result. | Approved design |
| Code Generation | Modify the workspace according to the approved plan. | Code change set |
| Test Generation & Execution | Generate or run tests and expose remaining gaps. | Test evidence |
| Code Review | Review correctness, safety, test evidence, and plan alignment. | Review decision |
| Delivery Integration | Prepare the final delivery result and delivery record. | Traceable delivery |

Human approval is embedded at the key quality gates. Runtime controls such as clarification, pause, resume, terminate, rollback, retry, and high-risk tool confirmation are part of the execution chain instead of separate side processes.

## Product Shape

AI DevFlow Engine is planned as a local-first development workspace:

| Area | Product direction |
| --- | --- |
| Workspace | A single console where the user inputs requirements, answers clarifications, approves designs, confirms risky actions, and reviews final delivery. |
| Narrative flow | A readable feed that shows how the system understands, designs, implements, tests, reviews, and delivers. |
| Inspector | A detailed side panel for inputs, process records, outputs, artifacts, metrics, and references. |
| Runtime controls | Built-in support for waiting, pause/resume, termination, rollback, retry, approval, and tool confirmation. |
| Delivery modes | Demonstration delivery for safe local flow and Git delivery for real branch, commit, and review request flow. |

## Architecture Blueprint

| Layer | V1 direction |
| --- | --- |
| Frontend | Single SPA with `React`, `Vite`, `React Router`, `TanStack Query`, `Zustand`, and an `EventSource` wrapper. |
| API surface | `FastAPI` exposes REST commands, query projections, SSE domain events, and OpenAPI documentation. |
| Runtime | `LangGraph` drives the staged execution chain; `LangChain` provides provider, message, tool binding, and structured output integration. |
| Persistence | Multiple SQLite files split by responsibility: control, runtime, graph, event, and log storage. |
| Observability | JSONL runtime logs, lightweight log indexes, audit records, trace identifiers, redaction, rotation, and diagnostic queries. |
| Workspace | Isolated run workspaces, controlled file tools, controlled shell execution, diff capture, and change-set construction. |
| Delivery | Safe demonstration delivery plus controlled Git delivery through branch, commit, push, and code review request flow. |

Raw runtime state stays internal. The frontend consumes domain objects, query projections, and domain events so the user-facing workflow remains stable as the implementation evolves.

## Development Status

This repository is currently in the V1 platform buildout. The authoritative product and implementation boundaries are the split specifications and platform plans under `docs/`. B0.0 creates the tracked directory skeleton with `.gitkeep` placeholders; later slices replace those placeholders with real source files, tests, assets, or documentation.

| Area | Status |
| --- | --- |
| Product, frontend, and backend split specifications | Defined under `docs/specs/` and under review. |
| Platform implementation plan | Defined under `docs/plans/function-one-platform-plan.md` with slice volumes. |
| Repository structure boundary | Documented in `docs/architecture/project-structure.md`. |
| Production backend/frontend code | Planned slice by slice; not treated as complete by this README. |
| Existing archived designs | Kept only as historical references under `docs/archive/`. |

## Development Commands

Backend commands:

```powershell
uv sync --extra dev
uv run pytest --collect-only
uv run pytest
```

Backend dependencies are resolved through the committed `uv.lock`; update it with `uv lock` whenever `pyproject.toml` changes. The Python interpreter managed by uv must be Python 3.11 or newer.

Frontend commands:

Frontend commands require Node.js `^20.19.0` or `>=22.12.0`.

```powershell
npm --prefix frontend install
npm --prefix frontend run dev
npm --prefix frontend run build
npm --prefix frontend run test -- --run
```

The B0.1 backend baseline does not create a FastAPI app entry. `backend/app/main.py` and API health checks are owned by B0.2. The B0.1 frontend baseline only creates the Vite/Vitest engineering entry; React routes, QueryClient setup, pages, and visible console UI are owned by F0.1.

## Repository Map

| Path | Purpose |
| --- | --- |
| `docs/specs/` | Current product, frontend, and backend specification set. |
| `docs/plans/function-one-platform-plan.md` | Platform-level V1 implementation plan. |
| `docs/plans/function-one-platform/` | Split plan volumes for implementation slices. |
| `docs/plans/implementation/` | Execution-time implementation plans for individual slices. |
| `docs/architecture/` | Durable architecture notes and ownership boundaries. |
| `backend/` | Tracked backend skeleton for FastAPI, domain, persistence, runtime, observability, tools, workspace, delivery, and tests. |
| `frontend/` | Tracked frontend skeleton for the Vite React SPA source tree. |
| `e2e/` | Tracked Playwright end-to-end test skeleton. |
| `docs/api/` | Tracked API and OpenAPI companion documentation, including [`function-one-openapi-notes.md`](docs/api/function-one-openapi-notes.md). |
| `assets/` | README and documentation visuals. |
| `refs/` | Project working references and development logs. |

## Current Specification Set

- Product boundary: [`docs/specs/function-one-product-overview-v1.md`](docs/specs/function-one-product-overview-v1.md)
- Frontend workspace design: [`docs/specs/frontend-workspace-global-design-v1.md`](docs/specs/frontend-workspace-global-design-v1.md)
- Backend engine and collaboration contract: [`docs/specs/function-one-backend-engine-design-v1.md`](docs/specs/function-one-backend-engine-design-v1.md)

When these documents overlap, the product overview owns product and stage boundaries, the frontend design owns interaction and presentation semantics, and the backend design owns domain model, API, projection, and event semantics.

## Scope Boundaries

V1 is scoped to a local project delivery workflow. It does not include browser injection, in-page selection editing, multi-tenant billing, an independent approval center, a custom stage orchestrator, or large-scale distributed execution. The design keeps those concerns outside the first platform version while preserving backend extension points for later work.

## License

This project is licensed under the [MIT License](LICENSE).
