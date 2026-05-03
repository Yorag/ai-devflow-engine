# 04 人工介入、工具确认与运行控制

## 范围

本分卷覆盖 Week 6 的人工介入、工具确认、运行控制、前端交互状态和交付快照 gate。完成后，澄清、审批、工具确认、暂停、恢复、终止和重新尝试都通过统一 runtime boundary 推进，前端能呈现对应控制块和禁用态。

本分卷承接 03 分卷的 Run 状态机和投影基础，负责运行中断、恢复、人工决策、工具确认和用户可触发运行控制。每个任务只处理一个控制行为或交互能力。
凡本分卷修改 `backend/app/api/routes/*` 的 API 切片，对应 API 测试必须在本切片内断言新增或修改的 path、method、请求 Schema、响应 Schema 和主要错误响应已进入 `/api/openapi.json`；V6.4 只做全局覆盖回归。

人工介入、工具确认、运行控制和交付前置动作必须嵌入日志审计能力。用户可触发命令必须为接受、拒绝、成功和失败结果写入审计记录；高风险工具确认请求与用户决定必须写入审计记录。审计记录写入失败时，高影响动作必须拒绝或回滚；普通运行日志失败不得破坏已持久化领域状态。

<a id="a40"></a>

## A4.0 Runtime orchestration boundary

**计划周期**：Week 6
**状态**：`[x]`
**目标**：在人工介入命令和工具确认命令落地前固定运行编排边界，使澄清、审批、工具确认、暂停、恢复和终止都通过统一 runtime boundary 与领域服务协作；重新尝试只验证旧 GraphThread 已终结并创建新的 PipelineRun，不恢复或复用旧执行图。
**实施计划**：`docs/plans/implementation/a4.0-runtime-orchestration-boundary.md`

**修改文件列表**：
- Create: `backend/app/services/runtime_orchestration.py`
- Create: `backend/app/domain/runtime_refs.py`
- Create: `backend/tests/services/test_runtime_orchestration_boundary.py`

**实现类/函数**：
- `RuntimeOrchestrationService`
- `GraphThreadRef`
- `GraphInterruptRef`
- `CheckpointRef`
- `RuntimeCommandPort`
- `CheckpointPort`
- `RuntimeOrchestrationService.create_interrupt()`
- `RuntimeOrchestrationService.create_tool_confirmation_interrupt()`
- `RuntimeOrchestrationService.resume_interrupt()`
- `RuntimeOrchestrationService.resume_tool_confirmation()`
- `RuntimeOrchestrationService.pause_thread()`
- `RuntimeOrchestrationService.resume_thread()`
- `RuntimeOrchestrationService.terminate_thread()`
- `RuntimeOrchestrationService.assert_thread_terminal_for_rerun()`

**验收标准**：
- 人工介入命令只依赖 `RuntimeOrchestrationService` 与领域对象，不直接读取或写入 raw graph state。
- 澄清、审批等待必须能通过 `GraphInterruptRef` 关联到源 run、源 StageRun 和源阶段类型。
- 工具确认等待必须能通过 `GraphInterruptRef(type=tool_confirmation)` 关联到 `ToolConfirmationRequest`、源 run、源 StageRun、源阶段类型和待执行工具动作。
- pause / resume / terminate 必须作用于当前活动 run 对应的 `GraphThreadRef`。
- 当 run 在暂停前停留于工具确认等待时，resume 后必须恢复到同一个 `waiting_tool_confirmation` 检查点，不创建新的工具确认请求。
- rerun 必须只确认旧 run 对应 `GraphThreadRef` 已处于终态，不得调用 `resume_interrupt()`，不得复用旧 `GraphThreadRef` 创建新 run。
- A4.0 只定义 orchestration boundary 和可 fake 的端口，不实现 deterministic 或 LangGraph 具体 runtime。
- 后续 H4.1、H4.3、H4.4、H4.4a、H4.5、H4.6、H4.7 不得绕过该边界直接推进或复用执行图状态。
- orchestration boundary 必须传递 `TraceContext`，为 interrupt、resume、pause、terminate、rerun terminal check 分配或继承 `span_id`。

**测试方法**：
- `pytest backend/tests/services/test_runtime_orchestration_boundary.py -v`

<a id="l41"></a>

## L4.1 命令审计失败语义

**计划周期**：Week 6
**状态**：`[x]`
**目标**：固定用户命令和高影响动作在审计写入失败时的拒绝或回滚语义，确保后续澄清、审批、暂停、恢复、终止、重新尝试和交付前置动作不会把审计失败降级为普通运行日志失败。
**实施计划**：`docs/plans/implementation/l4.1-command-audit-failure-semantics.md`
**验证摘要**：实施计划 `docs/plans/implementation/l4.1-command-audit-failure-semantics.md` 已完成并在 integration checkpoint 合入 `c6290f5`。`uv run python -m pytest backend/tests/observability/test_command_audit_failure_semantics.py -v` 通过 5 个 L4.1 focused tests；`uv run python -m pytest backend/tests/observability/test_audit_service.py backend/tests/observability/test_command_audit_failure_semantics.py -q` 通过 12 个 audit regressions；`uv run python -m pytest -q` 通过 330 个 backend tests。

**修改文件列表**：
- Modify: `backend/app/observability/audit.py`
- Create: `backend/tests/observability/test_command_audit_failure_semantics.py`

**实现类/函数**：
- `AuditService.require_audit_record()`
- `AuditService.record_rejected_command()`
- `AuditService.record_blocked_action()`

