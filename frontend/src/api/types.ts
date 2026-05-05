export type SessionStatus =
  | "draft"
  | "running"
  | "paused"
  | "waiting_clarification"
  | "waiting_approval"
  | "waiting_tool_confirmation"
  | "completed"
  | "failed"
  | "terminated";

export type RunStatus = Exclude<SessionStatus, "draft">;

export type StageStatus =
  | "running"
  | "waiting_clarification"
  | "waiting_approval"
  | "waiting_tool_confirmation"
  | "completed"
  | "failed"
  | "terminated"
  | "superseded";

export type StageType =
  | "requirement_analysis"
  | "solution_design"
  | "code_generation"
  | "test_generation_execution"
  | "code_review"
  | "delivery_integration";

export type FeedEntryType =
  | "user_message"
  | "stage_node"
  | "approval_request"
  | "tool_confirmation"
  | "control_item"
  | "approval_result"
  | "delivery_result"
  | "system_status";

export type DeliveryMode = "demo_delivery" | "git_auto_delivery";
export type DeliveryReadinessStatus = "unconfigured" | "invalid" | "ready";
export type CredentialStatus = "unbound" | "invalid" | "ready";
export type TemplateSource = "system_template" | "user_template";
export type ProviderSource = "builtin" | "custom";
export type ProviderProtocolType =
  | "volcengine_native"
  | "openai_completions_compatible";
export type ScmProviderType = "github" | "gitlab";
export type CodeReviewRequestType = "pull_request" | "merge_request";
export type RunTriggerSource = "initial_requirement" | "retry" | "ops_restart";
export type ApprovalType = "solution_design_approval" | "code_review_approval";
export type ApprovalStatus = "pending" | "approved" | "rejected" | "cancelled";
export type ToolConfirmationStatus =
  | "pending"
  | "allowed"
  | "denied"
  | "cancelled";
export type ToolConfirmationDenyFollowupAction =
  | "continue_current_stage"
  | "run_failed"
  | "awaiting_run_control";
export type ToolRiskLevel =
  | "read_only"
  | "low_risk_write"
  | "high_risk"
  | "blocked";
export type ToolRiskCategory =
  | "dependency_change"
  | "network_download"
  | "file_delete_or_move"
  | "broad_write"
  | "database_migration"
  | "lockfile_change"
  | "environment_config_change"
  | "unknown_command"
  | "credential_access"
  | "path_escape"
  | "platform_runtime_mutation"
  | "registry_or_audit_bypass";
export type ProviderCircuitBreakerStatus = "closed" | "open" | "half_open";
export type StageItemType =
  | "dialogue"
  | "context"
  | "reasoning"
  | "decision"
  | "model_call"
  | "provider_call"
  | "tool_call"
  | "tool_confirmation"
  | "diff_preview"
  | "result";
export type ControlItemType = "clarification_wait" | "rollback" | "retry";
export type SseEventType =
  | "session_created"
  | "session_message_appended"
  | "pipeline_run_created"
  | "stage_started"
  | "stage_updated"
  | "clarification_requested"
  | "clarification_answered"
  | "approval_requested"
  | "approval_result"
  | "tool_confirmation_requested"
  | "tool_confirmation_result"
  | "control_item_created"
  | "delivery_result"
  | "system_status"
  | "session_status_changed";

export type ConfigErrorCode =
  | "config_invalid_value"
  | "config_hard_limit_exceeded"
  | "config_version_conflict"
  | "config_storage_unavailable"
  | "config_snapshot_unavailable";

export type RuntimeErrorCode =
  | "approval_not_actionable"
  | "run_command_not_actionable"
  | "runtime_data_dir_unavailable";

export type ToolErrorCode =
  | "tool_unknown"
  | "tool_not_allowed"
  | "tool_input_schema_invalid"
  | "tool_workspace_boundary_violation"
  | "tool_timeout"
  | "tool_audit_required_failed"
  | "tool_confirmation_required"
  | "tool_confirmation_denied"
  | "tool_confirmation_not_actionable"
  | "tool_risk_blocked"
  | "bash_command_not_allowed";

