import { expect, test, type Page, type Route } from "@playwright/test";

const timestamp = "2026-05-01T09:00:00.000Z";
const project = {
  project_id: "project-default",
  name: "AI Devflow Engine",
  root_path: "C:/Users/lkw/Desktop/github/agent-project/ai-devflow-engine",
  default_delivery_channel_id: "delivery-default-demo",
  is_default: true,
  created_at: timestamp,
  updated_at: timestamp,
};

const template = {
  template_id: "template-feature",
  name: "新功能开发流程",
  description: "Build a new feature.",
  template_source: "system_template",
  base_template_id: null,
  fixed_stage_sequence: [
    "requirement_analysis",
    "solution_design",
    "code_generation",
    "test_generation_execution",
    "code_review",
    "delivery_integration",
  ],
  stage_role_bindings: [
    binding("requirement_analysis", "role-requirement-analyst"),
    binding("solution_design", "role-solution-designer"),
    binding("code_generation", "role-code-generator"),
    binding("test_generation_execution", "role-test-runner"),
    binding("code_review", "role-code-reviewer"),
    binding("delivery_integration", "role-delivery-integrator"),
  ],
  approval_checkpoints: ["solution_design_approval", "code_review_approval"],
  auto_regression_enabled: true,
  max_auto_regression_retries: 1,
  created_at: timestamp,
  updated_at: timestamp,
};

const provider = {
  provider_id: "provider-deepseek",
  display_name: "DeepSeek",
  provider_source: "builtin",
  protocol_type: "openai_completions_compatible",
  base_url: "https://api.deepseek.com",
  api_key_ref: "env:DEEPSEEK_API_KEY",
  default_model_id: "deepseek-chat",
  supported_model_ids: ["deepseek-chat"],
  runtime_capabilities: [
    {
      model_id: "deepseek-chat",
      context_window_tokens: 128000,
      max_output_tokens: 4096,
      supports_tool_calling: true,
      supports_structured_output: true,
      supports_native_reasoning: false,
    },
  ],
  created_at: timestamp,
  updated_at: timestamp,
};

const deliveryChannel = {
  project_id: project.project_id,
  delivery_channel_id: "delivery-default-demo",
  delivery_mode: "demo_delivery",
  scm_provider_type: null,
  repository_identifier: null,
  default_branch: null,
  code_review_request_type: null,
  credential_ref: null,
  credential_status: "ready",
  readiness_status: "ready",
  readiness_message: null,
  last_validated_at: "2026-05-01T08:55:00.000Z",
  updated_at: "2026-05-01T08:55:00.000Z",
};