**验收标准**：
- 用户可触发命令接口的成功、失败、被拒绝三类结果必须能通过本服务记录。
- L4.1 必须复用并补强 L2.4 建立的 `AuditService`，只增加审计写入失败时的提交、拒绝和回滚语义；不得创建第二套审计服务、第二套审计表或绕过 `AuditLogEntry` 的临时记录。
- 高影响动作在审计台账写入失败时必须拒绝或回滚，并返回明确错误；不得降级为普通运行日志失败。
- 普通运行日志写入失败不得破坏已持久化领域状态，但必须追加可定位的服务级错误线索。
- H4.1、H4.4、H4.5、H4.6、H4.7 与 D4.0 后续切片必须复用本切片的审计失败语义，不得各自临时分叉。
- L4.1 不暴露审计查询 API；只读查询能力由 L4.2 实现。

**测试方法**：
- `pytest backend/tests/observability/test_command_audit_failure_semantics.py -v`

<a id="l42"></a>

## L4.2 审计日志查询 API

**计划周期**：Week 6
**状态**：`[x]`
**目标**：实现平台审计日志只读查询，使本地诊断与运维可以按主体、动作、目标、run 和结果过滤审计记录。
**实施计划**：`docs/plans/implementation/l4.2-audit-log-query-api.md`
**验证摘要**：实施计划 `docs/plans/implementation/l4.2-audit-log-query-api.md` 已完成并在 integration checkpoint 合入 `4c780ed`。`uv run python -m pytest backend/tests/observability/test_audit_query_service.py backend/tests/schemas/test_observability_schemas.py -v` 通过 12 个 focused service/schema tests；`uv run python -m pytest backend/tests/api/test_audit_log_api.py -v` 通过 4 个 focused API/OpenAPI tests；`uv run python -m pytest backend/tests/observability/test_audit_service.py backend/tests/observability/test_audit_query_service.py backend/tests/schemas/test_observability_schemas.py backend/tests/api/test_audit_log_api.py -v` 通过 23 个 impacted audit regressions。

**修改文件列表**：
- Modify: `backend/app/observability/audit.py`
- Create: `backend/app/api/routes/audit_logs.py`
- Create: `backend/tests/observability/test_audit_query_service.py`
- Create: `backend/tests/api/test_audit_log_api.py`

**实现类/函数**：
- `AuditService.list_audit_logs()`

**验收标准**：
- `GET /api/audit-logs` 返回平台审计日志分页结果。
- 查询参数至少支持 `actor_type`、`action`、`target_type`、`target_id`、`run_id`、`result`、`since`、`until`、`cursor`、`limit`。
- 响应返回 `entries`、`next_cursor`、`has_more` 与查询条件回显。
- 审计查询响应不得返回完整大载荷，只返回动作主体、目标、结果、原因、摘要、关联标识和时间字段。
- `GET /api/audit-logs` 是后端诊断与本地运维只读接口，不属于前端工作台主路径依赖。
- API 测试必须断言 `GET /api/audit-logs` 的查询参数、响应 Schema、主要错误响应和 OpenAPI path/method 已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/observability/test_audit_query_service.py -v`
- `pytest backend/tests/api/test_audit_log_api.py -v`

<a id="h41"></a>

## H4.1 澄清记录与后端消息语义

**计划周期**：Week 6
**状态**：`[x]`
**目标**：实现 Requirement Analysis 内部澄清记录和 `clarification_reply` 后端语义，保证澄清不被建模为审批流程。
**实施计划**：`docs/plans/implementation/h4.1-clarification-backend.md`
**验证摘要**：实施计划 `docs/plans/implementation/h4.1-clarification-backend.md` 已完成并在 integration checkpoint 合入 `8040668`。本 checkpoint 手工融合 `backend/app/services/runs.py` 中的 R3.4 template snapshot run lifecycle surface 与 H4.1 clarification lifecycle surface。`uv run python -m pytest backend/tests/services/test_template_snapshot.py backend/tests/services/test_clarification_flow.py backend/tests/api/test_clarification_reply_api.py backend/tests/projections/test_workspace_projection.py backend/tests/api/test_query_api.py backend/tests/tools/test_tool_protocol_registry.py -v` 通过 39 个 focused backend tests；`uv run python -m pytest -q` 通过 395 个 backend tests。

**修改文件列表**：
- Modify: `backend/app/services/runs.py`
- Modify: `backend/app/services/sessions.py`
- Create: `backend/app/services/clarifications.py`
- Modify: `backend/app/api/routes/sessions.py`
- Create: `backend/tests/services/test_clarification_flow.py`
- Create: `backend/tests/api/test_clarification_reply_api.py`

**实现类/函数**：
- `ClarificationService.request_clarification()`
- `ClarificationService.answer_clarification()`
- `SessionService.append_clarification_reply()`
- `RunLifecycleService.mark_waiting_clarification()`
- `RuntimeOrchestrationService.create_interrupt()`
- `RuntimeOrchestrationService.resume_interrupt()`

**验收标准**：
- 需求澄清只发生在 `requirement_analysis` 内部。
- 澄清创建 `ClarificationRecord` 与 `control_item(type=clarification_wait)`。
- 澄清必须通过 A4.0 runtime boundary 创建 `GraphInterruptRef(type=clarification_request)`，不得只靠 run 状态字段表达等待。
- 澄清不创建 ApprovalRequest。
- `clarification_reply` 只能在 `waiting_clarification` 且当前阶段为 `requirement_analysis` 时使用。
- 补充信息回写到同一个业务阶段上下文，并通过 runtime boundary 恢复同一个 run 与同一个 GraphThreadRef。
- 澄清请求、澄清回复成功、非法状态拒绝和恢复失败必须写入审计记录和运行日志；澄清事实仍以 ClarificationRecord、领域事件和 StageArtifact 为准。
- API 测试必须断言 `POST /api/sessions/{sessionId}/messages` 的 `clarification_reply` 请求/响应 Schema、非法状态错误响应和 OpenAPI path/method 已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/services/test_clarification_flow.py -v`
- `pytest backend/tests/api/test_clarification_reply_api.py -v`

