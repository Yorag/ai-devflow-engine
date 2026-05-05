# Architecture Overview

AI DevFlow Engine separates user-facing workflow state from internal runtime execution. The frontend reads stable projections and domain events. The backend owns commands, orchestration, persistence, workspace tools, observability, and delivery records.

## System Layers

| Layer | Responsibility | Representative paths |
| --- | --- | --- |
| Frontend workspace | Routes, API hooks, workspace state, composer, narrative feed, inspector, approvals, templates, settings, and delivery views. | `frontend/src/app/`, `frontend/src/api/`, `frontend/src/features/` |
| API surface | REST commands, query endpoints, SSE events, OpenAPI, correlation middleware, and error contracts. | `backend/app/main.py`, `backend/app/api/`, `backend/app/schemas/` |
| Domain and services | Project, session, run, stage, approval, artifact, provider, template, delivery, and control-plane services. | `backend/app/domain/`, `backend/app/services/` |
| Runtime orchestration | Deterministic runtime, LangGraph boundary, stage agents, prompt rendering, provider adapter, interrupts, resume, retries, and auto-regression policy. | `backend/app/runtime/`, `backend/app/providers/`, `backend/app/prompts/` |
| Persistence | Control, runtime, graph, event, and log database roles with SQLAlchemy models and repositories. | `backend/app/db/`, `backend/app/repositories/` |
| Observability | Request correlation, audit records, JSONL runtime logs, redaction, retention, log index, and log queries. | `backend/app/observability/` |
| Workspace and tools | Isolated workspace management, file tools, grep tools, shell execution, risk classification, and execution gates. | `backend/app/workspace/`, `backend/app/tools/` |
| Delivery | Demo delivery, Git delivery boundaries, delivery snapshots, and delivery result presentation. | `backend/app/delivery/`, `frontend/src/features/delivery/` |

## Workflow Data Flow

1. The user works in the frontend workspace and submits requirements or runtime commands.
2. The frontend calls FastAPI command endpoints and subscribes to SSE event streams.
3. Backend services validate commands, update control/runtime state, and emit domain events.
4. The runtime executes deterministic or agent-backed stage transitions through the orchestration boundary.
5. Services publish query projections for the workspace, narrative feed, inspector, metrics, approvals, and delivery views.
6. The frontend renders projections instead of reading raw runtime internals.

This split keeps the UI contract stable while backend runtime details evolve.

## Runtime Boundary

The runtime layer supports two important modes:

| Mode | Role |
| --- | --- |
| Deterministic runtime | Provides reproducible local control-flow behavior for development, testing, E2E flows, and demonstration delivery. |
| LangGraph-backed runtime | Preserves the orchestration boundary for stage agents, interrupts, resume, provider calls, prompt assets, and future agent execution paths. |

Stage execution is mediated through ports, snapshots, prompt assets, provider policies, tool confirmations, and domain events. This keeps direct provider/tool behavior from leaking into frontend contracts.

## Persistence and Observability

The backend uses multiple SQLite roles rather than a single mixed store:

| Role | What it protects |
| --- | --- |
| Control | Projects, sessions, provider configuration, delivery channels, templates, approvals, and user-facing control data. |
| Runtime | Run state, stage state, artifacts, runtime records, and execution snapshots. |
| Graph | Compiled graph definitions and graph-related runtime metadata. |
| Event | Domain events and projection inputs. |
| Log | Audit, diagnostic, runtime log indexes, and queryable observability records. |

JSONL runtime logs and audit records are kept alongside database-backed indexes. Redaction and retention are explicit backend responsibilities.

## Extension Points

Feature-one work keeps backend concepts reusable for later selection-driven webpage editing and richer delivery modes. Important extension points include:

| Concept | Purpose |
| --- | --- |
| `ChangeSet` | Represents a bounded set of workspace changes. |
| `ContextReference` | Links stage work to source context and supporting evidence. |
| `PreviewTarget` | Provides a future-safe target model for previewing changes. |
| `DeliveryRecord` | Captures final delivery output, evidence, and traceability. |

These concepts remain backend-owned so future UI surfaces can extend workflow behavior without rewriting the core orchestration model.