test.describe("function one manual intervention path", () => {
  test("covers approval rejection, paused approval, terminate, and rerun focus", async ({
    page,
  }) => {
    const api = createControlFlowApi();
    await installControlFlowFixture(page, api);
    await acceptConfirmDialogs(page);

    await page.goto("/console");
    await page.getByLabel("当前输入").fill("Add guarded delivery controls.");
    await page.getByRole("button", { name: "发送" }).click();

    const approval = page.getByLabel("Approval request feed entry").filter({
      hasText: "Review solution design",
    });
    await approval.getByRole("button", { name: "Reject" }).click();
    await page
      .getByLabel("Reject reason")
      .fill("The implementation plan must keep rollback visible.");
    await page.getByRole("button", { name: "Submit reject reason" }).click();

    await expect(
      page.getByLabel("Approval result feed entry").filter({ hasText: "Rejected" }),
    ).toContainText("The implementation plan must keep rollback visible.");
    await expect(
      page
        .getByLabel("Control item feed entry")
        .filter({ hasText: "Rollback to Solution Design" }),
    ).toContainText("Solution Design");

    const revisedApproval = page.getByLabel("Approval request feed entry").filter({
      hasText: "Review revised solution design",
    });
    await expect(revisedApproval).toBeVisible();
    await page.getByRole("button", { name: "暂停" }).click();
    await expect(revisedApproval.getByRole("button", { name: "Approve" })).toBeDisabled();
    await expect(revisedApproval.getByRole("button", { name: "Reject" })).toBeDisabled();
    await expect(revisedApproval).toContainText("当前运行已暂停，恢复后继续等待审批");

    await page.getByRole("button", { name: "恢复" }).click();
    await expect(revisedApproval.getByRole("button", { name: "Approve" })).toBeEnabled();
    await revisedApproval.getByRole("button", { name: "Reject" }).click();
    await page.getByLabel("Reject reason").fill("Stale approval submit after pause.");
    await page.getByRole("button", { name: "Submit reject reason" }).click();
    await expect(revisedApproval).toContainText(
      "Approval cannot be submitted while the run is paused.",
    );

    await page.getByRole("button", { name: "终止当前运行" }).click();
    await expect(page.getByLabel("System status feed entry")).toContainText("Run terminated");
    await expect(page.getByRole("button", { name: "Retry run" })).toBeVisible();
    await page.getByRole("button", { name: "Retry run" }).click();

    await expect(page.getByLabel("Run 2 boundary")).toBeFocused();
    await expect(page.getByLabel("Run 2 boundary")).toContainText("Running");
    await expect(page.getByLabel("Run 2 boundary")).toContainText("Requirement Analysis");
    await expect(revisedApproval).toContainText("This approval belongs to a historical run.");
    await expect(revisedApproval.getByRole("button", { name: "Approve" })).toHaveCount(0);
    await expect(revisedApproval.getByRole("button", { name: "Reject" })).toHaveCount(0);
    await expectNoGlobalHorizontalOverflow(page);
  });

  test("covers high-risk tool allow, deny, paused disablement, and narrow layout", async ({
    page,
  }) => {
    const api = createControlFlowApi({ initialMode: "tool_confirmation" });
    await installControlFlowFixture(page, api);
    await acceptConfirmDialogs(page);

    await page.goto("/console");

    const firstTool = page.getByLabel("Tool confirmation feed entry").filter({
      hasText: "Approve dependency install",
    });
    await expect(firstTool).toContainText("High-risk tool confirmation");
    await page.getByRole("button", { name: "暂停" }).click();
    await expect(firstTool.getByRole("button", { name: "允许本次执行" })).toBeDisabled();
    await expect(firstTool.getByRole("button", { name: "拒绝本次执行" })).toBeDisabled();
    await expect(firstTool).toContainText("当前运行已暂停，恢复后继续等待工具确认");
    await page.getByRole("button", { name: "恢复" }).click();
    await firstTool.getByRole("button", { name: "允许本次执行" }).click();
    await expect(firstTool).toContainText("Allowed");

    const secondTool = page.getByLabel("Tool confirmation feed entry").filter({
      hasText: "Approve workspace cleanup",
    });
    await secondTool.getByRole("button", { name: "拒绝本次执行" }).click();
    await expect(secondTool).toContainText("Denied");
    await expect(secondTool).toContainText("拒绝后当前运行将失败");
    await expect(secondTool).not.toContainText("Solution design approval");
    await expect(secondTool).not.toContainText("Code review approval");
    await expect(
      page.getByLabel("System status feed entry").filter({ hasText: "Tool confirmation denied" }),
    ).toContainText("Tool confirmation denied");
    await expect(page.getByRole("button", { name: "Retry run" })).toBeVisible();
    await page.getByRole("button", { name: "Retry run" }).click();
    await expect(page.getByLabel("Run 2 boundary")).toContainText("Running");
    await expect(page.getByLabel("Run 2 boundary")).toContainText("Requirement Analysis");
    await expect(secondTool).toContainText("This tool confirmation belongs to a historical run.");
    await expect(secondTool.getByRole("button", { name: "允许本次执行" })).toBeDisabled();
    await expect(secondTool.getByRole("button", { name: "拒绝本次执行" })).toBeDisabled();

    await page.setViewportSize({ width: 390, height: 900 });
    await expect(page.getByLabel("Narrative workspace")).toBeVisible();
    await expect(secondTool).toBeVisible();
    await expectNoGlobalHorizontalOverflow(page);
  });
});

type ControlFlowMode = "draft" | "approval" | "tool_confirmation";

async function installControlFlowFixture(
  page: Page,
  api: ReturnType<typeof createControlFlowApi>,
): Promise<void> {
  await page.addInitScript(() => {
    class MockEventSource {
      readonly url: string;
      onerror: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      onopen: ((event: Event) => void) | null = null;
      readyState = 1;

      constructor(url: string) {
        this.url = url;
        setTimeout(() => this.onopen?.(new Event("open")), 0);
      }

      addEventListener(): void {}
      removeEventListener(): void {}
      close(): void {
        this.readyState = 2;
      }
      dispatchEvent(): boolean {
        return true;
      }
    }

    Object.defineProperty(window, "EventSource", {
      configurable: true,
      writable: true,
      value: MockEventSource,
    });
  });

  await page.route(
    (url) => url.pathname.startsWith("/api/"),
    async (route) => api.handle(route),
  );
}

