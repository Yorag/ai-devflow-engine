# Runtime Settings Internal Bindings Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backfill `PlatformRuntimeSettings.internal_model_bindings` across schema, control model, repository, service, admin API, and focused tests so C1.6, C1.10, and C2.8 can return to a complete implemented state.

**Architecture:** Extend the existing runtime settings contract with one new nested group that defines the three backend-only internal binding selections. Reuse the current `PlatformRuntimeSettings` persistence and update flow instead of creating a parallel source, then validate and expose the new group through the same service and admin API path.

**Tech Stack:** Python, Pydantic, SQLAlchemy, FastAPI, pytest

**Status:** Executed on branch `feat/runtime-settings-internal-bindings`. Focused tests and backend collect-only passed. Alembic migration baseline remains a separate follow-up because the repository currently has no valid control-schema revision chain to extend.

---

### Task 1: Add Schema Contract For Internal Bindings

**Files:**
- Modify: `backend/app/schemas/runtime_settings.py`
- Test: `backend/tests/schemas/test_runtime_settings_schemas.py`

- [x] **Step 1: Write the failing schema tests**

Add assertions that:
- `PlatformRuntimeSettingsRead` includes `internal_model_bindings`
- `PlatformRuntimeSettingsUpdate` accepts `internal_model_bindings`
- the three required binding keys are `context_compression`, `structured_output_repair`, `validation_pass`
- each binding carries `provider_id`, `model_id`, `model_parameters`, `source_config_version`

- [x] **Step 2: Run schema tests to verify they fail**

Run: `uv run --no-sync python -m pytest backend/tests/schemas/test_runtime_settings_schemas.py -q`
Expected: FAIL because `PlatformRuntimeSettingsRead` and `PlatformRuntimeSettingsUpdate` do not yet define `internal_model_bindings`

- [x] **Step 3: Write minimal schema implementation**

Add focused Pydantic models for:
- one internal binding selection
- the grouped `internal_model_bindings`
- read/update models that include the new group

Keep `extra="forbid"` and preserve the existing `compression_prompt` exclusion boundary.

- [x] **Step 4: Run schema tests to verify they pass**

Run: `uv run --no-sync python -m pytest backend/tests/schemas/test_runtime_settings_schemas.py -q`
Expected: PASS

### Task 2: Extend Control Model Boundary

**Files:**
- Modify: `backend/app/db/models/control.py`
- Test: `backend/tests/db/test_control_model_boundary.py`

- [x] **Step 1: Write the failing control model test**

Add assertions that `PlatformRuntimeSettingsModel` exposes an `internal_model_bindings` JSON column and that the boundary test instance can store the grouped payload.

- [x] **Step 2: Run control model tests to verify they fail**

Run: `uv run --no-sync python -m pytest backend/tests/db/test_control_model_boundary.py -q`
Expected: FAIL because `PlatformRuntimeSettingsModel` does not yet include `internal_model_bindings`

- [x] **Step 3: Write minimal control model implementation**

Add `internal_model_bindings: Mapped[JsonObject] = mapped_column(JSON, nullable=False)` to `PlatformRuntimeSettingsModel`.

- [x] **Step 4: Run control model tests to verify they pass**

Run: `uv run --no-sync python -m pytest backend/tests/db/test_control_model_boundary.py -q`
Expected: PASS

### Task 3: Backfill Repository And Service Flow

**Files:**
- Modify: `backend/app/repositories/runtime_settings.py`
- Modify: `backend/app/services/runtime_settings.py`
- Test: `backend/tests/services/test_runtime_settings_service.py`

- [x] **Step 1: Write the failing service tests**

Add tests that cover:
- initialization persists default `internal_model_bindings`
- partial update can modify one internal binding while preserving others
- persisted row contains `internal_model_bindings`
- update audit metadata includes changed internal binding fields

- [x] **Step 2: Run service tests to verify they fail**

Run: `uv run --no-sync python -m pytest backend/tests/services/test_runtime_settings_service.py -q`
Expected: FAIL because repository/service initialization, merge, changed-fields, and readback logic do not yet handle `internal_model_bindings`

- [x] **Step 3: Write minimal repository and service implementation**

Update:
- repository `_model_values()`
- service imports, default model, `_to_read()`, `_merged_settings_dicts()`, `_changed_fields()`, `_changed_groups()`, `_is_empty_update()`
- service log/audit metadata seed lists

Keep the implementation inside the existing `PlatformRuntimeSettingsService` flow.

- [x] **Step 4: Run service tests to verify they pass**

Run: `uv run --no-sync python -m pytest backend/tests/services/test_runtime_settings_service.py -q`
Expected: PASS

### Task 4: Backfill Admin API Contract

**Files:**
- Modify: `backend/app/api/routes/runtime_settings.py`
- Test: `backend/tests/api/test_runtime_settings_admin_api.py`

- [x] **Step 1: Write the failing API tests**

Add assertions that:
- `GET /api/runtime-settings` returns `internal_model_bindings`
- `PUT /api/runtime-settings` can update one internal binding
- OpenAPI includes the new schema group

- [x] **Step 2: Run API tests to verify they fail**

Run: `uv run --no-sync python -m pytest backend/tests/api/test_runtime_settings_admin_api.py -q`
Expected: FAIL because serialized response/OpenAPI currently omit `internal_model_bindings`

- [x] **Step 3: Write minimal API-facing implementation**

Rely on the service/schema updates so the route returns and accepts the new group without adding a second endpoint or special-case API path.

- [x] **Step 4: Run API tests to verify they pass**

Run: `uv run --no-sync python -m pytest backend/tests/api/test_runtime_settings_admin_api.py -q`
Expected: PASS

### Task 5: Run Focused Backfill Verification

**Files:**
- Modify: `backend/app/schemas/runtime_settings.py`
- Modify: `backend/app/db/models/control.py`
- Modify: `backend/app/repositories/runtime_settings.py`
- Modify: `backend/app/services/runtime_settings.py`
- Modify: `backend/tests/schemas/test_runtime_settings_schemas.py`
- Modify: `backend/tests/db/test_control_model_boundary.py`
- Modify: `backend/tests/services/test_runtime_settings_service.py`
- Modify: `backend/tests/api/test_runtime_settings_admin_api.py`

- [x] **Step 1: Run the full focused backfill test set**

Run: `uv run --no-sync python -m pytest backend/tests/schemas/test_runtime_settings_schemas.py backend/tests/db/test_control_model_boundary.py backend/tests/services/test_runtime_settings_service.py backend/tests/api/test_runtime_settings_admin_api.py -q`
Expected: PASS

- [x] **Step 2: Run backend collect-only for regression safety**

Run: `uv run --no-sync python -m pytest --collect-only -q`
Expected: PASS with no collection errors

- [x] **Step 3: Prepare checkpoint summary**

Record:
- changed files
- focused verification commands and results
- whether any migration work remains pending user approval
