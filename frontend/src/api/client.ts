import type {
  ApiErrorCode,
  ApiErrorResponse,
  ApiFieldError,
  ConfigErrorCode,
} from "./types";

export const CONFIG_ERROR_CODES = [
  "config_invalid_value",
  "config_hard_limit_exceeded",
  "config_version_conflict",
  "config_storage_unavailable",
  "config_snapshot_unavailable",
] as const satisfies readonly ConfigErrorCode[];

export type Fetcher = typeof fetch;

export type ApiRequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  baseUrl?: string;
  fetcher?: Fetcher;
};

export class ApiRequestError extends Error {
  readonly status: number;
  readonly code: ApiErrorCode;
  readonly requestId: string | null;
  readonly fieldErrors: ApiFieldError[];
  readonly payload: unknown;

  constructor(params: {
    status: number;
    code: ApiErrorCode;
    message: string;
    requestId: string | null;
    fieldErrors?: ApiFieldError[];
    payload?: unknown;
  }) {
    super(params.message);
    this.name = "ApiRequestError";
    this.status = params.status;
    this.code = params.code;
    this.requestId = params.requestId;
    this.fieldErrors = params.fieldErrors ?? [];
    this.payload = params.payload;
  }
}

export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const { body, baseUrl, fetcher = fetch, headers, ...requestInit } = options;
  const requestHeaders = new Headers(headers);
  let requestBody: BodyInit | undefined;

  if (body !== undefined) {
    requestHeaders.set("content-type", "application/json");
    requestBody = JSON.stringify(body);
  }

  const response = await fetcher(resolveApiUrl(path, baseUrl), {
    ...requestInit,
    headers: Object.fromEntries(requestHeaders.entries()),
    body: requestBody,
  });

  if (!response.ok) {
    throw await buildApiRequestError(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export function createEventSource(
  path: string,
  options: { baseUrl?: string } = {},
): EventSource {
  return new EventSource(resolveApiUrl(path, options.baseUrl));
}

export function resolveApiUrl(
  path: string,
  baseUrl = getDefaultApiBaseUrl(),
): string {
  if (/^https?:\/\//u.test(path)) {
    return path;
  }

  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  if (!baseUrl) {
    return normalizedPath;
  }

  const trimmedBase = baseUrl.replace(/\/+$/u, "");
  const pathWithoutApiPrefix = normalizedPath.replace(/^\/api\/?/u, "/");
  return `${trimmedBase}${pathWithoutApiPrefix}`;
}

export function isConfigErrorCode(code: string): code is ConfigErrorCode {
  return CONFIG_ERROR_CODES.includes(code as ConfigErrorCode);
}

function getDefaultApiBaseUrl(): string {
  return import.meta.env.VITE_API_BASE_URL ?? "/api";
}

async function buildApiRequestError(response: Response): Promise<ApiRequestError> {
  const payload = await parseJsonSafely(response);
  const errorPayload = isApiErrorResponse(payload) ? payload : null;
  const code =
    errorPayload?.error_code ??
    errorPayload?.code ??
    (response.status === 404 ? "not_found" : "internal_error");
  const message = errorPayload?.message ?? response.statusText ?? "Request failed.";
  const requestId =
    errorPayload?.request_id ?? response.headers.get("x-request-id") ?? null;

  return new ApiRequestError({
    status: response.status,
    code,
    message,
    requestId,
    fieldErrors: errorPayload?.field_errors,
    payload,
  });
}

async function parseJsonSafely(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    return null;
  }

  try {
    return await response.json();
  } catch {
    return null;
  }
}

function isApiErrorResponse(payload: unknown): payload is ApiErrorResponse {
  if (!payload || typeof payload !== "object") {
    return false;
  }

  const candidate = payload as Partial<ApiErrorResponse>;
  return (
    typeof candidate.message === "string" &&
    typeof candidate.request_id === "string"
  );
}
