import type {
  ApiErrorResponse,
  ConfigErrorCode,
  ConfigurationPackageExport,
  ConfigurationPackageImportResult,
  PipelineTemplateRead,
  ProjectDeliveryChannelDetailProjection,
  ProjectRead,
  ProviderRead,
  RunStatus,
  RunTimelineProjection,
  SessionRead,
  SessionStatus,
  SessionWorkspaceProjection,
  TopLevelFeedEntry,
} from "../api/types";

const timestamp = "2026-05-01T09:00:00.000Z";
const defaultProjectRoot =
  "C:/Users/lkw/Desktop/github/agent-project/ai-devflow-engine";

export const mockProjectList: ProjectRead[] = [
  {
    project_id: "project-default",
    name: "AI Devflow Engine",
    root_path: defaultProjectRoot,
    default_delivery_channel_id: "delivery-default-demo",
    is_default: true,
    created_at: "2026-05-01T08:00:00.000Z",
    updated_at: "2026-05-01T08:00:00.000Z",
  },
  {
    project_id: "project-loaded",
    name: "Checkout Service",
    root_path: "C:/work/checkout-service",
    default_delivery_channel_id: "delivery-loaded-git",
    is_default: false,
    created_at: "2026-05-01T08:10:00.000Z",
    updated_at: "2026-05-01T08:40:00.000Z",
  },
];

export const mockRemovedProject: ProjectRead = {
  project_id: "project-removed",
  name: "Removed Project",
  root_path: "C:/work/removed-project",
  default_delivery_channel_id: null,
  is_default: false,
  created_at: "2026-05-01T07:00:00.000Z",
  updated_at: "2026-05-01T07:20:00.000Z",
};

export const mockSessionList: SessionRead[] = [
  {
    session_id: "session-draft",
    project_id: "project-default",
    display_name: "Blank requirement",
    status: "draft",
    selected_template_id: "template-feature",
    current_run_id: null,
    latest_stage_type: null,
    created_at: "2026-05-01T09:00:00.000Z",
    updated_at: "2026-05-01T09:00:00.000Z",
  },
  {
    session_id: "session-running",
    project_id: "project-default",
    display_name: "Add workspace shell",
    status: "running",
    selected_template_id: "template-feature",
    current_run_id: "run-running",
    latest_stage_type: "solution_design",
    created_at: "2026-05-01T09:10:00.000Z",
    updated_at: "2026-05-01T09:25:00.000Z",
  },
  {
    session_id: "session-waiting-clarification",
    project_id: "project-default",
    display_name: "Clarify provider behavior",
    status: "waiting_clarification",
    selected_template_id: "template-feature",
    current_run_id: "run-waiting-clarification",
    latest_stage_type: "requirement_analysis",
    created_at: "2026-05-01T09:30:00.000Z",
    updated_at: "2026-05-01T09:38:00.000Z",
  },
  {
    session_id: "session-waiting-approval",
    project_id: "project-default",
    display_name: "Review delivery snapshot",
    status: "waiting_approval",
    selected_template_id: "template-feature",
    current_run_id: "run-waiting-approval",
    latest_stage_type: "solution_design",
    created_at: "2026-05-01T09:40:00.000Z",
    updated_at: "2026-05-01T09:55:00.000Z",
  },
  {
    session_id: "session-completed",
    project_id: "project-default",
    display_name: "Renamed checkout flow fix",
    status: "completed",
    selected_template_id: "template-bugfix",
    current_run_id: "run-completed",
    latest_stage_type: "delivery_integration",
    created_at: "2026-05-01T08:10:00.000Z",
    updated_at: "2026-05-01T08:45:00.000Z",
  },
  {
    session_id: "session-failed",
    project_id: "project-default",
    display_name: "Investigate failing run",
    status: "failed",
    selected_template_id: "template-feature",
    current_run_id: "run-failed",
    latest_stage_type: "test_generation_execution",
    created_at: "2026-05-01T10:00:00.000Z",
    updated_at: "2026-05-01T10:15:00.000Z",
  },
  {
    session_id: "session-terminated",
    project_id: "project-default",
    display_name: "Stopped refactor attempt",
    status: "terminated",
    selected_template_id: "template-refactor",
    current_run_id: "run-terminated",
    latest_stage_type: "code_generation",
    created_at: "2026-05-01T10:20:00.000Z",
    updated_at: "2026-05-01T10:30:00.000Z",
  },
];

