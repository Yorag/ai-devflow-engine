# 03 Run 主链、投影与叙事流

## 范围

本分卷覆盖 Week 4-6 的 Run 生命周期、运行快照、GraphDefinition、产物存储、查询投影、SSE 和前端 Narrative Feed。完成后，系统具备可回放的 run 主链、已固化的模板/Provider/模型绑定/运行上限快照、可消费的 workspace 快照、可增量更新的前端状态和可深看的 Inspector。

本分卷只处理 Run 主链的骨架、运行快照、事件来源与投影，不实现人工介入命令副作用和 runtime 执行内核。首个 run 启动必须在同一服务事务中创建 PipelineRun、模板快照、Provider 与模型绑定快照、运行上限快照、GraphDefinition、首条消息事件和初始 StageRun；暂停、恢复、终止和审批恢复的副作用放在 04 分卷。
查询投影必须基于 EventStore、领域对象、StageArtifact 和稳定引用组装，不允许先从业务表临时拼出一套独立 Narrative Feed 语义。
凡本分卷修改 `backend/app/api/routes/*` 的 API 或 SSE 切片，对应 API 测试必须在本切片内断言新增或修改的 path、method、请求 Schema、响应 Schema、SSE 事件说明和主要错误响应已进入 `/api/openapi.json`；V6.4 只做全局覆盖回归。

Run 主链必须嵌入日志审计关联语义。首个 run 启动时必须生成贯穿该 run 的 `trace_id`；同一用户动作触发的领域事件、运行日志、审计记录、SSE 增量和查询投影更新必须共享 `correlation_id`。日志审计记录不得替代 EventStore、Narrative Feed、StageArtifact 或 Inspector 投影。

<a id="r31"></a>

## R3.1 Run 状态机纯领域规则

**计划周期**：Week 4
**状态**：`[x]`
**目标**：实现 PipelineRun 与 Session 的纯状态转移规则，为后续 API 命令提供可测试的领域基础。
**实施计划**：`docs/plans/implementation/r3.1-run-state-machine.md`

**修改文件列表**：
- Create: `backend/app/domain/state_machine.py`
- Create: `backend/tests/domain/test_run_state_machine.py`

**实现类/函数**：
- `RunStateMachine.transition()`
- `RunStateMachine.assert_can_start_first_run()`
- `RunStateMachine.assert_can_create_rerun()`
- `RunStateMachine.assert_can_create_run_from_source()`
- `RunStateMachine.project_session_status()`

**验收标准**：
- 首条 `new_requirement` 只能在 draft Session 且 `current_run_id = null` 时创建首个 run。
- `clarification_reply` 只能在 `waiting_clarification` 使用。
- `completed` Session 不允许创建新 run。
- `failed` / `terminated` 当前 run 尾部允许创建新 run。
- `RunTriggerSource` 覆盖 `initial_requirement`、`retry`、`ops_restart`；外部用户重新尝试只映射为 `retry`。
- pause / resume 不创建新 run。
- 本切片不实现 API 命令副作用。

**测试方法**：
- `pytest backend/tests/domain/test_run_state_machine.py -v`

<a id="e31"></a>

## E3.1 领域事件 Schema 与 EventStore

**计划周期**：Week 4
**状态**：`[x]`
**目标**：建立领域事件日志和事件口径矩阵，使 Run 命令、查询投影和实时增量使用同一事件来源，避免内部领域事件、SSE `event_type` 与 Narrative Feed 条目漂移。
**实施计划**：`docs/plans/implementation/e3.1-domain-event-store.md`
**验证摘要**：实施计划 `docs/plans/implementation/e3.1-domain-event-store.md` 已完成并在 integration checkpoint 合入 `38defe9`。`uv run python -m pytest backend/tests/events/test_event_store.py backend/tests/runtime/test_runtime_engine_contract.py -v` 通过 26 个 E3.1 / A4.1 focused tests；`uv run python -m pytest -q` 通过 356 个 backend tests。

**修改文件列表**：
- Create: `backend/app/services/events.py`
- Create: `backend/tests/events/test_event_store.py`

**实现类/函数**：
- `DomainEvent`
- `EventStore.append()`
- `EventStore.list_after()`
- `EventStore.list_for_session()`
- `EventProjectionMatrix`
- `resolve_sse_event_type()`
- `resolve_feed_entry_type()`

**验收标准**：
- 事件记录包含 `event_id`、`session_id`、`run_id`、`event_type`、`occurred_at`、`payload`。
- 事件类型与正式规格一致。
- `new_requirement`、审批结果、澄清结果、工具确认请求、工具确认结果、控制条目、交付结果和终态状态都进入同一条会话事件流。
- EventStore 是 Narrative Feed 查询投影和 SSE 增量事件的共同来源。
- 原始 LangGraph 事件不直接作为对外领域事件暴露。
- `EventStore.append()` 必须接收或继承当前 `TraceContext`，并把 `correlation_id` 写入可追踪元数据；领域事件仍是产品事实真源，日志审计只记录运行观察事实和审计事实。
- 事件口径矩阵必须明确内部领域事件 PascalCase、SSE `event_type` snake_case、Narrative Feed 条目类型和投影更新目标之间的一一映射。
- 事件口径矩阵必须逐项固定终态映射：`DeliveryPrepared` 或等价交付完成事件生成 `delivery_result`，`RunCompleted` 只更新 run / session 状态且不生成 `system_status`，`RunFailed` 与 `RunTerminated` 生成顶层 `system_status`。
- 事件口径矩阵必须逐项固定工具确认与 Provider 过程映射：`ToolConfirmationRequested -> tool_confirmation_requested -> tool_confirmation`、`ToolConfirmationAllowed/ToolConfirmationDenied -> tool_confirmation_result -> tool_confirmation`、`ProviderCallRetried -> stage_updated -> provider_call`、`ProviderCircuitBreakerOpened/ProviderCircuitBreakerRecovered -> stage_updated -> provider_call`。
- Provider 重试与熔断领域事件必须能更新阶段内部 `provider_call` 条目或失败态 `system_status`，不得只停留在运行日志中。
- 测试必须覆盖 `PipelineRunCreated -> pipeline_run_created`、`ApprovalApproved/ApprovalRejected -> approval_result`、`ToolConfirmationRequested/ToolConfirmationAllowed/ToolConfirmationDenied -> tool_confirmation`、`ProviderCallRetried/ProviderCircuitBreakerOpened/ProviderCircuitBreakerRecovered -> stage_updated`、`DeliveryPrepared -> delivery_result`、`RunCompleted -> session_status_changed`、`RunFailed/RunTerminated -> system_status` 的映射，不允许前端 reducer 自行发明第二套事件语义。

**测试方法**：
- `pytest backend/tests/events/test_event_store.py -v`

<a id="r32a"></a>

## R3.2a 首个 run 启动多库可见性边界