function createControlFlowApi(options: { initialMode?: ControlFlowMode } = {}) {
  const session = {
    session_id: "session-control-flow",
    project_id: project.project_id,
    display_name: "Manual intervention regression",
    status: "draft",
    selected_template_id: template.template_id,
    current_run_id: null as string | null,
    latest_stage_type: null as string | null,
    created_at: timestamp,
    updated_at: timestamp,
  };
  const runs: Array<Record<string, unknown>> = [];
  const feed: Array<Record<string, unknown>> = [];
  let currentRunId: string | null = null;
  let currentStageType: string | null = null;
  let resumeStatus: "running" | "waiting_approval" | "waiting_tool_confirmation" =
    "waiting_approval";

  if (options.initialMode === "approval") {
    startApprovalRun("Existing guarded delivery controls.");
  } else if (options.initialMode === "tool_confirmation") {
    startToolConfirmationRun();
  }

  function workspace() {
    return {
      session,
      project,
      delivery_channel: deliveryChannel,
      runs,
      narrative_feed: feed,
      current_run_id: currentRunId,
      current_stage_type: currentStageType,
      composer_state: composerState(session.status, currentRunId),
    };
  }

  function startApprovalRun(content: string) {
    currentRunId = "run-control-1";
    currentStageType = "solution_design";
    resumeStatus = "waiting_approval";
    Object.assign(session, {
      status: "waiting_approval",
      current_run_id: currentRunId,
      latest_stage_type: currentStageType,
      updated_at: "2026-05-01T09:10:00.000Z",
    });
    runs.splice(0, runs.length, {
      run_id: currentRunId,
      attempt_index: 1,
      status: "waiting_approval",
      trigger_source: "initial_requirement",
      started_at: "2026-05-01T09:10:00.000Z",
      ended_at: null,
      current_stage_type: currentStageType,
      is_active: true,
    });
    feed.splice(
      0,
      feed.length,
      userMessage({
        entryId: "entry-control-requirement",
        runId: currentRunId,
        content,
      }),
      stageNode({
        entryId: "entry-solution-stage",
        runId: currentRunId,
        stageRunId: "stage-solution-control",
        stageType: "solution_design",
        status: "completed",
        summary:
          "Prepared a guarded delivery control plan with explicit rollback visibility.",
        itemTitle: "Design decision",
        itemSummary:
          "Rejected approvals return to Solution Design instead of tool semantics.",
      }),
      approvalRequest({
        entryId: "entry-solution-approval",
        runId: currentRunId,
        approvalId: "approval-solution-design",
        approvalType: "solution_design_approval",
        title: "Review solution design",
        excerpt:
          "The solution design keeps rollback, retry, and manual intervention states visible.",
      }),
    );
  }

  function startToolConfirmationRun() {
    currentRunId = "run-tool-control";
    currentStageType = "test_generation_execution";
    resumeStatus = "waiting_tool_confirmation";
    Object.assign(session, {
      status: "waiting_tool_confirmation",
      current_run_id: currentRunId,
      latest_stage_type: currentStageType,
      updated_at: "2026-05-01T09:18:00.000Z",
    });
    runs.splice(0, runs.length, {
      run_id: currentRunId,
      attempt_index: 1,
      status: "waiting_tool_confirmation",
      trigger_source: "initial_requirement",
      started_at: "2026-05-01T09:12:00.000Z",
      ended_at: null,
      current_stage_type: currentStageType,
      is_active: true,
    });
    feed.splice(
      0,
      feed.length,
      stageNode({
        entryId: "entry-tool-stage",
        runId: currentRunId,
        stageRunId: "stage-tool-control",
        stageType: "test_generation_execution",
        status: "waiting_tool_confirmation",
        summary:
          "Generated tests require a high-risk dependency installation confirmation.",
        itemTitle: "Tool confirmation needed",
        itemSummary: "Dependency installation is blocked until the user allows it.",
      }),
      toolConfirmation({
        entryId: "entry-tool-install",
        runId: currentRunId,
        stageRunId: "stage-tool-control",
        toolConfirmationId: "tool-confirmation-install",
        title: "Approve dependency install",
        toolName: "npm",
        commandPreview: "npm install playwright",
        targetSummary: "e2e/package.json and package-lock.json",
        riskCategories: ["dependency_change", "lockfile_change", "network_download"],
        reason:
          "The test runner needs a dependency install before executing browser checks.",
        expectedSideEffects: [
          "Update local dependency tree",
          "Write package lock metadata",
        ],
      }),
    );
  }

  function rejectApproval(reason: string) {
    const originalApproval = findFeedEntry("approval-solution-design");
    if (originalApproval) {
      originalApproval.status = "rejected";
      originalApproval.is_actionable = false;
    }
    Object.assign(session, {
      status: "waiting_approval",
      latest_stage_type: "solution_design",
      updated_at: "2026-05-01T09:24:00.000Z",
    });
    Object.assign(requireRun("run-control-1"), {
      status: "waiting_approval",
      current_stage_type: "solution_design",
    });
    currentStageType = "solution_design";
    resumeStatus = "waiting_approval";
    feed.push(
      approvalResult({
        entryId: "entry-solution-rejected",
        runId: "run-control-1",
        approvalId: "approval-solution-design",
        approvalType: "solution_design_approval",
        decision: "rejected",
        reason,
        nextStageType: "solution_design",
      }),
      controlItem({
        entryId: "entry-rollback-solution",
        runId: "run-control-1",
        controlRecordId: "control-rollback-solution",
        controlType: "rollback",
        sourceStageType: "solution_design",
        targetStageType: "solution_design",
        title: "Rollback to Solution Design",
        summary:
          "Approval rejection returned the active run to Solution Design for revision.",
        payloadRef: "artifact-rollback-solution",
      }),
      stageNode({
        entryId: "entry-revised-solution-stage",
        runId: "run-control-1",
        stageRunId: "stage-revised-solution-control",
        stageType: "solution_design",
        status: "completed",
        summary:
          "Revised the implementation plan to keep rollback controls visible.",
        itemTitle: "Revision",
        itemSummary: "The rollback path remains visible in the Narrative Feed.",
      }),
      approvalRequest({
        entryId: "entry-revised-solution-approval",
        runId: "run-control-1",
        approvalId: "approval-solution-revised",
        approvalType: "solution_design_approval",
        title: "Review revised solution design",
        excerpt:
          "The revised design preserves the rollback control item and approval history.",
      }),
    );
  }

  function pauseRun(runId: string) {
    const run = requireRun(runId);
    resumeStatus =
      session.status === "waiting_tool_confirmation"
        ? "waiting_tool_confirmation"
        : session.status === "running"
          ? "running"
          : "waiting_approval";
    Object.assign(session, {
      status: "paused",
      updated_at: "2026-05-01T09:28:00.000Z",
    });
    Object.assign(run, { status: "paused" });
    setPendingEntriesActionable(false);
    return run;
  }

  function resumeRun(runId: string) {
    const run = requireRun(runId);
    Object.assign(session, {
      status: resumeStatus,
      updated_at: "2026-05-01T09:30:00.000Z",
    });
    Object.assign(run, { status: resumeStatus });
    setPendingEntriesActionable(true);
    return run;
  }

  function terminateRun(runId: string) {
    const run = requireRun(runId);
    Object.assign(session, {
      status: "terminated",
      updated_at: "2026-05-01T09:34:00.000Z",
    });
    Object.assign(run, {
      status: "terminated",
      ended_at: "2026-05-01T09:34:00.000Z",
      is_active: true,
    });
    setPendingEntriesActionable(false);
    if (!findFeedEntry("entry-run-terminated")) {
      feed.push(
        systemStatus({
          entryId: "entry-run-terminated",
          runId,
          status: "terminated",
          title: "Run terminated",
          reason:
            "The current run was terminated by the operator. Retry is available from the terminal status.",
          retryAction: "create_rerun",
        }),
      );
    }
    return run;
  }

  function createRerun() {
    const previousRun = currentRunId ? requireRun(currentRunId) : null;
    if (previousRun) {
      previousRun.is_active = false;
    }
    currentRunId = "run-control-rerun";
    currentStageType = "requirement_analysis";
    resumeStatus = "running";
    const run = {
      run_id: currentRunId,
      attempt_index: 2,
      status: "running",
      trigger_source: "retry",
      started_at: "2026-05-01T09:40:00.000Z",
      ended_at: null,
      current_stage_type: currentStageType,
      is_active: true,
    };
    runs.push(run);
    Object.assign(session, {
      status: "running",
      current_run_id: currentRunId,
      latest_stage_type: currentStageType,
      updated_at: "2026-05-01T09:40:00.000Z",
    });
    markHistoricalPendingControlEntries();
    feed.push(
      stageNode({
        entryId: "entry-rerun-requirement-stage",
        runId: currentRunId,
        stageRunId: "stage-rerun-requirement-control",
        stageType: "requirement_analysis",
        status: "running",
        summary:
          "Retry started a fresh run at Requirement Analysis with a clean active boundary.",
        itemTitle: "Retry checkpoint",
        itemSummary: "Run 2 starts at Requirement Analysis after retry.",
      }),
    );
    return run;
  }

  function allowTool(toolConfirmationId: string) {
    const entry = requireToolConfirmation(toolConfirmationId);
    Object.assign(entry, {
      status: "allowed",
      is_actionable: false,
      responded_at: "2026-05-01T09:26:00.000Z",
      decision: "allowed",
      disabled_reason: null,
    });
    if (!findFeedEntry("tool-confirmation-cleanup")) {
      feed.push(
        toolConfirmation({
          entryId: "entry-tool-cleanup",
          runId: "run-tool-control",
          stageRunId: "stage-tool-control",
          toolConfirmationId: "tool-confirmation-cleanup",
          title: "Approve workspace cleanup",
          toolName: "Remove-Item",
          commandPreview: "Remove-Item -Recurse .runtime/tmp",
          targetSummary: "Temporary workspace artifacts",
          riskCategories: ["file_delete_or_move", "broad_write"],
          reason:
            "The cleanup command can delete workspace files and needs explicit tool confirmation.",
          expectedSideEffects: ["Delete temporary files from the workspace"],
        }),
      );
    }
    return entry;
  }

  function denyTool(toolConfirmationId: string) {
    const entry = requireToolConfirmation(toolConfirmationId);
    Object.assign(entry, {
      status: "denied",
      is_actionable: false,
      responded_at: "2026-05-01T09:32:00.000Z",
      decision: "denied",
      deny_followup_action: "run_failed",
      deny_followup_summary: "拒绝后当前运行将失败；没有审批回退语义",
      disabled_reason: null,
    });
    Object.assign(session, {
      status: "failed",
      updated_at: "2026-05-01T09:32:00.000Z",
    });
    Object.assign(requireRun(entry.run_id as string), {
      status: "failed",
      ended_at: "2026-05-01T09:32:00.000Z",
      is_active: true,
    });
    if (!findFeedEntry("entry-tool-denied-failed")) {
      feed.push(
        systemStatus({
          entryId: "entry-tool-denied-failed",
          runId: entry.run_id as string,
          status: "failed",
          title: "Tool confirmation denied",
          reason:
            "The high-risk tool confirmation was denied, so the current run failed without approval rollback semantics.",
          retryAction: "create_rerun",
        }),
      );
    }
    return entry;
  }

  function setPendingEntriesActionable(isActionable: boolean) {
    for (const entry of feed) {
      if (
        entry.run_id !== currentRunId ||
        (entry.type !== "approval_request" && entry.type !== "tool_confirmation") ||
        entry.status !== "pending"
      ) {
        continue;
      }
      entry.is_actionable = isActionable;
      entry.disabled_reason = isActionable
        ? null
        : entry.type === "approval_request"
          ? "当前运行已暂停，恢复后继续等待审批"
          : "当前运行已暂停，恢复后继续等待工具确认";
    }
  }

  function findFeedEntry(id: string) {
    return (
      feed.find(
        (entry) =>
          entry.entry_id === id ||
          entry.approval_id === id ||
          entry.tool_confirmation_id === id,
      ) ?? null
    );
  }

  function markHistoricalPendingControlEntries() {
    for (const entry of feed) {
      if (
        entry.run_id === currentRunId ||
        (entry.type !== "approval_request" && entry.type !== "tool_confirmation")
      ) {
        continue;
      }
      entry.is_actionable = false;
      if (entry.type === "approval_request") {
        entry.disabled_reason = "This approval belongs to a historical run.";
      } else {
        entry.disabled_reason = "This tool confirmation belongs to a historical run.";
      }
    }
  }

  function requireCurrentRunId() {
    if (!currentRunId) {
      throw new Error("Current run id is missing from the control flow fixture.");
    }
    return currentRunId;
  }

  function requireRun(runId: string) {
    const run = runs.find((candidate) => candidate.run_id === runId);
    if (!run) {
      throw new Error(`Missing run fixture metadata for ${runId}.`);
    }
    return run;
  }

  function requireToolConfirmation(toolConfirmationId: string) {
    const entry = findFeedEntry(toolConfirmationId);
    if (!entry || entry.type !== "tool_confirmation") {
      throw new Error(`Missing tool confirmation fixture ${toolConfirmationId}.`);
    }
    return entry;
  }

  return {
    async handle(route: Route): Promise<void> {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname;
      const method = request.method();

      if (method === "GET" && path === "/api/projects") {
        return fulfillJson(route, [project]);
      }
      if (method === "GET" && path === `/api/projects/${project.project_id}/sessions`) {
        return fulfillJson(route, [session]);
      }
      if (
        method === "GET" &&
        path === `/api/projects/${project.project_id}/delivery-channel`
      ) {
        return fulfillJson(route, deliveryChannel);
      }
      if (method === "GET" && path === "/api/pipeline-templates") {
        return fulfillJson(route, [template]);
      }
      if (method === "GET" && path === "/api/providers") {
        return fulfillJson(route, [provider]);
      }
      if (method === "GET" && path === `/api/sessions/${session.session_id}/workspace`) {
        return fulfillJson(route, workspace());
      }
      if (method === "POST" && path === `/api/sessions/${session.session_id}/messages`) {
        const body = JSON.parse(request.postData() ?? "{}") as { content?: string };
        startApprovalRun(body.content ?? "");
        return fulfillJson(route, {
          session,
          message_item: feed[0],
        });
      }
      if (method === "POST" && path === "/api/approvals/approval-solution-design/reject") {
        const body = JSON.parse(request.postData() ?? "{}") as { reason?: string };
        rejectApproval(body.reason ?? "");
        return fulfillJson(
          route,
          approvalResult({
            entryId: "api-solution-rejected",
            runId: "run-control-1",
            approvalId: "approval-solution-design",
            approvalType: "solution_design_approval",
            decision: "rejected",
            reason: body.reason ?? "",
            nextStageType: "solution_design",
          }),
        );
      }
      if (method === "POST" && path === "/api/approvals/approval-solution-revised/reject") {
        return fulfillJson(
          route,
          {
            message: "Approval cannot be submitted while the run is paused.",
            request_id: "e2e-paused-approval-submit",
            error_code: "validation_error",
          },
          409,
        );
      }
      const activeRunId = requireCurrentRunId();
      if (method === "POST" && path === `/api/runs/${activeRunId}/pause`) {
        return fulfillJson(route, pauseRun(activeRunId));
      }
      if (method === "POST" && path === `/api/runs/${activeRunId}/resume`) {
        return fulfillJson(route, resumeRun(activeRunId));
      }
      if (method === "POST" && path === `/api/runs/${activeRunId}/terminate`) {
        return fulfillJson(route, terminateRun(activeRunId));
      }
      if (method === "POST" && path === `/api/sessions/${session.session_id}/runs`) {
        return fulfillJson(route, createRerun());
      }
      if (
        method === "POST" &&
        path === "/api/tool-confirmations/tool-confirmation-install/allow"
      ) {
        return fulfillJson(route, {
          tool_confirmation: allowTool("tool-confirmation-install"),
        });
      }
      if (
        method === "POST" &&
        path === "/api/tool-confirmations/tool-confirmation-cleanup/deny"
      ) {
        return fulfillJson(route, {
          tool_confirmation: denyTool("tool-confirmation-cleanup"),
        });
      }
      if (method === "GET" && path === "/api/control-records/control-rollback-solution") {
        return fulfillJson(route, controlRecordInspector("control-rollback-solution"));
      }
      if (
        method === "GET" &&
        path === "/api/tool-confirmations/tool-confirmation-cleanup"
      ) {
        return fulfillJson(route, toolConfirmationInspector("tool-confirmation-cleanup"));
      }

      return fulfillJson(
        route,
        {
          message: `Unhandled e2e route ${method} ${path}`,
          request_id: "e2e-unhandled-route",
          error_code: "not_found",
        },
        404,
      );
    },
  };
}

