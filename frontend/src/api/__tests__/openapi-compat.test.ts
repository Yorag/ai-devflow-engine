import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { describe, expect, it } from "vitest";

type HttpMethod = "DELETE" | "GET" | "PATCH" | "POST" | "PUT";

type ClientApiRoute = {
  method: HttpMethod;
  path: string;
  sourceFile: string;
};

const OPENAPI_ROUTE_METHODS = {
  "/api/health": ["GET"],
  "/api/projects": ["GET", "POST"],
  "/api/projects/{projectId}": ["DELETE"],
  "/api/projects/{projectId}/configuration-package/export": ["GET"],
  "/api/projects/{projectId}/configuration-package/import": ["POST"],
  "/api/projects/{projectId}/delivery-channel": ["GET", "PUT"],
  "/api/projects/{projectId}/delivery-channel/validate": ["POST"],
  "/api/projects/{projectId}/sessions": ["GET", "POST"],
  "/api/providers": ["GET", "POST"],
  "/api/providers/{providerId}": ["DELETE", "GET", "PATCH"],
  "/api/pipeline-templates": ["GET", "POST"],
  "/api/pipeline-templates/{templateId}": ["DELETE", "GET", "PATCH"],
  "/api/pipeline-templates/{templateId}/save-as": ["POST"],
  "/api/runtime-settings": ["GET", "PUT"],
  "/api/sessions/{sessionId}": ["DELETE", "GET", "PATCH"],
  "/api/sessions/{sessionId}/template": ["PUT"],
  "/api/sessions/{sessionId}/messages": ["POST"],
  "/api/sessions/{sessionId}/runs": ["POST"],
  "/api/sessions/{sessionId}/workspace": ["GET"],
  "/api/sessions/{sessionId}/events/stream": ["GET"],
  "/api/approvals/{approvalId}/approve": ["POST"],
  "/api/approvals/{approvalId}/reject": ["POST"],
  "/api/runs/{runId}": ["GET"],
  "/api/runs/{runId}/timeline": ["GET"],
  "/api/runs/{runId}/pause": ["POST"],
  "/api/runs/{runId}/resume": ["POST"],
  "/api/runs/{runId}/terminate": ["POST"],
  "/api/runs/{runId}/logs": ["GET"],
  "/api/stages/{stageRunId}/inspector": ["GET"],
  "/api/stages/{stageRunId}/logs": ["GET"],
  "/api/control-records/{controlRecordId}": ["GET"],
  "/api/tool-confirmations/{toolConfirmationId}": ["GET"],
  "/api/tool-confirmations/{toolConfirmationId}/allow": ["POST"],
  "/api/tool-confirmations/{toolConfirmationId}/deny": ["POST"],
  "/api/delivery-records/{deliveryRecordId}": ["GET"],
  "/api/preview-targets/{previewTargetId}": ["GET"],
  "/api/audit-logs": ["GET"],
} as const satisfies Record<string, readonly HttpMethod[]>;

const EXPECTED_FRONTEND_CLIENT_ROUTES = [
  "DELETE /api/pipeline-templates/{templateId}",
  "DELETE /api/projects/{projectId}",
  "DELETE /api/providers/{providerId}",
  "DELETE /api/sessions/{sessionId}",
  "GET /api/control-records/{controlRecordId}",
  "GET /api/delivery-records/{deliveryRecordId}",
  "GET /api/pipeline-templates",
  "GET /api/pipeline-templates/{templateId}",
  "GET /api/projects",
  "GET /api/projects/{projectId}/configuration-package/export",
  "GET /api/projects/{projectId}/delivery-channel",
  "GET /api/projects/{projectId}/sessions",
  "GET /api/providers",
  "GET /api/providers/{providerId}",
  "GET /api/runs/{runId}",
  "GET /api/runs/{runId}/logs",
  "GET /api/runs/{runId}/timeline",
  "GET /api/sessions/{sessionId}",
  "GET /api/sessions/{sessionId}/events/stream",
  "GET /api/sessions/{sessionId}/workspace",
  "GET /api/stages/{stageRunId}/inspector",
  "GET /api/tool-confirmations/{toolConfirmationId}",
  "PATCH /api/pipeline-templates/{templateId}",
  "PATCH /api/providers/{providerId}",
  "PATCH /api/sessions/{sessionId}",
  "POST /api/approvals/{approvalId}/approve",
  "POST /api/approvals/{approvalId}/reject",
  "POST /api/pipeline-templates",
  "POST /api/pipeline-templates/{templateId}/save-as",
  "POST /api/projects",
  "POST /api/projects/{projectId}/configuration-package/import",
  "POST /api/projects/{projectId}/delivery-channel/validate",
  "POST /api/projects/{projectId}/sessions",
  "POST /api/providers",
  "POST /api/runs/{runId}/pause",
  "POST /api/runs/{runId}/resume",
  "POST /api/runs/{runId}/terminate",
  "POST /api/sessions/{sessionId}/messages",
  "POST /api/sessions/{sessionId}/runs",
  "PUT /api/projects/{projectId}/delivery-channel",
  "PUT /api/sessions/{sessionId}/template",
] as const;

