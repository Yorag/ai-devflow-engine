# 04 人工介入与执行内核

## 范围

本分卷覆盖 Week 6-9 的人工介入、运行控制、前端交互状态、deterministic runtime、demo_delivery、LangGraph runtime、Provider adapter 和自动回归。完成后，系统可以用 deterministic runtime 跑通 `demo_delivery` 全链路，并具备正式 LangGraph 编排路径。

本分卷承接 03 分卷的 Run 状态机和投影基础，负责运行中断、恢复、人工决策和执行内核副作用。每个任务只处理一个控制行为或 runtime 能力。

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

**验收标准**：
- 需求澄清只发生在 `requirement_analysis` 内部。
- 澄清创建 `ClarificationRecord` 与 `control_item(type=clarification_wait)`。
- 澄清不创建 ApprovalRequest。
- `clarification_reply` 只能在 `waiting_clarification` 且当前阶段为 `requirement_analysis` 时使用。
- 补充信息回写到同一个业务阶段上下文并恢复同一个 run。

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
- Create: `backend/app/api/routes/approvals.py`
- Create: `backend/tests/services/test_approval_creation.py`
- Create: `backend/tests/projections/test_approval_projection.py`

**实现类/函数**：
- `ApprovalService.create_solution_design_approval()`
- `ApprovalService.create_code_review_approval()`
- `ApprovalService.build_approval_request_projection()`

**验收标准**：
- 只创建 `solution_design_approval` 与 `code_review_approval`。
- 审批请求作为顶层 `approval_request` 插入 Narrative Feed。
- 创建审批请求后，源 StageRun 状态置为 `waiting_approval`。
- 审批等待期间，会话级 `latest_stage_type` 与 `current_stage_type` 保持源阶段类型不变。
- `approval_request` 包含 `is_actionable`、`disabled_reason`、`delivery_readiness_status` 和 `open_settings_action` 字段。

**测试方法**：
- `pytest backend/tests/services/test_approval_creation.py -v`
- `pytest backend/tests/projections/test_approval_projection.py -v`

<a id="h44"></a>

## H4.4 审批命令与交付就绪阻塞

**计划周期**：Week 6
**状态**：`[ ]`
**目标**：实现 Approve、Reject、拒绝理由、回退目标和 code review 交付就绪 gate。
**实施计划**：`docs/plans/implementation/h4.4-approval-commands-readiness-gate.md`

**修改文件列表**：
- Modify: `backend/app/services/approvals.py`
- Modify: `backend/app/api/routes/approvals.py`
- Create: `backend/tests/services/test_approval_commands.py`
- Create: `backend/tests/api/test_approval_api.py`

**实现类/函数**：
- `ApprovalService.approve()`
- `ApprovalService.reject()`
- `ApprovalService.assert_delivery_readiness_for_code_review()`
- `ApprovalService.resolve_reject_target_stage()`

**验收标准**：
- `Approve` 可直接提交。
- `Reject` 必须记录用户理由并进入后续上下文。
- `solution_design_approval` 的 Reject 固定回到 `solution_design`。
- `code_review_approval` 的 Reject 固定回到 `code_generation`。
- `git_auto_delivery` 未 ready 时阻塞 code review approve，并保持审批对象待处理。
- `demo_delivery` 不因远端配置缺失阻塞 approve。
- paused run 不接受审批提交，并返回明确错误信息。

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
- Create: `backend/app/services/control_records.py`
- Create: `backend/tests/services/test_pause_resume.py`
- Create: `backend/tests/api/test_pause_resume_api.py`

**实现类/函数**：
- `RunLifecycleService.pause_run()`
- `RunLifecycleService.resume_run()`
- `RunLifecycleService.save_resume_checkpoint()`
- `ControlRecordService.append_control_item()`

**验收标准**：
- pause 可发生在 `running`、`waiting_clarification`、`waiting_approval`。
- pause 调用成功后保存可恢复 checkpoint 与工作区快照引用。
- waiting_approval 下暂停后审批不可提交，投影 `is_actionable = false`。
- resume 继续同一 run，不创建新 run。
- 若 run 暂停前停留于审批等待，resume 后恢复到同一个 `waiting_approval` 检查点。

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
- Modify: `backend/app/services/control_records.py`
- Create: `backend/tests/services/test_terminate_run.py`
- Create: `backend/tests/api/test_terminate_run_api.py`