**计划周期**：Week 4
**状态**：`[x]`
**目标**：为首个 run 启动建立可复用的多 SQLite 公开语义边界，使 `runtime.db`、`graph.db`、`event.db` 中已落地但未发布的 startup truth 在 control-side publish 前对 workspace、timeline 和 SSE 不可见，并为后续 H4.4 复用同一类边界打基础。
**实施计划**：`docs/plans/implementation/r3.2a-first-run-publication-boundary.md`
**验证摘要**：实施计划 `docs/plans/implementation/r3.2a-first-run-publication-boundary.md` 已完成并在 integration checkpoint 合入 `2d1199a` 与 `07ab19a`。`uv run python -m pytest backend/tests/services/test_publication_boundary.py backend/tests/api/test_startup_publication_visibility.py -v` 通过 7 个 publication-boundary focused tests；`uv run python -m pytest backend/tests/services/test_start_first_run.py backend/tests/api/test_session_message_api.py backend/tests/api/test_clarification_reply_api.py backend/tests/api/test_startup_publication_visibility.py -v` 通过 23 个 run-start / API impacted tests；`uv run python -m pytest backend/tests/events/test_event_store.py backend/tests/projections/test_workspace_projection.py backend/tests/projections/test_timeline_projection.py backend/tests/api/test_query_api.py backend/tests/api/test_sse_stream.py -q` 通过 50 个 projection / SSE regressions。

**修改文件列表**：
- Create: `backend/app/domain/publication_boundary.py`
- Create: `backend/app/services/publication_boundary.py`
- Modify: `backend/app/db/models/control.py`
- Modify: `backend/app/services/runs.py`
- Modify: `backend/app/services/projections/workspace.py`
- Modify: `backend/app/services/projections/timeline.py`
- Modify: `backend/app/api/routes/events.py`
- Create: `backend/tests/services/test_publication_boundary.py`
- Modify: `backend/tests/services/test_start_first_run.py`
- Create: `backend/tests/api/test_startup_publication_visibility.py`

**实现类/函数**：
- `PublicationBoundaryService.begin_startup_publication()`
- `PublicationBoundaryService.publish_startup_visibility()`
- `PublicationBoundaryService.abort_startup_publication()`
- `PublicationBoundaryService.visible_run_ids_for_session()`
- `RunLifecycleService.start_first_run()`
- `WorkspaceProjectionService`
- `TimelineProjectionService`
- session event stream route

**验收标准**：
- 多 SQLite 职责拆分保持不变，不得回退为单库产品真源。
- 首个 run 启动允许先落地 runtime / graph / event truth，但在 control-side publish 前，workspace、timeline 和 SSE 不得暴露 pending startup 中间态。
- publish 点必须一次性完成 `Session.current_run_id`、Session 运行态可见性和 startup publication 状态切换；外部不得观察到半启动 run。
- publish 前任一阶段失败时，系统只能留下不可见且可恢复或可清理的 staging 状态，不得留下公开可见的半启动 run。
- 必须定义 stale pending startup 的 retry / cleanup 合同，不得把人工清理留成未定义行为。
- 本切片由 AL01 负责，包括为 enforce 该边界而对 `workspace.py`、`timeline.py`、`events.py` 做的 narrow visibility filter；AL02 仍保有通用 projection payload、SSE payload 和 query contract 演进的 owner scope。
- `R3.2` 最终完成必须复用本切片的 publication boundary，不得自行发明第二套启动可见性语义。

**测试方法**：
- `pytest backend/tests/services/test_publication_boundary.py -v`
- `pytest backend/tests/services/test_start_first_run.py -v`
- `pytest backend/tests/api/test_startup_publication_visibility.py -v`

<a id="r32"></a>

## R3.2 首条需求启动首个 run

**计划周期**：Week 4
**状态**：`[x]`
**目标**：实现 `POST /api/sessions/{sessionId}/messages` 中 `new_requirement` 语义，在复用 R3.2a 多库可见性边界的前提下创建首个 PipelineRun、模板快照、Provider 与模型绑定快照、RuntimeLimitSnapshot、ProviderCallPolicySnapshot、GraphDefinition、首条消息事件和初始 Requirement Analysis StageRun。
**实施计划**：`docs/plans/implementation/r3.2-start-first-run.md`

**修改文件列表**：
- Modify: `backend/app/services/runs.py`
- Modify: `backend/app/services/sessions.py`
- Modify: `backend/app/services/events.py`
- Modify: `backend/app/api/routes/sessions.py`
- Create: `backend/tests/services/test_start_first_run.py`
- Create: `backend/tests/api/test_session_message_api.py`

**实现类/函数**：
- `RunLifecycleService.start_first_run()`
- `SessionService.append_message()`
- `SessionService.start_run_from_new_requirement()`
- `TemplateSnapshotBuilder.build_for_run()`
- `ProviderSnapshotBuilder.build_for_run()`
- `ModelBindingSnapshotBuilder.build_for_run()`
- `RuntimeLimitSnapshotBuilder.build_for_run()`
- `ProviderCallPolicySnapshotBuilder.build_for_run()`
- `EventStore.append()`

