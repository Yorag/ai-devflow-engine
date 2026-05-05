import {
  expect,
  test,
  type APIRequestContext,
  type Locator,
  type Page,
} from "@playwright/test";

const backendPort = Number(process.env.E2E_BACKEND_PORT ?? "8000");
const apiBaseURL =
  process.env.E2E_API_BASE_URL ?? `http://127.0.0.1:${backendPort}/api`;
const testBaseURL = apiBaseURL.replace(/\/api\/?$/u, "");

test.skip(
  process.env.E2E_LIVE_BACKEND !== "1",
  "Live backend E2E requires E2E_LIVE_BACKEND=1.",
);

test.describe("function one live manual intervention path", () => {
  test("covers approval rejection, pause resume, terminate, rerun, and SSE", async ({
    page,
    request,
  }) => {
    await acceptConfirmDialogs(page);
    await page.goto("/console");
    const sessionId = await createUiSession(page, request);
    const runId = await startRequirement(page, request, sessionId);

    await advanceRun(request, runId);
    await advanceRun(request, runId);
    await expectSseEvent(request, sessionId, "approval_requested");

    const approval = page
      .getByLabel("Approval request feed entry")
      .filter({ hasText: "Review solution design" });
    await expect(approval).toBeVisible();
    await page.getByRole("button", { name: "暂停" }).click();
    await expect(approval.getByRole("button", { name: "Approve" })).toBeDisabled();
    await expect(approval.getByRole("button", { name: "Reject" })).toBeDisabled();
    await expect(approval).toContainText(
      "Current run is paused; resume it to continue approval.",
    );

    await page.getByRole("button", { name: "恢复" }).click();
    await expect(approval.getByRole("button", { name: "Reject" })).toBeEnabled();
    await approval.getByRole("button", { name: "Reject" }).click();
    await submitRejectReason(approval, "Live rejection must keep rollback visible.");
    await expectSseEvent(request, sessionId, "approval_result");
    await expect(
      page.getByLabel("Approval result feed entry").filter({ hasText: "Rejected" }),
    ).toContainText("Live rejection must keep rollback visible.");
    await expect(
      page
        .getByLabel("Control item feed entry")
        .filter({ hasText: "Rollback to solution_design" }),
    ).toContainText("Solution Design");

    await page.getByRole("button", { name: "终止当前运行" }).click();
    await expect(page.getByLabel("System status feed entry")).toContainText(
      "Run terminated",
    );
    await expect(page.getByRole("button", { name: "Retry run" })).toBeVisible();
    await page.getByRole("button", { name: "Retry run" }).click();
    await expect(page.getByLabel("Run 2 boundary")).toBeFocused();
    await expect(page.getByLabel("Run 2 boundary")).toContainText("Running");
    await expect(page.getByLabel("Run 2 boundary")).toContainText(
      "Requirement Analysis",
    );
    await expect(approval).toContainText("This approval belongs to a historical run.");
    await expectNoGlobalHorizontalOverflow(page);
  });

  test("covers live tool confirmation allow and deny follow-up on narrow layout", async ({
    page,
    request,
  }) => {
    await page.setViewportSize({ width: 390, height: 900 });
    await page.goto("/console");

    const allow = await startRunAtToolConfirmation(
      page,
      request,
      "Allow live tool action.",
    );
    const firstTool = page.getByLabel("Tool confirmation feed entry").filter({
      hasText: "Confirm bash tool action",
    });
    await expect(firstTool).toContainText("High-risk tool confirmation");
    await page.getByRole("button", { name: "暂停" }).click();
    await expect(firstTool.getByRole("button", { name: "允许本次执行" })).toBeDisabled();
    await expect(firstTool.getByRole("button", { name: "拒绝本次执行" })).toBeDisabled();
    await expect(firstTool).toContainText(
      "Current run is paused; resume it to continue tool confirmation.",
    );
    await page.getByRole("button", { name: "恢复" }).click();
    await firstTool.getByRole("button", { name: "允许本次执行" }).click();
    await expectSseEvent(request, allow.sessionId, "tool_confirmation_result");
    await expect(firstTool).toContainText("Allowed");

    const deny = await startRunAtToolConfirmation(
      page,
      request,
      "Deny live tool action.",
    );
    const secondTool = page
      .getByLabel("Tool confirmation feed entry")
      .filter({
        hasText: "Confirm bash tool action",
      })
      .last();
    await secondTool.getByRole("button", { name: "拒绝本次执行" }).click();
    await expectSseEvent(request, deny.sessionId, "tool_confirmation_result");
    await expect(secondTool).toContainText("Denied");
    await expect(secondTool).toContainText("拒绝后将继续当前阶段");
    await expect(secondTool).toContainText(
      "Code Generation will continue with a low-risk fallback.",
    );
    await expect(secondTool).not.toContainText("Solution design approval");
    await expect(secondTool).not.toContainText("Code review approval");
    await expect(page.getByLabel("Narrative workspace")).toBeVisible();
    await expectNoGlobalHorizontalOverflow(page);
  });
});