**实现类/函数**：
- `RunLifecycleService.terminate_run()`
- `ControlRecordService.append_system_status()`
- `RunLifecycleService.mark_terminal()`

**验收标准**：
- terminate 只终止当前活动 run，不删除历史。
- terminate 调用成功后终止当前 GraphThread 或 runtime 执行引用。
- terminated run 尾部出现顶层 `system_status` 终态条目。
- `system_status` 不属于 `control_item.control_type`。
- terminated run 中仍待处理的审批块退化为不可提交状态。

**测试方法**：
- `pytest backend/tests/services/test_terminate_run.py -v`
- `pytest backend/tests/api/test_terminate_run_api.py -v`

<a id="h47"></a>

## H4.7 Retry command 与多 run 分界

**计划周期**：Week 6
**状态**：`[ ]`
**目标**：补齐重新尝试命令的控制记录、事件和多 run 分界语义，使 failed / terminated 后的新 run 能被前端定位。
**实施计划**：`docs/plans/implementation/h4.7-retry-command-run-boundary.md`

**修改文件列表**：
- Modify: `backend/app/services/runs.py`
- Modify: `backend/app/services/control_records.py`
- Create: `backend/tests/services/test_retry_command_projection.py`
- Create: `backend/tests/api/test_retry_command_api.py`

**实现类/函数**：
- `RunLifecycleService.create_retry_run()`
- `ControlRecordService.append_retry_control_item()`
- `RunLifecycleService.build_retry_trigger_metadata()`

**验收标准**：
- failed / terminated 当前 run 尾部允许重新尝试。
- 重新尝试创建新的 PipelineRun，并在同一 Session 下形成新 run 分段。
- retry 控制条目进入事件流和投影。
- 新 run 的 `trigger_source` 与 attempt index 可回放。
- 重新尝试不继承旧 run 未交付的工作区改动。

**测试方法**：
- `pytest backend/tests/services/test_retry_command_projection.py -v`
- `pytest backend/tests/api/test_retry_command_api.py -v`

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

**测试方法**：
- `npm --prefix frontend run test -- ApprovalBlock`

<a id="f44"></a>

## F4.4 Retry UI 与历史审批禁用态

**计划周期**：Week 6
**状态**：`[ ]`
**目标**：实现失败或终止后的重新尝试入口，并完善历史 run 审批块只读态。
**实施计划**：`docs/plans/implementation/f4.4-retry-ui-historical-approval.md`

**修改文件列表**：
- Create: `frontend/src/features/runs/RetryRunAction.tsx`
- Create: `frontend/src/features/runs/__tests__/RetryRunAction.test.tsx`
- Modify: `frontend/src/features/approvals/ApprovalBlock.tsx`

**实现类/函数**：
- `RetryRunAction`
- `resolveRetryActionState()`
- `resolveHistoricalApprovalState()`

**验收标准**：
- failed / terminated 当前 run 尾部展示重新尝试动作。
- 重新尝试触发前明确提示新 run 从 Requirement Analysis 重新开始，且不继承旧 run 未交付工作区改动。
- 历史 run 的审批块为只读历史态，不提供可点击 Approve / Reject。
- 当前活动 run 已 terminated 时，原待处理审批块退化为不可提交状态。

**测试方法**：
- `npm --prefix frontend run test -- RetryRunAction`

<a id="a41"></a>

## A4.1 RuntimeEngine 接口

**计划周期**：Week 7
**状态**：`[ ]`
**目标**：定义 deterministic runtime 与 LangGraph runtime 的共同接口，使运行生命周期服务不依赖具体执行内核。
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
- deterministic 与 LangGraph runtime 可共享同一生命周期服务调用边界。
- deterministic runtime 只作为稳定测试、前端联调和可重复端到端验收路径；正式 Agent 编排路径由 LangGraph runtime 承担。
- `RuntimeEngine` 接口不得要求调用方识别 deterministic 或 LangGraph 的内部状态结构。