**验收标准**：
- `R3.2a` 必须先提供可复用的 publication boundary；未复用该边界时，本切片只能作为 business-semantic checkpoint，不得标记最终完成。
- `new_requirement` 创建 `PipelineRun`、固化 `template_snapshot_ref`、Provider 与模型绑定快照、`RuntimeLimitSnapshot`、`ProviderCallPolicySnapshot`、编译并绑定 `graph_definition_ref`、创建并绑定首个 `graph_thread_ref`、分配并绑定首个 `workspace_ref`、回写 `Session.current_run_id`，并将 Session 投影为 `running`。
- run 启动路径必须调用 R3.5 提供的 `GraphCompiler.compile()` 结果，不得在 `R3.2` 中引入第二套 `GraphDefinition` 编译真源。
- 首个 run 启动必须在同一服务事务中写入 `PipelineRun`、模板快照引用、Provider 快照引用、模型绑定快照引用、运行上限快照引用、Provider 调用策略快照引用、GraphDefinition、首个 GraphThread、首个 workspace_ref、首条消息事件和初始 StageRun；任一快照固化失败时不得留下半启动 run。
- run 启动服务必须在模板快照写入前经过单一 `system_prompt` 启动前边界校验调用点；A4.8a 完成后该调用点由 `PromptValidationService.validate_run_prompt_snapshots()` 承接，不得存在绕过启动前校验的 run 创建路径。
- `ModelBindingSnapshotBuilder.build_for_run()` 必须读取 C2.8 已持久化 `PlatformRuntimeSettings.internal_model_bindings` 中的 `context_compression`、`structured_output_repair`、`validation_pass` 三类选择；缺失、非法或不可解析时，run 启动必须失败，不得回退到模板阶段 Provider、Provider 默认模型或运行期临时推导。
- 新 run 的 `current_stage_type = requirement_analysis`。
- 首个 `StageRun(requirement_analysis)` 与 run 启动在同一事务中创建。
- 首个 `graph_thread_ref` 由 `RunLifecycleService.start_first_run()` 在本切片创建；后续 pause / resume / terminate / interrupt resume 只允许继续或控制同一个 thread。
- 首个 `workspace_ref` 由 `RunLifecycleService.start_first_run()` 在本切片分配为当前 run 的最小合法工作区引用；W5.1 负责把该引用接入正式 `WorkspaceManager` 工作区创建、定位、隔离和清理边界。
- 首条用户消息通过 EventStore 追加为顶层 `user_message` 事件来源。
- 本切片不得绕过 EventStore 直接写入第二套 Narrative Feed 来源。
- 非 draft Session 调用 `new_requirement` 被拒绝。
- 当前平台运行设置不可读取、运行上限超过平台硬上限、Provider 或模型绑定快照不可解析时，run 启动必须失败并返回 C1.10/B0.2 固定的稳定错误码，不得降级为默认配置继续启动。
- 首个 run 启动必须生成新的 `trace_id`，并继承当前请求的 `request_id` 与 `correlation_id`。
- run 创建成功、非 draft 调用被拒绝、模板快照、Provider/模型绑定快照、RuntimeLimitSnapshot 或 GraphDefinition 编译失败必须写入运行日志和审计记录。
- 运行日志和审计记录不得替代 `PipelineRun`、模板快照、Provider/模型绑定快照、RuntimeLimitSnapshot、GraphDefinition、首条消息事件或初始 StageRun。
- API 测试必须断言 `POST /api/sessions/{sessionId}/messages` 的 `new_requirement` 请求/响应 Schema、非法状态错误响应和 OpenAPI path/method 已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/services/test_start_first_run.py -v`
- `pytest backend/tests/api/test_session_message_api.py -v`

<a id="r33"></a>

## R3.3 重新尝试领域规则与内部创建基础

**计划周期**：Week 4
**状态**：`[x]`
**目标**：实现重新尝试的纯领域规则和内部创建基础，使 failed / terminated run 后的新 PipelineRun 语义先被状态机约束，但不提前暴露不完整外部命令。
**实施计划**：`docs/plans/implementation/r3.3-rerun-creation.md`

**修改文件列表**：
- Modify: `backend/app/services/runs.py`
- Create: `backend/tests/services/test_rerun_creation.py`

**实现类/函数**：
- `RunLifecycleService.prepare_rerun_creation()`
- `RunLifecycleService.assert_single_active_run()`
- `RunLifecycleService.build_next_attempt_index()`
- `RunLifecycleService.prepare_run_creation_from_source()`

**验收标准**：
- 只有前一个活动 run 处于 `failed` 或 `terminated` 后允许创建新 run。
- `completed` 表示会话链路已完成，不允许同一 Session 创建新 run。
- 内部创建基础必须能计算新 run 的 attempt index、`trigger_source` 和从 `requirement_analysis` 重新开始的初始字段；V1 合法机器值为 `initial_requirement`、`retry`、`ops_restart`。
- 内部创建基础不得暴露 `POST /api/sessions/{sessionId}/runs`，不得追加 `pipeline_run_created` 事件，也不得更新前端 run boundary metadata。
- 外部用户重新尝试命令、事件、投影和 API 路由统一由 H4.7 交付；运维重启只保留领域枚举和内部创建能力，不提供 V1 前端入口。
- 内部重新尝试准备必须定义新旧 `trace_id`、旧 run id、新 run 预期关联关系的记录口径，但不在本切片写外部命令审计记录。
- 新 run 不继承旧 run 未交付的工作区改动引用；实际工作区创建由 W5.1 验证。
- `control_item(type=retry)` 只用于当前 run 内自动回归或阶段内再次尝试。

**测试方法**：
- `pytest backend/tests/services/test_rerun_creation.py -v`

<a id="r34"></a>

## R3.4 模板快照固化

**计划周期**：Week 4
**状态**：`[x]`
**目标**：在 run 启动前固化模板快照，使后续角色绑定、Provider 绑定和自动回归配置不受模板后续修改影响。
**实施计划**：`docs/plans/implementation/r3.4-template-snapshot.md`
**验证摘要**：实施计划 `docs/plans/implementation/r3.4-template-snapshot.md` 已完成并在 integration checkpoint 合入 `d1fcb14`。`uv run python -m pytest backend/tests/services/test_template_snapshot.py backend/tests/services/test_clarification_flow.py backend/tests/api/test_clarification_reply_api.py backend/tests/projections/test_workspace_projection.py backend/tests/api/test_query_api.py backend/tests/tools/test_tool_protocol_registry.py -v` 通过 39 个 focused backend tests；`uv run python -m pytest -q` 通过 395 个 backend tests。

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
- 快照包含固定阶段序列、阶段槽位最终生效的 `role_id`、`system_prompt`、`provider_id`、自动回归开关和最大重试次数。
- 后续模板修改不得回写影响已启动 run。
- 快照不包含项目级 DeliveryChannel 配置。
- 快照不包含 Provider 运行时能力声明、调用策略或平台运行上限；这些由 R3.4a 和 R3.4b 分别固化。

**测试方法**：
- `pytest backend/tests/services/test_template_snapshot.py -v`

<a id="r34a"></a>

## R3.4a Provider 与模型绑定快照固化

**计划周期**：Week 4
**状态**：`[x]`
**目标**：在 run 启动前固化 ProviderSnapshot 与 ModelBindingSnapshot，使 Provider 修改、凭据轮换、默认模型调整或能力声明变化不影响已启动 run。
**实施计划**：`docs/plans/implementation/r3.4a-provider-model-binding-snapshots.md`
**验证摘要**：实施计划 `docs/plans/implementation/r3.4a-provider-model-binding-snapshots.md` 已完成并在 integration checkpoint 合入 `ec0b023`。`uv run python -m pytest backend/tests/services/test_provider_model_binding_snapshots.py backend/tests/services/test_template_snapshot.py backend/tests/db/test_runtime_model_boundary.py backend/tests/providers/test_provider_registry.py -q` 通过 33 个 impacted backend tests；`uv run python -m pytest -q` 通过 437 个 backend tests。

**修改文件列表**：
- Create: `backend/app/domain/provider_snapshot.py`
- Modify: `backend/app/repositories/runtime.py`
- Modify: `backend/app/services/runs.py`
- Create: `backend/tests/services/test_provider_model_binding_snapshots.py`

**实现类/函数**：
- `ProviderSnapshotBuilder.build_for_run()`
- `ModelBindingSnapshotBuilder.build_for_run()`
- `RuntimeSnapshotRepository.save_provider_snapshot()`
- `RuntimeSnapshotRepository.save_model_binding_snapshot()`
- `RunLifecycleService.attach_provider_snapshots()`

**验收标准**：
- 每次 run 启动前固化当前实际使用的 Provider 与模型绑定快照。
- ProviderSnapshot 至少记录 `provider_id`、`provider_source`、`protocol_type`、`base_url`、`model_id`、凭据引用、能力声明和 schema 版本；能力声明必须包含实际模型的 `context_window_tokens`、`max_output_tokens`、`supports_tool_calling`、`supports_structured_output`、`supports_native_reasoning`。
- ModelBindingSnapshot 至少记录每个 `AgentRole`、上下文压缩、结构化输出修复和 validation pass 实际绑定的 Provider、模型、参数与能力声明；能力声明必须包含实际模型的 `context_window_tokens`、`max_output_tokens`、`supports_tool_calling`、`supports_structured_output`、`supports_native_reasoning`。
- ProviderSnapshot 与 ModelBindingSnapshot 必须通过 C1.7 的结构化 runtime 快照模型持久化，并把稳定引用回写到当前 `PipelineRun` 或其快照关联表。
- run 启动后，Provider 修改、凭据轮换、默认模型调整或能力声明变化只影响后续 run，不得改变当前 run。
- 配置包导入或 Provider API 更新导致的 Provider 能力变化只影响后续 run；不得改变当前 run 的 ProviderSnapshot 或 ModelBindingSnapshot。
- 快照只保存凭据引用，不保存真实密钥明文。
- Provider 不存在、凭据环境变量名不被允许、模型绑定不可解析、`context_window_tokens` 或 `max_output_tokens` 非法、`supports_*` 字段不是布尔值、能力声明缺失时，快照固化失败并返回稳定错误码；不得使用最新 Provider 默认值或空快照继续启动 run。

**测试方法**：
- `pytest backend/tests/services/test_provider_model_binding_snapshots.py -v`

<a id="r34b"></a>

## R3.4b RuntimeLimitSnapshot 固化

**计划周期**：Week 4
**状态**：`[x]`
**目标**：在 run 启动前从 C2.8 当前平台运行设置固化 `RuntimeLimitSnapshot` 与 `ProviderCallPolicySnapshot`，使热重载运行设置不改变已启动 run 的执行语义。
**实施计划**：`docs/plans/implementation/r3.4b-runtime-limit-snapshot.md`

**修改文件列表**：
- Create: `backend/app/domain/runtime_limit_snapshot.py`
- Create: `backend/app/domain/provider_call_policy_snapshot.py`
- Modify: `backend/app/repositories/runtime.py`
- Modify: `backend/app/services/runs.py`
- Create: `backend/tests/services/test_runtime_limit_snapshot.py`
- Create: `backend/tests/services/test_provider_call_policy_snapshot.py`

**实现类/函数**：
- `RuntimeLimitSnapshotBuilder.build_for_run()`
- `ProviderCallPolicySnapshotBuilder.build_for_run()`
- `RuntimeSnapshotRepository.save_runtime_limit_snapshot()`
- `RuntimeSnapshotRepository.save_provider_call_policy_snapshot()`
- `RunLifecycleService.attach_runtime_limit_snapshot()`
- `RunLifecycleService.attach_provider_call_policy_snapshot()`

**验收标准**：
- 每次 run 启动前固化运行上限快照，并把 `runtime_limit_snapshot_ref` 写入 `PipelineRun`。
- 每次 run 启动前固化 Provider 调用策略快照，并把 `provider_call_policy_snapshot_ref` 写入 `PipelineRun` 或其运行快照关联表。
- `RuntimeLimitSnapshotBuilder` 必须读取 C2.8 当前已持久化的 `PlatformRuntimeSettings` 版本，不从环境变量、默认常量或前端请求体临时推导执行上限。
- 快照记录实际生效的 Agent 循环上限、Provider 调用策略、上下文裁剪限制、工具输出限制和 `compression_threshold_ratio`。
- `ProviderCallPolicySnapshot` 记录请求超时、网络错误重试次数、限流重试次数、指数退避基准、指数退避上限、连续失败熔断阈值、熔断恢复条件、来源配置版本和 schema 版本。
- 快照记录来源配置版本和平台硬上限版本。
- `compression_threshold_ratio` 来自 C2.8 已持久化的 `PlatformRuntimeSettings.context_limits`，不得从配置包、环境变量、前端请求体或默认常量临时推导。
- 模板中的 `max_auto_regression_retries` 可以低于或等于平台运行设置对应值，但不得超过平台硬上限。
- C2.8 后续热重载设置不得改变已启动 run 的 RuntimeLimitSnapshot。
- 当前设置缺失、配置版本不可读取、模板自动回归次数超过平台硬上限或快照写入失败时，run 启动失败并返回 `config_snapshot_unavailable`、`config_storage_unavailable` 或 `config_hard_limit_exceeded` 中对应错误码。
- 测试必须覆盖更新 `PlatformRuntimeSettings` 后新 run 使用新配置版本、旧 run 继续引用旧 `RuntimeLimitSnapshot` 与旧 `ProviderCallPolicySnapshot`。

**测试方法**：
- `pytest backend/tests/services/test_runtime_limit_snapshot.py -v`
- `pytest backend/tests/services/test_provider_call_policy_snapshot.py -v`

<a id="r35"></a>

## R3.5 GraphDefinition 固定主链编译

**计划周期**：Week 4
**状态**：`[x]`
**目标**：把模板快照和运行上限快照编译为固定六阶段 GraphDefinition，固化审批中断点、内部节点组、阶段契约和运行期配置来源。
**实施计划**：`docs/plans/implementation/r3.5-graph-definition-compiler.md`

**修改文件列表**：
- Create: `backend/app/services/graph_compiler.py`
- Create: `backend/app/domain/graph_definition.py`
- Create: `backend/tests/services/test_graph_compiler.py`

**实现类/函数**：
- `GraphDefinition`
- `GraphCompiler.compile(template_snapshot: TemplateSnapshot, runtime_limit_snapshot: RuntimeLimitSnapshot) -> GraphDefinition`
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
- GraphDefinition 的 `stage_contracts` 必须记录每个正式业务阶段的输入契约、输出契约、结构化产物要求、`allowed_tools` 与本次 run 的运行上限引用。
- GraphDefinition 必须记录 `runtime_limit_snapshot_ref` 和配置来源版本，只消费 R3.4/R3.4b 已固化快照，不读取最新 `PlatformRuntimeSettings`。
- GraphDefinition 不保存 LangGraph compiled graph 实例，只保存可持久化、可重建的领域图定义。
- `source_node_group -> stage_type` 映射必须支持后续 LangGraph node event 到 `StageRun` / `StageArtifact` 的转换。
- 图编译成功、编译失败和非法模板快照输入必须写入运行日志摘要，且不得把 GraphDefinition 内容只保存在日志中。

**测试方法**：
- `pytest backend/tests/services/test_graph_compiler.py -v`

<a id="r36"></a>

## R3.6 StageRun 持久化

**计划周期**：Week 4-5
**状态**：`[x]`
**目标**：建立 StageRun 创建、状态推进、阶段类型与图契约引用记录，使六个正式业务阶段可被查询和回放。
**实施计划**：`docs/plans/implementation/r3.6-stage-run-store.md`

**范围说明**：本切片负责把 `StageRunModel` 从 C1.7 的初始 runtime 边界补齐到当前 backend spec 要求，纳入 `graph_node_key` 与 `stage_contract_ref` 的持久化字段；这两个字段不留给后续切片隐式补齐。

**修改文件列表**：
- Modify: `backend/app/db/models/runtime.py`
- Modify: `backend/tests/db/test_runtime_model_boundary.py`
- Modify: `backend/app/repositories/runtime.py`
- Create: `backend/app/services/stages.py`
- Create: `backend/tests/services/test_stage_run_store.py`

**实现类/函数**：
- `StageRunService.start_stage()`
- `StageRunService.mark_stage_waiting()`
- `StageRunService.complete_stage()`
- `StageRunRepository`

**验收标准**：
- StageRun 的 `stage_type` 只允许六个正式业务阶段。
- StageRun 必须持久化 `graph_node_key` 与 `stage_contract_ref`，分别引用 `GraphDefinition` 的稳定 node key 映射和对应阶段契约快照，不得在后续查询或运行恢复时依赖即时推断。
- 审批等待或澄清等待时，`current_stage_type` 保持源阶段不变。
- `solution_design_approval` 和 `code_review_approval` 不创建独立 StageRun。
- StageRun 记录开始时间、结束时间、状态和 attempt index。
- StageRun 开始、等待、完成和失败必须继承当前 `TraceContext` 并写入运行日志摘要；StageRun 状态仍以 runtime 领域模型为准。

**测试方法**：
- `pytest backend/tests/db/test_runtime_model_boundary.py -v`
- `pytest backend/tests/services/test_stage_run_store.py -v`

<a id="r37"></a>

## R3.7 StageArtifact 存储

**计划周期**：Week 4-5
**状态**：`[x]`
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
- 产物写入失败、载荷裁剪和指标写入必须写入运行日志；完整阶段过程不得只存在于日志中。

**测试方法**：
- `pytest backend/tests/services/test_artifact_store.py -v`

<a id="q31"></a>

## Q3.1 SessionWorkspaceProjection

**计划周期**：Week 5
**状态**：`[x]`
**目标**：实现会话工作台查询投影，使前端可一次加载会话状态、项目摘要、多 run 分段、Narrative Feed 和 Composer 状态。
**实施计划**：`docs/plans/implementation/q3.1-session-workspace-projection.md`
**验证摘要**：实施计划 `docs/plans/implementation/q3.1-session-workspace-projection.md` 已完成并在 integration checkpoint 合入 `d07f094`。`uv run python -m pytest backend/tests/services/test_template_snapshot.py backend/tests/services/test_clarification_flow.py backend/tests/api/test_clarification_reply_api.py backend/tests/projections/test_workspace_projection.py backend/tests/api/test_query_api.py backend/tests/tools/test_tool_protocol_registry.py -v` 通过 39 个 focused backend tests；`uv run python -m pytest -q` 通过 395 个 backend tests。

**修改文件列表**：
- Create: `backend/app/services/projections/workspace.py`
- Create: `backend/app/api/routes/query.py`
- Create: `backend/tests/projections/test_workspace_projection.py`
- Create: `backend/tests/api/test_query_api.py`

**实现类/函数**：
- `WorkspaceProjectionService.get_session_workspace()`
- `WorkspaceProjectionService.build_composer_state()`
- `WorkspaceProjectionService.build_run_summaries()`

**验收标准**：
- workspace projection 包含项目摘要、会话状态、项目级交付配置摘要、run summaries、narrative feed、composer state。
- `run summaries` 或可深看引用必须能定位当前 run 的模板快照、Provider/模型绑定快照和 `RuntimeLimitSnapshot` 摘要引用；投影不得读取最新平台设置来解释历史 run。
- 当当前活动 run 处于 `waiting_tool_confirmation` 时，workspace projection 必须包含对应顶层 `tool_confirmation` 条目、不可通过 Composer 提交普通输入，并把当前焦点定位到该工具确认块。
- 被删除 Session 或已移除 Project 下的 Session 不得作为常规 workspace 查询入口继续打开；API 返回稳定不可见或不存在错误语义。
- narrative feed 必须从 EventStore、领域对象、StageArtifact 和稳定引用组装，不得定义第二套投影来源语义。
- 同一 Session 下的多个 run 按启动时间顺序返回。
- `composer_state.bound_run_id` 始终指向当前活动 run。
- 投影不暴露 raw graph state。
- Workspace projection 可以包含与当前对象直接相关的日志摘要引用或诊断定位信息，但不得通过 `RunLogEntry` 拼装 Narrative Feed。
- API 测试必须断言 `GET /api/sessions/{sessionId}/workspace` 的响应 Schema、主要错误响应和 OpenAPI path/method 已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/projections/test_workspace_projection.py -v`
- `pytest backend/tests/api/test_query_api.py -v`

