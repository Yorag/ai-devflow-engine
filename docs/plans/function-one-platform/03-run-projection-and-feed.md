# 03 Run 主链、投影与叙事流

## 范围

本分卷覆盖 Week 4-6 的 Run 生命周期、GraphDefinition、产物存储、查询投影、SSE 和前端 Narrative Feed。完成后，系统具备可回放的 run 主链、可消费的 workspace 快照、可增量更新的前端状态和可深看的 Inspector。

本分卷只处理 Run 主链的骨架与投影，不实现人工介入命令副作用和 runtime 执行内核。暂停、恢复、终止和审批恢复的副作用放在 04 分卷。

<a id="r31"></a>

## R3.1 Run 状态机纯领域规则

**计划周期**：Week 4
**状态**：`[ ]`
**目标**：实现 PipelineRun 与 Session 的纯状态转移规则，为后续 API 命令提供可测试的领域基础。
**实施计划**：`docs/plans/implementation/r3.1-run-state-machine.md`

**修改文件列表**：
- Create: `backend/app/domain/state_machine.py`
- Create: `backend/tests/domain/test_run_state_machine.py`

**实现类/函数**：
- `RunStateMachine.transition()`
- `RunStateMachine.assert_can_start_first_run()`
- `RunStateMachine.assert_can_create_retry_run()`
- `RunStateMachine.project_session_status()`

**验收标准**：
- 首条 `new_requirement` 只能在 draft Session 且 `current_run_id = null` 时创建首个 run。
- `clarification_reply` 只能在 `waiting_clarification` 使用。
- `completed` Session 不允许创建新 run。
- `failed` / `terminated` 当前 run 尾部允许创建新 run。
- pause / resume 不创建新 run。
- 本切片不实现 API 命令副作用。

**测试方法**：
- `pytest backend/tests/domain/test_run_state_machine.py -v`

<a id="r32"></a>

## R3.2 首条需求启动首个 run

**计划周期**：Week 4
**状态**：`[ ]`
**目标**：实现 `POST /api/sessions/{sessionId}/messages` 中 `new_requirement` 语义，自动创建首个 PipelineRun 并进入 `requirement_analysis`。
**实施计划**：`docs/plans/implementation/r3.2-start-first-run.md`

**修改文件列表**：
- Create: `backend/app/services/runs.py`
- Modify: `backend/app/services/sessions.py`
- Modify: `backend/app/api/routes/sessions.py`
- Create: `backend/tests/services/test_start_first_run.py`
- Create: `backend/tests/api/test_session_message_api.py`

**实现类/函数**：
- `RunLifecycleService.start_first_run()`
- `SessionService.append_message()`
- `SessionService.start_run_from_new_requirement()`

**验收标准**：
- `new_requirement` 创建 `PipelineRun`、回写 `Session.current_run_id`，并将 Session 投影为 `running`。
- 新 run 的 `current_stage_type = requirement_analysis`。
- 首条用户消息作为顶层 `user_message` 进入后续投影来源。
- 非 draft Session 调用 `new_requirement` 被拒绝。

**测试方法**：
- `pytest backend/tests/services/test_start_first_run.py -v`
- `pytest backend/tests/api/test_session_message_api.py -v`

<a id="r33"></a>

## R3.3 retry run 创建规则

**计划周期**：Week 4
**状态**：`[ ]`
**目标**：实现显式重新尝试命令的基础创建规则，使 failed / terminated run 可在同一 Session 下生成新 PipelineRun。
**实施计划**：`docs/plans/implementation/r3.3-retry-run-creation.md`

**修改文件列表**：
- Modify: `backend/app/services/runs.py`
- Create: `backend/app/api/routes/runs.py`
- Create: `backend/tests/services/test_retry_run_creation.py`
- Create: `backend/tests/api/test_retry_run_api.py`

**实现类/函数**：
- `RunLifecycleService.create_retry_run()`
- `RunLifecycleService.assert_single_active_run()`
- `register_run_routes(router: APIRouter) -> None`