**测试方法**：
- `pytest backend/tests/runtime/test_runtime_engine_contract.py -v`

<a id="a42"></a>

## A4.2 deterministic 六阶段推进

**计划周期**：Week 7
**状态**：`[ ]`
**目标**：实现稳定可控的 deterministic runtime 六阶段推进，使端到端测试和前端联调不依赖真实模型输出。
**实施计划**：`docs/plans/implementation/a4.2-deterministic-six-stage-runtime.md`

**修改文件列表**：
- Create: `backend/app/runtime/deterministic.py`
- Create: `backend/tests/runtime/test_deterministic_runtime.py`

**实现类/函数**：
- `DeterministicRuntimeEngine`
- `DeterministicRuntimeEngine.run_next()`
- `DeterministicRuntimeEngine.emit_stage_artifacts()`

**验收标准**：
- deterministic runtime 可稳定推进六个业务阶段。
- 每个阶段写入 StageRun、StageArtifact 和领域事件。
- Solution Validation 作为 `solution_design` 内部过程记录出现，不形成独立阶段。
- 前端端到端测试可使用固定输出。

**测试方法**：
- `pytest backend/tests/runtime/test_deterministic_runtime.py -v`

<a id="a43"></a>

## A4.3 deterministic 澄清与审批中断

**计划周期**：Week 7
**状态**：`[ ]`
**目标**：为 deterministic runtime 增加可配置澄清、方案审批和代码评审审批中断路径。
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
- 中断恢复继续同一个 run 和同一个源阶段。
- 审批拒绝按规格回到目标阶段。

**测试方法**：
- `pytest backend/tests/runtime/test_deterministic_interrupts.py -v`

<a id="a44"></a>

## A4.4 deterministic 终态控制

**计划周期**：Week 7
**状态**：`[ ]`
**目标**：为 deterministic runtime 增加失败和终止路径，使端到端测试能覆盖 run 终态和重新尝试前置条件。
**实施计划**：`docs/plans/implementation/a4.4-deterministic-terminal-control.md`

**修改文件列表**：
- Modify: `backend/app/runtime/deterministic.py`
- Create: `backend/tests/runtime/test_deterministic_terminal_states.py`

**实现类/函数**：
- `DeterministicRuntimeEngine.emit_terminal_result()`
- `DeterministicRuntimeEngine.fail_run()`
- `DeterministicRuntimeEngine.terminate_run()`

**验收标准**：
- deterministic runtime 可配置成功、失败和终止路径。
- failed / terminated run 尾部生成正确终态来源记录。
- 终态记录可支持后续 retry run 创建。
- 本切片不生成 DeliveryRecord，正式 `demo_delivery` 由 D4.2 负责。

**测试方法**：
- `pytest backend/tests/runtime/test_deterministic_terminal_states.py -v`

<a id="d41"></a>

## D4.1 Delivery base、snapshot 与 DeliveryRecord

**计划周期**：Week 7
**状态**：`[ ]`
**目标**：建立交付适配器基类、交付通道快照和 DeliveryRecord 服务，使 deterministic runtime 能进入正式 demo_delivery 出口。
**实施计划**：`docs/plans/implementation/d4.1-delivery-base-record.md`

**修改文件列表**：
- Create: `backend/app/delivery/base.py`
- Create: `backend/app/services/delivery.py`
- Create: `backend/tests/delivery/test_delivery_record_service.py`

**实现类/函数**：
- `DeliveryAdapter`
- `DeliveryService.prepare_delivery_snapshot()`
- `DeliveryRecordService.create_record()`
- `DeliveryRecordService.get_record()`

**验收标准**：
- DeliveryRecord 统一文本需求驱动与未来页面交互驱动的交付出口。
- DeliveryRecord 关联需求、方案、代码、测试、评审和交付产物。
- 交付通道快照在最终人工审批通过后、进入 Delivery Integration 前固化。
- 后续项目级 DeliveryChannel 修改不得影响已固化 run。

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
- deterministic runtime 可跑通六阶段到 `demo_delivery` 的完整成功链路。