<a id="q32"></a>

## Q3.2 RunTimelineProjection

**计划周期**：Week 5
**状态**：`[x]`
**目标**：实现单 run 时间线投影，使历史 run 能独立回放且条目语义与 workspace projection 保持一致。
**实施计划**：`docs/plans/implementation/q3.2-run-timeline-projection.md`
**验证摘要**：实施计划 `docs/plans/implementation/q3.2-run-timeline-projection.md` 已完成并在 integration checkpoint 合入 `827d4dd`。`uv run pytest backend/tests/api/test_query_api.py backend/tests/projections/test_timeline_projection.py backend/tests/projections/test_approval_projection.py backend/tests/services/test_approval_creation.py backend/tests/errors/test_error_code_catalog.py` 通过 34 个 focused backend tests。

**修改文件列表**：
- Create: `backend/app/services/projections/timeline.py`
- Modify: `backend/app/api/routes/query.py`
- Create: `backend/tests/projections/test_timeline_projection.py`
- Modify: `backend/tests/api/test_query_api.py`

**实现类/函数**：
- `TimelineProjectionService.get_run_timeline()`
- `TimelineProjectionService.build_timeline_entries()`

**验收标准**：
- `GET /api/runs/{runId}/timeline` 只返回目标 run 条目。
- `entries` 按发生时间顺序返回该 run 的全部顶层 Narrative Feed 条目。
- `entries[].type` 只允许正式顶层条目枚举。
- 条目语义与 `SessionWorkspaceProjection.narrative_feed` 保持一致。
- `tool_confirmation` 作为独立顶层条目出现在对应 run 时间线中，不得降级为 `approval_request` 或 `control_item`。
- Provider 重试与熔断更新必须体现在所属 `stage_node` 内部 `provider_call` 条目或状态摘要中，不得生成新的人工审批条目。
- API 测试必须断言 `GET /api/runs/{runId}/timeline` 的响应 Schema、主要错误响应和 OpenAPI path/method 已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/projections/test_timeline_projection.py -v`
- `pytest backend/tests/api/test_query_api.py -v`

<a id="q33"></a>

## Q3.3 StageInspectorProjection

**计划周期**：Week 5
**状态**：`[x]`
**目标**：实现阶段 Inspector 查询投影，使前端可深看阶段输入、过程、输出、引用和量化信息。
**实施计划**：`docs/plans/implementation/q3.3-stage-inspector-projection.md`

**修改文件列表**：
- Create: `backend/app/services/projections/inspector.py`
- Modify: `backend/app/api/routes/query.py`
- Create: `backend/tests/projections/test_stage_inspector_projection.py`
- Modify: `backend/tests/api/test_query_api.py`

**实现类/函数**：
- `InspectorProjectionService.get_stage_inspector()`
- `InspectorProjectionService.build_stage_identity()`
- `InspectorProjectionService.build_metric_section()`

**验收标准**：
- `GET /api/stages/{stageRunId}/inspector` 返回按 `identity/input/process/output/artifacts/metrics` 分组的完整阶段 Inspector 投影。
- 投影内容来自领域对象、StageArtifact 和稳定引用，不由前端回填关键事实。
- `solution_design` 阶段 Inspector 必须能展示 `SolutionDesignArtifact.implementation_plan`，并保留供 `code_generation`、`test_generation_execution` 与 `code_review` 引用的稳定任务标识。
- Inspector 必须能展示阶段内 Provider 调用状态、指数退避重试轨迹、熔断状态、失败原因摘要和 `provider_retry_trace` / `provider_circuit_breaker_trace` 引用。
- Inspector 必须能展示阶段内工具确认过程引用，但工具确认详情由 Q3.4a 的 `ToolConfirmationInspectorProjection` 提供。
- `approval_result` 关联信息可通过所属阶段 Inspector 读取。
- 投影不暴露 raw graph state。
- Inspector 可以展示与当前阶段直接相关的 `log_id`、裁剪日志片段或诊断定位信息，但阶段完整输入、过程、输出、产物和指标必须来自领域对象、StageArtifact 和稳定引用。
- API 测试必须断言 `GET /api/stages/{stageRunId}/inspector` 的响应 Schema、主要错误响应和 OpenAPI path/method 已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/projections/test_stage_inspector_projection.py -v`
- `pytest backend/tests/api/test_query_api.py -v`