type ProjectRead = {
  project_id: string;
  is_default: boolean;
};

type SessionRead = {
  session_id: string;
  project_id: string;
  display_name: string;
  current_run_id: string | null;
  updated_at: string;
};

type SessionWorkspaceProjection = {
  session: SessionRead;
  current_run_id: string | null;
  narrative_feed: TopLevelFeedEntry[];
};

type TopLevelFeedEntry =
  | {
      type: "approval_request";
      approval_id: string;
      title: string;
      status: string;
      run_id: string;
    }
  | {
      type: "tool_confirmation";
      tool_confirmation_id: string;
      title: string;
      status: string;
      run_id: string;
    }
  | {
      type: string;
      run_id: string;
    };

type AdvanceRuntimeResponse = {
  run_id: string;
  session_id: string;
  run_status: string;
  result_type: "stage_result" | "interrupt";
  interrupt_type: string | null;
  approval_id: string | null;
  tool_confirmation_id: string | null;
};

async function createUiSession(
  page: Page,
  request: APIRequestContext,
): Promise<string> {
  const project = await defaultProject(request);
  const before = await listSessions(request, project.project_id);
  await page.getByRole("button", { name: "New session" }).click();
  const after = await pollSessionCreated(
    request,
    project.project_id,
    new Set(before.map((session) => session.session_id)),
  );
  const session = newestSession(after, new Set(before.map((item) => item.session_id)));
  await page.getByRole("button", { name: `Open ${session.display_name}` }).first().click();
  await expect(page.getByLabel("当前输入")).toBeEnabled();
  return session.session_id;
}

async function startRequirement(
  page: Page,
  request: APIRequestContext,
  sessionId: string,
  content = "Add guarded delivery controls.",
): Promise<string> {
  await page.getByLabel("当前输入").fill(content);
  await page.getByRole("button", { name: "发送" }).click();
  return await pollCurrentRunId(request, sessionId);
}

async function startRunAtToolConfirmation(
  page: Page,
  request: APIRequestContext,
  content: string,
): Promise<{ sessionId: string; runId: string; toolConfirmationId: string }> {
  const sessionId = await createUiSession(page, request);
  const runId = await startRequirement(page, request, sessionId, content);
  await advanceRun(request, runId);
  await advanceRun(request, runId);
  const approvalId = await pollApprovalId(request, sessionId);
  await approveApproval(request, approvalId);
  await expectSseEvent(request, sessionId, "approval_result");
  await advanceRun(request, runId);
  await advanceRun(request, runId);
  await expectSseEvent(request, sessionId, "tool_confirmation_requested");
  const toolConfirmationId = await pollToolConfirmationId(request, sessionId);
  return { sessionId, runId, toolConfirmationId };
}

async function defaultProject(request: APIRequestContext): Promise<ProjectRead> {
  const projects = await apiGet<ProjectRead[]>(request, "/projects");
  const project = projects.find((candidate) => candidate.is_default) ?? projects[0];
  if (!project) {
    throw new Error("Live backend did not expose a project.");
  }
  return project;
}

async function listSessions(
  request: APIRequestContext,
  projectId: string,
): Promise<SessionRead[]> {
  return await apiGet<SessionRead[]>(request, `/projects/${projectId}/sessions`);
}

async function pollSessionCreated(
  request: APIRequestContext,
  projectId: string,
  previousIds: Set<string>,
): Promise<SessionRead[]> {
  let sessions: SessionRead[] = [];
  await expect
    .poll(async () => {
      sessions = await listSessions(request, projectId);
      return sessions.some((session) => !previousIds.has(session.session_id));
    })
    .toBe(true);
  return sessions;
}

function newestSession(sessions: SessionRead[], previousIds: Set<string>): SessionRead {
  const created = sessions.filter((session) => !previousIds.has(session.session_id));
  const candidates = created.length > 0 ? created : sessions;
  const newest = [...candidates].sort((left, right) =>
    right.updated_at.localeCompare(left.updated_at),
  )[0];
  if (!newest) {
    throw new Error("New session was not found through the live backend API.");
  }
  return newest;
}