**验收标准**：
- `POST /api/sessions/{sessionId}/runs` 对应显式重新尝试，不对应暂停后的继续执行。
- 只有前一个活动 run 处于 `failed` 或 `terminated` 后允许创建新 run。
- `completed` 表示会话链路已完成，不允许同一 Session 创建新 run。
- 新 run 从 `requirement_analysis` 重新开始。
- 新 run 不继承旧 run 未交付的工作区改动引用。

**测试方法**：
- `pytest backend/tests/services/test_retry_run_creation.py -v`
- `pytest backend/tests/api/test_retry_run_api.py -v`

<a id="r34"></a>

## R3.4 模板快照固化

**计划周期**：Week 4
**状态**：`[ ]`
**目标**：在 run 启动前固化模板快照，使后续角色绑定、Provider 绑定和自动回归配置不受模板后续修改影响。
**实施计划**：`docs/plans/implementation/r3.4-template-snapshot.md`

**修改文件列表**：
- Create: `backend/app/domain/template_snapshot.py`
- Modify: `backend/app/services/runs.py`
- Create: `backend/tests/services/test_template_snapshot.py`

**实现类/函数**：
- `TemplateSnapshot`
- `TemplateSnapshotBuilder.build_for_run()`
- `RunLifecycleService.attach_template_snapshot()`

**验收标准**：
- 每次 run 启动前固化模板快照。
- 快照包含固定阶段序列、角色槽位、`system_prompt`、Provider 绑定、自动回归开关和最大重试次数。
- 后续模板修改不得回写影响已启动 run。
- 快照不包含项目级 DeliveryChannel 配置。

**测试方法**：
- `pytest backend/tests/services/test_template_snapshot.py -v`

<a id="r35"></a>

## R3.5 GraphDefinition 固定主链编译

**计划周期**：Week 4
**状态**：`[ ]`
**目标**：把模板快照编译为固定六阶段 GraphDefinition，固化审批中断点、内部节点组和运行期配置来源。
**实施计划**：`docs/plans/implementation/r3.5-graph-definition-compiler.md`

**修改文件列表**：
- Create: `backend/app/services/graph_compiler.py`
- Create: `backend/app/domain/graph_definition.py`
- Create: `backend/tests/services/test_graph_compiler.py`

**实现类/函数**：
- `GraphDefinition`
- `GraphCompiler.compile(template_snapshot: TemplateSnapshot) -> GraphDefinition`
- `build_fixed_stage_sequence()`
- `build_interrupt_policy()`
- `build_solution_design_node_group()`

**验收标准**：
- GraphDefinition 包含六个正式业务阶段。
- `solution_design_approval` 与 `code_review_approval` 审批中断点固定存在。
- `Solution Validation` 是 `solution_design` 阶段内部第二个执行节点组，不形成独立 `StageRun`。
- `Solution Validation` 校验失败时回到 `solution_design` 阶段内部设计节点，不创建新阶段。
- 图编译结果记录稳定的 `source_node_group` 到 `stage_type` 映射关系。
- GraphDefinition 必须包含后续 StateGraph 构建所需的稳定节点 key、阶段节点组、条件路由标识和中断点标识。
- GraphDefinition 不保存 LangGraph compiled graph 实例，只保存可持久化、可重建的领域图定义。
- `source_node_group -> stage_type` 映射必须支持后续 LangGraph node event 到 `StageRun` / `StageArtifact` 的转换。

**测试方法**：
- `pytest backend/tests/services/test_graph_compiler.py -v`

<a id="r36"></a>

## R3.6 StageRun 持久化

**计划周期**：Week 4-5
**状态**：`[ ]`
**目标**：建立 StageRun 创建、状态推进和阶段类型记录，使六个正式业务阶段可被查询和回放。
**实施计划**：`docs/plans/implementation/r3.6-stage-run-store.md`

**修改文件列表**：
- Create: `backend/app/repositories/runtime.py`
- Create: `backend/app/services/stages.py`
- Create: `backend/tests/services/test_stage_run_store.py`

**实现类/函数**：
- `StageRunService.start_stage()`
- `StageRunService.mark_stage_waiting()`
- `StageRunService.complete_stage()`
- `StageRunRepository`