<a id="q34"></a>

## Q3.4 ControlItemInspectorProjection

**计划周期**：Week 5
**状态**：`[x]`
**目标**：实现控制型条目详情投影，使回退、重试和澄清等待可以被右栏深看；本切片不涉及交付结果详情或工具确认详情。
**实施计划**：`docs/plans/implementation/q3.4-control-item-inspector-projection.md`

**修改文件列表**：
- Modify: `backend/app/services/projections/inspector.py`
- Modify: `backend/app/api/routes/query.py`
- Create: `backend/tests/projections/test_control_item_detail_projection.py`
- Modify: `backend/tests/api/test_query_api.py`

**实现类/函数**：
- `InspectorProjectionService.get_control_item_detail()`
- `InspectorProjectionService.build_control_item_sections()`

**验收标准**：
- `GET /api/control-records/{controlRecordId}` 返回完整控制条目详情，不退化为摘要文本。
- `system_status` 终态条目不作为 `control_item.control_type` 持久化。
- `tool_confirmation` 不作为 `control_item.control_type` 的可见详情返回；即使领域层存在 `RunControlRecord(control_type=tool_confirmation)`，右栏详情也必须转交 Q3.4a 的 `ToolConfirmationInspectorProjection`。
- 本切片不实现 `GET /api/delivery-records/{deliveryRecordId}`，不伪造 DeliveryRecord，不定义临时交付详情投影语义。
- `DeliveryResultDetailProjection` 的 Schema 由 C1.4 保留，正式查询实现由 D4.3 基于 DeliveryRecord 交付。
- API 测试必须断言 `GET /api/control-records/{controlRecordId}` 的响应 Schema、主要错误响应和 OpenAPI path/method 已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/projections/test_control_item_detail_projection.py -v`
- `pytest backend/tests/api/test_query_api.py -v`

<a id="q34a"></a>

## Q3.4a ToolConfirmationInspectorProjection

**计划周期**：Week 5
**状态**：`[x]`
**目标**：实现高风险工具确认详情投影，使工具确认作为独立顶层交互对象被右栏深看，并与人工审批、控制条目详情保持边界清晰。
**实施计划**：`docs/plans/implementation/q3.4a-tool-confirmation-inspector-projection.md`
**验证摘要**：实施计划 `docs/plans/implementation/q3.4a-tool-confirmation-inspector-projection.md` 已完成并在 integration checkpoint 合入 `897a7c5`。`uv run python -m pytest backend/tests/projections/test_tool_confirmation_detail_projection.py backend/tests/api/test_query_api.py -v` 通过 18 个 focused projection/API tests；`uv run python -m pytest backend/tests/schemas/test_inspector_metrics_schemas.py backend/tests/schemas/test_run_feed_event_schemas.py backend/tests/projections/test_workspace_projection.py backend/tests/projections/test_timeline_projection.py backend/tests/projections/test_stage_inspector_projection.py backend/tests/projections/test_control_item_detail_projection.py backend/tests/projections/test_tool_confirmation_detail_projection.py backend/tests/api/test_query_api.py -q` 通过 53 个 impacted regressions。

**修改文件列表**：
- Modify: `backend/app/services/projections/inspector.py`
- Modify: `backend/app/api/routes/query.py`
- Create: `backend/tests/projections/test_tool_confirmation_detail_projection.py`
- Modify: `backend/tests/api/test_query_api.py`

**实现类/函数**：
- `InspectorProjectionService.get_tool_confirmation_detail()`
- `InspectorProjectionService.build_tool_confirmation_sections()`
- `InspectorProjectionService.build_tool_confirmation_process_trace()`

**验收标准**：
- `GET /api/tool-confirmations/{toolConfirmationId}` 返回 `ToolConfirmationInspectorProjection`，按 `identity/input/process/output/artifacts/metrics` 分组。
- 详情来源必须是 `ToolConfirmationRequest`、关联 `RunControlRecord(control_type=tool_confirmation)`、`StageArtifact.process` 中的 `tool_confirmation_trace`、工具结果和稳定引用，不得从前端摘要或运行日志反推。
- 投影必须包含工具名称、命令或参数摘要、目标资源、风险等级、风险分类、预期副作用、替代路径判断、用户决定、后续处理结果、审计引用和过程记录引用。
- 投影不得返回 `ApprovalRequest`、`ApprovalDecision` 或 `ControlItemInspectorProjection` 的替代结构。
- 允许后只能关联该确认请求覆盖的工具动作；拒绝后必须展示后端选择低风险替代路径、失败或等待显式运行控制的结果。
- API 测试必须断言 `GET /api/tool-confirmations/{toolConfirmationId}` 的响应 Schema、主要错误响应和 OpenAPI path/method 已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/projections/test_tool_confirmation_detail_projection.py -v`
- `pytest backend/tests/api/test_query_api.py -v`