<a id="h42"></a>

## H4.2 Composer 澄清输入语义

**计划周期**：Week 6
**状态**：`[x]`
**目标**：实现 Composer 对 draft、waiting_clarification 和 running requirement_analysis 的输入语义。
**实施计划**：`docs/plans/implementation/h4.2-composer-clarification-mode.md`

**修改文件列表**：
- Create: `frontend/src/features/composer/Composer.tsx`
- Create: `frontend/src/features/composer/composer-mode.ts`
- Create: `frontend/src/features/composer/__tests__/Composer.test.tsx`

**实现类/函数**：
- `Composer`
- `resolveComposerMode()`
- `canSubmitComposerMessage()`

**验收标准**：
- draft 时 Composer 可输入且主按钮为发送。
- `waiting_clarification` 时 Composer 可输入且主按钮为发送。
- `running` 且 `current_stage_type = requirement_analysis` 时，Composer 输入不承担发送动作，右端按钮切回暂停语义。
- 发送后内容追加到 Narrative Feed 的用户输入或澄清回复语义中。

**前端设计质量门**：
- 继承项目级前端主基调，不单独询问 Composer 风格。
- 实现后必须检查 draft、澄清等待、运行中 requirement_analysis 的输入态、禁用态、按钮层级和窄屏固定底部布局。
- Composer 必须清楚区分普通需求输入、澄清回复和运行控制，不得用视觉样式暗示 running 状态仍可发送普通消息。

**测试方法**：
- `npm --prefix frontend run test -- Composer`

<a id="h43"></a>

## H4.3 审批对象与投影语义

**计划周期**：Week 6
**状态**：`[x]`
**目标**：实现 solution design 与 code review 的审批对象创建和投影字段，使审批请求成为 Narrative Feed 顶层条目。
**实施计划**：`docs/plans/implementation/h4.3-approval-object-projection.md`
**验证摘要**：实施计划 `docs/plans/implementation/h4.3-approval-object-projection.md` 已完成并在 integration checkpoint 合入 `3cd8bb7`。`uv run pytest backend/tests/api/test_query_api.py backend/tests/projections/test_timeline_projection.py backend/tests/projections/test_approval_projection.py backend/tests/services/test_approval_creation.py backend/tests/errors/test_error_code_catalog.py` 通过 34 个 focused backend tests。

**修改文件列表**：
- Create: `backend/app/services/approvals.py`
- Create: `backend/tests/services/test_approval_creation.py`
- Create: `backend/tests/projections/test_approval_projection.py`

**实现类/函数**：
- `ApprovalService.create_solution_design_approval()`
- `ApprovalService.create_code_review_approval()`
- `ApprovalService.build_approval_request_projection()`
- `RuntimeOrchestrationService.create_interrupt()`

**验收标准**：
- 只创建 `solution_design_approval` 与 `code_review_approval`。
- 审批请求作为顶层 `approval_request` 插入 Narrative Feed。
- 创建审批请求后，源 StageRun 状态置为 `waiting_approval`。
- 创建审批请求必须通过 A4.0 runtime boundary 创建对应 `GraphInterruptRef`，不得只创建 ApprovalRequest 后直接阻塞领域状态。
- 审批等待期间，会话级 `latest_stage_type` 与 `current_stage_type` 保持源阶段类型不变。
- `approval_request` 包含 `is_actionable`、`disabled_reason`、`delivery_readiness_status` 和 `open_settings_action` 字段。
- 本切片只创建审批对象和投影来源，不暴露审批命令路由；审批命令路由由 H4.4 作为单一公开入口创建。
- 审批对象创建、中断创建成功和中断创建失败必须写入运行日志；本切片不写用户审批提交审计。

**测试方法**：
- `pytest backend/tests/services/test_approval_creation.py -v`
- `pytest backend/tests/projections/test_approval_projection.py -v`

<a id="d40"></a>

## D4.0 Delivery snapshot gate

**计划周期**：Week 6
**状态**：`[x]`
**目标**：在审批命令落地前固定最终审批通过时的交付快照固化边界，使 `code_review_approval` 的 Approve 不产生先 approve、后补 snapshot 的两段语义。
**实施计划**：`docs/plans/implementation/d4.0-delivery-snapshot-gate.md`

**修改文件列表**：
- Create: `backend/app/services/delivery_snapshots.py`
- Modify: `backend/app/services/delivery_channels.py`
- Create: `backend/tests/services/test_delivery_snapshot_gate.py`

**实现类/函数**：
- `DeliverySnapshotService.prepare_delivery_snapshot()`
- `DeliverySnapshotService.assert_snapshot_ready_for_delivery()`
- `DeliverySnapshotService.get_snapshot_for_run()`
- `DeliveryChannelService.resolve_current_project_channel()`

**验收标准**：
- 交付通道快照只在 `code_review_approval` 通过并准备进入 `delivery_integration` 时固化。
- `git_auto_delivery` 必须在固化前校验当前项目级 DeliveryChannel `readiness_status = ready`。
- `demo_delivery` 也必须固化交付快照，但不因远端配置缺失阻塞。
- 快照必须包含 `delivery_mode`、`scm_provider_type`、`repository_identifier`、`default_branch`、`code_review_request_type`、`credential_ref`、`credential_status`、`readiness_status`、`readiness_message` 与 `last_validated_at`。
- 项目级交付配置校验响应的动作时间字段使用 `validated_at`；固化到 run 的交付快照字段统一使用 `last_validated_at`。
- 固化后的 run 不受后续项目级 DeliveryChannel 修改影响。
- 本切片不创建 DeliveryRecord，不执行交付 adapter。

**测试方法**：
- `pytest backend/tests/services/test_delivery_snapshot_gate.py -v`

<a id="h44"></a>

## H4.4 审批命令与交付就绪阻塞