**验收标准**：
- StageRun 的 `stage_type` 只允许六个正式业务阶段。
- 审批等待或澄清等待时，`current_stage_type` 保持源阶段不变。
- `solution_design_approval` 和 `code_review_approval` 不创建独立 StageRun。
- StageRun 记录开始时间、结束时间、状态和 attempt index。

**测试方法**：
- `pytest backend/tests/services/test_stage_run_store.py -v`

<a id="r37"></a>

## R3.7 StageArtifact 存储

**计划周期**：Week 4-5
**状态**：`[ ]`
**目标**：建立 StageArtifact 存储，使阶段输入、过程、输出、附件和指标能够被后续阶段与 Inspector 稳定引用。
**实施计划**：`docs/plans/implementation/r3.7-stage-artifact-store.md`

**修改文件列表**：
- Create: `backend/app/services/artifacts.py`
- Create: `backend/tests/services/test_artifact_store.py`

**实现类/函数**：
- `ArtifactStore.create_stage_input()`
- `ArtifactStore.append_process_record()`
- `ArtifactStore.complete_stage_output()`
- `ArtifactStore.attach_metric_set()`
- `ArtifactStore.get_stage_artifact()`

**验收标准**：
- StageArtifact 能承载 input、process、output、artifacts、metrics。
- StageRun 的输入输出通过稳定引用读取。
- Inspector 不需要从 LangGraph 原始状态回填关键事实。
- 结构化产物索引留在 runtime 职责边界内。

**测试方法**：
- `pytest backend/tests/services/test_artifact_store.py -v`

<a id="q31"></a>

## Q3.1 SessionWorkspaceProjection

**计划周期**：Week 5
**状态**：`[ ]`
**目标**：实现会话工作台查询投影，使前端可一次加载会话状态、项目摘要、多 run 分段、Narrative Feed 和 Composer 状态。
**实施计划**：`docs/plans/implementation/q3.1-session-workspace-projection.md`

**修改文件列表**：
- Create: `backend/app/services/projections/workspace.py`
- Create: `backend/app/api/routes/query.py`
- Create: `backend/tests/projections/test_workspace_projection.py`

**实现类/函数**：
- `WorkspaceProjectionService.get_session_workspace()`
- `WorkspaceProjectionService.build_composer_state()`
- `WorkspaceProjectionService.build_run_summaries()`

**验收标准**：
- workspace projection 包含项目摘要、会话状态、项目级交付配置摘要、run summaries、narrative feed、composer state。
- 同一 Session 下的多个 run 按启动时间顺序返回。
- `composer_state.bound_run_id` 始终指向当前活动 run。
- 投影不暴露 raw graph state。

**测试方法**：
- `pytest backend/tests/projections/test_workspace_projection.py -v`

<a id="q32"></a>

## Q3.2 RunTimelineProjection

**计划周期**：Week 5
**状态**：`[ ]`
**目标**：实现单 run 时间线投影，使历史 run 能独立回放且条目语义与 workspace projection 保持一致。
**实施计划**：`docs/plans/implementation/q3.2-run-timeline-projection.md`

**修改文件列表**：
- Create: `backend/app/services/projections/timeline.py`
- Modify: `backend/app/api/routes/query.py`
- Create: `backend/tests/projections/test_timeline_projection.py`

**实现类/函数**：
- `TimelineProjectionService.get_run_timeline()`
- `TimelineProjectionService.build_timeline_entries()`

**验收标准**：
- `GET /api/runs/{runId}/timeline` 只返回目标 run 条目。
- `entries` 按发生时间顺序返回该 run 的全部顶层 Narrative Feed 条目。
- `entries[].type` 只允许正式顶层条目枚举。
- 条目语义与 `SessionWorkspaceProjection.narrative_feed` 保持一致。

**测试方法**：
- `pytest backend/tests/projections/test_timeline_projection.py -v`

<a id="q33"></a>

## Q3.3 StageInspectorProjection

