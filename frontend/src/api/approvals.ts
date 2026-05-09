import { apiRequest, type ApiRequestOptions } from "./client";
import type { ApprovalCommandResponse } from "./types";

export type ApprovalRejectRequest = {
  reason: string;
};

export function approveApproval(
  approvalId: string,
  options?: ApiRequestOptions,
): Promise<ApprovalCommandResponse> {
  return apiRequest(`/api/approvals/${approvalId}/approve`, {
    ...options,
    method: "POST",
    body: {},
  });
}

export function rejectApproval(
  approvalId: string,
  body: ApprovalRejectRequest,
  options?: ApiRequestOptions,
): Promise<ApprovalCommandResponse> {
  return apiRequest(`/api/approvals/${approvalId}/reject`, {
    ...options,
    method: "POST",
    body,
  });
}