async function acceptConfirmDialogs(page: Page): Promise<void> {
  page.on("dialog", async (dialog) => {
    await dialog.accept();
  });
}

function binding(stageType: string, roleId: string) {
  return {
    stage_type: stageType,
    role_id: roleId,
    system_prompt: `Execute ${stageType} with stable artifacts.`,
    provider_id: "provider-deepseek",
  };
}

function composerState(status: string, runId: string | null) {
  const terminal = status === "completed" || status === "failed" || status === "terminated";

  if (terminal) {
    return {
      mode: "readonly",
      is_input_enabled: false,
      primary_action: "disabled",
      secondary_actions: [],
      bound_run_id: runId,
    };
  }

  if (status === "draft") {
    return {
      mode: "draft",
      is_input_enabled: true,
      primary_action: "send",
      secondary_actions: [],
      bound_run_id: runId,
    };
  }

  if (status === "waiting_clarification") {
    return {
      mode: "waiting_clarification",
      is_input_enabled: true,
      primary_action: "send",
      secondary_actions: ["pause", "terminate"],
      bound_run_id: runId,
    };
  }

  if (status === "paused") {
    return {
      mode: "paused",
      is_input_enabled: false,
      primary_action: "resume",
      secondary_actions: ["terminate"],
      bound_run_id: runId,
    };
  }

  return {
    mode: status,
    is_input_enabled: false,
    primary_action: "pause",
    secondary_actions: ["terminate"],
    bound_run_id: runId,
  };
}