**计划周期**：Week 5
**状态**：`[ ]`
**目标**：实现阶段 Inspector 查询投影，使前端可深看阶段输入、过程、输出、引用和量化信息。
**实施计划**：`docs/plans/implementation/q3.3-stage-inspector-projection.md`

**修改文件列表**：
- Create: `backend/app/services/projections/inspector.py`
- Modify: `backend/app/api/routes/query.py`
- Create: `backend/tests/projections/test_stage_inspector_projection.py`

**实现类/函数**：
- `InspectorProjectionService.get_stage_inspector()`
- `InspectorProjectionService.build_stage_identity()`
- `InspectorProjectionService.build_metric_section()`

**验收标准**：
- `GET /api/stages/{stageRunId}/inspector` 返回按 `identity/input/process/output/artifacts/metrics` 分组的完整阶段 Inspector 投影。
- 投影内容来自领域对象、StageArtifact 和稳定引用，不由前端回填关键事实。
- `approval_result` 关联信息可通过所属阶段 Inspector 读取。
- 投影不暴露 raw graph state。

**测试方法**：
- `pytest backend/tests/projections/test_stage_inspector_projection.py -v`

<a id="q34"></a>

## Q3.4 ControlItem 与 Delivery detail 投影

**计划周期**：Week 5
**状态**：`[ ]`
**目标**：实现控制型条目和交付结果详情投影，使回退、重试、澄清等待和交付结果可以被右栏深看。
**实施计划**：`docs/plans/implementation/q3.4-control-delivery-detail-projections.md`

**修改文件列表**：
- Modify: `backend/app/services/projections/inspector.py`
- Modify: `backend/app/api/routes/query.py`
- Create: `backend/tests/projections/test_control_delivery_detail_projection.py`

**实现类/函数**：
- `InspectorProjectionService.get_control_item_detail()`
- `InspectorProjectionService.get_delivery_record_detail()`
- `InspectorProjectionService.build_control_item_sections()`
- `InspectorProjectionService.build_delivery_result_sections()`

**验收标准**：
- `GET /api/control-records/{controlRecordId}` 返回完整控制条目详情，不退化为摘要文本。
- `GET /api/delivery-records/{deliveryRecordId}` 返回完整交付结果详情。
- `system_status` 终态条目不作为 `control_item.control_type` 持久化。
- `delivery_result` 详情包含交付模式、变更结果、测试结论、评审结论、产物与量化信息。

**测试方法**：
- `pytest backend/tests/projections/test_control_delivery_detail_projection.py -v`

<a id="e31"></a>

## E3.1 领域事件 Schema 与 EventStore

**计划周期**：Week 5
**状态**：`[ ]`
**目标**：建立领域事件日志，使查询投影和实时增量使用同一事件来源。
**实施计划**：`docs/plans/implementation/e3.1-domain-event-store.md`

**修改文件列表**：
- Create: `backend/app/services/events.py`
- Create: `backend/tests/events/test_event_store.py`

**实现类/函数**：
- `DomainEvent`
- `EventStore.append()`
- `EventStore.list_after()`
- `EventStore.list_for_session()`

**验收标准**：
- 事件记录包含 `event_id`、`session_id`、`run_id`、`event_type`、`occurred_at`、`payload`。
- 事件类型与正式规格一致。
- 审批结果与澄清结果进入同一条会话事件流。
- 原始 LangGraph 事件不直接作为对外领域事件暴露。

**测试方法**：
- `pytest backend/tests/events/test_event_store.py -v`

<a id="e32"></a>

## E3.2 SSE 流端点与断线恢复

**计划周期**：Week 5
**状态**：`[ ]`
**目标**：建立会话级 SSE 流，使前端可用 workspace 快照加增量事件维持 Narrative Feed 一致状态。
**实施计划**：`docs/plans/implementation/e3.2-sse-stream-reconnect.md`

**修改文件列表**：
- Create: `backend/app/api/routes/events.py`
- Modify: `backend/app/services/events.py`
- Create: `backend/tests/api/test_sse_stream.py`

**实现类/函数**：
- `SseEventEncoder.encode()`
- `stream_session_events()`
- `register_event_routes(router: APIRouter) -> None`

