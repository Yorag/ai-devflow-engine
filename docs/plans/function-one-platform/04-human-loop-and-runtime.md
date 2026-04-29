# 04 人工介入与执行内核

## 范围

本分卷覆盖 Week 6-9 的人工介入、运行控制、前端交互状态、`deterministic test runtime`、demo_delivery、LangGraph runtime、Stage Agent Runtime、Context Management、Provider adapter 和自动回归。完成后，系统可以用 `deterministic test runtime` 跑通 `demo_delivery` 全链路，并具备正式 LangGraph 编排路径。

本分卷承接 03 分卷的 Run 状态机和投影基础，负责运行中断、恢复、人工决策和执行内核副作用。每个任务只处理一个控制行为或 runtime 能力。
凡本分卷修改 `backend/app/api/routes/*` 的 API 切片，对应 API 测试必须在本切片内断言新增或修改的 path、method、请求 Schema、响应 Schema 和主要错误响应已进入 `/api/openapi.json`；V6.4 只做全局覆盖回归。

人工介入、运行控制、runtime、Provider 和交付前置动作必须嵌入日志审计能力。用户可触发命令必须为接受、拒绝、成功和失败结果写入审计记录；系统自动执行的高影响动作必须以 `system`、`agent` 或 `tool` 主体写入审计记录。审计记录写入失败时，高影响动作必须拒绝或回滚；普通运行日志失败不得破坏已持久化领域状态。

<a id="a40"></a>

## A4.0 Runtime orchestration boundary

**计划周期**：Week 6
**状态**：`[ ]`
**目标**：在人工介入命令落地前固定运行编排边界，使澄清、审批、暂停、恢复和终止都通过统一 runtime boundary 与领域服务协作；重新尝试只验证旧 GraphThread 已终结并创建新的 PipelineRun，不恢复或复用旧执行图。
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
- `RuntimeOrchestrationService.resume_interrupt()`
- `RuntimeOrchestrationService.pause_thread()`
- `RuntimeOrchestrationService.resume_thread()`
- `RuntimeOrchestrationService.terminate_thread()`
- `RuntimeOrchestrationService.assert_thread_terminal_for_rerun()`

**验收标准**：
- 人工介入命令只依赖 `RuntimeOrchestrationService` 与领域对象，不直接读取或写入 raw graph state。
- 澄清、审批等待必须能通过 `GraphInterruptRef` 关联到源 run、源 StageRun 和源阶段类型。
- pause / resume / terminate 必须作用于当前活动 run 对应的 `GraphThreadRef`。
- rerun 必须只确认旧 run 对应 `GraphThreadRef` 已处于终态，不得调用 `resume_interrupt()`，不得复用旧 `GraphThreadRef` 创建新 run。
- A4.0 只定义 orchestration boundary 和可 fake 的端口，不实现 deterministic 或 LangGraph 具体 runtime。
- 后续 H4.1、H4.3、H4.4、H4.5、H4.6、H4.7 不得绕过该边界直接推进或复用执行图状态。
- orchestration boundary 必须传递 `TraceContext`，为 interrupt、resume、pause、terminate、rerun terminal check 分配或继承 `span_id`。

**测试方法**：
- `pytest backend/tests/services/test_runtime_orchestration_boundary.py -v`

<a id="l41"></a>

## L4.1 命令审计失败语义

**计划周期**：Week 6
**状态**：`[ ]`
**目标**：固定用户命令和高影响动作在审计写入失败时的拒绝或回滚语义，确保后续澄清、审批、暂停、恢复、终止、重新尝试和交付前置动作不会把审计失败降级为普通运行日志失败。
**实施计划**：`docs/plans/implementation/l4.1-command-audit-failure-semantics.md`

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
**状态**：`[ ]`
**目标**：实现平台审计日志只读查询，使本地诊断与运维可以按主体、动作、目标、run 和结果过滤审计记录。
**实施计划**：`docs/plans/implementation/l4.2-audit-log-query-api.md`

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
**状态**：`[ ]`
**目标**：实现 Requirement Analysis 内部澄清记录和 `clarification_reply` 后端语义，保证澄清不被建模为审批流程。
**实施计划**：`docs/plans/implementation/h4.1-clarification-backend.md`

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
**状态**：`[ ]`
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
**状态**：`[ ]`
**目标**：实现 solution design 与 code review 的审批对象创建和投影字段，使审批请求成为 Narrative Feed 顶层条目。
**实施计划**：`docs/plans/implementation/h4.3-approval-object-projection.md`

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
**状态**：`[ ]`
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
**状态**：`[ ]`
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

<a id="h45"></a>

## H4.5 Pause/Resume checkpoint 语义

**计划周期**：Week 6
**状态**：`[ ]`
**目标**：实现暂停和恢复命令副作用，使 running、waiting_clarification、waiting_approval 都能保存可恢复状态。
**实施计划**：`docs/plans/implementation/h4.5-pause-resume-checkpoint.md`

**修改文件列表**：
- Modify: `backend/app/services/runs.py`
- Modify: `backend/app/services/control_records.py`
- Create: `backend/app/api/routes/runs.py`
- Create: `backend/tests/services/test_pause_resume.py`
- Create: `backend/tests/api/test_pause_resume_api.py`

**实现类/函数**：
- `RunLifecycleService.pause_run()`
- `RunLifecycleService.resume_run()`
- `RunLifecycleService.save_resume_checkpoint()`
- `ControlRecordService.append_control_item()`
- `RuntimeOrchestrationService.pause_thread()`
- `RuntimeOrchestrationService.resume_thread()`

**验收标准**：
- pause 可发生在 `running`、`waiting_clarification`、`waiting_approval`。
- pause 调用成功后通过 A4.0 runtime boundary 保存可恢复 checkpoint 与工作区快照引用。
- H4.5 创建 `backend/app/api/routes/runs.py` 并注册 run 控制路由，后续 H4.6/H4.7 在同一路由文件扩展终止与重新尝试命令。
- waiting_approval 下暂停后审批不可提交，投影 `is_actionable = false`。
- resume 继续同一 run 和同一 GraphThreadRef，不创建新 run。
- 若 run 暂停前停留于审批等待，resume 后恢复到同一个 `waiting_approval` 检查点。
- pause 接受、pause 成功、resume 接受、resume 成功、非法状态拒绝和 checkpoint 保存失败必须写入审计记录和运行日志。
- API 测试必须断言 `POST /api/runs/{runId}/pause`、`POST /api/runs/{runId}/resume` 的请求/响应 Schema、非法状态错误响应和 OpenAPI path/method 已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/services/test_pause_resume.py -v`
- `pytest backend/tests/api/test_pause_resume_api.py -v`

<a id="h46"></a>

## H4.6 Terminate 与 system_status

**计划周期**：Week 6
**状态**：`[ ]`
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
- terminate 接受、terminate 成功、非法状态拒绝和 runtime terminate 失败必须写入审计记录和运行日志。
- API 测试必须断言 `POST /api/runs/{runId}/terminate` 的请求/响应 Schema、非法状态错误响应和 OpenAPI path/method 已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/services/test_terminate_run.py -v`
- `pytest backend/tests/api/test_terminate_run_api.py -v`

