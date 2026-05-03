import { apiRequest, type ApiRequestOptions } from "../../api/client";
import type { ToolConfirmationFeedEntry } from "../../api/types";

export type ToolConfirmationDecision = "allow" | "deny";

export type ToolConfirmationDecisionResponse = {
  tool_confirmation: ToolConfirmationFeedEntry;
};

export function submitToolConfirmationDecision(
  entry: ToolConfirmationFeedEntry,
  decision: ToolConfirmationDecision,
  options?: ApiRequestOptions,
): Promise<ToolConfirmationDecisionResponse> {
  const body = {};
  return apiRequest(
    `/api/tool-confirmations/${entry.tool_confirmation_id}/${decision}`,
    {
      ...options,
      body,
      method: "POST",
    },
  );
}