function userMessage(input: { entryId: string; runId: string; content: string }) {
  return {
    entry_id: input.entryId,
    run_id: input.runId,
    type: "user_message",
    occurred_at: "2026-05-01T09:10:00.000Z",
    message_id: `${input.entryId}-message`,
    author: "user",
    content: input.content,
    stage_run_id: null,
  };
}

function approvalRequest(input: {
  entryId: string;
  runId: string;
  approvalId: string;
  approvalType: string;
  title: string;
  excerpt: string;
  isActionable?: boolean;
  disabledReason?: string | null;
}) {
  return {
    entry_id: input.entryId,
    run_id: input.runId,
    type: "approval_request",
    occurred_at: "2026-05-01T09:22:00.000Z",
    approval_id: input.approvalId,
    approval_type: input.approvalType,
    status: "pending",
    title: input.title,
    approval_object_excerpt: input.excerpt,
    risk_excerpt: "Manual control semantics remain separated from tool confirmation.",
    approval_object_preview: { stage_type: "solution_design" },
    approve_action: "approve",
    reject_action: "reject",
    is_actionable: input.isActionable ?? true,
    requested_at: "2026-05-01T09:22:00.000Z",
    delivery_readiness_status: null,
    delivery_readiness_message: null,
    open_settings_action: null,
    disabled_reason: input.disabledReason ?? null,
  };
}