<a id="q34b"></a>

## Q3.4b ToolConfirmation 顶层拒绝后续语义契约修复

**计划周期**：Week 5-6
**状态**：`[x]`
**目标**：读取 `H4.4b` 固化的 runtime-side deny follow-up source，并修复顶层 `tool_confirmation` 在 query / workspace / timeline / SSE 中的拒绝后续语义契约，使前端无需读取 Inspector 或推断 run 终态即可稳定展示 deny 后运行结果。
**实施计划**：`docs/plans/implementation/q3.4b-tool-confirmation-top-level-outcome-contract.md`
**验证摘要**：实施计划 `docs/plans/implementation/q3.4b-tool-confirmation-top-level-outcome-contract.md` 已完成并在 integration checkpoint 合入 `3c1ec4f`。`uv run python -m pytest backend/tests/schemas/test_run_feed_event_schemas.py backend/tests/projections/test_workspace_projection.py backend/tests/projections/test_timeline_projection.py backend/tests/api/test_query_api.py backend/tests/api/test_sse_stream.py backend/tests/services/test_tool_confirmation_commands.py backend/tests/api/test_tool_confirmation_api.py -v` 通过 77 个 focused and impacted backend tests；`uv run python -m pytest -q` 通过 811 个 backend tests。

**修改文件列表**：
- Modify: `backend/app/schemas/feed.py`
- Modify: `backend/app/services/projections/workspace.py`
- Modify: `backend/app/services/projections/timeline.py`
- Modify: `backend/app/api/routes/query.py`
- Modify: `backend/app/api/routes/events.py`
- Modify: `backend/app/services/tool_confirmations.py`
- Modify: `backend/tests/schemas/test_run_feed_event_schemas.py`
- Modify: `backend/tests/projections/test_workspace_projection.py`
- Modify: `backend/tests/projections/test_timeline_projection.py`
- Modify: `backend/tests/api/test_query_api.py`
- Modify: `backend/tests/api/test_sse_stream.py`
- Modify: `backend/tests/services/test_tool_confirmation_commands.py`
- Modify: `backend/tests/api/test_tool_confirmation_api.py`