**验收标准**：
- `GET /api/sessions/{sessionId}/events/stream` 提供会话级 SSE。
- payload 中的 feed 条目语义与查询投影一致。
- 断线后可通过 workspace 快照 + `EventStore.list_after()` 重建一致状态。
- SSE 只传递增量，不定义第二套产品语义。

**测试方法**：
- `pytest backend/tests/api/test_sse_stream.py -v`

<a id="f31"></a>

## F3.1 Workspace Store 快照初始化

**计划周期**：Week 5
**状态**：`[ ]`
**目标**：实现前端 workspace store，使页面状态由 `SessionWorkspaceProjection` 快照初始化。
**实施计划**：`docs/plans/implementation/f3.1-workspace-store-snapshot.md`

**修改文件列表**：
- Create: `frontend/src/features/workspace/workspace-store.ts`
- Create: `frontend/src/features/workspace/__tests__/workspace-store.test.ts`

**实现类/函数**：
- `useWorkspaceStore`
- `initializeWorkspaceFromSnapshot()`
- `selectCurrentRun()`
- `selectComposerState()`

**验收标准**：
- 前端状态由 workspace 快照初始化。
- 当前 run 焦点、Inspector 开关和 Composer 状态属于 Zustand store 管理。
- 初始化不直接修改 UI 组件局部状态。

**测试方法**：
- `npm --prefix frontend run test -- workspace-store`

<a id="f32"></a>

## F3.2 SSE Client 与 Event Reducer

**计划周期**：Week 5
**状态**：`[ ]`
**目标**：实现 EventSource 薄封装和事件 reducer，使 SSE 增量通过统一状态模型合并。
**实施计划**：`docs/plans/implementation/f3.2-sse-client-event-reducer.md`

**修改文件列表**：
- Create: `frontend/src/features/workspace/sse-client.ts`
- Create: `frontend/src/features/workspace/event-reducer.ts`
- Create: `frontend/src/features/workspace/__tests__/event-reducer.test.ts`

**实现类/函数**：
- `createSessionEventSource()`
- `applySessionEvent()`
- `mergeStageNodeUpdate()`
- `updateComposerStateFromSessionStatus()`

**验收标准**：
- SSE 增量可追加 Narrative Feed、更新阶段、更新审批块、更新会话状态。
- `session_status_changed` 更新当前 Composer 状态。
- 前端不绕过状态模型直接改 UI。
- 重复事件不会造成重复条目。

**测试方法**：
- `npm --prefix frontend run test -- event-reducer`

<a id="f33"></a>

## F3.3 Feed Entry Renderer

**计划周期**：Week 5-6
**状态**：`[ ]`
**目标**：实现 Narrative Feed 顶层条目分发渲染，使不同条目类型具备独立展示语义。
**实施计划**：`docs/plans/implementation/f3.3-feed-entry-renderer.md`

**修改文件列表**：
- Create: `frontend/src/features/feed/NarrativeFeed.tsx`
- Create: `frontend/src/features/feed/FeedEntryRenderer.tsx`
- Create: `frontend/src/features/feed/__tests__/FeedEntryRenderer.test.tsx`

**实现类/函数**：
- `NarrativeFeed`
- `FeedEntryRenderer`
- `renderFeedEntryByType()`

**验收标准**：
- `user_message`、`stage_node`、`approval_request`、`control_item`、`approval_result`、`delivery_result`、`system_status` 使用不同展示语义。
- `system_status` 只作为顶层条目渲染。
- `completed` run 以 `delivery_result` 收束，不追加完成态 `system_status`。

**测试方法**：
- `npm --prefix frontend run test -- FeedEntryRenderer`

<a id="f34"></a>

## F3.4 StageNode 与阶段内部条目

**计划周期**：Week 5-6
**状态**：`[ ]`
**目标**：实现阶段结点大框和阶段内部条目展示，使 Requirement Analysis 澄清对话和正式研发阶段内容在同一主流中连续阅读。
**实施计划**：`docs/plans/implementation/f3.4-stage-node-items.md`