**计划周期**：Week 6
**状态**：`[x]`
**目标**：实现 Approve、Reject、拒绝理由、回退控制记录、回退目标和 code review 交付就绪 gate，使审批结果、交付快照固化和 runtime 恢复保持单一公开入口。
**实施计划**：`docs/plans/implementation/h4.4-approval-commands-readiness-gate.md`

**四个 red-green 实施步骤**：
1. `approval_result` command：实现单一公开 approve/reject API、审批状态更新、顶层 `approval_result` 事件与投影。
2. Reject rollback：实现拒绝理由、目标阶段解析和 `RunControlRecord(type=rollback)`。
3. code review readiness gate：实现 `git_auto_delivery` 的 ready 校验阻塞，未 ready 时保持审批待处理且不固化 snapshot。
4. Approve snapshot + resume：实现 `code_review_approval` Approve 通过后的交付快照固化和 runtime boundary 恢复。

**修改文件列表**：
- Modify: `backend/app/services/approvals.py`
- Create: `backend/app/services/control_records.py`
- Create: `backend/app/api/routes/approvals.py`
- Create: `backend/tests/services/test_approval_commands.py`
- Create: `backend/tests/api/test_approval_api.py`

**实现类/函数**：
- `ApprovalService.approve()`
- `ApprovalService.reject()`
- `ApprovalService.assert_delivery_readiness_for_code_review()`
- `ApprovalService.resolve_reject_target_stage()`
- `ControlRecordService.append_rollback_control_item()`
- `DeliverySnapshotService.prepare_delivery_snapshot()`
- `RuntimeOrchestrationService.resume_interrupt()`

**验收标准**：
- `Approve` 可直接提交。
- `Approve` 与 `Reject` 都必须创建顶层 `approval_result` 并进入事件流和 Narrative Feed 投影。
- `Reject` 必须记录用户理由并进入后续上下文。
- `Reject` 必须创建 `RunControlRecord(type=rollback)`。
- rollback 记录必须包含 `source_stage_type`、`target_stage_type`、用户拒绝理由和后续推进说明。
- rollback control item 必须进入事件流和 Narrative Feed 投影。
- `solution_design_approval` 的 Reject 固定回到 `solution_design`。
- `code_review_approval` 的 Reject 固定回到 `code_generation`。
- `git_auto_delivery` 未 ready 时阻塞 code review approve，并保持审批对象待处理，不固化交付快照。
- `git_auto_delivery` 未 ready 时不得创建 `approval_result`，不得固化 `delivery_channel_snapshot_ref`。
- `code_review_approval` Approve 通过时必须在同一服务事务中完成 ready gate、审批决策、顶层 `approval_result` 事件、完整 `delivery_channel_snapshot_ref` 固化和 runtime boundary 恢复；外部不得观察到已通过审批但交付快照尚未固化的中间态。
- 事务内的领域顺序必须保证 `DeliverySnapshotService.prepare_delivery_snapshot()` 成功后，才提交 `approval_result` 事件和恢复对应中断进入 `delivery_integration`。
- `demo_delivery` 不因远端配置缺失阻塞 approve。
- paused run 不接受审批提交，并返回明确错误信息。
- 本切片不得新增第二条 code review approve 入口。
- 审批提交接受、审批提交被 paused 拒绝、delivery readiness 阻塞、Approve 成功、Reject 成功和 runtime resume 失败必须写入审计记录。
- 审计写入失败时不得提交审批决策、`approval_result` 事件或交付快照。
- 运行日志必须记录审批命令耗时、结果状态、阻塞原因摘要和关联的 `approval_id`、`run_id`、`stage_run_id`。
- API 测试必须断言 `POST /api/approvals/{approvalId}/approve`、`POST /api/approvals/{approvalId}/reject` 的请求/响应 Schema、paused 错误、delivery readiness 错误和 OpenAPI path/method 已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/services/test_approval_commands.py -v`
- `pytest backend/tests/api/test_approval_api.py -v`

<a id="h44a"></a>

## H4.4a ToolConfirmationRequest 与工具确认命令

**计划周期**：Week 6-7
**状态**：`[x]`
**目标**：实现高风险工具确认的领域对象、命令入口和 runtime 恢复语义，使工具确认作为运行时权限控制点独立于人工审批检查点。
**实施计划**：`docs/plans/implementation/h4.4a-tool-confirmation-commands.md`

**修改文件列表**：
- Create: `backend/app/services/tool_confirmations.py`
- Modify: `backend/app/services/control_records.py`
- Modify: `backend/app/services/runtime_orchestration.py`
- Create: `backend/app/api/routes/tool_confirmations.py`
- Create: `backend/tests/services/test_tool_confirmation_commands.py`
- Create: `backend/tests/api/test_tool_confirmation_api.py`

**实现类/函数**：
- `ToolConfirmationService.create_request()`
- `ToolConfirmationService.allow()`
- `ToolConfirmationService.deny()`
- `ToolConfirmationService.cancel_for_terminal_run()`
- `ToolConfirmationService.build_projection()`
- `ControlRecordService.append_tool_confirmation_record()`
- `RuntimeOrchestrationService.create_tool_confirmation_interrupt()`
- `RuntimeOrchestrationService.resume_tool_confirmation()`

**验收标准**：
- 创建高风险工具确认时，必须同时创建 `ToolConfirmationRequest`、`GraphInterruptRef(type=tool_confirmation)`、`RunControlRecord(control_type=tool_confirmation)` 过程留痕和 `tool_confirmation_requested` 领域事件。
- 创建后必须把当前 `PipelineRun.status` 与当前 `StageRun.status` 投影为 `waiting_tool_confirmation`。
- `POST /api/tool-confirmations/{toolConfirmationId}/allow` 只能执行该确认请求覆盖的具体工具动作，不得扩大到同类命令、同类路径或后续工具调用。
- `POST /api/tool-confirmations/{toolConfirmationId}/deny` 必须记录用户决定和后续处理结果；存在低风险替代路径时恢复运行到替代路径，不存在替代路径时进入结构化失败或等待用户显式暂停、终止。
- deny 结果必须稳定产出 `deny_followup_action` 与 `deny_followup_summary`；当存在低风险替代路径时固定为 `continue_current_stage`，当进入失败路径时固定为 `run_failed`，当等待用户显式运行控制时固定为 `awaiting_run_control`。
- 工具确认允许或拒绝都必须生成 `tool_confirmation_result` 领域事件，并更新顶层 `tool_confirmation` 投影。
- 工具确认不得创建 `ApprovalRequest`、`ApprovalDecision` 或顶层 `approval_result`，也不得触发审批 Reject 的 rollback 语义。
- paused run 拒绝 allow / deny 提交并返回稳定错误；resume 后恢复到同一个 `waiting_tool_confirmation` 检查点。
- terminated、failed、completed run 下的待处理工具确认必须变为只读不可提交状态，历史记录保留；若服务层需要关闭待处理请求，必须使用 `ToolConfirmationStatus.cancelled`，不得写成允许或拒绝。
- 工具确认请求、允许、拒绝、取消、低风险替代路径判断、无替代失败和 runtime resume 失败必须写入审计记录与运行日志摘要。
- 审计写入失败时不得提交工具确认决定、`tool_confirmation_result` 事件或执行对应工具动作。
- API 测试必须断言 `POST /api/tool-confirmations/{toolConfirmationId}/allow`、`POST /api/tool-confirmations/{toolConfirmationId}/deny` 的请求/响应 Schema、paused 错误、终态错误和 OpenAPI path/method 已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/services/test_tool_confirmation_commands.py -v`
- `pytest backend/tests/api/test_tool_confirmation_api.py -v`