async function pollCurrentRunId(
  request: APIRequestContext,
  sessionId: string,
): Promise<string> {
  return await expect
    .poll(async () => {
      const workspace = await getWorkspace(request, sessionId);
      return workspace.current_run_id;
    })
    .not.toBeNull()
    .then(async () => {
      const workspace = await getWorkspace(request, sessionId);
      if (!workspace.current_run_id) {
        throw new Error("Current run id was not available after polling.");
      }
      return workspace.current_run_id;
    });
}

async function pollApprovalId(
  request: APIRequestContext,
  sessionId: string,
): Promise<string> {
  return await pollFeedId(request, sessionId, "approval_request", "approval_id");
}

async function pollToolConfirmationId(
  request: APIRequestContext,
  sessionId: string,
): Promise<string> {
  return await pollFeedId(
    request,
    sessionId,
    "tool_confirmation",
    "tool_confirmation_id",
  );
}

async function pollFeedId<
  TType extends "approval_request" | "tool_confirmation",
  TKey extends TType extends "approval_request"
    ? "approval_id"
    : "tool_confirmation_id",
>(
  request: APIRequestContext,
  sessionId: string,
  type: TType,
  key: TKey,
): Promise<string> {
  let found = "";
  await expect
    .poll(async () => {
      const workspace = await getWorkspace(request, sessionId);
      const entry = workspace.narrative_feed.find(
        (candidate) =>
          candidate.type === type &&
          "status" in candidate &&
          candidate.status === "pending",
      );
      found = entry && key in entry ? String(entry[key]) : "";
      return found;
    })
    .not.toBe("");
  return found;
}

async function getWorkspace(
  request: APIRequestContext,
  sessionId: string,
): Promise<SessionWorkspaceProjection> {
  return await apiGet<SessionWorkspaceProjection>(
    request,
    `/sessions/${sessionId}/workspace`,
  );
}

async function advanceRun(
  request: APIRequestContext,
  runId: string,
): Promise<AdvanceRuntimeResponse> {
  const response = await request.post(`${testBaseURL}/__test__/runtime/runs/${runId}/advance`, {
    data: {},
  });
  if (!response.ok()) {
    throw new Error(
      `Failed to advance run ${runId}: ${response.status()} ${await response.text()}`,
    );
  }
  return (await response.json()) as AdvanceRuntimeResponse;
}

async function approveApproval(
  request: APIRequestContext,
  approvalId: string,
): Promise<void> {
  await apiPost(request, `/approvals/${approvalId}/approve`, {});
}

async function submitRejectReason(
  approval: Locator,
  reason: string,
): Promise<void> {
  const form = approval.getByRole("form", { name: "Reject approval with reason" });

  for (let attempt = 0; attempt < 3; attempt += 1) {
    await expect(form).toBeVisible();
    await form.getByLabel("Reject reason").fill(reason);
    await expect(form.getByLabel("Reject reason")).toHaveValue(reason);
    const submit = form.getByRole("button", { name: "Submit reject reason" });
    await expect(submit).toBeEnabled();

    try {
      await submit.click({ timeout: 3_000 });
      return;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (
        !message.includes("element was detached") &&
        !message.includes("element is not enabled") &&
        !message.includes("Timeout")
      ) {
        throw error;
      }
    }
  }

  await form.getByLabel("Reject reason").fill(reason);
  await form.getByRole("button", { name: "Submit reject reason" }).click();
}

async function expectSseEvent(
  request: APIRequestContext,
  sessionId: string,
  eventType: string,
): Promise<void> {
  await expect
    .poll(async () => {
      const response = await request.get(
        `${apiBaseURL}/sessions/${sessionId}/events/stream?limit=100`,
      );
      if (!response.ok()) {
        return "";
      }
      return await response.text();
    })
    .toContain(`event: ${eventType}`);
}

async function apiGet<T>(
  request: APIRequestContext,
  path: string,
): Promise<T> {
  const response = await request.get(`${apiBaseURL}${path}`);
  if (!response.ok()) {
    throw new Error(`GET ${path} failed: ${response.status()} ${await response.text()}`);
  }
  return (await response.json()) as T;
}

async function apiPost(
  request: APIRequestContext,
  path: string,
  data: unknown,
): Promise<unknown> {
  const response = await request.post(`${apiBaseURL}${path}`, { data });
  if (!response.ok()) {
    throw new Error(
      `POST ${path} failed: ${response.status()} ${await response.text()}`,
    );
  }
  return await response.json();
}

async function acceptConfirmDialogs(page: Page): Promise<void> {
  page.on("dialog", async (dialog) => {
    await dialog.accept();
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