const API_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SOURCE_EXCLUDES = new Set(["client.ts", "hooks.ts", "types.ts"]);

function collectFrontendApiPaths(apiRoot = API_ROOT): ClientApiRoute[] {
  const routes: ClientApiRoute[] = [];
  const sourceFiles = fs
    .readdirSync(apiRoot)
    .filter((fileName) => fileName.endsWith(".ts"))
    .filter((fileName) => !SOURCE_EXCLUDES.has(fileName))
    .sort();

  for (const sourceFile of sourceFiles) {
    const absolutePath = path.join(apiRoot, sourceFile);
    const sourceText = fs.readFileSync(absolutePath, "utf8");
    const parsed = ts.createSourceFile(
      sourceFile,
      sourceText,
      ts.ScriptTarget.Latest,
      true,
      ts.ScriptKind.TS,
    );

    const visit = (node: ts.Node): void => {
      if (ts.isCallExpression(node)) {
        const callName = getCallName(node.expression);
        if (callName === "apiRequest" || callName === "createEventSource") {
          const clientPath = renderPathExpression(node.arguments[0], parsed);
          if (clientPath?.startsWith("/api/")) {
            routes.push({
              method:
                callName === "createEventSource"
                  ? "GET"
                  : getHttpMethod(node.arguments[1]),
              path: clientPath,
              sourceFile,
            });
          }
        }
      }

      ts.forEachChild(node, visit);
    };

    visit(parsed);
  }

  return routes.sort(
    (left, right) =>
      routeKey(left).localeCompare(routeKey(right)) ||
      left.sourceFile.localeCompare(right.sourceFile),
  );
}

function assert_frontend_client_paths_match_openapi(
  clientRoutes = collectFrontendApiPaths(),
  openApiRouteMethods: Record<string, readonly HttpMethod[]> = OPENAPI_ROUTE_METHODS,
  expectedRouteKeys: readonly string[] = EXPECTED_FRONTEND_CLIENT_ROUTES,
): void {
  const openApiRouteKeys = new Set(
    Object.entries(openApiRouteMethods).flatMap(([pathName, methods]) =>
      methods.map((method) => `${method} ${pathName}`),
    ),
  );
  const clientRouteKeys = uniqueSorted(clientRoutes.map(routeKey));
  const sourceFilesByRouteKey = groupSourceFilesByRouteKey(clientRoutes);
  const missingFromOpenApi = clientRouteKeys.filter(
    (clientRouteKey) => !openApiRouteKeys.has(clientRouteKey),
  );
  if (missingFromOpenApi.length > 0) {
    throw new Error(
      [
        "Frontend API client calls routes missing from OpenAPI:",
        ...missingFromOpenApi.map(
          (route) => `- ${formatRouteWithSourceFiles(route, sourceFilesByRouteKey)}`,
        ),
      ].join("\n"),
    );
  }

  const missingFromClient = expectedRouteKeys.filter(
    (expectedRouteKey) => !clientRouteKeys.includes(expectedRouteKey),
  );
  if (missingFromClient.length > 0) {
    throw new Error(
      [
        "Frontend API client no longer exposes expected V6.5 routes:",
        ...missingFromClient.map((route) => `- ${route}`),
      ].join("\n"),
    );
  }

  const untrackedClientRoutes = clientRouteKeys.filter(
    (clientRouteKey) => !expectedRouteKeys.includes(clientRouteKey),
  );
  if (untrackedClientRoutes.length > 0) {
    throw new Error(
      [
        "Frontend API client exposes untracked routes; update V6.5 compatibility expectations with the OpenAPI route set:",
        ...untrackedClientRoutes.map(
          (route) => `- ${formatRouteWithSourceFiles(route, sourceFilesByRouteKey)}`,
        ),
      ].join("\n"),
    );
  }
}

function getCallName(expression: ts.Expression): string | null {
  if (ts.isIdentifier(expression)) {
    return expression.text;
  }
  return null;
}