export const mockDeletedSession: SessionRead = {
  session_id: "session-deleted",
  project_id: "project-default",
  display_name: "Deleted historical session",
  status: "completed",
  selected_template_id: "template-feature",
  current_run_id: "run-deleted",
  latest_stage_type: "delivery_integration",
  created_at: "2026-04-30T08:00:00.000Z",
  updated_at: "2026-04-30T08:45:00.000Z",
};

export const mockPipelineTemplates: PipelineTemplateRead[] = [
  createTemplate("template-bugfix", "Bug 修复流程", "Diagnose and repair a defect."),
  createTemplate("template-feature", "新功能开发流程", "Build a new feature."),
  createTemplate("template-refactor", "重构流程", "Refactor existing code safely."),
];

export const mockProviderList: ProviderRead[] = [
  {
    provider_id: "provider-volcengine",
    display_name: "火山引擎",
    provider_source: "builtin",
    protocol_type: "volcengine_native",
    base_url: "https://ark.cn-beijing.volces.com/api/v3",
    api_key_ref: "env:VOLCENGINE_API_KEY",
    default_model_id: "doubao-seed-1-6",
    supported_model_ids: ["doubao-seed-1-6"],
    runtime_capabilities: [modelCapabilities("doubao-seed-1-6")],
    created_at: timestamp,
    updated_at: timestamp,
  },
  {
    provider_id: "provider-deepseek",
    display_name: "DeepSeek",
    provider_source: "builtin",
    protocol_type: "openai_completions_compatible",
    base_url: "https://api.deepseek.com",
    api_key_ref: "env:DEEPSEEK_API_KEY",
    default_model_id: "deepseek-chat",
    supported_model_ids: ["deepseek-chat"],
    runtime_capabilities: [modelCapabilities("deepseek-chat")],
    created_at: timestamp,
    updated_at: timestamp,
  },
  {
    provider_id: "provider-custom",
    display_name: "Local compatible model",
    provider_source: "custom",
    protocol_type: "openai_completions_compatible",
    base_url: "http://localhost:11434/v1",
    api_key_ref: "env:LOCAL_MODEL_API_KEY",
    default_model_id: "local-dev",
    supported_model_ids: ["local-dev"],
    runtime_capabilities: [modelCapabilities("local-dev")],
    created_at: timestamp,
    updated_at: timestamp,
  },
];

