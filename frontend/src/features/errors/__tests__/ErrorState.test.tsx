import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "../../../api/client";
import type { ApiErrorCode } from "../../../api/types";
import { ErrorState, formatApiError } from "../ErrorState";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function apiError(params: {
  code: ApiErrorCode;
  message: string;
  status?: number;
  requestId?: string | null;
}): ApiRequestError {
  return new ApiRequestError({
    status: params.status ?? 409,
    code: params.code,
    message: params.message,
    requestId: params.requestId ?? "request-error-1",
  });
}

describe("formatApiError", () => {
  it("maps approval and run command conflicts to clear recovery actions", () => {
    expect(
      formatApiError(
        apiError({
          code: "approval_not_actionable",
          message: "Current run is paused; resume it to continue approval.",
        }),
      ),
    ).toMatchObject({
      title: "Approval cannot be submitted",
      detail: "Current run is paused; resume it to continue approval.",
      recovery: "Resume the run, then submit the same approval again.",
      requestId: "request-error-1",
    });

    expect(
      formatApiError(
        apiError({
          code: "run_command_not_actionable",
          message: "Run can be resumed only when it is paused.",
        }),
      ),
    ).toMatchObject({
      title: "Run command is not available",
      recovery:
        "Refresh the workspace and use the action available for the current run state.",
    });
  });

  it("maps delivery, tool, provider, validation, and generic API errors", () => {
    expect(
      formatApiError(
        apiError({
          code: "delivery_snapshot_not_ready",
          message: "DeliveryChannel is not ready for approval.",
        }),
      ).recovery,
    ).toBe("Open project delivery settings, validate the channel, then retry.");

    expect(
      formatApiError(
        apiError({
          code: "tool_confirmation_not_actionable",
          message: "Tool confirmation is not actionable.",
        }),
      ).title,
    ).toBe("Tool confirmation cannot be submitted");

    expect(
      formatApiError(
        apiError({
          code: "provider_circuit_open",
          message: "Provider circuit breaker is open.",
          status: 503,
        }),
      ).recovery,
    ).toBe(
      "Wait for the provider circuit to recover or adjust provider settings before retrying.",
    );

    expect(
      formatApiError(
        apiError({
          code: "validation_error",
          message: "Request validation failed.",
          status: 422,
        }),
      ).title,
    ).toBe("Request needs correction");

    expect(formatApiError(new Error("Network offline"))).toMatchObject({
      title: "Request failed",
      detail: "Network offline",
    });
  });

  it("does not expose credential-shaped content from backend messages", () => {
    const formatted = formatApiError(
      apiError({
        code: "config_credential_env_not_allowed",
        message: "Authorization: Bearer real-secret-token api_key=real-secret",
        status: 422,
      }),
    );

    expect(formatted.detail).toBe(
      "The request failed, but sensitive details were hidden.",
    );
    expect(JSON.stringify(formatted)).not.toContain("real-secret");
    expect(JSON.stringify(formatted)).not.toContain("Bearer");
  });

  it("hides token, secret, and credential-shaped diagnostics", () => {
    const formatted = formatApiError(
      apiError({
        code: "internal_error",
        message:
          "token=raw-token client_secret=raw-secret credential=raw-credential",
        status: 500,
      }),
    );

    expect(formatted.detail).toBe(
      "The request failed, but sensitive details were hidden.",
    );
    expect(JSON.stringify(formatted)).not.toContain("raw-token");
    expect(JSON.stringify(formatted)).not.toContain("raw-secret");
    expect(JSON.stringify(formatted)).not.toContain("raw-credential");
  });
});

describe("ErrorState", () => {
  it("renders a safe alert with request id and recovery action", () => {
    const onAction = vi.fn();

    render(
      <ErrorState
        error={apiError({
          code: "delivery_snapshot_not_ready",
          message: "DeliveryChannel is not ready for approval.",
        })}
        actionLabel="Open settings"
        onAction={onAction}
      />,
    );

    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByText("Delivery is not ready")).toBeTruthy();
    expect(
      screen.getByText("DeliveryChannel is not ready for approval."),
    ).toBeTruthy();
    expect(screen.getByText("Request request-error-1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Open settings" }));
    expect(onAction).toHaveBeenCalledTimes(1);
  });
});
