# Verification

Run verification from the repository root unless a command states otherwise. Backend commands use `uv run`. Frontend commands use `npm --prefix frontend`. E2E commands use `npm --prefix e2e`.

## Backend

Collect tests without running them:

```powershell
uv run pytest --collect-only
```

Run the backend test suite:

```powershell
uv run pytest
```

Run a focused backend test file:

```powershell
uv run pytest backend/tests/services/test_runtime_orchestration_boundary.py
```

## Frontend

Build the frontend:

```powershell
npm --prefix frontend run build
```

Run frontend tests once:

```powershell
npm --prefix frontend run test -- --run
```

Run a focused frontend test file:

```powershell
npm --prefix frontend run test -- src/features/workspace/__tests__/WorkspaceShell.test.tsx --run
```

## E2E

Run Playwright with the mocked frontend flow:

```powershell
npm --prefix e2e run test
```

Run Playwright with the live backend harness:

```powershell
npm --prefix e2e run test:live
```

Run a focused E2E spec:

```powershell
npm --prefix e2e run test -- tests/function-one-control-flow.spec.ts
```

## API Contract Checks

The frontend includes OpenAPI compatibility coverage under `frontend/src/api/__tests__/openapi-compat.test.ts`. Run it with:

```powershell
npm --prefix frontend run test -- src/api/__tests__/openapi-compat.test.ts --run
```

Backend OpenAPI documentation is served at:

```text
http://127.0.0.1:8000/api/docs
```
