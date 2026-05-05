# AI DevFlow Engine Documentation

This directory contains the durable project documents behind the top-level README. The README gives the first impression and quick path into the system; these documents hold the deeper product, architecture, development, and verification detail.

## Start Here

| Document | Use it for |
| --- | --- |
| [Getting Started](getting-started.md) | Local setup, backend and frontend startup, runtime data, and E2E entry points. |
| [Architecture Overview](architecture/overview.md) | System layers, data flow, orchestration boundary, persistence, observability, and extension points. |
| [Verification](development/verification.md) | Backend, frontend, OpenAPI, and Playwright verification commands. |
| [OpenAPI Notes](api/function-one-openapi-notes.md) | API documentation notes and contract expectations. |

## Current Feature-One Specifications

| Document | Ownership |
| --- | --- |
| [Product Overview](specs/function-one-product-overview-v1.md) | Product boundary, stage boundary, and end-to-end workflow semantics. |
| [Frontend Workspace Design](specs/frontend-workspace-global-design-v1.md) | Workspace interaction, presentation, narrative feed, inspector, and runtime control semantics. |
| [Backend Engine Design](specs/function-one-backend-engine-design-v1.md) | Domain model, API contract, projection contract, event semantics, runtime, persistence, tools, and delivery boundaries. |

When these specifications overlap, product and stage boundaries come from the product overview, frontend interaction semantics come from the frontend design, and backend contracts come from the backend engine design.

## Implementation Planning

| Path | Purpose |
| --- | --- |
| [plans/function-one-platform-plan.md](plans/function-one-platform-plan.md) | Platform-level implementation plan and slice index. |
| [plans/function-one-platform/](plans/function-one-platform/) | Split plan volumes for implementation slices. |
| [plans/implementation/](plans/implementation/) | Execution-time implementation plans for individual slices. |
| [plans/acceleration/reports/](plans/acceleration/reports/) | Worker evidence reports from acceleration lanes. |

## Historical References

The documents in [archive](archive/) are retained for audit and historical comparison. They are not active scheduling or product-boundary sources.