<a id="h44b"></a>

## H4.4b ToolConfirmation 拒绝后续处理语义固化

**计划周期**：Week 6-7
**状态**：`[ ]`
**目标**：为工具确认拒绝结果固化稳定的 runtime-side 后续处理语义来源，供 `Q3.4b` 读取并暴露到顶层 `tool_confirmation` payload；本切片不直接扩展 query / SSE 顶层契约。
**实施计划**：`docs/plans/implementation/h4.4b-tool-confirmation-deny-followup-source.md`

**修改文件列表**：
- Modify: `backend/app/db/models/runtime.py`
- Modify: `backend/app/services/tool_confirmations.py`
- Modify: `backend/app/services/control_records.py`
- Modify: `backend/tests/services/test_tool_confirmation_commands.py`
- Modify: `backend/tests/api/test_tool_confirmation_api.py`

**实现类/函数**：
- `ToolConfirmationRequestModel`
- `ToolConfirmationService.deny()`
- `ControlRecordService.append_tool_confirmation_record()`

**验收标准**：
- deny 路径必须稳定写入 `deny_followup_action` 与 `deny_followup_summary`，不得只依赖 `alternative_path_summary` 或事后读取 run 终态推断。
- `deny_followup_action` 只允许 `continue_current_stage`、`run_failed`、`awaiting_run_control`。
- 当存在低风险替代路径并继续当前阶段时，必须写入 `continue_current_stage` 和稳定摘要。
- 当无替代路径并直接进入失败路径时，必须写入 `run_failed` 和稳定摘要。
- 当拒绝后等待用户显式 `pause` / `terminate` 一类运行控制决定时，必须写入 `awaiting_run_control` 和稳定摘要。
- 这些字段必须持久化在 `ToolConfirmationRequestModel` 或等价稳定过程记录中，供后续 `Q3.4b` 暴露到 query / workspace / timeline / SSE。
- 本切片只允许修改 AL03 owner scope 的 runtime model、runtime service、control record 与相关测试；不得直接扩展 `ToolConfirmationFeedEntry`、workspace/timeline projection payload、SSE payload 或 query schema。
- 审计写入失败或 deny 处理失败时，不得留下已拒绝但无后续处理语义的半成品记录。
- 服务与 API 测试必须覆盖三种 deny 后续结果分支，以及 paused / terminal run 的稳定错误语义。

**测试方法**：
- `pytest backend/tests/services/test_tool_confirmation_commands.py -v`
- `pytest backend/tests/api/test_tool_confirmation_api.py -v`

<a id="h45"></a>

## H4.5 Pause/Resume checkpoint 语义

**计划周期**：Week 6
**状态**：`[x]`
**目标**：实现暂停和恢复命令副作用，使 running、waiting_clarification、waiting_approval、waiting_tool_confirmation 都能保存可恢复状态。
**实施计划**：`docs/plans/implementation/h4.5-pause-resume-checkpoint.md`

**修改文件列表**：
- Modify: `backend/app/services/runs.py`
- Create: `backend/app/api/routes/runs.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/schemas/run.py`
- Create: `backend/tests/services/test_pause_resume.py`
- Create: `backend/tests/api/test_pause_resume_api.py`

**实现类/函数**：
- `RunLifecycleService.pause_run()`
- `RunLifecycleService.resume_run()`
- `RunLifecycleService._persist_recovery_checkpoint()`
- `RunLifecycleService._refresh_pending_wait_entry_for_pause()`
- `RunLifecycleService._refresh_pending_wait_entry_for_resume()`
- `RuntimeOrchestrationService.pause_thread()`
- `RuntimeOrchestrationService.resume_thread()`