function approvalResult(input: {
  entryId: string;
  runId: string;
  approvalId: string;
  approvalType: string;
  decision: "approved" | "rejected";
  reason: string | null;
  nextStageType: string;
}) {
  return {
    entry_id: input.entryId,
    run_id: input.runId,
    type: "approval_result",
    occurred_at: "2026-05-01T09:24:00.000Z",
    approval_id: input.approvalId,
    approval_type: input.approvalType,
    decision: input.decision,
    reason: input.reason,
    created_at: "2026-05-01T09:24:00.000Z",
    next_stage_type: input.nextStageType,
  };
}

function toolConfirmation(input: {
  entryId: string;
  runId: string;
  stageRunId: string;
  toolConfirmationId: string;
  title: string;
  toolName: string;
  commandPreview: string;
  targetSummary: string;
  riskCategories: string[];
  reason: string;
  expectedSideEffects: string[];
  isActionable?: boolean;
  disabledReason?: string | null;
}) {
  return {
    entry_id: input.entryId,
    run_id: input.runId,
    type: "tool_confirmation",
    occurred_at: "2026-05-01T09:24:00.000Z",
    stage_run_id: input.stageRunId,
    tool_confirmation_id: input.toolConfirmationId,
    status: "pending",
    title: input.title,
    tool_name: input.toolName,
    command_preview: input.commandPreview,
    target_summary: input.targetSummary,
    risk_level: "high_risk",
    risk_categories: input.riskCategories,
    reason: input.reason,
    expected_side_effects: input.expectedSideEffects,
    allow_action: "allow",
    deny_action: "deny",
    is_actionable: input.isActionable ?? true,
    requested_at: "2026-05-01T09:24:00.000Z",
    responded_at: null,
    decision: null,
    deny_followup_action: null,
    deny_followup_summary: null,
    disabled_reason: input.disabledReason ?? null,
  };
}