<a id="h47"></a>

## H4.7 重新尝试命令与多 run 分界

**计划周期**：Week 6
**状态**：`[ ]`
**目标**：补齐重新尝试命令的事件、trigger metadata 和多 run 分界语义，使 failed / terminated 后的新 run 能被前端定位。
**实施计划**：`docs/plans/implementation/h4.7-rerun-command-run-boundary.md`

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
**状态**：`[ ]`
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
- `waiting_approval` 时输入框不承担聊天输入，右端按钮保持暂停语义。
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
**状态**：`[ ]`
**目标**：实现暂停、恢复和终止的前端控制入口，使运行控制不与普通消息发送混用。
**实施计划**：`docs/plans/implementation/f4.2-run-control-buttons.md`

**修改文件列表**：
- Create: `frontend/src/features/composer/RunControlButtons.tsx`
- Create: `frontend/src/features/runs/TerminateRunAction.tsx`
- Create: `frontend/src/features/composer/__tests__/RunControlButtons.test.tsx`

**实现类/函数**：
- `RunControlButtons`
- `TerminateRunAction`
- `canPauseRun()`
- `canResumeRun()`
- `canTerminateRun()`

**验收标准**：
- paused 显示恢复。
- waiting_clarification 且主按钮承担发送时，当前活动 run 仍存在可触发的次级暂停入口。
- 终止动作位于中栏右上工具区。
- 终止只作用于当前活动 run。
- 历史 run 不展示可执行暂停、恢复或终止操作。

**前端设计质量门**：
- 继承项目级前端主基调。
- 实现后必须检查暂停、恢复、终止入口的危险层级、确认状态、禁用态、焦点态和窄屏可用性。
- 终止入口必须可见但不过度抢占主流程，不得与普通发送按钮混用。

**测试方法**：
- `npm --prefix frontend run test -- RunControlButtons`

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

<a id="a41"></a>

## A4.1 RuntimeEngine 接口

**计划周期**：Week 7
**状态**：`[ ]`
**目标**：定义 `deterministic test runtime` 与 LangGraph runtime 的共同接口，使运行生命周期服务不依赖具体执行内核，并保证两条执行路径只消费 run 已固化的运行快照。
**实施计划**：`docs/plans/implementation/a4.1-runtime-engine-interface.md`

**修改文件列表**：
- Create: `backend/app/runtime/base.py`
- Create: `backend/tests/runtime/test_runtime_engine_contract.py`

**实现类/函数**：
- `RuntimeEngine`
- `RuntimeExecutionContext`
- `RuntimeStepResult`
- `RuntimeInterrupt`
- `RuntimeTerminalResult`

**验收标准**：
- runtime 接口支持启动、推进、从中断恢复和终止。
- runtime 结果只返回领域对象、事件和产物引用，不返回 raw graph state。
- `deterministic test runtime` 与 LangGraph runtime 必须实现 A4.0 定义的 `RuntimeCommandPort` / `CheckpointPort` 调用边界。
- `deterministic test runtime` 只作为稳定测试、前端联调和可重复端到端验收路径；正式 Agent 编排路径由 LangGraph runtime 承担。
- `RuntimeEngine` 接口不得要求调用方识别 deterministic 或 LangGraph 的内部状态结构。
- runtime 接口必须接收并传递 `TraceContext`，运行步骤结果必须允许返回日志摘要引用和审计引用，但不得要求调用方读取日志来推进状态。
- `RuntimeExecutionContext` 必须携带 `template_snapshot_ref`、Provider/模型绑定快照引用、`runtime_limit_snapshot_ref`、`graph_definition_ref` 和必要的交付快照引用；runtime 不得读取最新 Provider、模板或平台运行设置来改变当前 run。

**测试方法**：
- `pytest backend/tests/runtime/test_runtime_engine_contract.py -v`

<a id="a42"></a>

## A4.2 deterministic test runtime 六阶段推进

**计划周期**：Week 7
**状态**：`[ ]`
**目标**：实现稳定可控的 `deterministic test runtime` 六阶段推进，使端到端测试和前端联调不依赖真实模型输出。
**实施计划**：`docs/plans/implementation/a4.2-deterministic-six-stage-runtime.md`

**修改文件列表**：
- Create: `backend/app/runtime/deterministic.py`
- Create: `backend/tests/runtime/test_deterministic_runtime.py`

**实现类/函数**：
- `DeterministicRuntimeEngine`
- `DeterministicRuntimeEngine.run_next()`
- `DeterministicRuntimeEngine.emit_stage_artifacts()`

**验收标准**：
- `deterministic test runtime` 可稳定推进六个业务阶段。
- 每个阶段写入 StageRun、StageArtifact 和领域事件。
- Solution Validation 作为 `solution_design` 内部过程记录出现，不形成独立阶段。
- `deterministic test runtime` 在调用 `read_file`、`write_file`、`edit_file`、`glob`、`grep` 或 `bash` 能力时必须通过 W5.0 `ToolProtocol` 与 `ToolRegistry`；若本切片尚未调用工具，则只能写入固定结构化产物和领域事件，不得引入临时工具函数。
- `deterministic test runtime` 每个阶段推进必须写入运行日志摘要，包含阶段、耗时、结果状态、产物引用和 `span_id`；阶段事实仍由 StageRun、StageArtifact 和领域事件承载。
- `deterministic test runtime` 必须使用 R3.4、R3.4a、R3.4b 固化的模板、Provider/模型绑定和运行上限快照，不得读取最新配置或暴露为用户可选运行模式。
- 前端端到端测试可使用固定输出。

**测试方法**：
- `pytest backend/tests/runtime/test_deterministic_runtime.py -v`

<a id="a43"></a>

## A4.3 deterministic test runtime 澄清与审批中断

**计划周期**：Week 7
**状态**：`[ ]`
**目标**：为 `deterministic test runtime` 增加可配置澄清、方案审批和代码评审审批中断路径。
**实施计划**：`docs/plans/implementation/a4.3-deterministic-interrupts.md`

**修改文件列表**：
- Modify: `backend/app/runtime/deterministic.py`
- Create: `backend/tests/runtime/test_deterministic_interrupts.py`

