# QA-V6.5 Worker Evidence Report

## Claim

- Claim: `QA-V6.5`
- Task: `V6.5`
- Lane: `QA`
- Branch: `test/al-regression-hardening`
- Evidence path: `docs/plans/acceleration/reports/QA-V6.5.md`
- Implementation plan: `docs/plans/implementation/v6.5-frontend-openapi-compat.md`
- Local result: `reported`
- Expected ingest result after checkpoint commit: `implemented`

## Scope

Implemented a frontend API client/OpenAPI compatibility regression in:

- `frontend/src/api/__tests__/openapi-compat.test.ts`

The regression:

- collects `apiRequest()` and `createEventSource()` calls from `frontend/src/api/*.ts`;
- normalizes template-string client paths into OpenAPI path templates;
- asserts the frontend client route-method set is the expected V6.5 subset;
- asserts every frontend client route-method exists in the V6.4 OpenAPI route-method set;
- includes a negative check proving a route removed from the OpenAPI route set fails with route and source-file diagnostics.

No production frontend API modules, backend files, UI files, dependency manifests, lock files, platform/split final tracking state, acceleration execution plan, coordination store, or Git state were modified.

## TDD Evidence

### Initial RED

```powershell
npm --prefix frontend run test -- --run src/api/__tests__/openapi-compat.test.ts
```

Exit: `1`

Key output:

```text
3 failed
ReferenceError: collectFrontendApiPaths is not defined
```

### Initial GREEN

```powershell
npm --prefix frontend run test -- --run src/api/__tests__/openapi-compat.test.ts
```

Exit: `0`

Key output:

```text
Test Files 1 passed (1)
Tests 3 passed (3)
```

### Review Fix RED

Reviewer feedback noted that drift diagnostics omitted `sourceFile`. A focused test assertion was changed to require source-file output.

```powershell
npm --prefix frontend run test -- --run src/api/__tests__/openapi-compat.test.ts
```

Exit: `1`

Key output:

```text
expected [Function] to throw error including 'GET /api/runs/{runId}/timeline (runs.ts)' but got:
Frontend API client calls routes missing from OpenAPI:
- GET /api/runs/{runId}/timeline
```

### Review Fix GREEN

```powershell
npm --prefix frontend run test -- --run src/api/__tests__/openapi-compat.test.ts
```

Exit: `0`

Key output:

```text
Test Files 1 passed (1)
Tests 3 passed (3)
```

## Review Evidence

- Spec / plan compliance review: no Critical or Important findings.
- Code quality / testing / regression review: no Critical or Important findings.
- Minor diagnostic finding fixed: OpenAPI/client drift errors now include source files, for example `GET /api/runs/{runId}/timeline (runs.ts)`.
- Re-review after diagnostic fix: no Critical or Important findings.

## Verification

### Focused V6.5 Compatibility

```powershell
npm --prefix frontend run test -- --run src/api/__tests__/openapi-compat.test.ts
```

Exit: `0`

Key output:

```text
Test Files 1 passed (1)
Tests 3 passed (3)
```

### Focused API Client Regression

```powershell
npm --prefix frontend run test -- --run src/api/__tests__/openapi-compat.test.ts src/api/__tests__/client.test.ts src/api/__tests__/hooks.test.ts
```

Exit: `0`

Key output:

```text
Test Files 3 passed (3)
Tests 16 passed (16)
```

### Frontend Build

```powershell
npm --prefix frontend run build
```

Exit: `0`

Key output:

```text
tsc --noEmit && vite build
136 modules transformed
built in 1.56s
```

### Full Frontend Suite

```powershell
npm --prefix frontend run test -- --run
```

Exit: `0`

Key output:

```text
Test Files 26 passed (26)
Tests 215 passed (215)
```

## Former Blocker

The prior out-of-scope Inspector test blocker was resolved separately in AL06 and is present in the current integration base `2271a4e`. Full frontend verification now passes on this base.

## Git And Tracking

- Worker did not update coordination store.
- Worker did not update `docs/plans/function-one-acceleration-execution-plan.md`.
- Worker did not update platform-plan or split-plan final status.
- Worker did not run Git write operations.