**修改文件列表**：
- Create: `frontend/src/features/feed/StageNode.tsx`
- Create: `frontend/src/features/feed/StageNodeItems.tsx`
- Create: `frontend/src/features/feed/__tests__/StageNode.test.tsx`

**实现类/函数**：
- `StageNode`
- `StageNodeItems`
- `renderStageItemByType()`

**验收标准**：
- 每个正式业务阶段以阶段结点大框展示。
- 阶段内部条目至少支持 `dialogue`、`reasoning`、`decision`、`tool_call`、`diff_preview`、`result`。
- Requirement Analysis 阶段内澄清问答显示为阶段内部连续对话内容。
- 阶段结点正文展示高信号指标，完整信息留给 Inspector。

**测试方法**：
- `npm --prefix frontend run test -- StageNode`

<a id="f35"></a>

## F3.5 Run Boundary 与 Run Switcher

**计划周期**：Week 5-6
**状态**：`[ ]`
**目标**：实现同一 Session 多 run 的视觉分界和页面内定位控件，使 Run Switcher 只承担导航职责。
**实施计划**：`docs/plans/implementation/f3.5-run-boundary-switcher.md`

**修改文件列表**：
- Create: `frontend/src/features/feed/RunBoundary.tsx`
- Create: `frontend/src/features/feed/RunSwitcher.tsx`
- Create: `frontend/src/features/feed/__tests__/RunSwitcher.test.tsx`

**实现类/函数**：
- `RunBoundary`
- `RunSwitcher`
- `groupEntriesByRun()`
- `scrollToRunBoundary()`

**验收标准**：
- 同一 Session 的多个 run 在同一主流中按时间展示。
- run 分界强可见，并与 Run Switcher 列表一一对应。
- Run Switcher 只做页面内定位，不创建会话、不重新运行、不编辑模板。
- 历史 run 的分界头部只承担信息展示与导航定位。

**测试方法**：
- `npm --prefix frontend run test -- RunSwitcher`

<a id="f36"></a>

## F3.6 Inspector Shell 与打开状态

**计划周期**：Week 5-6
**状态**：`[ ]`
**目标**：实现右侧 Inspector 容器、打开关闭状态和查询入口，使阶段、控制条目和交付结果可打开深看。
**实施计划**：`docs/plans/implementation/f3.6-inspector-shell.md`

**修改文件列表**：
- Create: `frontend/src/features/inspector/InspectorPanel.tsx`
- Create: `frontend/src/features/inspector/useInspector.ts`
- Create: `frontend/src/features/inspector/__tests__/InspectorPanel.test.tsx`

**实现类/函数**：
- `InspectorPanel`
- `useInspector()`
- `openInspectorTarget()`
- `closeInspector()`

**验收标准**：
- 点击阶段结点、控制条目或交付结果可打开 Inspector。
- 右栏默认关闭。
- Inspector 不承担审批主操作。
- `approval_result` 不作为独立右栏打开对象。

**测试方法**：
- `npm --prefix frontend run test -- InspectorPanel`

<a id="f37"></a>

## F3.7 Inspector 分组与 Metrics 展示

**计划周期**：Week 5-6
**状态**：`[ ]`
**目标**：实现 Inspector 内容分组、量化指标展示和不适用指标隐藏，使右栏深看符合原始信息展示边界。
**实施计划**：`docs/plans/implementation/f3.7-inspector-sections-metrics.md`

**修改文件列表**：
- Create: `frontend/src/features/inspector/InspectorSections.tsx`
- Create: `frontend/src/features/inspector/MetricGrid.tsx`
- Create: `frontend/src/features/inspector/__tests__/InspectorSections.test.tsx`

**实现类/函数**：
- `InspectorSections`
- `MetricGrid`
- `hideInapplicableMetrics()`

**验收标准**：
- Inspector 信息按 `input/process/output/artifacts/metrics` 展示。
- Inspector 中的信息量大于中栏结点正文。
- 不适用指标隐藏，不使用空模板占位。
- 前端只做呈现层分组、折叠、排序和语法高亮，不改写语义。

**测试方法**：
- `npm --prefix frontend run test -- InspectorSections`