function controlItem(input: {
  entryId: string;
  runId: string;
  controlRecordId: string;
  controlType: string;
  sourceStageType: string;
  targetStageType: string | null;
  title: string;
  summary: string;
  payloadRef: string | null;
}) {
  return {
    entry_id: input.entryId,
    run_id: input.runId,
    type: "control_item",
    occurred_at: "2026-05-01T09:24:00.000Z",
    control_record_id: input.controlRecordId,
    control_type: input.controlType,
    source_stage_type: input.sourceStageType,
    target_stage_type: input.targetStageType,
    title: input.title,
    summary: input.summary,
    payload_ref: input.payloadRef,
  };
}

function systemStatus(input: {
  entryId: string;
  runId: string;
  status: "failed" | "terminated";
  title: string;
  reason: string;
  retryAction: string | null;
}) {
  return {
    entry_id: input.entryId,
    run_id: input.runId,
    type: "system_status",
    occurred_at: "2026-05-01T09:34:00.000Z",
    status: input.status,
    title: input.title,
    reason: input.reason,
    retry_action: input.retryAction,
  };
}

function stageNode(input: {
  entryId: string;
  runId: string;
  stageRunId: string;
  stageType: string;
  status: string;
  summary: string;
  itemTitle: string;
  itemSummary: string;
}) {
  return {
    entry_id: input.entryId,
    run_id: input.runId,
    type: "stage_node",
    occurred_at: "2026-05-01T09:20:00.000Z",
    stage_run_id: input.stageRunId,
    stage_type: input.stageType,
    status: input.status,
    attempt_index: 1,
    started_at: "2026-05-01T09:12:00.000Z",
    ended_at: input.status === "completed" ? "2026-05-01T09:20:00.000Z" : null,
    summary: input.summary,
    items: [
      {
        item_id: `${input.stageRunId}-item`,
        type: "decision",
        occurred_at: "2026-05-01T09:16:00.000Z",
        title: input.itemTitle,
        summary: input.itemSummary,
        content: input.itemSummary,
        artifact_refs: [`artifact-${input.stageRunId}`],
        metrics: { total_tokens: 1024 },
      },
    ],
    metrics: { duration_ms: 120000, total_tokens: 2048 },
  };
}