export const mockProjectDeliveryChannel: ProjectDeliveryChannelDetailProjection = {
  project_id: "project-default",
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

export const mockGitProjectDeliveryChannel: ProjectDeliveryChannelDetailProjection = {
  project_id: "project-loaded",
  delivery_channel_id: "delivery-loaded-git",
  delivery_mode: "git_auto_delivery",
  scm_provider_type: "github",
  repository_identifier: "example/checkout-service",
  default_branch: "main",
  code_review_request_type: "pull_request",
  credential_ref: "env:GITHUB_TOKEN",
  credential_status: "invalid",
  readiness_status: "invalid",
  readiness_message: "Credential reference cannot be resolved.",
  last_validated_at: "2026-05-01T08:56:00.000Z",
  updated_at: "2026-05-01T08:56:00.000Z",
};

const userMessage: TopLevelFeedEntry = {
  entry_id: "entry-user-message",
  run_id: "run-running",
  type: "user_message",
  occurred_at: "2026-05-01T09:11:00.000Z",
  message_id: "message-1",
  author: "user",
  content: "Add a workspace shell.",
  stage_run_id: null,
};

const stageNode: TopLevelFeedEntry = {
  entry_id: "entry-stage-node",
  run_id: "run-running",
  type: "stage_node",
  occurred_at: "2026-05-01T09:12:00.000Z",
  stage_run_id: "stage-solution-design-running",
  stage_type: "solution_design",
  status: "running",
  attempt_index: 1,
  started_at: "2026-05-01T09:12:00.000Z",
  ended_at: null,
  summary: "Designing the workspace shell boundaries.",
  items: [
    {
      item_id: "stage-item-decision",
      type: "decision",
      occurred_at: "2026-05-01T09:13:00.000Z",
      title: "Keep Project and Session navigation in the left rail.",
      summary: "The shell keeps the Narrative Feed as the center of gravity.",
      content: "Navigation state remains outside the main execution feed.",
      artifact_refs: [],
      metrics: {},
    },
    {
      item_id: "stage-item-provider-call",
      type: "provider_call",
      occurred_at: "2026-05-01T09:14:00.000Z",
      title: "Provider call",
      summary: "Provider call is retrying after a rate limit.",
      content: null,
      artifact_refs: [],
      metrics: { total_tokens: 1200 },
      provider_id: "provider-deepseek",
      model_id: "deepseek-chat",
      status: "retrying",
      retry_attempt: 1,
      max_retry_attempts: 3,
      backoff_wait_seconds: 2,
      circuit_breaker_status: "closed",
      failure_reason: "rate_limit",
      process_ref: "provider-trace-1",
    },
  ],
  metrics: { duration_ms: 120000 },
};

const approvalRequest: TopLevelFeedEntry = {
  entry_id: "entry-approval-request",
  run_id: "run-waiting-approval",
  type: "approval_request",
  occurred_at: "2026-05-01T09:50:00.000Z",
  approval_id: "approval-solution-design",
  approval_type: "solution_design_approval",
  status: "pending",
  title: "Review solution design",
  approval_object_excerpt: "The plan updates workspace shell layout and query usage.",
  risk_excerpt: "No backend contract changes.",
  approval_object_preview: { stage_type: "solution_design" },
  approve_action: "approve",
  reject_action: "reject",
  is_actionable: true,
  requested_at: "2026-05-01T09:50:00.000Z",
  delivery_readiness_status: null,
  delivery_readiness_message: null,
  open_settings_action: null,
  disabled_reason: null,
};

const toolConfirmation: TopLevelFeedEntry = {
  entry_id: "entry-tool-confirmation",
  run_id: "run-running",
  type: "tool_confirmation",
  occurred_at: "2026-05-01T09:20:00.000Z",
  stage_run_id: "stage-code-generation-running",
  tool_confirmation_id: "tool-confirmation-1",
  status: "pending",
  title: "Allow dependency install",
  tool_name: "bash",
  command_preview: "npm install",
  target_summary: "frontend/package-lock.json",
  risk_level: "high_risk",
  risk_categories: ["dependency_change", "network_download"],
  reason: "Installing dependencies changes lock files and downloads packages.",
  expected_side_effects: ["package-lock update"],
  allow_action: "allow_once",
  deny_action: "deny_once",
  is_actionable: true,
  requested_at: "2026-05-01T09:20:00.000Z",
  responded_at: null,
  decision: null,
  disabled_reason: null,
};

const controlItem: TopLevelFeedEntry = {
  entry_id: "entry-control-item",
  run_id: "run-waiting-clarification",
  type: "control_item",
  occurred_at: "2026-05-01T09:35:00.000Z",
  control_record_id: "control-clarification",
  control_type: "clarification_wait",
  source_stage_type: "requirement_analysis",
  target_stage_type: "requirement_analysis",
  title: "Clarification needed",
  summary: "The target provider behavior is ambiguous.",
  payload_ref: "artifact-clarification-1",
};

const approvalResult: TopLevelFeedEntry = {
  entry_id: "entry-approval-result",
  run_id: "run-completed",
  type: "approval_result",
  occurred_at: "2026-05-01T08:30:00.000Z",
  approval_id: "approval-code-review",
  approval_type: "code_review_approval",
  decision: "approved",
  reason: null,
  created_at: "2026-05-01T08:30:00.000Z",
  next_stage_type: "delivery_integration",
};

const deliveryResult: TopLevelFeedEntry = {
  entry_id: "entry-delivery-result",
  run_id: "run-completed",
  type: "delivery_result",
  occurred_at: "2026-05-01T08:44:00.000Z",
  delivery_record_id: "delivery-record-1",
  delivery_mode: "demo_delivery",
  status: "succeeded",
  summary: "Demo delivery generated a reviewable summary.",
  branch_name: null,
  commit_sha: null,
  code_review_url: null,
  test_summary: "12 tests passed.",
  result_ref: "delivery-result-ref-1",
};

const systemStatus: TopLevelFeedEntry = {
  entry_id: "entry-system-status",
  run_id: "run-failed",
  type: "system_status",
  occurred_at: "2026-05-01T10:15:00.000Z",
  status: "failed",
  title: "Run failed",
  reason: "Tests failed after retry limit.",
  retry_action: "create_rerun",
};

export const mockFeedEntriesByType = {
  user_message: userMessage,
  stage_node: stageNode,
  approval_request: approvalRequest,
  tool_confirmation: toolConfirmation,
  control_item: controlItem,
  approval_result: approvalResult,
  delivery_result: deliveryResult,
  system_status: systemStatus,
} satisfies Record<TopLevelFeedEntry["type"], TopLevelFeedEntry>;

export const mockSessionWorkspaces: Record<string, SessionWorkspaceProjection> = {
  "session-draft": createWorkspace("session-draft", []),
  "session-running": createWorkspace("session-running", [userMessage, stageNode]),
  "session-waiting-clarification": createWorkspace("session-waiting-clarification", [
    userMessage,
    controlItem,
  ]),
  "session-waiting-approval": createWorkspace("session-waiting-approval", [
    userMessage,
    stageNode,
    approvalRequest,
  ]),
  "session-completed": createWorkspace("session-completed", [
    userMessage,
    approvalResult,
    deliveryResult,
  ]),
  "session-failed": createWorkspace("session-failed", [userMessage, systemStatus]),
  "session-terminated": createWorkspace("session-terminated", [
    userMessage,
    {
      ...systemStatus,
      entry_id: "entry-system-status-terminated",
      run_id: "run-terminated",
      status: "terminated",
      title: "Run terminated",
      reason: "User terminated the run.",
    },
  ]),
};

export const mockSessionWorkspace = mockSessionWorkspaces["session-draft"];

export const mockRunTimelines: Record<string, RunTimelineProjection> =
  Object.fromEntries(
    Object.values(mockSessionWorkspaces)
      .flatMap((workspace) => workspace.runs)
      .map((run) => [
        run.run_id,
        {
          run_id: run.run_id,
          session_id: findSessionIdByRunId(run.run_id),
          attempt_index: run.attempt_index,
          trigger_source: run.trigger_source,
          status: run.status,
          started_at: run.started_at,
          ended_at: run.ended_at,
          current_stage_type: run.current_stage_type,
          entries:
            Object.values(mockSessionWorkspaces).find((workspace) =>
              workspace.runs.some((candidate) => candidate.run_id === run.run_id),
            )?.narrative_feed ?? [],
        } satisfies RunTimelineProjection,
      ]),
  );

export const mockConfigurationPackageExport: ConfigurationPackageExport = {
  export_id: "config-export-1",
  exported_at: "2026-05-01T09:05:00.000Z",
  package_schema_version: "function-one-config-v1",
  scope: { scope_type: "project", project_id: "project-default" },
  providers: [
    {
      provider_id: "provider-custom",
      display_name: "Local compatible model",
      provider_source: "custom",
      protocol_type: "openai_completions_compatible",
      base_url: "http://localhost:11434/v1",
      api_key_ref: "env:LOCAL_MODEL_API_KEY",
      default_model_id: "local-dev",
      supported_model_ids: ["local-dev"],
      runtime_capabilities: [modelCapabilities("local-dev")],
    },
  ],
  delivery_channels: [{ delivery_mode: "demo_delivery" }],
  pipeline_templates: [
    {
      template_id: "template-feature",
      name: "新功能开发流程",
      template_source: "system_template",
      stage_role_bindings: createStageRoleBindings(),
      auto_regression_enabled: true,
      max_auto_regression_retries: 1,
    },
  ],
};

export const mockConfigurationPackageImportSuccess: ConfigurationPackageImportResult =
  {
    package_id: "config-import-1",
    summary: "Imported 2 configuration objects.",
    changed_objects: [
      { object_type: "provider", object_id: "provider-custom", action: "updated" },
      {
        object_type: "delivery_channel",
        object_id: "delivery-default-demo",
        action: "updated",
      },
    ],
  };

export const mockConfigurationPackageImportFieldError: ConfigurationPackageImportResult =
  {
    package_id: "config-import-invalid",
    summary: "Import failed validation.",
    field_errors: [
      { field: "providers[0].default_model_id", message: "Model is not listed." },
    ],
  };

export function mockApiError(
  code: ConfigErrorCode | "not_found" | "validation_error",
  options: { field?: string; message?: string } = {},
): ApiErrorResponse {
  const defaultMessages: Record<string, string> = {
    config_invalid_value: "Configuration value is invalid.",
    config_hard_limit_exceeded:
      "Configuration value exceeds the platform hard limit.",
    config_version_conflict: "Configuration version conflict.",
    config_storage_unavailable: "Configuration storage is unavailable.",
    config_snapshot_unavailable: "Configuration snapshot is unavailable.",
    not_found: "Mock route not found.",
    validation_error: "Validation failed.",
  };

  return {
    error_code: code,
    code,
    message: options.message ?? defaultMessages[code],
    request_id: `mock-request-${code.replaceAll("_", "-")}`,
    field_errors: options.field
      ? [{ field: options.field, message: "Invalid value." }]
      : undefined,
  };
}

function createTemplate(
  templateId: string,
  name: string,
  description: string,
): PipelineTemplateRead {
  return {
    template_id: templateId,
    name,
    description,
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
    stage_role_bindings: createStageRoleBindings(),
    approval_checkpoints: [
      "solution_design_approval",
      "code_review_approval",
    ],
    auto_regression_enabled: true,
    max_auto_regression_retries: 1,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

function createStageRoleBindings() {
  return [
    {
      stage_type: "requirement_analysis",
      role_id: "role-requirement-analyst",
      system_prompt:
        "Analyze the requirement and ask clarifying questions when needed.",
      provider_id: "provider-deepseek",
    },
    {
      stage_type: "solution_design",
      role_id: "role-solution-designer",
      system_prompt: "Design a bounded implementation plan.",
      provider_id: "provider-deepseek",
    },
    {
      stage_type: "code_generation",
      role_id: "role-code-generator",
      system_prompt: "Implement approved changes.",
      provider_id: "provider-deepseek",
    },
    {
      stage_type: "test_generation_execution",
      role_id: "role-test-runner",
      system_prompt: "Generate and run tests.",
      provider_id: "provider-deepseek",
    },
    {
      stage_type: "code_review",
      role_id: "role-code-reviewer",
      system_prompt: "Review implementation and tests.",
      provider_id: "provider-deepseek",
    },
    {
      stage_type: "delivery_integration",
      role_id: "role-delivery-integrator",
      system_prompt: "Prepare delivery output.",
      provider_id: "provider-deepseek",
    },
  ] as PipelineTemplateRead["stage_role_bindings"];
}

function modelCapabilities(modelId: string) {
  return {
    model_id: modelId,
    context_window_tokens: 128000,
    max_output_tokens: 4096,
    supports_tool_calling: false,
    supports_structured_output: true,
    supports_native_reasoning: false,
  };
}

function createWorkspace(
  sessionId: string,
  feed: TopLevelFeedEntry[],
): SessionWorkspaceProjection {
  const session = mockSessionList.find((candidate) => candidate.session_id === sessionId);
  if (!session) {
    throw new Error(`Missing mock session ${sessionId}`);
  }

  const terminal = ["completed", "failed", "terminated"].includes(session.status);
  const run = session.current_run_id
    ? ({
        run_id: session.current_run_id,
        attempt_index: 1,
        status: toRunStatus(session.status),
        trigger_source: "initial_requirement",
        started_at: session.created_at,
        ended_at: terminal ? session.updated_at : null,
        current_stage_type: session.latest_stage_type,
        is_active: !terminal,
      } satisfies SessionWorkspaceProjection["runs"][number])
    : null;

  return {
    session,
    project:
      mockProjectList.find((project) => project.project_id === session.project_id) ??
      mockProjectList[0],
    delivery_channel: mockProjectDeliveryChannel,
    runs: run ? [run] : [],
    narrative_feed: feed,
    current_run_id: session.current_run_id,
    current_stage_type: session.latest_stage_type,
    composer_state: {
      mode: toComposerMode(session.status),
      is_input_enabled:
        session.status === "draft" || session.status === "waiting_clarification",
      primary_action:
        session.status === "draft" || session.status === "waiting_clarification"
          ? "send"
          : session.status === "paused"
            ? "resume"
            : terminal
              ? "disabled"
              : "pause",
      secondary_actions: session.status === "draft" || terminal ? [] : ["terminate"],
      bound_run_id: session.current_run_id,
    },
  };
}

function findSessionIdByRunId(runId: string): string {
  const workspace = Object.values(mockSessionWorkspaces).find((candidate) =>
    candidate.runs.some((run) => run.run_id === runId),
  );
  return workspace?.session.session_id ?? "session-draft";
}

function toRunStatus(status: SessionStatus): RunStatus {
  return status === "draft" ? "running" : status;
}

function toComposerMode(
  status: SessionStatus,
): SessionWorkspaceProjection["composer_state"]["mode"] {
  return status === "completed" || status === "failed" || status === "terminated"
    ? "readonly"
    : status;
}