**实现类/函数**：
- `ToolConfirmationFeedEntry`
- `WorkspaceProjectionService`
- `TimelineProjectionService`
- `SseEventEncoder`

**验收标准**：
- 顶层 `tool_confirmation` payload 必须新增 `deny_followup_action` 与 `deny_followup_summary`。
- `deny_followup_action` 只允许 `continue_current_stage`、`run_failed`、`awaiting_run_control`；当 `decision != denied` 时必须为 `null`。
- `deny_followup_summary` 在 `decision = denied` 时必须返回稳定产品语义摘要；其它场景必须为 `null`。
- `Q3.4b` 负责扩展 `ToolConfirmationFeedEntry`、workspace/timeline payload 和 SSE/query schema；`H4.4b` 不承担这些 shared-entry 修改。
- query 返回的 workspace feed、run timeline feed 与 SSE `tool_confirmation_requested` / `tool_confirmation_result` 必须携带同语义 `tool_confirmation` payload，不允许为 query 和 SSE 定义不同字段名或不同状态含义。
- `continue_current_stage` 只能表示后端已经确认存在低风险替代路径并将继续当前阶段；`run_failed` 与 `awaiting_run_control` 不得要求前端通过 Inspector、原始 run 状态或 `alternative_path_summary` 私有字段自行推断。
- 本切片只修复顶层投影契约，不把 deny 后续语义下沉为 Inspector-only 信息，也不把 `tool_confirmation` 降级为 `approval_request`、`control_item` 或 `system_status` 替代结构。
- 若 `H4.4b` 尚未提供稳定 deny follow-up source，或其持久化结果仍不能稳定区分 `run_failed` 与 `awaiting_run_control`，则本切片必须停止并回报 owner dependency，不得以猜测映射完成该契约。
- API 与 schema 测试必须断言新增字段进入 query 响应、SSE payload 和 `/api/openapi.json` 对应 Schema。

**测试方法**：
- `pytest backend/tests/schemas/test_run_feed_event_schemas.py -v`
- `pytest backend/tests/projections/test_workspace_projection.py -v`
- `pytest backend/tests/projections/test_timeline_projection.py -v`
- `pytest backend/tests/api/test_query_api.py -v`
- `pytest backend/tests/api/test_sse_stream.py -v`

<a id="e32"></a>

## E3.2 SSE 流端点与断线恢复

**计划周期**：Week 5
**状态**：`[x]`
**目标**：建立会话级 SSE 流，使前端可用 workspace 快照加增量事件维持 Narrative Feed 一致状态。
**实施计划**：`docs/plans/implementation/e3.2-sse-stream-reconnect.md`

**修改文件列表**：
- Create: `backend/app/api/routes/events.py`
- Modify: `backend/app/services/events.py`
- Create: `backend/tests/api/test_sse_stream.py`

**实现类/函数**：
- `SseEventEncoder.encode()`
- `stream_session_events()`

**验收标准**：
- `GET /api/sessions/{sessionId}/events/stream` 提供会话级 SSE。
- payload 中的 feed 条目语义与查询投影一致。
- SSE 必须覆盖 `tool_confirmation_requested` 与 `tool_confirmation_result`，并携带与查询投影同语义的 `tool_confirmation` payload。
- SSE 必须覆盖 Provider 重试与熔断相关阶段更新，使前端能更新阶段内部 `provider_call` 状态、指数退避等待摘要和熔断状态。
- 断线后可通过 workspace 快照 + `EventStore.list_after()` 重建一致状态。
- SSE 只传递增量，不定义第二套产品语义。
- SSE payload 可携带 `correlation_id` 便于诊断关联，但前端 reducer 不得依赖日志审计接口合并产品状态。
- API 测试必须断言 `GET /api/sessions/{sessionId}/events/stream` 的 SSE 响应说明、主要错误响应和 OpenAPI path/method 已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/api/test_sse_stream.py -v`

<a id="l31"></a>

## L3.1 Run 与 Stage 日志轻查询 API

**计划周期**：Week 5
**状态**：`[x]`
**目标**：实现 run 级和 stage 级运行日志只读轻查询，使后端诊断工具可按对象聚焦查看裁剪后的日志摘要，而不把日志查询接入前端主路径。
**实施计划**：`docs/plans/implementation/l3.1-run-stage-log-query-api.md`

**修改文件列表**：
- Create: `backend/app/observability/log_query.py`
- Modify: `backend/app/schemas/observability.py`
- Modify: `backend/app/api/routes/query.py`
- Create: `backend/tests/observability/test_log_query_service.py`
- Modify: `backend/tests/schemas/test_observability_schemas.py`
- Modify: `backend/tests/api/test_query_api.py`

**实现类/函数**：
- `LogQueryService.list_run_logs()`
- `LogQueryService.list_stage_logs()`
- `LogQueryService.encode_cursor()`
- `LogQueryService.decode_cursor()`

**验收标准**：
- `GET /api/runs/{runId}/logs` 返回该 run 关联的运行日志分页结果，不返回其他 run 的日志。
- `GET /api/stages/{stageRunId}/logs` 返回该阶段关联的运行日志分页结果，不返回同一 run 中其他阶段的日志。
- 查询参数至少支持 `level`、`category`、`source`、`since`、`until`、`cursor`、`limit`。
- 日志分页使用稳定游标，稳定顺序基于 `created_at + log_id` 或等价全局稳定顺序，不只依赖 offset。
- 响应返回 `entries`、`next_cursor`、`has_more` 与查询条件回显。
- 响应不得返回完整大载荷，只能返回 `message`、`payload_excerpt`、`payload_size_bytes`、`redaction_status`、`log_file_ref`、`line_offset`、`line_number`、`log_file_generation` 和关联标识。
- 日志查询接口不得作为 Narrative Feed、Inspector、审批块或交付结果投影的依赖接口。
- `limit` 默认值和最大值来自当前 C2.8 `PlatformRuntimeSettings.log_policy`，但该诊断查询设置只影响查询分页，不改变已启动 run 的领域事件、投影条目或快照语义。
- `limit` 非法或超过当前最大值时返回稳定错误码，不静默截断为最大值。
- API 测试必须断言 `GET /api/runs/{runId}/logs` 与 `GET /api/stages/{stageRunId}/logs` 的查询参数、响应 Schema、主要错误响应和 OpenAPI path/method 已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/observability/test_log_query_service.py backend/tests/schemas/test_observability_schemas.py -v`
- `pytest backend/tests/api/test_query_api.py -k "run_logs or stage_logs or query_log_routes" -v`

<a id="f31"></a>

## F3.1 Workspace Store 快照初始化

**计划周期**：Week 5
**状态**：`[x]`
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
**状态**：`[x]`
**目标**：实现 EventSource 薄封装和事件 reducer，使 SSE 增量通过统一状态模型合并。
**实施计划**：`docs/plans/implementation/f3.2-sse-client-event-reducer.md`
**验证摘要**：实施计划 `docs/plans/implementation/f3.2-sse-client-event-reducer.md` 已完成并在 integration checkpoint 合入 `c5f11d1`。`npm --prefix frontend run test -- event-reducer` 通过 7 个 F3.2 focused tests；`npm --prefix frontend run build` 通过 TypeScript 检查和 Vite production build。

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
- SSE 增量可追加和更新 `tool_confirmation` 顶层块，并更新阶段内部 `provider_call` 的重试、等待、熔断和失败状态。
- `session_status_changed` 更新当前 Composer 状态。
- 前端不绕过状态模型直接改 UI。
- 重复事件不会造成重复条目。