**测试方法**：
- `pytest backend/tests/delivery/test_demo_delivery.py -v`
- `pytest backend/tests/e2e/test_deterministic_run_flow.py -v`

<a id="a45"></a>

## A4.5 LangGraph 主链与 checkpoint

**计划周期**：Week 8
**状态**：`[ ]`
**目标**：接入 LangGraph 主链和 checkpoint，使正式执行路径具备固定业务阶段编排能力。
**实施计划**：`docs/plans/implementation/a4.5-langgraph-main-chain-checkpoint.md`

**修改文件列表**：
- Create: `backend/app/runtime/langgraph_engine.py`
- Create: `backend/app/runtime/nodes.py`
- Create: `backend/app/runtime/checkpoints.py`
- Create: `backend/tests/runtime/test_langgraph_engine.py`

**实现类/函数**：
- `LangGraphRuntimeEngine`
- `build_stage_graph()`
- `run_stage_node()`
- `save_graph_checkpoint()`

**验收标准**：
- LangGraph 表达固定主链、阶段节点、条件边和 checkpoint。
- GraphDefinition 的六阶段映射进入 LangGraph 构建过程。
- 每次业务阶段切换前后具备可恢复 checkpoint。
- raw graph state 不进入前端投影。
- `GraphDefinition` 映射为 LangGraph `StateGraph` 构建输入，运行时编译为 compiled graph。
- `GraphThread.graph_thread_id` 映射为 LangGraph configurable `thread_id`。
- 条件路由使用 LangGraph conditional edges 表达，不在 `RunLifecycleService` 中另写一套阶段分支状态机。
- checkpoint 通过 LangGraph checkpointer 保存，并同步写入 `GraphCheckpoint.checkpoint_ref`。
- 测试断言 checkpoint 可用于同一 `GraphThread` 恢复，而不是只验证业务状态字段变化。

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
- `clarification_reply`、`approval approve/reject` 不得绕过 `GraphInterrupt` 直接推进阶段状态。
- pause 后 resume 不创建新的 `GraphThread`，也不创建新的 `PipelineRun`。

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

**测试方法**：
- `pytest backend/tests/runtime/test_langgraph_event_translation.py -v`

<a id="a48"></a>

## A4.8 Provider Registry

**计划周期**：Week 8
**状态**：`[ ]`
**目标**：实现 Provider registry，使运行时能从模板快照解析内置 Provider 与 custom Provider。
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

**验收标准**：
- 内置 Provider 与 custom Provider 走统一解析路径。
- 运行时读取模板快照中的 Provider 绑定。
- Provider 绑定单位是 AgentRole。
- Provider 配置不直接泄漏密钥内容到前端。

**测试方法**：
- `pytest backend/tests/providers/test_provider_registry.py -v`

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
- `LangChainProviderAdapter.create_chat_model()`
- `LangChainProviderAdapter.bind_tools()`
- `LangChainProviderAdapter.with_structured_output()`

**验收标准**：
- LangChain 封装模型供应商、消息对象、结构化输出与内部工具绑定。
- custom Provider 使用 `OpenAI Completions compatible` 接入协议。
- 测试使用 fake model，不调用真实远端模型。
- LangChain adapter 只创建 chat model、绑定工具、声明结构化输出，不表达业务阶段流转。
- 工具绑定对象来自统一 Workspace / Delivery Tool 协议，不直接绑定零散业务函数。
- 结构化输出失败必须返回可处理错误，不得直接推进 LangGraph 节点成功完成。

**测试方法**：
- `pytest backend/tests/providers/test_langchain_adapter.py -v`

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
- 最大重试次数受控，并落在平台定义统一上限内。
- Code Review 相关自动回归统一回到 `code_generation`。
- 自动回归结束后才能进入 code review approval。

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
- 控制条目包含 `retry_index` 与 `source_attempt_index`。
- 自动回归超限后输出明确失败或高风险状态，不静默推进。
- 自动回归结束且得到稳定评审产物后，创建 `code_review_approval`。

**测试方法**：
- `pytest backend/tests/runtime/test_auto_regression_control_items.py -v`