function section(records: Record<string, unknown>) {
  return {
    title: "Section",
    records,
    stable_refs: [],
    log_refs: [],
    truncated: false,
    redaction_status: "none",
  };
}

function controlRecordInspector(controlRecordId: string) {
  return {
    control_record_id: controlRecordId,
    run_id: "run-control-1",
    control_type: "rollback",
    source_stage_type: "solution_design",
    target_stage_type: "solution_design",
    occurred_at: "2026-05-01T09:24:00.000Z",
    identity: section({ control_record_id: controlRecordId, control_type: "rollback" }),
    input: section({ rejected_approval_id: "approval-solution-design" }),
    process: section({
      rollback_summary: "Approval rejection returned the run to Solution Design.",
    }),
    output: section({ target_stage_type: "solution_design" }),
    artifacts: section({ payload_ref: "artifact-rollback-solution" }),
    metrics: { retry_index: 0 },
  };
}

function toolConfirmationInspector(toolConfirmationId: string) {
  return {
    tool_confirmation_id: toolConfirmationId,
    run_id: "run-tool-control",
    stage_run_id: "stage-tool-control",
    status: "denied",
    requested_at: "2026-05-01T09:24:00.000Z",
    responded_at: "2026-05-01T09:32:00.000Z",
    tool_name: "Remove-Item",
    command_preview: "Remove-Item -Recurse .runtime/tmp",
    target_summary: "Temporary workspace artifacts",
    risk_level: "high_risk",
    risk_categories: ["file_delete_or_move", "broad_write"],
    reason:
      "The cleanup command can delete workspace files and needs explicit tool confirmation.",
    expected_side_effects: ["Delete temporary files from the workspace"],
    decision: "denied",
    identity: section({ tool_confirmation_id: toolConfirmationId, status: "denied" }),
    input: section({ command_preview: "Remove-Item -Recurse .runtime/tmp" }),
    process: section({ deny_followup_action: "run_failed" }),
    output: section({
      deny_followup_summary: "拒绝后当前运行将失败；没有审批回退语义",
    }),
    artifacts: section({ trace_ref: "tool-confirmation-cleanup-trace" }),
    metrics: { tool_call_count: 1 },
  };
}

async function fulfillJson(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function expectNoGlobalHorizontalOverflow(page: Page): Promise<void> {
  await expect
    .poll(async () =>
      page.evaluate(() => {
        const documentElement = document.documentElement;
        return documentElement.scrollWidth - documentElement.clientWidth;
      }),
    )
    .toBeLessThanOrEqual(1);
}
