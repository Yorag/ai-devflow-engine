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
      supports_tool_calling: false,
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

test.describe("function one success path", () => {
  test("completes requirement, clarification, approvals, and delivery result in the console", async ({
    page,
  }) => {
    const api = createSuccessFlowApi();
    await installApiFixture(page, api);

    await page.goto("/console");

    await expect(page.getByRole("region", { name: "Template empty state" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "新功能开发流程" })).toBeVisible();
    await expect(page.getByLabel("Current project summary")).toContainText(
      "demo_delivery",
    );
    await expect(page.getByRole("button", { name: "发送" })).toBeDisabled();

    await page.getByLabel("当前输入").fill(
      "Add a delivery summary panel that keeps run artifacts visible.",
    );
    await expect(page.getByRole("button", { name: "发送" })).toBeEnabled();
    await page.getByRole("button", { name: "发送" }).click();

    await expect(page.getByLabel("Narrative Feed run groups")).toContainText(
      "Clarification needed",
    );
    await expect(page.getByRole("navigation", { name: "Run Switcher" })).toBeVisible();
    await expect(
      page.getByRole("button", { name: /Run 2 Waiting Clarification Current run/u }),
    ).toHaveAttribute("aria-current", "true");
    await page.getByRole("button", { name: /Run 1 Completed/u }).click();
    await expect(page.getByLabel("Run 1 boundary")).toBeVisible();
    await expect(page.getByLabel("Run 2 boundary")).toContainText("Waiting Clarification");
    await expect(page.getByLabel("当前输入")).toHaveAttribute(
      "placeholder",
      "补充澄清信息",
    );

    await page.getByLabel("当前输入").fill(
      "Use demo delivery, keep the inspector source of truth, and include the test summary.",
    );
    await page.getByRole("button", { name: "发送" }).click();

    const solutionApproval = page
      .getByLabel("Approval request feed entry")
      .filter({ hasText: "Review solution design" });
    await expect(solutionApproval).toBeVisible();
    await expect(
      page.getByLabel("Stage feed entry").filter({ hasText: "Solution Design" }),
    ).toBeVisible();
    await openStageInspector(page);
    await expect(page.getByRole("complementary", { name: "Inspector" })).toContainText(
      "Structured Requirement",
    );
    await expect(page.getByRole("button", { name: "Close inspector" })).toBeFocused();
    await page.keyboard.press("Escape");

    await solutionApproval.getByRole("button", { name: "Approve" }).click();

    await expect(page.getByLabel("Approval result feed entry")).toContainText(
      "Approved",
    );
    const codeReviewApproval = page
      .getByLabel("Approval request feed entry")
      .filter({ hasText: "Review code review" });
    await expect(codeReviewApproval).toBeVisible();

    await codeReviewApproval.getByRole("button", { name: "Approve" }).click();

    await expect(page.getByLabel("Delivery result feed entry")).toContainText(
      "Demo delivery generated a reviewable summary.",
    );
    await expect(page.getByLabel("Delivery result feed entry")).toContainText(
      "18 tests passed.",
    );
    await expect(page.getByLabel("Run 2 boundary")).toContainText("Completed");
    await expect(
      page.getByRole("button", { name: /Run 2 Completed Current run/u }),
    ).toHaveAttribute("aria-current", "true");
    await expect(page.getByLabel("当前输入")).toBeDisabled();

    await page
      .getByLabel("Delivery result feed entry")
      .getByRole("button", { name: "Details" })
      .click();
    await expect(page.getByRole("complementary", { name: "Inspector" })).toContainText(
      "delivery-record-success",
    );
    await expect(page.getByRole("button", { name: "Close inspector" })).toBeFocused();

    await expectNoGlobalHorizontalOverflow(page);

    await page.setViewportSize({ width: 390, height: 900 });
    await expect(page.getByLabel("Narrative workspace")).toBeVisible();
    await expect(page.getByLabel("Delivery result feed entry")).toBeVisible();
    await expect(page.getByRole("complementary", { name: "Inspector" })).toBeVisible();
    await expectNoGlobalHorizontalOverflow(page);
  });
});

