# Project Structure

## Purpose

This document records the repository structure for function-one platform V1 implementation. It is both a tracked skeleton reference and a path ownership reference for implementation slices.

## Structure

`backend/` contains the FastAPI service, domain model, persistence adapters, runtime orchestration, observability, provider, tool, workspace, and delivery code.

`frontend/` contains the Vite React SPA, console routes, API client, feature modules, mocks, pages, and global styles.

`e2e/` contains Playwright configuration and browser-level cross-end tests.

`docs/api/` contains API and OpenAPI companion documentation.

`docs/architecture/` contains durable architecture notes such as this structure map.

`docs/archive/` contains historical design and specification references that are not current implementation sources.

`docs/plans/` contains the platform plan, split plans, and execution-time implementation plans.

`docs/plans/implementation/` contains one implementation plan per execution slice.

`docs/specs/` contains the current function-one specification set.

`pyproject.toml` is the backend Python dependency, pytest, and tooling entry point once B0.1 creates it.

`README.md` is the repository entry point for current plans, specifications, and architecture references.

## Backend Boundaries

`backend/alembic/` owns Alembic configuration and migration scripts for database structure changes.

`backend/app/api/` owns API router aggregation, error response contracts, and OpenAPI exposure.

`backend/app/core/` owns startup configuration, `EnvironmentSettings`, application dependencies, and common middleware wiring.

`backend/app/db/` owns SQLAlchemy session helpers, database roles, and multi-SQLite bindings.

`backend/app/domain/` owns pure domain objects and enums, including stage status, run status, graph definitions, runtime snapshots, and future extension objects.

`backend/app/repositories/` owns SQLAlchemy persistence adapters. Repositories encapsulate reads and writes, not business state machines, approval semantics, or projection assembly.

`backend/app/schemas/` owns Pydantic request, response, projection, event, and snapshot schemas.

`backend/app/services/` owns business services and projection assembly services.

`backend/app/observability/` owns runtime data preflight, JSONL logs, log indexes, audit records, trace context, redaction, rotation, retention, and diagnostic log queries.

`backend/app/runtime/` owns deterministic test runtime, LangGraph runtime integration, runtime limit consumption, and automated regression execution.

`backend/app/context/` owns `ContextEnvelope`, `ContextManifest`, context source resolution, context size guard, and compression process records.

`backend/app/prompts/` owns system prompt assets, `PromptRegistry`, `PromptRenderer`, prompt version traceability, and rendering helpers.

`backend/app/prompts/assets/` owns versioned built-in prompt files grouped by compression, repair, role, runtime, and tool usage concerns.

`backend/app/providers/` owns Provider registry and LangChain-compatible provider adapters.

`backend/app/tools/` owns `ToolProtocol`, `ToolRegistry`, tool input/output schemas, tool errors, audit references, and cross-tool contracts.

`backend/app/workspace/` owns isolated workspace management and workspace tools: `bash`, `read_file`, `edit_file`, `write_file`, `glob`, and `grep`.

`backend/app/delivery/` owns `demo_delivery`, `git_auto_delivery`, SCM adapters, delivery snapshots, and `DeliveryRecord` production.

## Frontend Boundaries

`frontend/package.json`, `frontend/tsconfig.json`, and `frontend/vite.config.ts` own the frontend dependency, TypeScript, Vite, and script baselines once B0.1 creates them.

`frontend/src/api/` owns API client types, REST hooks, query keys, and cache integration.

`frontend/src/app/` owns router setup, `QueryClient`, global providers, and test utilities.

`frontend/src/features/` owns feature modules for approvals, composer, delivery, errors, feed, inspector, runs, settings, templates, tool confirmations, and workspace behavior.

`frontend/src/mocks/` owns mock fixtures and mock handlers derived from backend schemas and projection contracts.

`frontend/src/pages/` owns route-level page composition.

`frontend/src/styles/` owns global CSS and theme variables.

## Test Boundaries

`backend/tests/api/` owns FastAPI route, error response, and OpenAPI contract tests.

`backend/tests/core/` owns startup configuration and application dependency boundary tests.

`backend/tests/db/` owns database session, model, migration, and multi-SQLite boundary tests.

`backend/tests/e2e/` owns backend API/runtime end-to-end tests that do not launch a browser.

`backend/tests/errors/` owns error-code catalog, error response, and cross-tool error contract tests.

`backend/tests/domain/`, `backend/tests/schemas/`, `backend/tests/services/`, `backend/tests/projections/`, `backend/tests/events/`, `backend/tests/runtime/`, `backend/tests/tools/`, `backend/tests/workspace/`, `backend/tests/delivery/`, `backend/tests/providers/`, `backend/tests/prompts/`, and `backend/tests/context/` own tests for their matching production boundaries.

`backend/tests/observability/` owns runtime data, log, audit, redaction, trace context, rotation, retention, and diagnostic query tests.

`backend/tests/fixtures/` owns fake providers, fake tools, fixture repositories, mock remote contracts, and settings overrides used by tests.

`backend/tests/regression/` owns release-candidate cross-slice regression tests.

`backend/tests/support/` owns shared test helpers that do not define business fake semantics.

`e2e/package.json` and `e2e/playwright.config.ts` own Playwright dependency, script, and browser-test configuration once the end-to-end baseline lands.

`e2e/tests/` owns browser-level Playwright tests.

## Slice Traceability

`B0.1` creates the first backend and frontend engineering baseline files under `backend/`, `backend/tests/`, and `frontend/`.

`B0.2` creates the FastAPI application and API error contract under `backend/app/api/`, `backend/app/core/`, and `backend/tests/api/`.

`F0.1` creates the SPA shell under `frontend/src/app/`, `frontend/src/pages/`, and `frontend/src/styles/`.

`C1.10a` creates prompt schema tests and prompt schemas under `backend/app/schemas/`, `backend/tests/schemas/`, and later prompt runtime assets under `backend/app/prompts/`.

`A4.8b-A4.8d` use `backend/app/context/`, `backend/app/prompts/`, `backend/tests/context/`, and `backend/tests/prompts/` for context and prompt runtime boundaries.

`A4.9a-A4.9b` use `backend/app/context/`, `backend/app/runtime/`, `backend/tests/context/`, and `backend/tests/runtime/` for context envelope building, context manifest recording, size guards, and compression process records.

## Skeleton Placeholder Rule

B0.0 tracks the initial directory skeleton with `.gitkeep` placeholders in leaf directories. Later slices remove a placeholder when they add the first real source file, test, asset, or documentation file to that directory. Placeholder files do not define runtime behavior, package boundaries, imports, API contracts, or test targets.