export type ProviderErrorCode =
  | "provider_retry_exhausted"
  | "provider_circuit_open";

export type DeliveryErrorCode =
  | "delivery_snapshot_missing"
  | "delivery_snapshot_not_ready"
  | "delivery_git_cli_failed"
  | "delivery_remote_request_failed";

export type LogAuditErrorCode =
  | "audit_write_failed"
  | "log_query_invalid"
  | "log_payload_blocked";

export type ApiErrorCode =
  | "internal_error"
  | "not_found"
  | "validation_error"
  | ConfigErrorCode
  | "config_credential_env_not_allowed"
  | "config_snapshot_mutation_blocked"
  | RuntimeErrorCode
  | ToolErrorCode
  | ProviderErrorCode
  | DeliveryErrorCode
  | LogAuditErrorCode;

export type ApiFieldError = {
  field: string;
  message: string;
};

export type ApiErrorResponse = {
  error_code?: ApiErrorCode;
  code?: ApiErrorCode;
  message: string;
  request_id: string;
  field_errors?: ApiFieldError[];
};

export type ProjectRead = {
  project_id: string;
  name: string;
  root_path: string;
  default_delivery_channel_id: string | null;
  is_default: boolean;
  created_at: string;
  updated_at: string;
};

export type ProjectCreateRequest = {
  root_path: string;
};

export type ProjectRemoveResult = {
  project_id: string;
  visibility_removed: boolean;
  blocked_by_active_run: boolean;
  blocking_run_id: string | null;
  error_code: string | null;
  message: string;
  deletes_local_project_folder: false;
  deletes_target_repository: false;
  deletes_remote_repository: false;
  deletes_remote_branch: false;
  deletes_commits: false;
  deletes_code_review_requests: false;
};

export type SessionRead = {
  session_id: string;
  project_id: string;
  display_name: string;
  status: SessionStatus;
  selected_template_id: string;
  current_run_id: string | null;
  latest_stage_type: StageType | null;
  created_at: string;
  updated_at: string;
};

export type SessionRenameRequest = {
  display_name: string;
};

export type SessionTemplateUpdateRequest = {
  template_id: string;
};

export type SessionMessageAppendRequest = {
  message_type: "new_requirement" | "clarification_reply";
  content: string;
};

export type SessionMessageAppendResponse = {
  session: SessionRead;
  message_item: MessageFeedEntry;
};

export type SessionDeleteResult = ProjectRemoveResult & {
  session_id: string;
  project_id: string;
};

export type StageRoleBinding = {
  stage_type: StageType;
  role_id: string;
  system_prompt: string;
  provider_id: string;
};

export type PipelineTemplateRead = {
  template_id: string;
  name: string;
  description: string | null;
  template_source: TemplateSource;
  base_template_id: string | null;
  fixed_stage_sequence: StageType[];
  stage_role_bindings: StageRoleBinding[];
  approval_checkpoints: ApprovalType[];
  auto_regression_enabled: boolean;
  max_auto_regression_retries: number;
  created_at: string;
  updated_at: string;
};

export type PipelineTemplateWriteRequest = {
  name: string;
  description?: string | null;
  stage_role_bindings: StageRoleBinding[];
  auto_regression_enabled: boolean;
  max_auto_regression_retries: number;
};

export type ModelRuntimeCapabilities = {
  model_id: string;
  context_window_tokens: number;
  max_output_tokens: number;
  supports_tool_calling: boolean;
  supports_structured_output: boolean;
  supports_native_reasoning: boolean;
};

export type ProviderRead = {
  provider_id: string;
  display_name: string;
  provider_source: ProviderSource;
  protocol_type: ProviderProtocolType;
  base_url: string;
  api_key_ref: string | null;
  default_model_id: string;
  supported_model_ids: string[];
  runtime_capabilities: ModelRuntimeCapabilities[];
  created_at: string;
  updated_at: string;
};

export type ProviderWriteRequest = {
  display_name?: string;
  protocol_type?: ProviderProtocolType;
  base_url: string;
  api_key_ref: string | null;
  default_model_id: string;
  supported_model_ids: string[];
  runtime_capabilities: ModelRuntimeCapabilities[];
};