function renderPathExpression(
  expression: ts.Expression | undefined,
  sourceFile: ts.SourceFile,
): string | null {
  if (!expression) {
    return null;
  }

  if (ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)) {
    return stripQueryString(expression.text);
  }

  if (ts.isTemplateExpression(expression)) {
    let rendered = expression.head.text;
    for (const span of expression.templateSpans) {
      const expressionText = span.expression.getText(sourceFile);
      if (!expressionText.startsWith("toQueryString(")) {
        rendered += `{${toOpenApiParameterName(expressionText)}}`;
      }
      rendered += span.literal.text;
    }
    return stripQueryString(rendered);
  }

  throw new Error(
    `Unsupported API path expression in ${sourceFile.fileName}: ${expression.getText(
      sourceFile,
    )}`,
  );
}

function getHttpMethod(expression: ts.Expression | undefined): HttpMethod {
  if (!expression || !ts.isObjectLiteralExpression(expression)) {
    return "GET";
  }

  for (const property of expression.properties) {
    if (!ts.isPropertyAssignment(property)) {
      continue;
    }
    const propertyName = getPropertyName(property.name);
    if (propertyName !== "method") {
      continue;
    }
    if (
      ts.isStringLiteral(property.initializer) ||
      ts.isNoSubstitutionTemplateLiteral(property.initializer)
    ) {
      return property.initializer.text.toUpperCase() as HttpMethod;
    }
  }

  return "GET";
}

function getPropertyName(name: ts.PropertyName): string | null {
  if (ts.isIdentifier(name) || ts.isStringLiteral(name)) {
    return name.text;
  }
  return null;
}

function toOpenApiParameterName(expressionText: string): string {
  const trimmedExpression = expressionText.trim();
  if (/^[A-Za-z_$][\w$]*$/u.test(trimmedExpression)) {
    return trimmedExpression;
  }

  const identifierMatch = /[A-Za-z_][A-Za-z0-9_]*(?:Id|ID)\b/u.exec(
    trimmedExpression,
  );
  if (identifierMatch) {
    return identifierMatch[0];
  }

  throw new Error(`Cannot normalize dynamic API path expression: ${expressionText}`);
}

function stripQueryString(pathName: string): string {
  return pathName.split("?")[0];
}

function routeKey(route: ClientApiRoute): string {
  return `${route.method} ${route.path}`;
}

function groupSourceFilesByRouteKey(
  routes: readonly ClientApiRoute[],
): Map<string, string[]> {
  const sourceFilesByRouteKey = new Map<string, string[]>();
  for (const route of routes) {
    const key = routeKey(route);
    const sourceFiles = sourceFilesByRouteKey.get(key) ?? [];
    if (!sourceFiles.includes(route.sourceFile)) {
      sourceFiles.push(route.sourceFile);
      sourceFiles.sort();
    }
    sourceFilesByRouteKey.set(key, sourceFiles);
  }
  return sourceFilesByRouteKey;
}

function formatRouteWithSourceFiles(
  route: string,
  sourceFilesByRouteKey: ReadonlyMap<string, readonly string[]>,
): string {
  const sourceFiles = sourceFilesByRouteKey.get(route);
  if (!sourceFiles || sourceFiles.length === 0) {
    return route;
  }
  return `${route} (${sourceFiles.join(", ")})`;
}

function uniqueSorted(values: readonly string[]): string[] {
  return Array.from(new Set(values)).sort();
}

describe("frontend API client OpenAPI compatibility", () => {
  it("collects every API client route from frontend source modules", () => {
    const routeKeys = collectFrontendApiPaths()
      .map((route) => `${route.method} ${route.path}`)
      .filter((routeKey, index, routeKeys) => routeKeys.indexOf(routeKey) === index)
      .sort();

    expect(routeKeys).toEqual([...EXPECTED_FRONTEND_CLIENT_ROUTES].sort());
  });

  it("keeps frontend API client routes inside the OpenAPI route set", () => {
    expect(() => assert_frontend_client_paths_match_openapi()).not.toThrow();
  });

  it("fails if an OpenAPI path is removed or renamed while the client still calls it", () => {
    const openApiWithoutRunTimeline = {
      ...OPENAPI_ROUTE_METHODS,
      "/api/runs/{runId}/timeline": [],
    };

    expect(() =>
      assert_frontend_client_paths_match_openapi(
        [
          {
            method: "GET",
            path: "/api/runs/{runId}/timeline",
            sourceFile: "runs.ts",
          },
        ],
        openApiWithoutRunTimeline,
        ["GET /api/runs/{runId}/timeline"],
      ),
    ).toThrow("GET /api/runs/{runId}/timeline (runs.ts)");
  });
});