**测试方法**：
- `npm --prefix frontend run test -- event-reducer`

<a id="f33"></a>

## F3.3 Feed Entry Renderer

**计划周期**：Week 5-6
**状态**：`[x]`
**目标**：实现 Narrative Feed 顶层条目分发渲染，使不同条目类型具备独立展示语义。
**实施计划**：`docs/plans/implementation/f3.3-feed-entry-renderer.md`
**验证摘要**：实施计划 `docs/plans/implementation/f3.3-feed-entry-renderer.md` 已完成并在 integration checkpoint 合入 `47946f8`。`npm --prefix frontend run test -- FeedEntryRenderer` 通过 7 个 F3.3 focused tests；`npm --prefix frontend run build` 通过 TypeScript 检查和 Vite production build。

**修改文件列表**：
- Create: `frontend/src/features/feed/NarrativeFeed.tsx`
- Create: `frontend/src/features/feed/FeedEntryRenderer.tsx`
- Create: `frontend/src/features/feed/__tests__/FeedEntryRenderer.test.tsx`

**实现类/函数**：
- `NarrativeFeed`
- `FeedEntryRenderer`
- `renderFeedEntryByType()`

**验收标准**：
- `user_message`、`stage_node`、`approval_request`、`tool_confirmation`、`control_item`、`approval_result`、`delivery_result`、`system_status` 使用不同展示语义。
- `system_status` 只作为顶层条目渲染。
- `tool_confirmation` 只作为顶层交互块渲染，不使用 Approval Block，不显示 Approve / Reject 文案。
- `completed` run 以 `delivery_result` 收束，不追加完成态 `system_status`。

**前端设计质量门**：
- 继承项目级前端主基调，不单独询问 Narrative Feed 风格。
- 实现前必须梳理顶层条目层级、条目密度、时间顺序、可扫描性和窄屏阅读策略。
- 实现后必须检查文本溢出、对比度、焦点态、屏幕阅读语义和视觉反模式。
- 顶层 `new_requirement`、`approval_request`、`tool_confirmation`、`approval_result`、`delivery_result` 必须可扫描，且不得与阶段内部条目混淆。

**测试方法**：
- `npm --prefix frontend run test -- FeedEntryRenderer`

<a id="f34"></a>

## F3.4 StageNode 与阶段内部条目

**计划周期**：Week 5-6
**状态**：`[x]`
**目标**：实现阶段结点大框和阶段内部条目展示，使 Requirement Analysis 澄清对话和正式研发阶段内容在同一主流中连续阅读。
**实施计划**：`docs/plans/implementation/f3.4-stage-node-items.md`
**验证摘要**：实施计划 `docs/plans/implementation/f3.4-stage-node-items.md` 已完成并在 integration checkpoint 合入 `f694762`。`npm --prefix frontend run test -- StageNode` 通过 7 个 F3.4 focused tests；`npm --prefix frontend run build` 通过 TypeScript 检查和 Vite production build。

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
- 阶段内部条目至少支持 `dialogue`、`reasoning`、`decision`、`provider_call`、`tool_call`、`diff_preview`、`result`。
- `provider_call` 必须展示 Provider 名称或模型绑定摘要、调用状态、耗时、重试次数、指数退避等待摘要、熔断状态和详情入口。
- Requirement Analysis 阶段内澄清问答显示为阶段内部连续对话内容。
- 阶段结点正文展示高信号指标，完整信息留给 Inspector。

**前端设计质量门**：
- 继承项目级前端主基调。
- 实现前必须梳理阶段大框、内部条目、折叠密度和 Inspector 入口的呈现关系。
- 实现后必须检查阶段内长 reasoning、工具摘要、diff 预览、指标摘要和窄屏布局。
- 阶段大框必须服务连续阅读，不得形成嵌套卡片堆叠或与顶层 Feed 条目竞争主层级。

**测试方法**：
- `npm --prefix frontend run test -- StageNode`

<a id="f35"></a>

## F3.5 Run Boundary 与 Run Switcher

**计划周期**：Week 5-6
**状态**：`[x]`
**目标**：实现同一 Session 多 run 的视觉分界和页面内定位控件，使 Run Switcher 只承担导航职责。
**实施计划**：`docs/plans/implementation/f3.5-run-boundary-switcher.md`
**验证摘要**：实施计划 `docs/plans/implementation/f3.5-run-boundary-switcher.md` 已完成并在 integration checkpoint 合入 `4042594`。`npm --prefix frontend test -- --run` 通过 94 个 frontend tests；`npm --prefix frontend run build` 通过 TypeScript 检查和 Vite production build。

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

**前端设计质量门**：
- 继承项目级前端主基调；若 run 分界需要特殊视觉区分，只在主基调内定义区分规则。
- 实现前必须梳理多 run 分界、历史态、当前态和页面内定位体验。
- 实现后必须检查分界可见性、历史 run 可读性、窄屏切换和 Composer 遮挡风险。
- Run Switcher 的视觉权重必须低于 Narrative Feed 主内容，不得暗示它能触发重新运行或编辑模板。

**测试方法**：
- `npm --prefix frontend run test -- RunSwitcher`

<a id="f36"></a>

## F3.6 Inspector Shell 与打开状态

**计划周期**：Week 5-6
**状态**：`[x]`
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
- 点击阶段结点、工具确认、控制条目或交付结果可打开 Inspector。
- 右栏默认关闭。
- Inspector 不承担审批主操作。
- `approval_result` 不作为独立右栏打开对象。

**前端设计质量门**：
- 继承项目级前端主基调，不单独询问 Inspector 风格。
- 实现前必须梳理右栏打开、关闭、抽屉、固定宽度、焦点回收和深看入口。
- 实现后必须检查可访问性、键盘关闭、窄屏抽屉、空态和与 Feed 主阅读路径的层级关系。
- Inspector 必须是深看面板，不承载审批或工具确认主操作，也不把 `approval_result` 变成独立详情对象。

**测试方法**：
- `npm --prefix frontend run test -- InspectorPanel`

<a id="f37"></a>

## F3.7 Inspector 分组与 Metrics 展示

**计划周期**：Week 5-6
**状态**：`[x]`
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
- Inspector 必须能展示 `implementation_plan`、Provider 重试轨迹、熔断状态和工具确认过程引用；工具确认独立详情按 `ToolConfirmationInspectorProjection` 渲染。
- 不适用指标隐藏，不使用空模板占位。
- 前端只做呈现层分组、折叠、排序和语法高亮，不改写语义。

**前端设计质量门**：
- 继承项目级前端主基调；若 metrics 需要图表呈现，只在主基调内记录图表密度和颜色边界。
- 实现后必须检查分组节奏、长 artifact 名称、空 metrics、失败 metrics、代码块横向滚动和窄屏可读性。
- Metrics 和 artifacts 的视觉表达必须保留原始信息边界，不通过文案或颜色改写后端语义。

**测试方法**：
- `npm --prefix frontend run test -- InspectorSections`