export type ProjectDeliveryChannelDetailProjection = {
  project_id: string;
  delivery_channel_id: string;
  delivery_mode: DeliveryMode;
  scm_provider_type: ScmProviderType | null;
  repository_identifier: string | null;
  default_branch: string | null;
  code_review_request_type: CodeReviewRequestType | null;
  credential_ref: string | null;
  credential_status: CredentialStatus;
  readiness_status: DeliveryReadinessStatus;
  readiness_message: string | null;
  last_validated_at: string | null;
  updated_at: string;
};

export type ProjectDeliveryChannelUpdateRequest = {
  delivery_mode: DeliveryMode;
  scm_provider_type?: ScmProviderType | null;
  repository_identifier?: string | null;
  default_branch?: string | null;
  code_review_request_type?: CodeReviewRequestType | null;
  credential_ref?: string | null;
};

export type ProjectDeliveryChannelValidationResult = {
  readiness_status: DeliveryReadinessStatus;
  readiness_message: string | null;
  credential_status: CredentialStatus;
  validated_fields: string[];
  validated_at: string;
};

export type ConfigurationPackageScope = {
  scope_type: "project";
  project_id: string;
};

export type ConfigurationPackageModelRuntimeCapabilities = Omit<
  ModelRuntimeCapabilities,
  "max_output_tokens"
> & {
  max_output_tokens?: number | null;
};

export type ConfigurationPackageProvider = Omit<
  ProviderRead,
  "created_at" | "updated_at" | "runtime_capabilities"
> & {
  runtime_capabilities: ConfigurationPackageModelRuntimeCapabilities[];
};

export type ConfigurationPackageDeliveryChannel =
  ProjectDeliveryChannelUpdateRequest;

export type ConfigurationPackageTemplateConfig = {
  template_id: string;
  name: string;
  template_source: TemplateSource;
  stage_role_bindings: StageRoleBinding[];
  auto_regression_enabled: boolean;
  max_auto_regression_retries: number;
};

export type ConfigurationPackageImportRequest = {
  package_schema_version: string;
  scope: ConfigurationPackageScope;
  providers: ConfigurationPackageProvider[];
  delivery_channels: ConfigurationPackageDeliveryChannel[];
  pipeline_templates: ConfigurationPackageTemplateConfig[];
};

export type ConfigurationPackageRead = ConfigurationPackageImportRequest & {
  package_id: string;
  exported_at: string;
};

export type ConfigurationPackageExport = ConfigurationPackageImportRequest & {
  export_id: string;
  exported_at: string;
};

export type ConfigurationPackageImportResult = {
  package_id?: string;
  changed_objects?: Array<{
    object_type: "provider" | "delivery_channel" | "pipeline_template";
    object_id: string;
    action: "created" | "updated" | "unchanged";
  }>;
  field_errors?: ApiFieldError[];
  summary?: string;
};

export type RunSummaryProjection = {
  run_id: string;
  attempt_index: number;
  status: RunStatus;
  trigger_source: RunTriggerSource;
  started_at: string;
  ended_at: string | null;
  current_stage_type: StageType | null;
  is_active: boolean;
};

export type RunCommandResponse = {
  session: SessionRead;
  run: RunSummaryProjection;
};

export type ComposerStateProjection = {
  mode:
    | "draft"
    | "running"
    | "waiting_clarification"
    | "waiting_approval"
    | "waiting_tool_confirmation"
    | "paused"
    | "readonly";
  is_input_enabled: boolean;
  primary_action: "send" | "pause" | "resume" | "disabled";
  secondary_actions: Array<"pause" | "terminate">;
  bound_run_id: string | null;
};

export type JsonObject = Record<string, unknown>;

export type FeedEntryBase = {
  entry_id: string;
  run_id: string;
  type: FeedEntryType;
  occurred_at: string;
};

export type MessageFeedEntry = FeedEntryBase & {
  type: "user_message";
  message_id: string;
  author: "user" | "assistant" | "system";
  content: string;
  stage_run_id: string | null;
};

