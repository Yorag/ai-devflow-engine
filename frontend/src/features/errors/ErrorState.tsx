import type { ApiErrorCode, ApiFieldError } from "../../api/types";

export type FormattedApiError = {
  code: ApiErrorCode | "unknown_error";
  title: string;
  detail: string;
  recovery: string;
  requestId: string | null;
};

type ErrorStateProps = {
  error: unknown;
  actionLabel?: string;
  onAction?: () => void;
};

type ErrorLike = {
  code?: unknown;
  error_code?: unknown;
  message?: unknown;
  requestId?: unknown;
  request_id?: unknown;
  fieldErrors?: unknown;
  field_errors?: unknown;
};

type ErrorCopy = {
  title: string;
  recovery: string;
};

export function ErrorState({
  error,
  actionLabel,
  onAction,
}: ErrorStateProps): JSX.Element {
  const formatted = formatApiError(error);

  return (
    <div className="error-state" role="alert" aria-live="polite">
      <div className="error-state__content">
        <strong>{formatted.title}</strong>
        <p>{formatted.detail}</p>
        <p>{formatted.recovery}</p>
        {formatted.requestId ? (
          <span className="error-state__request-id">
            Request {formatted.requestId}
          </span>
        ) : null}
      </div>
      {actionLabel && onAction ? (
        <button
          type="button"
          className="workspace-button workspace-button--secondary workspace-button--compact"
          onClick={onAction}
        >
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}

export function formatApiError(error: unknown): FormattedApiError {
  const candidate = readErrorLike(error);
  const code = normalizeApiErrorCode(candidate.code);
  const detail = sanitizeErrorDetail(
    formatErrorDetail(candidate.message, candidate.fieldErrors),
  );
  const copy = ERROR_COPY[code] ?? ERROR_COPY.unknown_error;

  return {
    code,
    title: copy.title,
    detail,
    recovery: copy.recovery,
    requestId: candidate.requestId,
  };
}

const ERROR_COPY = {
  approval_not_actionable: {
    title: "Approval cannot be submitted",
    recovery: "Resume the run, then submit the same approval again.",
  },
  run_command_not_actionable: {
    title: "Run command is not available",
    recovery:
      "Refresh the workspace and use the action available for the current run state.",
  },
  runtime_data_dir_unavailable: {
    title: "Runtime storage is unavailable",
    recovery: "Check the runtime data directory and retry after it is writable.",
  },
  tool_unknown: {
    title: "Tool is unavailable",
    recovery: "Refresh the workspace and retry with an available tool.",
  },
  tool_not_allowed: {
    title: "Tool is not allowed",
    recovery: "Use an action allowed for the current stage.",
  },
  tool_input_schema_invalid: {
    title: "Tool input is invalid",
    recovery: "Adjust the tool input and retry.",
  },
  tool_workspace_boundary_violation: {
    title: "Workspace boundary blocked the tool",
    recovery: "Choose a path inside the run workspace.",
  },
  tool_timeout: {
    title: "Tool timed out",
    recovery: "Retry after narrowing the command or target.",
  },
  tool_audit_required_failed: {
    title: "Tool audit could not be recorded",
    recovery: "Retry after audit storage is available.",
  },
  tool_confirmation_required: {
    title: "Tool confirmation is required",
    recovery: "Review the pending tool confirmation before continuing.",
  },
  tool_confirmation_denied: {
    title: "Tool confirmation was denied",
    recovery: "Review the follow-up status in the run feed.",
  },
  tool_confirmation_not_actionable: {
    title: "Tool confirmation cannot be submitted",
    recovery: "Refresh the workspace and act on the latest tool confirmation.",
  },
  tool_risk_blocked: {
    title: "Tool action was blocked",
    recovery: "Choose a lower-risk approach before retrying.",
  },
  bash_command_not_allowed: {
    title: "Command is not allowed",
    recovery: "Use an allowed project command.",
  },
  provider_retry_exhausted: {
    title: "Provider retries were exhausted",
    recovery: "Wait briefly, then retry or adjust provider settings.",
  },
  provider_circuit_open: {
    title: "Provider circuit is open",
    recovery:
      "Wait for the provider circuit to recover or adjust provider settings before retrying.",
  },
  delivery_snapshot_missing: {
    title: "Delivery snapshot is missing",
    recovery: "Refresh the run details before retrying delivery.",
  },
  delivery_snapshot_not_ready: {
    title: "Delivery is not ready",
    recovery: "Open project delivery settings, validate the channel, then retry.",
  },
  delivery_git_cli_failed: {
    title: "Git delivery failed",
    recovery: "Review the delivery details, then retry after the Git issue is resolved.",
  },
  delivery_remote_request_failed: {
    title: "Remote delivery failed",
    recovery: "Check the remote service status and retry delivery.",
  },
  audit_write_failed: {
    title: "Audit record could not be written",
    recovery: "Retry after audit storage is available.",
  },
  log_query_invalid: {
    title: "Log query is invalid",
    recovery: "Adjust the log filters and query again.",
  },
  log_payload_blocked: {
    title: "Log payload was blocked",
    recovery: "Use the redacted summary or inspect the linked safe detail.",
  },
  config_invalid_value: {
    title: "Configuration value is invalid",
    recovery: "Correct the highlighted configuration value and save again.",
  },
  config_hard_limit_exceeded: {
    title: "Configuration exceeds a platform limit",
    recovery: "Lower the value to fit the platform limit.",
  },
  config_version_conflict: {
    title: "Configuration changed",
    recovery: "Refresh settings, review the latest value, and save again.",
  },
  config_storage_unavailable: {
    title: "Configuration storage is unavailable",
    recovery: "Retry after local storage is available.",
  },
  config_snapshot_unavailable: {
    title: "Configuration snapshot is unavailable",
    recovery: "Refresh the run and retry after the snapshot is available.",
  },
  config_credential_env_not_allowed: {
    title: "Credential reference is not allowed",
    recovery: "Use an allowed environment credential reference.",
  },
  config_snapshot_mutation_blocked: {
    title: "Configuration snapshot cannot be changed",
    recovery: "Apply configuration changes to a new run instead.",
  },
  validation_error: {
    title: "Request needs correction",
    recovery: "Check the entered values and try again.",
  },
  not_found: {
    title: "Item was not found",
    recovery: "Refresh the workspace and confirm the item still exists.",
  },
  internal_error: {
    title: "Unexpected server error",
    recovery: "Retry the action. Use the request id if the failure repeats.",
  },
  unknown_error: {
    title: "Request failed",
    recovery: "Refresh the workspace and retry the action.",
  },
} satisfies Record<FormattedApiError["code"], ErrorCopy>;

const KNOWN_CODES = new Set<string>(Object.keys(ERROR_COPY));

const SENSITIVE_PATTERNS = [
  /Traceback/u,
  /File\s+"[^"]+",\s+line\s+\d+/iu,
  /^\s*at\s+\S+/imu,
  /\bat\s+\S.*\([^)]*:\d+:\d+\)/iu,
  /Authorization:/iu,
  /Cookie:/iu,
  /\bBearer\s+\S+/iu,
  /api[_-]?key\s*[=:]\s*\S+/iu,
  /(?:^|\b)token\s*[=:]\s*\S+/iu,
  /(?:^|\b)(?:client[_-]?secret|secret)\s*[=:]\s*\S+/iu,
  /(?:^|\b)credential\s*[=:]\s*\S+/iu,
  /password\s*[=:]\s*\S+/iu,
  /private key/iu,
];

function readErrorLike(error: unknown): {
  code: string | undefined;
  message: string;
  requestId: string | null;
  fieldErrors: ApiFieldError[];
} {
  if (typeof error === "string") {
    return {
      code: undefined,
      message: error,
      requestId: null,
      fieldErrors: [],
    };
  }

  if (!error || typeof error !== "object") {
    return {
      code: undefined,
      message: "Request failed.",
      requestId: null,
      fieldErrors: [],
    };
  }

  const candidate = error as ErrorLike;
  return {
    code:
      typeof candidate.code === "string"
        ? candidate.code
        : readString(candidate.error_code),
    message:
      typeof candidate.message === "string"
        ? candidate.message
        : "Request failed.",
    requestId: readRequestId(candidate.requestId ?? candidate.request_id),
    fieldErrors: readFieldErrors(candidate.fieldErrors ?? candidate.field_errors),
  };
}

function normalizeApiErrorCode(code: string | undefined): FormattedApiError["code"] {
  if (code && KNOWN_CODES.has(code)) {
    return code as FormattedApiError["code"];
  }
  return "unknown_error";
}

function formatErrorDetail(message: string, fieldErrors: ApiFieldError[]): string {
  const trimmed = message.trim();
  if (fieldErrors.length === 0) {
    return trimmed || "Request failed.";
  }

  const fieldSummary = fieldErrors
    .map((fieldError) => `${fieldError.field}: ${fieldError.message}`)
    .join("; ");
  return [trimmed, fieldSummary].filter(Boolean).join(" ");
}

function sanitizeErrorDetail(message: string): string {
  const value = message.trim() || "Request failed.";
  if (SENSITIVE_PATTERNS.some((pattern) => pattern.test(value))) {
    return "The request failed, but sensitive details were hidden.";
  }
  return value;
}

function readString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function readRequestId(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function readFieldErrors(value: unknown): ApiFieldError[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.filter((item): item is ApiFieldError => {
    if (!item || typeof item !== "object") {
      return false;
    }
    const candidate = item as Partial<ApiFieldError>;
    return (
      typeof candidate.field === "string" &&
      typeof candidate.message === "string"
    );
  });
}
