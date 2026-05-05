# Function One OpenAPI Notes

This note records the OpenAPI coverage boundary for Function One.

## Documentation Entry Points

- Machine-readable OpenAPI document: `GET /api/openapi.json`
- Human-readable API documentation page: `GET /api/docs`

## V6.4 Coverage Boundary

V6.4 is a global coverage regression. It verifies that the generated OpenAPI document contains the core Function One route groups, request schemas, response schemas, main error responses, the SSE route, and the event payload component schemas already emitted by the current FastAPI application.

V6.4 does not replace route-local API assertions. Each API implementation slice remains responsible for its own path, method, request schema, response schema, and main error response assertions when that route is introduced or changed.

## Core Route Groups

The global regression covers these groups:

- Project and project deletion routes.
- Project `DeliveryChannel` read/update/validation routes.
- Project configuration package import/export routes.
- Session create/list/read/update/delete, template selection, message, rerun, workspace projection, and event stream routes.
- Pipeline run lifecycle routes for pause, resume, and terminate.
- Run timeline, stage Inspector, control record detail, tool confirmation detail, delivery record detail, preview target detail, run log query, stage log query, and audit log query routes.
- Pipeline template, Provider, and runtime settings routes.
- Approval command routes.
- Tool confirmation allow and deny command routes.

## Required High-Risk Coverage Points

The global regression explicitly verifies:

- `GET /api/sessions/{sessionId}/events/stream` exposes `sessionId`, `after`, and `limit` parameters and a `text/event-stream` response.
- Event/feed payload component schemas include session, message, run summary, execution node, approval request, approval result, control item, tool confirmation, delivery result, system status, session status, and stage type schemas.
- Exact event payload component coverage includes `SessionRead`, `MessageFeedEntry`, `RunSummaryProjection`, `ExecutionNodeProjection`, `ApprovalRequestFeedEntry`, `ApprovalResultFeedEntry`, `ControlItemFeedEntry`, `ToolConfirmationFeedEntry`, `DeliveryResultFeedEntry`, `SystemStatusFeedEntry`, `SessionStatus`, and `StageType`.
- The `session_status_changed` SSE event payload shape is tracked as `session_id`, `status`, `current_run_id`, and `current_stage_type`; `status` uses `SessionStatus`, and `current_stage_type` uses `StageType` when present.
- `POST /api/tool-confirmations/{toolConfirmationId}/allow`, `POST /api/tool-confirmations/{toolConfirmationId}/deny`, and `GET /api/tool-confirmations/{toolConfirmationId}` expose their request, response, error, and detail projection schemas.
- `GET /api/runs/{runId}` exposes the `runId` path parameter, `RunStatusSummaryProjection`, and main error responses.
- `GET /api/runs/{runId}/logs` and `GET /api/stages/{stageRunId}/logs` expose log query parameters, `RunLogQueryResponse`, and main error responses.
- `GET /api/audit-logs` exposes audit query parameters including `stage_run_id` and `correlation_id`, `AuditLogQueryResponse`, and main error responses.

## Verification Command

```powershell
uv run pytest backend/tests/api/test_openapi_contract.py -v
```