**实现类/函数**：
- `DeterministicRuntimeEngine.configure_interrupts()`
- `DeterministicRuntimeEngine.resume_from_interrupt()`
- `DeterministicRuntimeEngine.emit_approval_request()`

**验收标准**：
- 可配置触发澄清。
- 可配置触发 solution design approval。
- 可配置触发 code review approval。
- 中断恢复必须通过 A4.0 runtime boundary 继续同一个 run、同一个 GraphThreadRef 和同一个源阶段。
- 审批拒绝按规格回到目标阶段。
- deterministic 中断、恢复、审批请求生成和恢复失败必须写入运行日志，并继承同一 `trace_id` 与 `correlation_id`。

**测试方法**：
- `pytest backend/tests/runtime/test_deterministic_interrupts.py -v`

<a id="a44"></a>

## A4.4 deterministic test runtime 终态控制

**计划周期**：Week 7
**状态**：`[ ]`
**目标**：为 `deterministic test runtime` 增加失败和终止路径，使端到端测试能覆盖 run 终态和重新尝试前置条件。
**实施计划**：`docs/plans/implementation/a4.4-deterministic-terminal-control.md`

**修改文件列表**：
- Modify: `backend/app/runtime/deterministic.py`
- Create: `backend/tests/runtime/test_deterministic_terminal_states.py`

**实现类/函数**：
- `DeterministicRuntimeEngine.emit_terminal_result()`
- `DeterministicRuntimeEngine.fail_run()`
- `DeterministicRuntimeEngine.terminate_run()`
- `TerminalStatusProjector.append_terminal_system_status()`

**验收标准**：
- `deterministic test runtime` 可配置成功、失败和终止路径。
- failed / terminated run 尾部生成正确终态来源记录，并统一通过 `TerminalStatusProjector` 追加顶层 `system_status`。
- 终态记录可支持后续重新尝试 run 创建。
- 本切片不生成 DeliveryRecord，正式 `demo_delivery` 由 D4.2 负责。
- deterministic 失败和终止必须写入运行日志，并记录直接失败点、源阶段和后续重新尝试所需的关联线索。

**测试方法**：
- `pytest backend/tests/runtime/test_deterministic_terminal_states.py -v`

<a id="d41"></a>

## D4.1 Delivery base 与 DeliveryRecord

**计划周期**：Week 7
**状态**：`[ ]`
**目标**：建立交付适配器基类和 DeliveryRecord 服务，使 `deterministic test runtime` 能进入正式 demo_delivery 出口；交付通道快照固化已经由 D4.0 负责。
**实施计划**：`docs/plans/implementation/d4.1-delivery-base-record.md`

**修改文件列表**：
- Create: `backend/app/delivery/base.py`
- Create: `backend/app/services/delivery.py`
- Create: `backend/tests/delivery/test_delivery_record_service.py`

**实现类/函数**：
- `DeliveryAdapter`
- `DeliveryRecordService.create_record()`
- `DeliveryRecordService.get_record()`
- `DeliveryService.get_adapter()`
- `DeliveryService.create_delivery_record_from_adapter_result()`

**验收标准**：
- DeliveryRecord 统一文本需求驱动与未来页面交互驱动的交付出口。
- DeliveryRecord 关联需求、方案、代码、测试、评审和交付产物。
- DeliveryRecord 必须读取 D4.0 已固化的 `delivery_channel_snapshot_ref`，不得重新读取项目级最新 DeliveryChannel。
- 本切片不改变 `ApprovalService.approve()`，不承担交付快照固化。
- 交付 adapter base 只定义输入、输出、错误和审计引用边界，不执行真实 Git 写动作。
- DeliveryRecord 创建成功、创建失败和 adapter 选择失败必须写入运行日志；未来真实交付的高影响动作审计由 D5.1-D5.4 嵌入。

**测试方法**：
- `pytest backend/tests/delivery/test_delivery_record_service.py -v`

<a id="d42"></a>

## D4.2 demo_delivery adapter 与 delivery_result

**计划周期**：Week 7
**状态**：`[ ]`
**目标**：实现 `demo_delivery` 交付路径，使 deterministic 成功链路可生成完整 DeliveryRecord 和展示型交付结果且不执行真实 Git 写动作。
**实施计划**：`docs/plans/implementation/d4.2-demo-delivery-adapter.md`

**修改文件列表**：
- Create: `backend/app/delivery/demo.py`
- Modify: `backend/app/services/delivery.py`
- Create: `backend/tests/delivery/test_demo_delivery.py`
- Create: `backend/tests/e2e/test_deterministic_run_flow.py`

**实现类/函数**：
- `DemoDeliveryAdapter.deliver()`
- `DeliveryRecordService.create_demo_record()`
- `DeliveryService.append_delivery_result()`
- `startDeterministicRunFixture()`

**验收标准**：
- `demo_delivery` 生成展示型交付结果。
- 不执行真实 Git 写动作。
- 成功后追加顶层 `delivery_result`。
- `delivery_result` 详情可通过 DeliveryResultDetailProjection 深看。
- `deterministic test runtime` 可跑通六阶段到 `demo_delivery` 的完整成功链路。
- `demo_delivery` 必须读取已固化交付快照，不重新读取项目级最新 DeliveryChannel。
- `demo_delivery` 必须写入运行日志和审计记录，明确其不执行真实 Git 写动作；审计引用进入 DeliveryRecord 或交付过程引用。

**测试方法**：
- `pytest backend/tests/delivery/test_demo_delivery.py -v`
- `pytest backend/tests/e2e/test_deterministic_run_flow.py -v`

<a id="d43"></a>

## D4.3 DeliveryResultDetailProjection 正式实现

**计划周期**：Week 7
**状态**：`[ ]`
**目标**：在 DeliveryRecord 与 `demo_delivery` 落地后，实现正式交付结果详情投影，替代 Week 5 不允许实现的临时交付详情投影语义。
**实施计划**：`docs/plans/implementation/d4.3-delivery-result-detail-projection.md`

**修改文件列表**：
- Modify: `backend/app/services/projections/inspector.py`
- Modify: `backend/app/api/routes/query.py`
- Create: `backend/tests/projections/test_delivery_result_detail_projection.py`
- Modify: `backend/tests/api/test_query_api.py`

**实现类/函数**：
- `InspectorProjectionService.get_delivery_record_detail()`
- `InspectorProjectionService.build_delivery_result_sections()`