export type StageItemProjection = {
  item_id: string;
  type: Exclude<StageItemType, "provider_call">;
  occurred_at: string;
  title: string;
  summary: string | null;
  content: string | null;
  artifact_refs: string[];
  metrics: JsonObject;
};

export type ProviderCallStageItem = Omit<StageItemProjection, "type"> & {
  type: "provider_call";
  provider_id: string;
  model_id: string;
  status:
    | "queued"
    | "running"
    | "retrying"
    | "succeeded"
    | "failed"
    | "circuit_open";
  retry_attempt: number;
  max_retry_attempts: number;
  backoff_wait_seconds: number | null;
  circuit_breaker_status: ProviderCircuitBreakerStatus;
  failure_reason: string | null;
  process_ref: string | null;
};

export type ExecutionNodeProjection = FeedEntryBase & {
  type: "stage_node";
  stage_run_id: string;
  stage_type: StageType;
  status: StageStatus;
  attempt_index: number;
  started_at: string;
  ended_at: string | null;
  summary: string;
  items: Array<StageItemProjection | ProviderCallStageItem>;
  metrics: JsonObject;
};

export type ApprovalRequestFeedEntry = FeedEntryBase & {
  type: "approval_request";
  approval_id: string;
  approval_type: ApprovalType;
  status: ApprovalStatus;
  title: string;
  approval_object_excerpt: string;
  risk_excerpt: string | null;
  approval_object_preview: JsonObject;
  approve_action: string;
  reject_action: string;
  is_actionable: boolean;
  requested_at: string;
  delivery_readiness_status: DeliveryReadinessStatus | null;
  delivery_readiness_message: string | null;
  open_settings_action: string | null;
  disabled_reason: string | null;
};

export type ToolConfirmationFeedEntry = FeedEntryBase & {
  type: "tool_confirmation";
  stage_run_id: string;
  tool_confirmation_id: string;
  status: ToolConfirmationStatus;
  title: string;
  tool_name: string;
  command_preview: string | null;
  target_summary: string;
  risk_level: "high_risk";
  risk_categories: ToolRiskCategory[];
  reason: string;
  expected_side_effects: string[];
  allow_action: string;
  deny_action: string;
  is_actionable: boolean;
  requested_at: string;
  responded_at: string | null;
  decision: "allowed" | "denied" | null;
  deny_followup_action: ToolConfirmationDenyFollowupAction | null;
  deny_followup_summary: string | null;
  disabled_reason: string | null;
};

export type ControlItemFeedEntry = FeedEntryBase & {
  type: "control_item";
  control_record_id: string;
  control_type: ControlItemType;
  source_stage_type: StageType;
  target_stage_type: StageType | null;
  title: string;
  summary: string;
  payload_ref: string | null;
};

export type ApprovalResultFeedEntry = FeedEntryBase & {
  type: "approval_result";
  approval_id: string;
  approval_type: ApprovalType;
  decision: "approved" | "rejected";
  reason: string | null;
  created_at: string;
  next_stage_type: StageType;
};

export type DeliveryResultFeedEntry = FeedEntryBase & {
  type: "delivery_result";
  delivery_record_id: string;
  delivery_mode: DeliveryMode;
  status: "succeeded";
  summary: string;
  branch_name: string | null;
  commit_sha: string | null;
  code_review_url: string | null;
  test_summary: string | null;
  result_ref: string | null;
};

export type SystemStatusFeedEntry = FeedEntryBase & {
  type: "system_status";
  status: "failed" | "terminated";
  title: string;
  reason: string;
  retry_action: string | null;
};

export type TopLevelFeedEntry =
  | MessageFeedEntry
  | ExecutionNodeProjection
  | ApprovalRequestFeedEntry
  | ToolConfirmationFeedEntry
  | ControlItemFeedEntry
  | ApprovalResultFeedEntry
  | DeliveryResultFeedEntry
  | SystemStatusFeedEntry;

export type SessionWorkspaceProjection = {
  session: SessionRead;
  project: ProjectRead;
  delivery_channel: ProjectDeliveryChannelDetailProjection | null;
  runs: RunSummaryProjection[];
  narrative_feed: TopLevelFeedEntry[];
  current_run_id: string | null;
  current_stage_type: StageType | null;
  composer_state: ComposerStateProjection;
};

