# QA-CONFIG-V6.8 Worker Evidence

## Claim

- Claim id: `QA-CONFIG-V6.8`
- Lane id: `QA-CONFIG`
- Task id: `V6.8`
- Branch: `test/qa-config-snapshot-regression`
- Implementation plan: `docs/plans/implementation/v6.8-config-snapshot-regression.md`
- Local result: `reported`
- Expected ingest result after user-approved checkpoint commit: `implemented`

## Scope

V6.8 adds regression coverage for configuration source boundaries, run snapshot immutability, prompt asset boundaries, frontend settings visibility, and project/session history behavior.

## Current Progress

- Worker auto-discovery returned a single active claim for this branch: `QA-CONFIG-V6.8`, status `claimed`.
- Added backend config/snapshot regression coverage in `backend/tests/regression/test_config_snapshot_regression.py`.
- Added backend prompt asset boundary regression coverage in `backend/tests/regression/test_prompt_asset_boundary_regression.py`.
- Added backend project/session history regression coverage in `backend/tests/regression/test_project_session_history_regression.py`.
- Added frontend settings boundary regression coverage in `frontend/src/features/settings/__tests__/SettingsBoundary.test.tsx`.
- Added frontend project/session history regression coverage in `frontend/src/features/workspace/__tests__/ProjectSessionHistory.test.tsx`.
- Updated `frontend/src/features/inspector/__tests__/InspectorPanel.test.tsx` to scope a delivery result detail assertion after full frontend suite exposed duplicate stable refs inside the Inspector detail.
- Updated this evidence report and `docs/plans/implementation/v6.8-config-snapshot-regression.md`.
- No production files, coordination store, acceleration execution plan, platform plan, split-plan status files, package manifests, lock files, migrations, or environment files were modified.
- The worker branch is behind `integration/function-one-acceleration` by `16` commits according to the latest `worker-start --json`; no sync, merge, or rebase was performed in this worker session.

## Review Evidence

- Final spec/plan reviewer Important finding was fixed by adding real `DeliverySnapshotService` coverage proving source `DeliveryChannelModel` mutation after snapshot creation does not mutate `DeliveryChannelSnapshotModel` or `PipelineRunModel.delivery_channel_snapshot_ref`.
- Final code-quality reviewer Minor finding for append-order-sensitive compression process record assertions was fixed by keying records by `process_key`.
- Final code-quality reviewer Minor finding for representative soft-hide preservation was fixed with explicit `StageArtifactModel`, `ApprovalRequestModel`, `ApprovalDecisionModel`, and `ToolConfirmationRequestModel` assertions for both Session delete and Project remove flows.
- Focused re-review subagent reported no Critical, Important, or Minor issues in the latest review fixes.

## Verification Evidence

Dependency setup was approved by the user and completed with:

```powershell
uv sync --extra dev
npm --prefix frontend ci
```

Focused delivery snapshot review fix:

```powershell
uv run pytest backend/tests/regression/test_config_snapshot_regression.py::test_delivery_channel_updates_do_not_mutate_started_run_snapshot_or_run_ref -v
```

Exit code: `0`.
Key output: `1 passed`.

Combined backend V6.8 regression:

```powershell
uv run pytest backend/tests/regression/test_config_snapshot_regression.py backend/tests/regression/test_prompt_asset_boundary_regression.py backend/tests/regression/test_project_session_history_regression.py -v
```

Exit code: `0`.
Key output: `12 passed`.

Combined frontend V6.8 regression:

```powershell
npm --prefix frontend run test -- SettingsBoundary ProjectSessionHistory
```

Exit code: `0`.
Key output: `2 passed (2)` test files, `7 passed (7)` tests.

Impacted backend regression:

```powershell
uv run pytest backend/tests/core/test_environment_settings.py backend/tests/services/test_runtime_limit_snapshot.py backend/tests/services/test_provider_model_binding_snapshots.py backend/tests/services/test_configuration_package_service.py backend/tests/context/test_context_size_guard.py backend/tests/context/test_context_compression.py backend/tests/api/test_session_history_api.py backend/tests/api/test_project_remove_api.py backend/tests/services/test_project_remove_history.py backend/tests/services/test_delivery_snapshot_gate.py -v
```

Exit code: `0`.
Key output: `115 passed`.

Impacted frontend regression:

```powershell
npm --prefix frontend run test -- SettingsModal TemplateEditor WorkspaceShell
```

Exit code: `0`.
Key output: `3 passed (3)` test files, `55 passed (55)` tests.

Full backend suite:

```powershell
uv run pytest -q
```

Exit code: `0`.
Key output: `1295 passed, 3 warnings in 604.59s`.

Full frontend suite:

```powershell
npm --prefix frontend run test -- --run
```

Initial exit code: `1`.
Root cause: `InspectorPanel.test.tsx` used a single global text query for `delivery-record-1`, while the rendered delivery result detail contains the same stable ref in identity and stable-ref records. The test assertion was scoped to the Inspector and changed to `findAllByText`.

Rerun exit code: `0`.
Key output: `27 passed (27)` test files, `219 passed (219)` tests.

Frontend build:

```powershell
npm --prefix frontend run build
```

Exit code: `0`.
Key output: `tsc --noEmit && vite build`, `136 modules transformed`, `built in 975ms`.

## TDD Red/Green Summary

- Initial RED commands for the five new regression files failed because the files did not exist or because assertions were not yet implemented.
- Backend focused GREEN: V6.8 backend regression files now pass together with `12 passed`.
- Frontend focused GREEN: V6.8 frontend regression files now pass together with `7 passed`.
- Review-fix GREEN: delivery snapshot freeze focused test passed with `1 passed`.
- Full-suite GREEN: backend full suite, frontend full suite, and frontend build pass after the final InspectorPanel test stability fix.

## Changed Files

- `backend/tests/regression/test_config_snapshot_regression.py`
- `backend/tests/regression/test_prompt_asset_boundary_regression.py`
- `backend/tests/regression/test_project_session_history_regression.py`
- `frontend/src/features/settings/__tests__/SettingsBoundary.test.tsx`
- `frontend/src/features/workspace/__tests__/ProjectSessionHistory.test.tsx`
- `frontend/src/features/inspector/__tests__/InspectorPanel.test.tsx`
- `docs/plans/implementation/v6.8-config-snapshot-regression.md`
- `docs/plans/acceleration/reports/QA-CONFIG-V6.8.md`

## Remaining Notes

- This worker report is local `reported` evidence only. The claim becomes `implemented` only after a user-approved checkpoint commit containing this report, implementation plan, code, and tests is ingested by the main coordination session.
- This worker did not write the coordination store, central checkpoint snapshot, platform plan, or split-plan final task status.