async function installApiFixture(
  page: Page,
  api: ReturnType<typeof createSuccessFlowApi>,
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

function createSuccessFlowApi() {
  const session = {
    session_id: "session-success",
    project_id: project.project_id,
    display_name: "Draft delivery result flow",
    status: "draft",
    selected_template_id: template.template_id,
    current_run_id: null,
    latest_stage_type: null,
    created_at: timestamp,
    updated_at: timestamp,
  };
  const runs: Array<Record<string, unknown>> = [];
  const feed: Array<Record<string, unknown>> = [];
  let currentRunId: string | null = null;
  let currentStageType: string | null = null;

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

  function startRequirement(content: string) {
    currentRunId = "run-success";
    currentStageType = "requirement_analysis";
    const messageItem = userMessage("entry-new-requirement", content, "new_requirement");
    Object.assign(session, {
      status: "waiting_clarification",
      current_run_id: currentRunId,
      latest_stage_type: currentStageType,
      updated_at: "2026-05-01T09:10:00.000Z",
    });
    runs.splice(0, runs.length, {
      run_id: "run-history",
      attempt_index: 1,
      status: "completed",
      trigger_source: "rerun",
      started_at: "2026-05-01T08:30:00.000Z",
      ended_at: "2026-05-01T08:45:00.000Z",
      current_stage_type: "delivery_integration",
      is_active: false,
    }, {
      run_id: currentRunId,
      attempt_index: 2,
      status: "waiting_clarification",
      trigger_source: "initial_requirement",
      started_at: "2026-05-01T09:10:00.000Z",
      ended_at: null,
      current_stage_type: currentStageType,
      is_active: true,
    });
    feed.splice(
      0,
      feed.length,
      messageItem,
      stageNode({
        entryId: "entry-requirement-stage",
        stageRunId: "stage-requirement-success",
        stageType: "requirement_analysis",
        status: "waiting_clarification",
        summary:
          "The requirement is understood, with one delivery output detail to clarify.",
        itemTitle: "Clarification question",
        itemSummary: "Confirm whether demo delivery is acceptable for this run.",
      }),
      {
        entry_id: "entry-clarification-wait",
        run_id: currentRunId,
        type: "control_item",
        occurred_at: "2026-05-01T09:12:00.000Z",
        control_record_id: "control-clarification-success",
        control_type: "clarification_wait",
        source_stage_type: "requirement_analysis",
        target_stage_type: "requirement_analysis",
        title: "Clarification needed",
        summary: "Confirm delivery mode and result summary expectations.",
        payload_ref: "artifact-clarification-success",
      },
    );
    return messageItem;
  }

  function answerClarification(content: string) {
    currentStageType = "solution_design";
    const messageItem = userMessage(
      "entry-clarification-reply",
      content,
      "clarification_reply",
    );
    Object.assign(session, {
      status: "waiting_approval",
      latest_stage_type: currentStageType,
      updated_at: "2026-05-01T09:20:00.000Z",
    });
    Object.assign(requireCurrentRun(), {
      status: "waiting_approval",
      current_stage_type: currentStageType,
    });
    feed.push(
      messageItem,
      stageNode({
        entryId: "entry-solution-stage",
        stageRunId: "stage-solution-success",
        stageType: "solution_design",
        status: "completed",
        summary:
          "Designed the delivery result panel around backend projection fields.",
        itemTitle: "Design decision",
        itemSummary:
          "Narrative Feed remains primary, Inspector owns complete delivery detail.",
      }),
      approvalRequest({
        entryId: "entry-solution-approval",
        approvalId: "approval-solution-design",
        approvalType: "solution_design_approval",
        title: "Review solution design",
        excerpt:
          "The plan keeps delivery result display aligned with DeliveryRecord projection.",
      }),
    );
    return messageItem;
  }

  function approveSolution() {
    currentStageType = "code_review";
    Object.assign(session, {
      status: "waiting_approval",
      latest_stage_type: currentStageType,
      updated_at: "2026-05-01T09:34:00.000Z",
    });
    Object.assign(requireCurrentRun(), {
      status: "waiting_approval",
      current_stage_type: currentStageType,
    });
    replaceApproval(feed, "approval-solution-design", "approved");
    feed.push(
      approvalResult("entry-solution-approval-result", "approval-solution-design"),
      stageNode({
        entryId: "entry-code-stage",
        stageRunId: "stage-code-success",
        stageType: "code_generation",
        status: "completed",
        summary: "Implemented the delivery result presentation.",
        itemTitle: "Change set",
        itemSummary: "Updated the result block and Inspector detail link.",
      }),
      stageNode({
        entryId: "entry-test-stage",
        stageRunId: "stage-test-success",
        stageType: "test_generation_execution",
        status: "completed",
        summary: "Generated and executed focused frontend tests.",
        itemTitle: "Test result",
        itemSummary: "18 tests passed.",
      }),
      stageNode({
        entryId: "entry-review-stage",
        stageRunId: "stage-review-success",
        stageType: "code_review",
        status: "completed",
        summary: "Reviewed the change set and test evidence.",
        itemTitle: "Review conclusion",
        itemSummary: "No blocking issues found.",
      }),
      approvalRequest({
        entryId: "entry-code-review-approval",
        approvalId: "approval-code-review",
        approvalType: "code_review_approval",
        title: "Review code review",
        excerpt:
          "The review confirms implementation, tests, and delivery readiness.",
      }),
    );
  }

  function approveCodeReview() {
    currentStageType = "delivery_integration";
    Object.assign(session, {
      status: "completed",
      latest_stage_type: currentStageType,
      updated_at: "2026-05-01T09:45:00.000Z",
    });
    Object.assign(requireCurrentRun(), {
      status: "completed",
      current_stage_type: currentStageType,
      ended_at: "2026-05-01T09:45:00.000Z",
      is_active: false,
    });
    replaceApproval(feed, "approval-code-review", "approved");
    feed.push(
      approvalResult("entry-code-review-approval-result", "approval-code-review"),
      stageNode({
        entryId: "entry-delivery-stage",
        stageRunId: "stage-delivery-success",
        stageType: "delivery_integration",
        status: "completed",
        summary: "Prepared demo delivery output from the frozen delivery snapshot.",
        itemTitle: "Delivery integration",
        itemSummary: "Created a stable DeliveryRecord projection.",
      }),
      {
        entry_id: "entry-delivery-result-success",
        run_id: currentRunId,
        type: "delivery_result",
        occurred_at: "2026-05-01T09:45:00.000Z",
        delivery_record_id: "delivery-record-success",
        delivery_mode: "demo_delivery",
        status: "succeeded",
        summary: "Demo delivery generated a reviewable summary.",
        branch_name: "demo/success-flow",
        commit_sha: "abc1234",
        code_review_url: null,
        test_summary: "18 tests passed.",
        result_ref: "delivery-result-ref-success",
      },
    );
  }

  function requireCurrentRun() {
    const run = runs.find((candidate) => candidate.run_id === currentRunId);
    if (!run) {
      throw new Error("Current run metadata is missing from the E2E fixture.");
    }
    return run;
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
        const body = JSON.parse(request.postData() ?? "{}") as {
          message_type?: string;
          content?: string;
        };
        const messageItem =
          body.message_type === "clarification_reply"
            ? answerClarification(body.content ?? "")
            : startRequirement(body.content ?? "");
        return fulfillJson(route, {
          session,
          message_item: messageItem,
        });
      }
      if (method === "POST" && path === "/api/approvals/approval-solution-design/approve") {
        approveSolution();
        return fulfillJson(route, approvalResult("api-solution-result", "approval-solution-design"));
      }
      if (method === "POST" && path === "/api/approvals/approval-code-review/approve") {
        approveCodeReview();
        return fulfillJson(route, approvalResult("api-code-review-result", "approval-code-review"));
      }
      if (method === "GET" && path === "/api/stages/stage-solution-success/inspector") {
        return fulfillJson(route, stageInspector());
      }
      if (method === "GET" && path === "/api/delivery-records/delivery-record-success") {
        return fulfillJson(route, deliveryInspector());
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
  return {
    mode:
      terminal
        ? "readonly"
        : status === "draft"
          ? "draft"
          : status === "waiting_clarification"
            ? "waiting_clarification"
            : status,
    is_input_enabled: status === "draft" || status === "waiting_clarification",
    primary_action:
      status === "draft" || status === "waiting_clarification"
        ? "send"
        : terminal
          ? "disabled"
          : "pause",
    secondary_actions:
      status === "draft" || terminal
        ? []
        : status === "waiting_clarification"
          ? ["pause", "terminate"]
          : ["terminate"],
    bound_run_id: runId,
  };
}

function userMessage(entryId: string, content: string, messageType: string) {
  return {
    entry_id: entryId,
    run_id: "run-success",
    type: "user_message",
    occurred_at: "2026-05-01T09:10:00.000Z",
    message_id: `message-${messageType}`,
    author: "user",
    content,
    stage_run_id: null,
  };
}

function stageNode(input: {
  entryId: string;
  stageRunId: string;
  stageType: string;
  status: string;
  summary: string;
  itemTitle: string;
  itemSummary: string;
}) {
  return {
    entry_id: input.entryId,
    run_id: "run-success",
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

function approvalRequest(input: {
  entryId: string;
  approvalId: string;
  approvalType: string;
  title: string;
  excerpt: string;
}) {
  return {
    entry_id: input.entryId,
    run_id: "run-success",
    type: "approval_request",
    occurred_at: "2026-05-01T09:22:00.000Z",
    approval_id: input.approvalId,
    approval_type: input.approvalType,
    status: "pending",
    title: input.title,
    approval_object_excerpt: input.excerpt,
    risk_excerpt: "No backend contract drift is introduced.",
    approval_object_preview: { stage_type: input.approvalType },
    approve_action: "approve",
    reject_action: "reject",
    is_actionable: true,
    requested_at: "2026-05-01T09:22:00.000Z",
    delivery_readiness_status: input.approvalType === "code_review_approval" ? "ready" : null,
    delivery_readiness_message: null,
    open_settings_action: null,
    disabled_reason: null,
  };
}

function replaceApproval(
  feed: Array<Record<string, unknown>>,
  approvalId: string,
  status: string,
) {
  const entry =
    feed.find(
      (candidate) =>
        candidate.type === "approval_request" &&
        candidate.approval_id === approvalId,
    ) ?? null;
  if (entry) {
    entry.status = status;
    entry.is_actionable = false;
  }
}

function approvalResult(entryId: string, approvalId: string) {
  const isCodeReview = approvalId === "approval-code-review";
  return {
    entry_id: entryId,
    run_id: "run-success",
    type: "approval_result",
    occurred_at: "2026-05-01T09:30:00.000Z",
    approval_id: approvalId,
    approval_type: isCodeReview ? "code_review_approval" : "solution_design_approval",
    decision: "approved",
    reason: null,
    created_at: "2026-05-01T09:30:00.000Z",
    next_stage_type: isCodeReview ? "delivery_integration" : "code_generation",
  };
}

function stageInspector() {
  return {
    stage_run_id: "stage-solution-success",
    run_id: "run-success",
    stage_type: "solution_design",
    status: "completed",
    attempt_index: 1,
    started_at: "2026-05-01T09:18:00.000Z",
    ended_at: "2026-05-01T09:22:00.000Z",
    identity: section({ stage_run_id: "stage-solution-success", status: "completed" }),
    input: section({
      structured_requirement:
        "Add a delivery summary panel that keeps run artifacts visible.",
      clarification_summary:
        "Use demo delivery, inspector source of truth, and visible test summary.",
    }),
    process: section({
      design_decisions: [
        "Keep Narrative Feed as the primary reading path.",
        "Use DeliveryRecord projection for Inspector details.",
      ],
    }),
    output: section({
      design_summary: "Render delivery result summary with stable detail access.",
    }),
    artifacts: section({
      verification_commands: ["npm --prefix e2e run test -- function-one-full-flow.spec.ts"],
    }),
    metrics: { duration_ms: 240000, total_tokens: 4096 },
    implementation_plan: {
      plan_id: "solution-plan-success",
      source_stage_run_id: "stage-solution-success",
      created_at: "2026-05-01T09:21:00.000Z",
      downstream_refs: ["docs/plans/implementation/v6.2-playwright-success-flow.md"],
      tasks: [
        {
          task_id: "task-delivery-result",
          order_index: 1,
          title: "Render delivery result projection",
          depends_on_task_ids: [],
          target_files: ["frontend/src/features/feed/FeedEntryRenderer.tsx"],
          target_modules: ["DeliveryResultEntry"],
          acceptance_refs: ["V6.2"],
          verification_commands: ["npm --prefix e2e run test -- function-one-full-flow.spec.ts"],
          risk_handling: "Do not invent delivery fields outside the projection.",
        },
      ],
    },
    tool_confirmation_trace_refs: [],
    provider_retry_trace_refs: [],
    provider_circuit_breaker_trace_refs: [],
    approval_result_refs: ["approval-solution-design"],
  };
}

function deliveryInspector() {
  return {
    delivery_record_id: "delivery-record-success",
    run_id: "run-success",
    delivery_mode: "demo_delivery",
    status: "succeeded",
    created_at: "2026-05-01T09:45:00.000Z",
    identity: section({
      delivery_record_id: "delivery-record-success",
      status: "succeeded",
    }),
    input: section({
      source_run_id: "run-success",
      delivery_channel_snapshot: "delivery-default-demo",
    }),
    process: section({
      integration_summary: "Prepared demo delivery from the frozen snapshot.",
    }),
    output: section({
      branch_name: "demo/success-flow",
      commit_sha: "abc1234",
      delivery_summary: "Demo delivery generated a reviewable summary.",
    }),
    artifacts: section({
      test_summary: "18 tests passed.",
      result_ref: "delivery-result-ref-success",
    }),
    metrics: { duration_ms: 32000, passed_test_count: 18, delivery_artifact_count: 1 },
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

async function fulfillJson(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function openStageInspector(page: Page): Promise<void> {
  await page
    .getByLabel("Stage feed entry")
    .filter({ hasText: "Solution Design" })
    .getByRole("button", { name: "Details" })
    .click();
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
