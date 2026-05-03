import { describe, expect, it, vi } from "vitest";

import type { ApiRequestError, ApiRequestOptions } from "../../../api/client";
import type { ToolConfirmationFeedEntry } from "../../../api/types";
import { submitToolConfirmationDecision } from "../tool-confirmation-actions";

function buildEntry(
  overrides: Partial<ToolConfirmationFeedEntry> = {},
): ToolConfirmationFeedEntry {
  return {
    entry_id: "entry-tool-confirmation",
    run_id: "run-running",
    type: "tool_confirmation",
    occurred_at: "2026-05-01T09:20:00.000Z",
    stage_run_id: "stage-code-generation-running",
    tool_confirmation_id: "tool-confirmation-1",
    status: "pending",
    title: "Confirm bash tool action",
    tool_name: "bash",
    command_preview: "npm install",
    target_summary: "frontend/package-lock.json",
    risk_level: "high_risk",
    risk_categories: ["dependency_change", "network_download"],
    reason: "Installing dependencies changes lock files and downloads packages.",
    expected_side_effects: ["package-lock update"],
    allow_action: "allow:tool-confirmation-1",
    deny_action: "deny:tool-confirmation-1",
    is_actionable: true,
    requested_at: "2026-05-01T09:20:00.000Z",
    responded_at: null,
    decision: null,
    deny_followup_action: null,
    deny_followup_summary: null,
    disabled_reason: null,
    ...overrides,
  };
}

describe("submitToolConfirmationDecision", () => {
  it("posts allow decisions to the canonical tool-confirmation allow endpoint", async () => {
    const fetcher = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            tool_confirmation: buildEntry({
              status: "allowed",
              decision: "allowed",
              responded_at: "2026-05-01T09:21:00.000Z",
            }),
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
    );
    const request: ApiRequestOptions = { fetcher };

    const result = await submitToolConfirmationDecision(
      buildEntry(),
      "allow",
      request,
    );

    expect(result.tool_confirmation.status).toBe("allowed");
    expect(fetcher).toHaveBeenCalledWith(
      "/api/tool-confirmations/tool-confirmation-1/allow",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({}),
      }),
    );
  });

  it("posts deny decisions to the canonical tool-confirmation deny endpoint", async () => {
    const fetcher = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            tool_confirmation: buildEntry({
              status: "denied",
              decision: "denied",
              responded_at: "2026-05-01T09:21:00.000Z",
              deny_followup_action: "run_failed",
              deny_followup_summary:
                "The current run will fail because no low-risk alternative path exists.",
            }),
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
    );
    const request: ApiRequestOptions = { fetcher };

    const result = await submitToolConfirmationDecision(
      buildEntry(),
      "deny",
      request,
    );

    expect(result.tool_confirmation.status).toBe("denied");
    expect(result.tool_confirmation.deny_followup_action).toBe("run_failed");
    expect(fetcher).toHaveBeenCalledWith(
      "/api/tool-confirmations/tool-confirmation-1/deny",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({}),
      }),
    );
  });

  it("throws through ApiRequestError payloads unchanged", async () => {
    const error = new Error(
      "Current run is paused; resume it to continue tool confirmation.",
    ) as ApiRequestError;
    const fetcher = vi.fn(async () => {
      throw error;
    });

    await expect(
      submitToolConfirmationDecision(buildEntry(), "allow", { fetcher }),
    ).rejects.toBe(error);
  });
});