export type RunTimelineProjection = {
  run_id: string;
  session_id: string;
  attempt_index: number;
  trigger_source: RunTriggerSource;
  status: RunStatus;
  started_at: string;
  ended_at: string | null;
  current_stage_type: StageType | null;
  entries: TopLevelFeedEntry[];
};

export type ImplementationPlanTaskRead = {
  task_id: string;
  order_index: number;
  title: string;
  depends_on_task_ids: string[];
  target_files: string[];
  target_modules: string[];
  acceptance_refs: string[];
  verification_commands: string[];
  risk_handling: string | null;
};

export type SolutionImplementationPlanRead = {
  plan_id: string;
  source_stage_run_id: string;
  tasks: ImplementationPlanTaskRead[];
  downstream_refs: string[];
  created_at: string;
};

export type InspectorSection = {
  title: string;
  records: JsonObject;
  stable_refs: string[];
  log_refs: string[];
  truncated: boolean;
  redaction_status: "none" | "redacted" | "blocked";
};

export type MetricSet = {
  duration_ms?: number;
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  attempt_index?: number;
  context_file_count?: number;
  reasoning_step_count?: number;
  tool_call_count?: number;
  changed_file_count?: number;
  added_line_count?: number;
  removed_line_count?: number;
  generated_test_count?: number;
  executed_test_count?: number;
  passed_test_count?: number;
  failed_test_count?: number;
  skipped_test_count?: number;
  test_gap_count?: number;
  retry_index?: number;
  source_attempt_index?: number;
  delivery_artifact_count?: number;
};

export type StageInspectorProjection = {
  stage_run_id: string;
  run_id: string;
  stage_type: StageType;
  status: StageStatus;
  attempt_index: number;
  started_at: string;
  ended_at: string | null;
  identity: InspectorSection;
  input: InspectorSection;
  process: InspectorSection;
  output: InspectorSection;
  artifacts: InspectorSection;
  metrics: MetricSet;
  implementation_plan: SolutionImplementationPlanRead | null;
  tool_confirmation_trace_refs: string[];
  provider_retry_trace_refs: string[];
  provider_circuit_breaker_trace_refs: string[];
  approval_result_refs: string[];
};

export type ControlItemInspectorProjection = {
  control_record_id: string;
  run_id: string;
  control_type: ControlItemType;
  source_stage_type: StageType;
  target_stage_type: StageType | null;
  occurred_at: string;
  identity: InspectorSection;
  input: InspectorSection;
  process: InspectorSection;
  output: InspectorSection;
  artifacts: InspectorSection;
  metrics: MetricSet;
};

export type ToolConfirmationInspectorProjection = {
  tool_confirmation_id: string;
  run_id: string;
  stage_run_id: string;
  status: ToolConfirmationStatus;
  requested_at: string;
  responded_at: string | null;
  tool_name: string;
  command_preview: string | null;
  target_summary: string;
  risk_level: "high_risk";
  risk_categories: ToolRiskCategory[];
  reason: string;
  expected_side_effects: string[];
  decision: "allowed" | "denied" | null;
  identity: InspectorSection;
  input: InspectorSection;
  process: InspectorSection;
  output: InspectorSection;
  artifacts: InspectorSection;
  metrics: MetricSet;
};

export type DeliveryResultDetailProjection = {
  delivery_record_id: string;
  run_id: string;
  delivery_mode: DeliveryMode;
  status: "succeeded";
  created_at: string;
  identity: InspectorSection;
  input: InspectorSection;
  process: InspectorSection;
  output: InspectorSection;
  artifacts: InspectorSection;
  metrics: MetricSet;
};

export type LogQueryResponse<TEntry = unknown> = {
  entries: TEntry[];
  next_cursor: string | null;
  has_more: boolean;
  query: JsonObject;
};

export type SessionEvent = {
  event_id: string;
  session_id: string;
  run_id: string | null;
  event_type: SseEventType;
  occurred_at: string;
  payload: JsonObject;
};