**验收标准**：
- pause 可发生在 `running`、`waiting_clarification`、`waiting_approval`、`waiting_tool_confirmation`。
- pause 调用成功后通过 A4.0 runtime boundary 保存可恢复 checkpoint 与工作区快照引用。
- H4.5 创建 `backend/app/api/routes/runs.py` 并注册 run 控制路由，后续 H4.6/H4.7 在同一路由文件扩展终止与重新尝试命令。
- pause 不新增 `control_item` 或新的 `RunControlRecordType`；暂停和恢复语义通过 `RUN_PAUSED`、`RUN_RESUMED` 以及已有等待条目的刷新事件表达。
- waiting_approval 下暂停后审批不可提交，投影 `is_actionable = false`。
- waiting_tool_confirmation 下暂停后工具确认不可提交，投影 `is_actionable = false`。
- resume 继续同一 run 和同一 GraphThreadRef，不创建新 run。
- 若 run 暂停前停留于审批等待，resume 后恢复到同一个 `waiting_approval` 检查点。
- 若 run 暂停前停留于工具确认等待，resume 后恢复到同一个 `waiting_tool_confirmation` 检查点。
- pause 保持当前 `StageRun.status` 为暂停前的 waiting/running 状态，resume 从最新 `recovery_checkpoint` artifact 恢复同一 run 的暂停前 run/session 语义。
- pause 接受、pause 成功、resume 接受、resume 成功、非法状态拒绝和 checkpoint 保存失败必须写入审计记录和运行日志。
- API 测试必须断言 `POST /api/runs/{runId}/pause`、`POST /api/runs/{runId}/resume` 的请求/响应 Schema、非法状态错误响应和 OpenAPI path/method 已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/services/test_pause_resume.py -v`
- `pytest backend/tests/api/test_pause_resume_api.py -v`

<a id="h46"></a>

## H4.6 Terminate 与 system_status

**计划周期**：Week 6
**状态**：`[x]`
**目标**：实现终止命令和 run 尾部终态条目，使 terminated run 保留历史且不可继续提交。
**实施计划**：`docs/plans/implementation/h4.6-terminate-system-status.md`

**修改文件列表**：
- Modify: `backend/app/services/runs.py`
- Modify: `backend/app/api/routes/runs.py`
- Create: `backend/tests/services/test_terminate_run.py`
- Create: `backend/tests/api/test_terminate_run_api.py`

**实现类/函数**：
- `RunLifecycleService.terminate_run()`
- `RunLifecycleService.mark_terminal()`
- `TerminalStatusProjector.append_terminal_system_status()`
- `RuntimeOrchestrationService.terminate_thread()`

**验收标准**：
- terminate 只终止当前活动 run，不删除历史。
- terminate 调用成功后通过 A4.0 runtime boundary 终止当前 GraphThreadRef。
- terminated run 尾部出现顶层 `system_status` 终态条目。
- failed 与 terminated 的顶层 `system_status` 必须由同一个 `TerminalStatusProjector.append_terminal_system_status()` 生成，不得分散在不同服务中各自拼装。
- `system_status` 不属于 `control_item.control_type`。
- terminated run 中仍待处理的审批块退化为不可提交状态。
- terminated run 中仍待处理的工具确认块退化为不可提交状态，并保留历史确认对象和风险信息；若后端取消待处理确认，请求状态使用 `cancelled`。
- terminate 接受、terminate 成功、非法状态拒绝和 runtime terminate 失败必须写入审计记录和运行日志。
- API 测试必须断言 `POST /api/runs/{runId}/terminate` 的请求/响应 Schema、非法状态错误响应和 OpenAPI path/method 已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/services/test_terminate_run.py -v`
- `pytest backend/tests/api/test_terminate_run_api.py -v`

<a id="h47"></a>

## H4.7 重新尝试命令与多 run 分界

**计划周期**：Week 6
**状态**：`[x]`
**目标**：补齐重新尝试命令的事件、trigger metadata 和多 run 分界语义，使 failed / terminated 后的新 run 能被前端定位。
**实施计划**：`docs/plans/implementation/h4.7-rerun-command-run-boundary.md`
**验证摘要**：实施计划 `docs/plans/implementation/h4.7-rerun-command-run-boundary.md` 已完成并在 integration checkpoint 合入 `58a020b`。`uv run python -m pytest backend/tests/services/test_rerun_command_projection.py -v` 通过 11 个 focused service tests；`uv run python -m pytest backend/tests/api/test_rerun_command_api.py -v` 通过 7 个 focused API/OpenAPI tests；`uv run python -m pytest backend/tests/services/test_rerun_command_projection.py backend/tests/api/test_rerun_command_api.py backend/tests/domain/test_run_state_machine.py backend/tests/services/test_terminate_run.py backend/tests/services/test_pause_resume.py backend/tests/api/test_session_api.py backend/tests/api/test_query_api.py backend/tests/projections/test_workspace_projection.py backend/tests/projections/test_timeline_projection.py backend/tests/events/test_event_store.py backend/tests/schemas/test_run_feed_event_schemas.py -q` 通过 114 个 impacted regressions。

**修改文件列表**：
- Modify: `backend/app/services/runs.py`
- Modify: `backend/app/api/routes/runs.py`
- Create: `backend/tests/services/test_rerun_command_projection.py`
- Create: `backend/tests/api/test_rerun_command_api.py`

**实现类/函数**：
- `RunLifecycleService.create_rerun()`
- `RunLifecycleService.build_rerun_trigger_metadata()`
- `RuntimeOrchestrationService.assert_thread_terminal_for_rerun()`

