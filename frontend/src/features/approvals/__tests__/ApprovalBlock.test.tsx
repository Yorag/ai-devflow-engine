import { QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { approveApproval, rejectApproval } from "../../../api/approvals";
import type { ApprovalRequestFeedEntry } from "../../../api/types";
import { createQueryClient } from "../../../app/query-client";
import { ApprovalBlock } from "../ApprovalBlock";

vi.mock("../../../api/approvals", async () => {
  const actual = await vi.importActual<typeof import("../../../api/approvals")>(
    "../../../api/approvals",
  );
  return {
    ...actual,
    approveApproval: vi.fn(),
    rejectApproval: vi.fn(),
  };
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function buildApprovalEntry(
  overrides: Partial<ApprovalRequestFeedEntry> = {},
): ApprovalRequestFeedEntry {
  return {
    entry_id: "entry-approval-request",
    run_id: "run-waiting-approval",
    type: "approval_request",
    occurred_at: "2026-05-01T09:50:00.000Z",
    approval_id: "approval-code-review",
    approval_type: "code_review_approval",
    status: "pending",
    title: "Review code review output",
    approval_object_excerpt: "The patch updates the workspace approval block.",
    risk_excerpt: "Touches only frontend AL06 files.",
    approval_object_preview: { stage_type: "code_review" },
    approve_action: "approve",
    reject_action: "reject",
    is_actionable: true,
    requested_at: "2026-05-01T09:50:00.000Z",
    delivery_readiness_status: "ready",
    delivery_readiness_message: null,
    open_settings_action: null,
    disabled_reason: null,
    ...overrides,
  };
}

function renderApprovalBlock(
  entry: ApprovalRequestFeedEntry,
  options: {
    currentRunId?: string | null;
    sessionId?: string;
    projectId?: string;
    onOpenSettings?: () => void;
  } = {},
) {
  const queryClient = createQueryClient();

  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <ApprovalBlock
          entry={entry}
          currentRunId={options.currentRunId ?? "run-waiting-approval"}
          sessionId={options.sessionId ?? "session-waiting-approval"}
          projectId={options.projectId ?? "project-default"}
          onOpenSettings={options.onOpenSettings}
        />
      </QueryClientProvider>,
    ),
  };
}

describe("ApprovalBlock", () => {
  it("submits approve inline for the current pending run and invalidates workspace queries", async () => {
    vi.mocked(approveApproval).mockResolvedValue({
      entry_id: "entry-approval-result",
      run_id: "run-waiting-approval",
      type: "approval_result",
      occurred_at: "2026-05-01T09:56:00.000Z",
      approval_id: "approval-code-review",
      approval_type: "code_review_approval",
      decision: "approved",
      reason: null,
      created_at: "2026-05-01T09:56:00.000Z",
      next_stage_type: "delivery_integration",
    });

    const { queryClient } = renderApprovalBlock(buildApprovalEntry());
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => {
      expect(approveApproval).toHaveBeenCalledWith(
        "approval-code-review",
        expect.anything(),
      );
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ["sessions", "session-waiting-approval", "workspace"],
        refetchType: "all",
      });
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ["projects", "project-default", "sessions"],
        refetchType: "all",
      });
    });
  });

  it("expands an inline reject form, requires a reason, and submits it through rejectApproval", async () => {
    vi.mocked(rejectApproval).mockResolvedValue({
      entry_id: "entry-approval-result",
      run_id: "run-waiting-approval",
      type: "approval_result",
      occurred_at: "2026-05-01T09:56:00.000Z",
      approval_id: "approval-code-review",
      approval_type: "code_review_approval",
      decision: "rejected",
      reason: "The rollback explanation is still incomplete.",
      created_at: "2026-05-01T09:56:00.000Z",
      next_stage_type: "code_generation",
    });

    renderApprovalBlock(buildApprovalEntry());

    fireEvent.click(screen.getByRole("button", { name: "Reject" }));

    const form = screen.getByRole("form", { name: "Reject approval with reason" });
    expect(
      within(form).getByRole("button", { name: "Submit reject reason" }),
    ).toHaveProperty("disabled", true);
    fireEvent.change(within(form).getByLabelText("Reject reason"), {
      target: { value: "The rollback explanation is still incomplete." },
    });
    fireEvent.click(
      within(form).getByRole("button", { name: "Submit reject reason" }),
    );

    await waitFor(() => {
      expect(rejectApproval).toHaveBeenCalledWith(
        "approval-code-review",
        { reason: "The rollback explanation is still incomplete." },
        expect.anything(),
      );
    });
  });

  it("disables only Approve when git delivery readiness is not ready and exposes a settings shortcut", () => {
    const onOpenSettings = vi.fn();
    renderApprovalBlock(
      buildApprovalEntry({
        delivery_readiness_status: "invalid",
        delivery_readiness_message: "Credential reference cannot be resolved.",
        open_settings_action: "open_general_settings",
      }),
      { onOpenSettings },
    );

    expect(screen.getByRole("button", { name: "Approve" })).toHaveProperty(
      "disabled",
      true,
    );
    expect(screen.getByRole("button", { name: "Reject" })).toHaveProperty(
      "disabled",
      false,
    );
    fireEvent.click(screen.getByRole("button", { name: "Open settings" }));
    expect(onOpenSettings).toHaveBeenCalledTimes(1);
  });

  it("shows disabled pending controls for a paused current run and hides actions for history runs", () => {
    const { rerender } = renderApprovalBlock(
      buildApprovalEntry({
        is_actionable: false,
        disabled_reason: "当前运行已暂停，恢复后继续等待审批",
      }),
    );

    expect(screen.getByRole("button", { name: "Approve" })).toHaveProperty(
      "disabled",
      true,
    );
    expect(screen.getByRole("button", { name: "Reject" })).toHaveProperty(
      "disabled",
      true,
    );
    expect(screen.getByText("当前运行已暂停，恢复后继续等待审批")).toBeTruthy();

    rerender(
      <QueryClientProvider client={createQueryClient()}>
        <ApprovalBlock entry={buildApprovalEntry()} currentRunId="run-latest" />
      </QueryClientProvider>,
    );

    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
    expect(screen.getByText("Pending")).toBeTruthy();
  });
});