**验收标准**：
- `GET /api/delivery-records/{deliveryRecordId}` 返回完整交付结果详情。
- 详情来源必须是 DeliveryRecord、已固化交付快照、StageArtifact 和稳定引用，不得使用前端摘要或临时 projection payload 反推。
- `delivery_result` 详情包含交付模式、变更结果、测试结论、评审结论、产物、原始交付过程引用与量化信息。
- `approval_result` 仍不作为独立右栏对象；交付详情只服务 `delivery_result`。
- DeliveryResultDetailProjection 可以展示与交付过程直接相关的日志摘要、裁剪片段和审计引用，但不得从日志反推交付结果。
- API 测试必须断言 `GET /api/delivery-records/{deliveryRecordId}` 的响应 Schema、主要错误响应和 OpenAPI path/method 已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/projections/test_delivery_result_detail_projection.py -v`
- `pytest backend/tests/api/test_query_api.py -v`

<a id="a45"></a>

## A4.5 LangGraph 主链与 checkpoint

**计划周期**：Week 8
**状态**：`[ ]`
**目标**：接入 LangGraph 主链和 checkpoint，使正式执行路径具备固定业务阶段编排能力，并把单阶段内部执行限定为可替换的 stage runner 调用边界。
**实施计划**：`docs/plans/implementation/a4.5-langgraph-main-chain-checkpoint.md`

**修改文件列表**：
- Create: `backend/app/runtime/langgraph_engine.py`
- Create: `backend/app/runtime/nodes.py`
- Create: `backend/app/runtime/checkpoints.py`
- Create: `backend/app/runtime/stage_runner_port.py`
- Create: `backend/tests/runtime/test_langgraph_engine.py`

**实现类/函数**：
- `LangGraphRuntimeEngine`
- `StageNodeRunnerPort`
- `build_stage_graph()`
- `run_stage_node()`
- `save_graph_checkpoint()`

**验收标准**：
- LangGraph 表达固定主链、阶段节点、条件边和 checkpoint。
- GraphDefinition 的六阶段映射进入 LangGraph 构建过程。
- 每次业务阶段切换前后具备可恢复 checkpoint。
- raw graph state 不进入前端投影。
- LangGraph runtime 必须实现 A4.0 runtime boundary，不新增第二套中断、恢复或终止调用路径。
- `GraphDefinition` 映射为 LangGraph `StateGraph` 构建输入，运行时编译为 compiled graph。
- `GraphThread.graph_thread_id` 映射为 LangGraph configurable `thread_id`。
- 条件路由使用 LangGraph conditional edges 表达，不在 `RunLifecycleService` 中另写一套阶段分支状态机。
- LangGraph stage node 只把 `run_id`、`stage_run_id`、`stage_contract_ref`、`RuntimeExecutionContext` 和 `TraceContext` 交给 `StageNodeRunnerPort`；不得在 LangGraph node 内直接构建 `ContextEnvelope`、调用 Provider、解析 `AgentDecision` 或执行工具。
- A4.5 测试可使用 fake stage runner 验证主链和 checkpoint；正式 `Stage Agent Runtime` 由 A4.9d 接入。
- checkpoint 通过 LangGraph checkpointer 保存，并同步写入 `GraphCheckpoint.checkpoint_ref`。
- 测试断言 checkpoint 可用于同一 `GraphThread` 恢复，而不是只验证业务状态字段变化。
- LangGraph graph build、thread start、node start、node completed、checkpoint saved、graph failed 必须写入运行日志摘要，并继承 `TraceContext`。

**测试方法**：
- `pytest backend/tests/runtime/test_langgraph_engine.py -v`

<a id="a46"></a>

## A4.6 LangGraph interrupt resume

**计划周期**：Week 8
**状态**：`[ ]`
**目标**：实现 LangGraph 澄清中断、审批中断和恢复，使正式 runtime 符合人工介入语义。
**实施计划**：`docs/plans/implementation/a4.6-langgraph-interrupt-resume.md`

**修改文件列表**：
- Modify: `backend/app/runtime/langgraph_engine.py`
- Modify: `backend/app/runtime/checkpoints.py`
- Create: `backend/tests/runtime/test_langgraph_interrupts.py`

**实现类/函数**：
- `create_graph_interrupt()`
- `resume_graph_interrupt()`
- `LangGraphRuntimeEngine.resume_from_interrupt()`

**验收标准**：
- 澄清中断可恢复同一 GraphThread。
- 审批中断可恢复同一 GraphThread。
- run 在暂停前停留于审批等待时，resume 后重新进入同一个 `waiting_approval` 检查点。
- 审批命令在 run 未暂停时通过恢复对应 GraphInterrupt 继续执行图。
- 澄清与审批等待必须通过 LangGraph interrupt payload 表达，并持久化为 `GraphInterrupt`。
- resume 必须使用同一 `thread_id` 和对应 resume command 继续执行。
- `clarification_reply`、`approval approve/reject` 必须通过 A4.0 runtime boundary 进入 LangGraph resume，不得由 API 或领域服务直接调用 LangGraph internals。
- `clarification_reply`、`approval approve/reject` 不得绕过 `GraphInterrupt` 直接推进阶段状态。
- pause 后 resume 不创建新的 `GraphThread`，也不创建新的 `PipelineRun`。
- LangGraph interrupt、resume command、resume success 和 resume failure 必须写入运行日志；审批或澄清命令审计仍由对应 H4 命令切片负责。

**测试方法**：
- `pytest backend/tests/runtime/test_langgraph_interrupts.py -v`

<a id="a47"></a>

## A4.7 LangGraph 事件到领域产物转换

**计划周期**：Week 8
**状态**：`[ ]`
**目标**：把 LangGraph 内部事件转换为领域事件、StageArtifact 和投影来源记录，防止 raw graph state 泄漏到产品 API。
**实施计划**：`docs/plans/implementation/a4.7-langgraph-event-translation.md`

**修改文件列表**：
- Create: `backend/app/runtime/event_translator.py`
- Create: `backend/tests/runtime/test_langgraph_event_translation.py`

**实现类/函数**：
- `LangGraphEventTranslator.translate_node_started()`
- `LangGraphEventTranslator.translate_node_completed()`
- `LangGraphEventTranslator.translate_interrupt()`
- `LangGraphEventTranslator.write_stage_artifact()`

**验收标准**：
- 执行图内部事件不直接作为前端产品事件暴露。
- Graph node 事件转换为领域事件、阶段产物或稳定引用。
- 投影层只读取领域对象、事件和产物引用。
- Inspector 投影不需要 raw graph state 回填关键事实。
- LangGraph stream / node event 只允许进入 `LangGraphEventTranslator`。
- translator 输出领域事件、`StageArtifact`、`RunControlRecord` 或稳定引用。
- SSE、Projection、Inspector 不读取 LangGraph raw event、raw state、compiled graph 或 checkpoint 原始 payload。
- 测试覆盖 raw graph event 不会直接出现在对外事件 payload 中。
- translator 必须把底层事件先分类、裁剪、关联后再写入运行日志；raw LangGraph event 不得作为可查询日志载荷原样保存。

**测试方法**：
- `pytest backend/tests/runtime/test_langgraph_event_translation.py -v`

<a id="a48"></a>

## A4.8 Provider Registry

**计划周期**：Week 8
**状态**：`[ ]`
**目标**：实现 Provider registry，使运行时能从 R3.4a 固化的 ProviderSnapshot 与 ModelBindingSnapshot 解析内置 Provider 与 custom Provider。
**实施计划**：`docs/plans/implementation/a4.8-provider-registry.md`

**修改文件列表**：
- Create: `backend/app/providers/base.py`
- Create: `backend/app/providers/provider_registry.py`
- Create: `backend/tests/providers/test_provider_registry.py`

**实现类/函数**：
- `ProviderConfig`
- `ModelProvider`
- `ProviderRegistry.resolve()`
- `ProviderRegistry.resolve_from_template_snapshot()`
- `ProviderRegistry.resolve_from_model_binding_snapshot()`

**验收标准**：
- 内置 Provider 与 custom Provider 走统一解析路径。
- 运行时读取 ModelBindingSnapshot 中已固化的 Provider 与模型绑定。
- Provider 绑定单位是 AgentRole。
- Provider 配置不直接泄漏密钥内容到前端。
- Provider 解析成功、解析失败和凭据引用不可用必须写入运行日志；日志和审计摘要不得包含真实密钥。
- run 启动后 Provider 配置变化、凭据轮换或能力声明变化不得改变当前 run 已固化的模型调用语义。

**测试方法**：
- `pytest backend/tests/providers/test_provider_registry.py -v`

<a id="a48a"></a>

## A4.8a PromptValidation 边界校验

**计划周期**：Week 8
**状态**：`[ ]`
**目标**：实现用户可编辑 `system_prompt` 的边界校验，使模板保存和 run 启动前都能拒绝覆盖平台指令、阶段契约、工具边界、审批边界、交付边界、审计边界或输出 Schema 的提示词。
**实施计划**：`docs/plans/implementation/a4.8a-prompt-validation-boundaries.md`

**修改文件列表**：
- Create: `backend/app/runtime/prompt_validation.py`
- Modify: `backend/app/services/templates.py`
- Modify: `backend/app/services/runs.py`
- Create: `backend/tests/runtime/test_prompt_validation.py`
- Create: `backend/tests/services/test_prompt_validation_integration.py`

**实现类/函数**：
- `PromptValidationRule`
- `PromptValidationResult`
- `PromptValidationError`
- `PromptValidationService`
- `PromptValidationService.validate_system_prompt()`
- `PromptValidationService.validate_template_prompts_before_save()`
- `PromptValidationService.validate_run_prompt_snapshots()`

**验收标准**：
- `system_prompt` 保存前必须校验长度上限、上下文预算和平台边界冲突，超过上限时返回明确错误，不得静默截断后保存。
- run 启动前必须对即将进入 `template_snapshot_ref` 的 `system_prompt` 再次执行同一套 PromptValidation，防止旧模板或并发修改绕过保存时校验。
- 校验必须拒绝要求忽略平台指令、调用未授权工具、跳过澄清或审批、绕过审计、泄露凭据、泄露 raw chain-of-thought、修改交付模式、关闭结构化输出、覆盖阶段契约或覆盖输出 Schema 的提示词。
- A4.8a 必须接管 C2.4 模板保存和 R3.2 run 启动预留的 `system_prompt` 边界校验调用点；完成后不得保留仅长度校验、前端校验或绕过 PromptValidation 的保存/启动路径。
- PromptValidation 必须读取 R3.5 `GraphDefinition.stage_contracts`；模板保存时 `GraphDefinition` 尚未生成，必须读取与 R3.5 `GraphCompiler` 生成 `stage_contracts` 相同的阶段契约来源；不得新增与 `stage_contracts` 并行的阶段规则表。
- PromptValidation 只校验提示词与平台边界、阶段契约和安全约束的冲突；不得把语言风格、技术偏好或业务判断质量作为阻塞保存或启动 run 的依据。
- 用户可编辑 `system_prompt` 通过校验后仍只能作为低权威 `agent_role_prompt` 进入后续 `ContextEnvelope`，不得升级为 `runtime_instructions`。
- 校验接受、校验拒绝和 run 启动前校验失败必须写入运行日志摘要；涉及用户保存请求的拒绝必须写入审计记录。

**测试方法**：
- `pytest backend/tests/runtime/test_prompt_validation.py -v`
- `pytest backend/tests/services/test_prompt_validation_integration.py -v`

<a id="a48b"></a>

## A4.8b ContextEnvelope 与 ContextManifest Schema

**计划周期**：Week 8
**状态**：`[ ]`
**目标**：固定 `ContextEnvelope`、`ContextManifest`、上下文块和上下文可信边界的结构化 Schema，使模型调用前的上下文输入与过程记录具备统一数据契约。
**实施计划**：`docs/plans/implementation/a4.8b-context-envelope-manifest-schema.md`

**修改文件列表**：
- Create: `backend/app/context/schemas.py`
- Create: `backend/tests/context/test_context_schemas.py`

**实现类/函数**：
- `ContextEnvelope`
- `ContextManifest`
- `ContextEnvelopeSection`
- `ContextBlock`
- `ContextSourceRef`
- `ContextTrustLevel`
- `ContextBoundaryAction`
- `ContextManifestRecord`
- `ContextEnvelope.validate_section_order()`
- `ContextManifest.from_envelope()`

**验收标准**：
- `ContextEnvelope` Schema 必须按规约顺序表达 `runtime_instructions`、`stage_contract`、`agent_role_prompt`、`task_objective`、`specified_action`、`input_artifact_refs`、`context_references`、`working_observations`、`reasoning_trace`、`available_tools`、`recent_observations`、`response_schema` 和 `trace_context`。
- `ContextManifest` Schema 必须记录 `session_id`、`run_id`、`stage_run_id`、`trace_id`、`correlation_id`、`span_id`、构建时间、`template_snapshot_ref`、`system_prompt` 快照引用、最终渲染提示词或消息序列引用、hash、模板版本、Provider 与模型绑定快照引用、阶段契约、输出 Schema、可用工具及 schema 版本、来源对象、可信级别、边界处理、裁剪压缩状态、完整内容稳定引用和估算规模。
- `ContextBlock` 必须区分系统可信上下文、低权威角色配置上下文和不可信业务事实或观察结果；用户消息、澄清回复、审批反馈、附件、仓库文件、测试输出、工具观察和外部交付返回不得覆盖 `runtime_instructions`、`stage_contract`、`allowed_tools` 或 `response_schema`。
- `available_tools` 只能表达来自 W5.0 `ToolProtocol` / `ToolRegistry` 的工具名称、schema 版本和可绑定描述；不得保存具体工具实例、临时工具函数或未注册工具。
- Schema 必须支持把 `context_manifest` 作为 R3.7 `StageArtifact.process` 过程记录类型引用，且不把大文本直接复制到 manifest 中。
- raw LangGraph state、raw checkpoint payload、raw node event、raw thread 对象、raw tool adapter 对象和 raw Provider adapter 对象不得通过 Schema 校验进入 `ContextEnvelope`。
- 本切片只固定 Schema 和校验，不实现上下文来源解析、尺寸守卫、压缩或模型调用；后续 A4.9a 使用本 Schema 构建实际 envelope。

**测试方法**：
- `pytest backend/tests/context/test_context_schemas.py -v`

<a id="a49"></a>

## A4.9 LangChain Provider Adapter

**计划周期**：Week 8
**状态**：`[ ]`
**目标**：实现 LangChain 适配层，使正式 runtime 可以创建模型调用对象和结构化输出边界。
**实施计划**：`docs/plans/implementation/a4.9-langchain-provider-adapter.md`

**修改文件列表**：
- Create: `backend/app/providers/langchain_adapter.py`
- Create: `backend/tests/providers/test_langchain_adapter.py`

**实现类/函数**：
- `LangChainProviderAdapter`
- `ModelCallResult`
- `LangChainProviderAdapter.create_chat_model()`
- `LangChainProviderAdapter.bind_tools()`
- `LangChainProviderAdapter.with_structured_output()`
- `LangChainProviderAdapter.invoke_structured()`

**验收标准**：
- LangChain 封装模型供应商、消息对象、结构化输出与内部工具绑定。
- custom Provider 使用 `OpenAI Completions compatible` 接入协议。
- 测试使用 fake model，不调用真实远端模型。
- LangChain adapter 只创建 chat model、绑定工具、声明结构化输出，不表达业务阶段流转。
- LangChain adapter 只消费调用方传入的消息序列、可绑定工具描述和结构化输出 Schema；不得自行解析业务上下文、读取 StageArtifact 或修改 `ContextManifest`。
- 工具绑定对象来自 W5.0 定义的抽象 `ToolProtocol` 与工具注册表；Week 8 只能绑定已注册 `bash`、`read_file`、`edit_file`、`write_file`、`glob`、`grep` 或 fake 工具，不得在 D5.1-D5.4 前绑定具体 delivery tool 实例。
- 结构化输出失败必须返回可处理错误，不得直接推进 LangGraph 节点成功完成。
- `ModelCallResult` 必须返回原始响应引用、结构化输出候选、tool call request 候选、Provider 错误、token 用量摘要和 `model_call_trace` 写入所需元数据；不得把自由文本直接标记为阶段成功。
- 模型请求、模型响应、结构化输出解析、模型错误和重试必须写入运行日志摘要；模型输入输出进入日志前必须裁剪、阻断敏感字段并限制长度。
- Provider 请求超时、网络错误重试次数、限流重试次数和退避上限必须来自当前 run 的 `RuntimeLimitSnapshot` 或其引用的配置版本，不得读取最新 `PlatformRuntimeSettings`。
- 上下文压缩使用系统内置 `compression_prompt`；Adapter 只能记录系统定义的 prompt id/version 引用，不得把 `compression_prompt` 作为用户配置、环境变量或热重载设置读取。

**测试方法**：
- `pytest backend/tests/providers/test_langchain_adapter.py -v`

<a id="a49a"></a>

## A4.9a ContextEnvelope Builder 与 ContextManifest 记录

**计划周期**：Week 8
**状态**：`[ ]`
**目标**：实现上下文来源解析和 `ContextEnvelope` 构建，把阶段契约、角色提示词、阶段产物、工具观察和不可信上下文按固定顺序组装，并把实际上下文使用记录写入 `StageArtifact.process`。
**实施计划**：`docs/plans/implementation/a4.9a-context-envelope-builder.md`

**修改文件列表**：
- Create: `backend/app/context/source_resolver.py`
- Create: `backend/app/context/builder.py`
- Modify: `backend/app/services/artifacts.py`
- Create: `backend/tests/context/test_context_source_resolver.py`
- Create: `backend/tests/context/test_context_envelope_builder.py`

**实现类/函数**：
- `ContextSourceResolver`
- `ContextEnvelopeBuilder`
- `ContextBuildRequest`
- `ContextBuildResult`
- `ContextEnvelopeBuilder.build_for_stage_call()`
- `ContextEnvelopeBuilder.render_messages()`
- `ContextEnvelopeBuilder.append_manifest_record()`
- `ContextSourceResolver.resolve_stage_inputs()`
- `ContextSourceResolver.resolve_context_references()`
- `ArtifactStore.append_context_manifest()`

**验收标准**：
- Builder 必须消费 A4.8b `ContextEnvelope` / `ContextManifest` Schema，不得输出临时 dict 或前端投影专用载荷。
- Builder 必须从 R3.5 `GraphDefinition.stage_contracts` 读取当前阶段职责、输入契约、输出契约、`allowed_tools`、结构化产物要求和运行上限引用；不得再引入 `stage_execution_mode` 或并行权限表。
- Builder 必须从 R3.7 `StageArtifact`、`ContextReference`、ClarificationRecord、ApprovalDecision、工具结果、ChangeSet 和工作区稳定引用解析上下文来源；不得从运行日志反推业务事实。
- `agent_role_prompt` 必须来自已通过 A4.8a PromptValidation 并固化到当前 run `template_snapshot_ref` 的提示词；Builder 不得读取最新模板或最新 AgentRole 配置。
- `available_tools` 必须通过 W5.0 `ToolRegistry.list_bindable_tools()` 按当前 `stage_contract.allowed_tools` 过滤生成；未注册工具、未授权工具和具体工具实例不得进入 `ContextEnvelope`。
- 用户消息、澄清回复、审批反馈、附件、仓库文件、测试输出、工具观察和外部交付返回必须作为不可信 `ContextBlock` 进入，并记录来源标识、可信级别、边界说明和稳定引用。
- 每次构建必须生成 `ContextManifest`，并通过 `ArtifactStore.append_context_manifest()` 写入当前 `StageArtifact.process` 或其稳定引用；运行日志只保存摘要和定位信息。
- Builder 必须记录最终渲染提示词或消息序列引用、hash、模板版本、提示词片段来源、Provider 与模型绑定快照引用和可用工具 schema 版本。
- raw LangGraph state、raw checkpoint payload、raw node event、raw thread 对象、raw Provider response 和 raw tool adapter 对象不得进入 envelope 或 manifest。

**测试方法**：
- `pytest backend/tests/context/test_context_source_resolver.py -v`
- `pytest backend/tests/context/test_context_envelope_builder.py -v`

<a id="a49b"></a>

## A4.9b Context Size Guard 与压缩过程记录

**计划周期**：Week 8
**状态**：`[ ]`
**目标**：实现单次模型调用前的上下文尺寸守卫、观察结果预算、滑动工作窗口和上下文压缩记录，防止大文件、工具输出、测试输出或长链路过程无界进入模型上下文。
**实施计划**：`docs/plans/implementation/a4.9b-context-size-guard.md`

**修改文件列表**：
- Create: `backend/app/context/size_guard.py`
- Create: `backend/app/context/compression.py`
- Modify: `backend/app/context/builder.py`
- Modify: `backend/app/services/artifacts.py`
- Create: `backend/tests/context/test_context_size_guard.py`
- Create: `backend/tests/context/test_context_compression.py`

**实现类/函数**：
- `ContextTokenEstimator`
- `ContextSizeGuard`
- `ContextCompressionRunner`
- `CompressedContextBlock`
- `ContextOverflowError`
- `ContextSizeGuard.apply_observation_budget()`
- `ContextSizeGuard.apply_sliding_window()`
- `ContextSizeGuard.ensure_within_model_window()`
- `ContextCompressionRunner.compress()`
- `ArtifactStore.append_compressed_context_block()`

**验收标准**：
- Size guard 必须读取当前 run 的 `RuntimeLimitSnapshot`、Provider 与模型绑定快照能力声明和 A4.9 Provider Adapter 返回的模型窗口信息；不得读取最新 `PlatformRuntimeSettings` 改变当前 run。
- 大文件读取、`grep` 结果、测试输出、diff、`bash` stdout / stderr、工具错误和远端交付返回进入 `ContextEnvelope` 前必须被预算化，只保留预览、摘要、路径、hash、行号、退出码、错误摘要和稳定引用。
- 阶段内 ReAct 循环必须应用滑动工作窗口，保留最近必要过程，并把更早过程转为结构化索引或引用；不得删除 R3.7 `StageArtifact.process` 中的原始过程记录。
- `pinned_context` 包含 `runtime_instructions`、`stage_contract`、`task_objective`、`response_schema`、`system_prompt` 快照引用、结构化需求、已批准方案、当前审批或拒绝理由、当前 active file task 和可用工具 schema，压缩时不得丢失。
- 上下文压缩必须通过 A4.9 `LangChainProviderAdapter.invoke_structured()` 发起 `model_call_type = context_compression` 的模型调用，并使用系统内置 `compression_prompt` 引用；不得把压缩提示词作为用户配置、环境变量或热重载设置读取。
- 压缩输出必须形成结构化 `CompressedContextBlock`，并写入 `StageArtifact.process` 的 `compressed_context_block` 和对应 `model_call_trace`；自由文本摘要不得作为唯一结果。
- 压缩失败不得伪造摘要；若仍能构建 envelope，必须记录 warning 和 manifest 处理结果；若无法构建 envelope，当前 `StageRun.status` 与 `PipelineRun.status` 必须进入 `failed`，并通过尾部 `system_status` 暴露 `context_overflow` 原因。
- 连续压缩失败必须按当前 run 的运行上限熔断，不得无限重试。

**测试方法**：
- `pytest backend/tests/context/test_context_size_guard.py -v`
- `pytest backend/tests/context/test_context_compression.py -v`

<a id="a49c"></a>

## A4.9c AgentDecision Schema 与解析器

**计划周期**：Week 8
**状态**：`[ ]`
**目标**：固定 Stage Agent 每轮模型调用的结构化决策协议和解析器，使工具请求、阶段产物提交、澄清请求、结构化修复、重试计划和阶段失败都通过可校验的 `AgentDecision` 表达。
**实施计划**：`docs/plans/implementation/a4.9c-agent-decision-parser.md`

**修改文件列表**：
- Create: `backend/app/runtime/agent_decision.py`
- Create: `backend/tests/runtime/test_agent_decision_parser.py`

**实现类/函数**：
- `AgentDecision`
- `AgentDecisionType`
- `ToolCallDecision`
- `SubmitStageArtifactDecision`
- `ClarificationDecision`
- `StructuredRepairDecision`
- `RetryWithRevisedPlanDecision`
- `FailStageDecision`
- `AgentDecisionParser`
- `AgentDecisionParser.parse_model_result()`
- `AgentDecisionParser.validate_against_stage_contract()`

**验收标准**：
- `AgentDecision.decision_type` 至少支持 `request_tool_call`、`submit_stage_artifact`、`request_clarification`、`repair_structured_output`、`retry_with_revised_plan` 和 `fail_stage`。
- 解析器必须消费 A4.9 `ModelCallResult` 的结构化输出候选和 tool call request 候选；不得用自由文本、正则、字符串命令解析或 JSON 猜测触发工具、推进状态、创建审批或交付动作。
- `request_tool_call` 只能引用当前 `ContextEnvelope.available_tools` 中存在的工具名称和 schema 版本；未知工具、未授权工具、schema 不匹配或重复无效 tool call 不得执行，必须形成结构化模型调用错误。
- `submit_stage_artifact` 必须按 R3.5 当前 `stage_contract` 的输出契约和 R3.7 `StageArtifact.output` 要求校验证据引用、失败/风险字段和必填结构化产物；缺失时只能进入结构化输出修复或阶段失败。
- `request_clarification` 只允许在当前阶段契约声明可澄清且缺失信息阻塞阶段输出时使用，并必须携带缺失事实、影响范围、关联引用和回答后需更新的结构化字段。
- `fail_stage` 必须携带失败原因、已执行证据引用、未完成事项和可展示错误摘要；不得只返回模型自由文本。
- 解析成功、解析失败、结构化输出修复请求、非法 tool call 和无效阶段产物提交必须写入 `decision_trace` 或 `model_call_trace` 过程记录引用。

**测试方法**：
- `pytest backend/tests/runtime/test_agent_decision_parser.py -v`

<a id="a49d"></a>

## A4.9d Stage Agent Runtime 执行循环

**计划周期**：Week 8
**状态**：`[ ]`
**目标**：实现正式阶段内执行循环，把 Context Management、Provider Adapter、AgentDecision、ToolRegistry、StageArtifact 和阶段恢复游标串成单阶段 runner，供 LangGraph stage node 调用。
**实施计划**：`docs/plans/implementation/a4.9d-stage-agent-runtime-loop.md`

**修改文件列表**：
- Create: `backend/app/runtime/stage_agent.py`
- Modify: `backend/app/runtime/stage_runner_port.py`
- Modify: `backend/app/runtime/nodes.py`
- Modify: `backend/app/services/artifacts.py`
- Create: `backend/tests/runtime/test_stage_agent_runtime.py`
- Create: `backend/tests/runtime/test_stage_agent_process_records.py`

**实现类/函数**：
- `StageAgentRuntime`
- `StageExecutionRequest`
- `StageExecutionResult`
- `StageRecoveryCursor`
- `StageAgentRuntime.run_stage()`
- `StageAgentRuntime.run_iteration()`
- `StageAgentRuntime.execute_tool_decision()`
- `StageAgentRuntime.submit_stage_artifact()`
- `StageAgentRuntime.persist_recovery_checkpoint()`

**验收标准**：
- `StageAgentRuntime` 必须实现 A4.5 `StageNodeRunnerPort`，由 LangGraph stage node 调用；阶段 runner 不得直接修改 `PipelineRun` 主链状态。
- 每次阶段执行、ReAct iteration、结构化输出修复、validation pass 或上下文压缩调用前，必须通过 A4.9a/A4.9b 生成 `ContextEnvelope` 和 `ContextManifest`。
- 模型调用必须通过 A4.9 `LangChainProviderAdapter`，并使用 A4.9c `AgentDecisionParser` 解析决策；自由文本不得作为运行时状态推进、工具执行、审批创建或交付动作依据。
- 工具执行必须经过 W5.0 `ToolRegistry`、当前 `stage_contract.allowed_tools`、输入 Schema、工作区边界、超时策略和审计策略校验；模型不得动态声明新工具或绕过工具注册表调用本地函数。
- 阶段结果必须写入 R3.7 `StageArtifact.input`、`StageArtifact.process`、`StageArtifact.output`、metrics 和稳定引用；下游阶段不得只依赖上一阶段摘要文本。
- `StageArtifact.process` 必须记录 `context_manifest`、`reasoning_trace`、`decision_trace`、`tool_trace`、`model_call_trace`、`file_edit_trace`、`command_trace`、`validation_trace`、`compressed_context_block`、`structured_output_repair_trace`、`recovery_checkpoint`、`side_effect_reconciliation_trace` 和 `untrusted_context_trace` 中本阶段实际发生的记录类型。
- `request_clarification` 决策必须转交 H4.1 澄清服务和 A4.0 runtime boundary；`submit_stage_artifact` 达到审批点时必须转交 H4.3 审批对象创建或 LangGraph 后续路由，不得由 Stage Agent Runtime 自建审批状态。
- `delivery_integration` 的确定性交付执行不得由模型自由文本决定真实 Git 写动作；真实交付工具仍由后续 D5.1-D5.4 通过 W5.0 ToolProtocol 实现。
- ReAct iteration、tool call 数、文件编辑次数、结构化输出修复次数、自动回归次数和无进展次数必须受当前 run `RuntimeLimitSnapshot` 约束，超限后进入结构化失败或 run failed 语义。
- 每次 iteration 完成后必须持久化 `StageRecoveryCursor`、最近 `ContextManifest`、工具结果引用、模型调用引用、文件编辑引用和 `recovery_checkpoint`；恢复时不得重新执行已确认成功且具有副作用的工具调用。
- 无法协调的工具副作用、文件写入、`bash` 命令或交付动作必须记录 `side_effect_reconciliation_trace`，并使当前 `StageRun.status` 与 `PipelineRun.status` 进入 `failed`。
- Stage Agent 执行开始、模型调用、工具调用、阶段产物提交、结构化修复、澄清请求、失败、恢复和副作用协调必须写入运行日志摘要并继承 `TraceContext`；审计记录仍由对应工具、命令或交付适配器负责。

**测试方法**：
- `pytest backend/tests/runtime/test_stage_agent_runtime.py -v`
- `pytest backend/tests/runtime/test_stage_agent_process_records.py -v`

<a id="a410"></a>

## A4.10 自动回归策略

**计划周期**：Week 8-9
**状态**：`[ ]`
**目标**：实现代码评审自动回归策略，使受控 retry 能按模板快照配置运行。
**实施计划**：`docs/plans/implementation/a4.10-auto-regression-policy.md`

**修改文件列表**：
- Create: `backend/app/runtime/auto_regression.py`
- Create: `backend/tests/runtime/test_auto_regression_policy.py`

**实现类/函数**：
- `AutoRegressionPolicy`
- `should_retry_review_issue()`
- `resolve_max_auto_regression_retries()`

**验收标准**：
- 自动回归配置来自模板快照。
- 最大重试次数同时受模板快照和当前 run 的 `RuntimeLimitSnapshot` 约束，并落在平台定义统一硬上限内。
- Code Review 相关自动回归统一回到 `code_generation`。
- 自动回归结束后才能进入 code review approval。
- 自动回归策略判定、跳过、进入重试和超限必须写入运行日志，并继承当前 run 的 `trace_id`。
- C2.8 后续热重载运行设置不得改变当前 run 的自动回归上限。

**测试方法**：
- `pytest backend/tests/runtime/test_auto_regression_policy.py -v`

<a id="a411"></a>

## A4.11 自动回归控制条目与超限失败

**计划周期**：Week 8-9
**状态**：`[ ]`
**目标**：实现自动回归过程记录、retry 控制条目和超限失败语义，使前端能解释为何回退和为何停止。
**实施计划**：`docs/plans/implementation/a4.11-auto-regression-control-items.md`

**修改文件列表**：
- Modify: `backend/app/runtime/auto_regression.py`
- Modify: `backend/app/services/control_records.py`
- Create: `backend/tests/runtime/test_auto_regression_control_items.py`

**实现类/函数**：
- `AutoRegressionRunner.run()`
- `AutoRegressionRunner.append_retry_control_item()`
- `AutoRegressionRunner.mark_retry_exhausted()`

**验收标准**：
- retry 控制条目进入事件流和投影。
- 本切片中的 `retry` 指当前 run 内自动回归或阶段内再次尝试，不表示 failed / terminated 后创建新 PipelineRun 的“重新尝试”。
- 控制条目包含 `retry_index` 与 `source_attempt_index`。
- 自动回归超限后输出明确失败或高风险状态，不静默推进。
- 自动回归结束且得到稳定评审产物后，创建 `code_review_approval`。
- 自动回归产生的 retry 控制条目仍由领域对象和事件驱动投影；运行日志只记录诊断摘要和关联标识。

**测试方法**：
- `pytest backend/tests/runtime/test_auto_regression_control_items.py -v`