**验收标准**：
- `POST /api/sessions/{sessionId}/runs` 对应显式重新尝试，不对应暂停后的继续执行。
- failed / terminated 当前 run 尾部允许重新尝试。
- 创建重新尝试前必须通过 A4.0 runtime boundary 确认旧 run 的 `GraphThreadRef` 已处于终态。
- 重新尝试创建新的 PipelineRun，并在同一 Session 下形成新 run 分段。
- 重新尝试必须创建新的 `GraphThreadRef`，不得恢复旧 GraphThread，不得调用 `RuntimeOrchestrationService.resume_interrupt()`。
- 重新尝试产生 `pipeline_run_created`、会话状态变化事件和新 run 分界所需 metadata。
- 新 run 的 `trigger_source` 与 attempt index 可回放。
- metadata 中的机器字段 `trigger_source` 必须保持规格值 `retry`，但服务方法和前端语义使用“重新尝试 / rerun”命名。
- 重新尝试不继承旧 run 未交付的工作区改动。
- 重新尝试不创建 `RunControlRecord(type=retry)`；`control_item(type=retry)` 只用于当前 run 内自动回归或阶段内再次尝试。
- 本切片是重新尝试外部命令唯一落点；R3.3 只提供内部创建基础。
- 重新尝试接受、旧 GraphThread 未终结拒绝、非法 run 状态拒绝、创建成功和创建失败必须写入审计记录；新 run 必须生成新 `trace_id` 并记录新旧 run 与 trace 关联。
- API 测试必须断言 `POST /api/sessions/{sessionId}/runs` 的请求/响应 Schema、旧 GraphThread 未终结错误、非法 run 状态错误和 OpenAPI path/method 已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/services/test_rerun_command_projection.py -v`
- `pytest backend/tests/api/test_rerun_command_api.py -v`

<a id="f41"></a>

## F4.1 Composer 生命周期按钮状态

**计划周期**：Week 6
**状态**：`[x]`
**目标**：实现 Composer 右端发送、暂停、恢复、禁用按钮状态，使按钮严格绑定当前活动 run。
**实施计划**：`docs/plans/implementation/f4.1-composer-lifecycle-state.md`

**修改文件列表**：
- Modify: `frontend/src/features/composer/Composer.tsx`
- Create: `frontend/src/features/composer/composer-state.ts`
- Create: `frontend/src/features/composer/__tests__/composer-state.test.ts`

**实现类/函数**：
- `resolveComposerState()`
- `canSendMessage()`
- `resolveComposerActionLabel()`

**验收标准**：
- draft 与 `waiting_clarification` 支持发送。
- `running` 且 `current_stage_type = requirement_analysis` 时显示暂停语义。
- `waiting_approval` 与 `waiting_tool_confirmation` 时输入框不承担聊天输入，右端按钮保持暂停语义。
- 工具确认的允许或拒绝主操作只出现在 Narrative Feed 中的工具确认块内，不由 Composer 承担。
- 一旦进入 `solution_design` 及之后的正式研发链路，运行期持续保持暂停语义。
- failed、terminated、completed 保留禁用按钮。

**前端设计质量门**：
- 继承项目级前端主基调。
- 实现后必须检查发送、暂停、恢复、禁用按钮的视觉层级、可访问名称、焦点态和移动端可触达性。
- 按钮状态必须与当前活动 run 绑定，历史 run 或终态 run 不得出现可执行样式。

**测试方法**：
- `npm --prefix frontend run test -- composer-state`

<a id="f42"></a>

## F4.2 Run 控制按钮与终止入口

**计划周期**：Week 6
**状态**：`[x]`
**目标**：实现暂停、恢复和终止的前端控制入口，使运行控制不与普通消息发送混用。
**实施计划**：`docs/plans/implementation/f4.2-run-control-buttons.md`

**修改文件列表**：
- Create: `frontend/src/features/composer/RunControlButtons.tsx`
- Create: `frontend/src/features/runs/TerminateRunAction.tsx`
- Create: `frontend/src/features/composer/__tests__/RunControlButtons.test.tsx`
- Modify: `frontend/src/features/composer/Composer.tsx`
- Modify: `frontend/src/features/composer/__tests__/Composer.test.tsx`
- Modify: `frontend/src/features/workspace/WorkspaceShell.tsx`
- Modify: `frontend/src/features/workspace/__tests__/WorkspaceShell.test.tsx`
- Modify: `frontend/src/mocks/fixtures.ts`
- Modify: `frontend/src/styles/global.css`

**实现类/函数**：
- `RunControlButtons`
- `TerminateRunAction`
- `canPauseRun()`
- `canTerminateRun()`

**验收标准**：
- paused 显示恢复。
- waiting_clarification 且主按钮承担发送时，当前活动 run 仍存在可触发的次级暂停入口。
- running、waiting_approval 和 paused 下的主 Composer 生命周期按钮可直接执行暂停或恢复，不再只是只读展示。
- 终止动作位于中栏右上工具区。
- 终止只作用于当前活动 run。
- 历史 run 不展示可执行暂停、恢复或终止操作。
- 运行控制动作成功后同时刷新 `sessionWorkspace` 和 `projectSessions` 查询，避免工作台与会话列表状态漂移。

**前端设计质量门**：
- 继承项目级前端主基调。
- 实现后必须检查暂停、恢复、终止入口的危险层级、确认状态、禁用态、焦点态和窄屏可用性。
- 终止入口必须可见但不过度抢占主流程，不得与普通发送按钮混用。

**测试方法**：
- `npm --prefix frontend run test -- RunControlButtons`
- `npm --prefix frontend test`
- `npm --prefix frontend run build`

<a id="f43"></a>

## F4.3 Approval Block 与 Reject 输入

**计划周期**：Week 6
**状态**：`[ ]`
**目标**：实现内联审批块和 Reject 理由输入，使人工决策留在 Narrative Feed 中。
**实施计划**：`docs/plans/implementation/f4.3-approval-block-reject.md`

**修改文件列表**：
- Create: `frontend/src/features/approvals/ApprovalBlock.tsx`
- Create: `frontend/src/features/approvals/RejectReasonForm.tsx`
- Create: `frontend/src/features/approvals/DeliveryReadinessNotice.tsx`
- Create: `frontend/src/features/approvals/__tests__/ApprovalBlock.test.tsx`

**实现类/函数**：
- `ApprovalBlock`
- `RejectReasonForm`
- `DeliveryReadinessNotice`
- `resolveApprovalActionState()`

**验收标准**：
- Approval Request 内联展示 Approve / Reject。
- Reject 展开理由输入，提交后写入 Narrative Feed。
- paused 或历史 run 的审批不可提交。
- `git_auto_delivery` 未 ready 时阻塞 Approve 并提供打开设置入口。
- `demo_delivery` 不因远端配置缺失阻塞 Approve。

**前端设计质量门**：
- 继承项目级前端主基调，不单独询问审批块风格。
- 实现前必须梳理审批请求、Approve/Reject、拒绝理由、交付就绪阻塞和设置入口的信息层级。
- 实现后必须检查禁用态、历史态、错误态、长拒绝理由、键盘操作和可访问性。
- Approval Block 必须是 Narrative Feed 内联决策块，不得转成首选 modal，也不得改变 `approval_request` / `approval_result` 的顶层条目语义。

**测试方法**：
- `npm --prefix frontend run test -- ApprovalBlock`

<a id="f43a"></a>

## F4.3a Tool Confirmation Block 与确认交互

**计划周期**：Week 6-7
**状态**：`[ ]`
**目标**：实现 Narrative Feed 中的高风险工具确认块，使用户可以针对具体工具动作允许或拒绝本次执行，并与 Approval Block 保持交互和文案边界。
**实施计划**：`docs/plans/implementation/f4.3a-tool-confirmation-block.md`

**修改文件列表**：
- Create: `frontend/src/features/feed/ToolConfirmationBlock.tsx`
- Create: `frontend/src/features/tool-confirmations/tool-confirmation-actions.ts`
- Modify: `frontend/src/features/workspace/event-reducer.ts`
- Create: `frontend/src/features/feed/__tests__/ToolConfirmationBlock.test.tsx`
- Create: `frontend/src/features/tool-confirmations/__tests__/tool-confirmation-actions.test.ts`

**实现类/函数**：
- `ToolConfirmationBlock`
- `resolveToolConfirmationActions()`
- `submitToolConfirmationDecision()`
- `applyToolConfirmationEvent()`

**验收标准**：
- `tool_confirmation` 以 Narrative Feed 顶层交互块展示，不渲染为 Approval Block、Control Item 或阶段内部条目。
- 工具确认块必须展示工具名称、命令或参数摘要、目标资源、风险等级、风险分类、预期副作用、替代路径摘要和当前状态。
- 工具确认块必须直接消费顶层 `tool_confirmation.deny_followup_action` 与 `tool_confirmation.deny_followup_summary` 展示拒绝后的后续运行语义，不得依赖 `ToolConfirmationInspectorProjection`、原始 run 终态推断或 runtime 私有字段。
- 主操作文案使用 `允许本次执行` / `拒绝本次执行` 或等价权限动作，不使用 `Approve` / `Reject`。
- paused、历史 run、terminated、failed、completed 状态下的工具确认块不可提交，并展示稳定禁用原因。
- 拒绝工具动作后，前端不得展示审批拒绝、方案回退或 rollback 文案；后端进入替代路径、失败或等待运行控制时，按对应投影展示。
- 允许动作提交后只更新该 `tool_confirmation_id` 覆盖的条目，不批量允许后续同类工具调用。
- 点击工具确认块可打开 `ToolConfirmationInspectorProjection`，主操作仍保留在 Feed 块内。
- 组件测试必须覆盖 pending、allowed、denied、paused、历史态、终态、API 错误、重复事件合并和文案边界。

**前端设计质量门**：
- 继承项目级前端主基调，不单独询问工具确认块风格。
- 实现前必须梳理风险摘要、具体动作、目标资源、允许/拒绝按钮、禁用态和 Inspector 入口的信息层级。
- 实现后必须检查长命令、长路径、风险分类换行、危险动作层级、焦点态、移动端布局和可访问名称。
- Tool Confirmation Block 必须显著表达权限确认，不得表现为阶段质量审批或普通错误提示。

**测试方法**：
- `npm --prefix frontend run test -- ToolConfirmationBlock`
- `npm --prefix frontend run test -- tool-confirmation-actions`

<a id="f44"></a>

## F4.4 重新尝试 UI 与历史审批禁用态

**计划周期**：Week 6
**状态**：`[ ]`
**目标**：实现失败或终止后的重新尝试入口，并完善历史 run 审批块只读态。
**实施计划**：`docs/plans/implementation/f4.4-rerun-ui-historical-approval.md`

**修改文件列表**：
- Create: `frontend/src/features/runs/RerunAction.tsx`
- Create: `frontend/src/features/runs/__tests__/RerunAction.test.tsx`
- Modify: `frontend/src/features/approvals/ApprovalBlock.tsx`

**实现类/函数**：
- `RerunAction`
- `resolveRerunActionState()`
- `resolveHistoricalApprovalState()`

**验收标准**：
- failed / terminated 当前 run 尾部展示重新尝试动作。
- 重新尝试触发前明确提示新 run 从 Requirement Analysis 重新开始，且不继承旧 run 未交付工作区改动。
- 历史 run 的审批块为只读历史态，不提供可点击 Approve / Reject。
- 当前活动 run 已 terminated 时，原待处理审批块退化为不可提交状态。

**前端设计质量门**：
- 继承项目级前端主基调。
- 实现后必须检查重新尝试入口、历史审批只读态、失败原因、新 run 分界提示、禁用态和误操作风险。
- 重新尝试 UI 必须清楚表达新 run 从 Requirement Analysis 重新开始，不得暗示暂停后的继续执行或继承旧 run 未交付改动。

**测试方法**：
- `npm --prefix frontend run test -- RerunAction`
