import { apiRequest, type ApiRequestOptions } from "./client";
import type { ApprovalResultFeedEntry } from "./types";

export type ApprovalRejectRequest = {
  reason: string;
};

export function approveApproval(
  approvalId: string,
  options?: ApiRequestOptions,
): Promise<ApprovalResultFeedEntry> {
  return apiRequest(`/api/approvals/${approvalId}/approve`, {
    ...options,
    method: "POST",
  });
}

export function rejectApproval(
  approvalId: string,
  body: ApprovalRejectRequest,
  options?: ApiRequestOptions,
): Promise<ApprovalResultFeedEntry> {
  return apiRequest(`/api/approvals/${approvalId}/reject`, {
    ...options,
    method: "POST",
    body,
  });
}
