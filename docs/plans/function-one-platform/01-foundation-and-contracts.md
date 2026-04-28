# 01 工程基线与契约层

## 范围

本分卷覆盖 Week 1-2 的工程基线、后端契约、前端基线和持久化边界。完成后，前后端具备可运行项目骨架、基础测试命令、领域枚举、投影 Schema、事件载荷 Schema、日志审计契约和多 SQLite 职责拆分。

本分卷的拆分目标是先锁定契约，再进入控制面与 Run 主链。每个契约切片只处理一组稳定字段，避免单次任务同时修改所有 Schema。日志审计能力在本分卷只固定启动前置条件、Schema、TraceContext、`log.db` 边界和 `event.db` 分离边界；具体采集点随后续控制面、Run、runtime、工具和交付切片嵌入实现。

<a id="b01"></a>

## B0.1 工程与开发命令基线

**计划周期**：Week 1
**状态**：`[ ]`
**目标**：建立前后端最小工程依赖、测试命令和开发脚本入口，不实现具体 API 与页面业务。
**实施计划**：`docs/plans/implementation/b0.1-engineering-command-baseline.md`

**修改文件列表**：
- Create: `pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/tests/conftest.py`
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/src/main.tsx`
- Modify: `README.md`

**实现类/函数**：
- 无业务函数。
- `pyproject.toml` 定义后端依赖与 pytest 配置。
- `frontend/package.json` 定义 `dev`、`build`、`test` 脚本。

**验收标准**：
- 后端依赖安装后 `pytest` 命令可运行。
- 前端依赖安装后 `npm --prefix frontend run test` 命令可运行。
- README 中记录后端、前端和测试命令。
- 本切片不创建 `backend/app/main.py`，FastAPI app 由 B0.2 负责。

**测试方法**：
- `pytest --collect-only`
- `npm --prefix frontend run test -- --run`
- `rg -n "pytest|npm --prefix frontend" README.md`

<a id="b02"></a>

## B0.2 后端 FastAPI 应用与错误契约

**计划周期**：Week 1
**状态**：`[ ]`
**目标**：建立 FastAPI 应用入口、路由聚合、健康检查和统一错误响应契约，使后续 API 可以在一致服务骨架上扩展。
**实施计划**：`docs/plans/implementation/b0.2-fastapi-error-contract.md`

**修改文件列表**：
- Create: `backend/app/main.py`
- Create: `backend/app/api/router.py`
- Create: `backend/app/api/errors.py`
- Create: `backend/app/core/config.py`
- Create: `backend/tests/api/test_health.py`
- Create: `backend/tests/api/test_error_contract.py`

**实现类/函数**：
- `create_app() -> FastAPI`
- `build_api_router() -> APIRouter`
- `ApiError`
- `register_error_handlers(app: FastAPI) -> None`

**验收标准**：
- `GET /api/health` 返回服务状态。
- `build_api_router()` 采用统一路由装配模式：各 `backend/app/api/routes/*.py` 模块导出模块级 `router`，由 `build_api_router()` 统一 `include_router()`；后续切片不得混用额外的 `register_*_routes(router)` 函数模式。
- 通用错误响应包含稳定错误码、消息和 request id。
- `GET /api/openapi.json` 可访问。
- B0.1 中的后端测试命令可继续运行。

**测试方法**：
- `pytest backend/tests/api/test_health.py -v`
- `pytest backend/tests/api/test_error_contract.py -v`
- `python -m uvicorn backend.app.main:app --reload`

<a id="l01"></a>

## L0.1 运行数据目录与日志启动预检

**计划周期**：Week 1
**状态**：`[ ]`
**目标**：建立平台运行数据根目录和 `.runtime/logs` 启动预检，使后端在接受用户命令前确认日志目录存在且可写。
**实施计划**：`docs/plans/implementation/l0.1-runtime-data-log-preflight.md`

**修改文件列表**：
- Modify: `backend/app/core/config.py`
- Create: `backend/app/observability/runtime_data.py`
- Create: `backend/tests/observability/test_runtime_data_preflight.py`

**实现类/函数**：
- `RuntimeDataSettings`
- `RuntimeDataPreflight.ensure_runtime_data_ready()`
- `RuntimeDataPreflight.resolve_logs_dir()`
- `RuntimeDataPreflight.assert_writable()`

**验收标准**：
- 平台运行数据根目录可通过配置指定；未配置时默认使用服务当前运行目录下的 `.runtime`。
- 启动前必须确保运行数据目录、`.runtime/logs` 与 `.runtime/logs/runs` 存在且可写。
- 目录不可创建或不可写时，后端不得进入可接受用户命令的正常运行状态。
- `.runtime/logs` 被明确标记为平台运行期私有数据，不属于目标项目工作区内容。
- 本切片不实现日志写入、日志索引、审计记录或日志查询 API。

**测试方法**：
- `pytest backend/tests/observability/test_runtime_data_preflight.py -v`

<a id="f01"></a>

## F0.1 前端 SPA 骨架与测试基线

**计划周期**：Week 1
**状态**：`[ ]`
**目标**：建立 React SPA、路由、QueryClient 和测试工具基线，使控制台页面可以独立于后端实现并行推进。
**实施计划**：`docs/plans/implementation/f0.1-frontend-spa-baseline.md`

**修改文件列表**：
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/app/router.tsx`
- Create: `frontend/src/app/query-client.ts`
- Create: `frontend/src/app/test-utils.tsx`
- Create: `frontend/src/pages/ConsolePage.tsx`
- Create: `frontend/src/pages/HomePage.tsx`
- Create: `frontend/src/styles/global.css`
- Create: `frontend/src/pages/__tests__/ConsolePage.test.tsx`

**实现类/函数**：
- `App`
- `createAppRouter()`
- `createQueryClient()`
- `ConsolePage`
- `HomePage`

**验收标准**：
- SPA 路由包含控制台页面。
- TanStack Query Provider 挂载完成。
- 测试工具支持渲染路由和 Query Client。
- 本切片不实现工作台三栏和业务组件。

**前端设计质量门**：
- 实施计划必须包含 `Frontend Design Gate` 小节，并记录项目级前端主基调。
- 若用户提供参考示例，将参考示例提炼为主基调；后续前端展示切片默认继承该主基调，不逐项重新询问。
- 若用户未提供参考示例，主基调采用安静、专业、高信息密度、便于扫描的产品型工作台界面。
- 主基调先记录在本切片实施计划中；若后续需要新增正式设计上下文文档，必须先经过用户评审。
- 确认后续前端切片可以执行设计塑形、审查和硬化质量门。
- 本切片只建立主基调记录和调用口径，不进行业务页面视觉打磨。

**测试方法**：
- `npm --prefix frontend run test -- ConsolePage`
- `npm --prefix frontend run dev`

<a id="c11"></a>

## C1.1 全局枚举与状态契约

**计划周期**：Week 2
**状态**：`[ ]`
**目标**：固化功能一 V1 的状态、阶段、模板、Provider、交付、事件和运行触发枚举，为后续 Schema、投影、事件矩阵和前端状态提供单一 machine value 来源。
**实施计划**：`docs/plans/implementation/c1.1-enum-contracts.md`

**修改文件列表**：
- Create: `backend/app/domain/enums.py`
- Create: `backend/app/schemas/common.py`
- Create: `backend/tests/schemas/test_enum_contracts.py`

**实现类/函数**：
- `SessionStatus`
- `RunStatus`
- `StageStatus`
- `StageType`
- `FeedEntryType`
- `ControlItemType`
- `ApprovalType`
- `DeliveryMode`
- `DeliveryReadinessStatus`
- `CredentialStatus`
- `TemplateSource`
- `ProviderSource`
- `ProviderProtocolType`
- `ScmProviderType`
- `CodeReviewRequestType`
- `RunTriggerSource`
- `ApprovalStatus`
- `StageItemType`
- `SseEventType`

**验收标准**：
- `StageType` 只包含 `requirement_analysis`、`solution_design`、`code_generation`、`test_generation_execution`、`code_review`、`delivery_integration`。
- `FeedEntryType` 只包含 `user_message`、`stage_node`、`approval_request`、`control_item`、`approval_result`、`delivery_result`、`system_status`。
- `ApprovalType` 只包含 `solution_design_approval` 与 `code_review_approval`。
- `SessionStatus` 覆盖 `draft`、`running`、`paused`、`waiting_clarification`、`waiting_approval`、`completed`、`failed`、`terminated`。
- `RunStatus` 只覆盖 `running`、`paused`、`waiting_clarification`、`waiting_approval`、`completed`、`failed`、`terminated`。
- `StageStatus` 只覆盖 `running`、`waiting_clarification`、`waiting_approval`、`completed`、`failed`、`superseded`，不得包含底层装配态 `pending`。
- `ControlItemType` 至少包含 `clarification_wait`、`rollback`、`retry`；`retry` 只表示当前 run 内自动回归或阶段内再次尝试。
- `TemplateSource` 只包含 `system_template`、`user_template`。
- `ProviderSource` 只包含 `builtin`、`custom`。
- `ProviderProtocolType` 至少包含 `openai_completions_compatible`。
- `ScmProviderType` 至少包含 `github`、`gitlab`。
- `CodeReviewRequestType` 只包含 `pull_request`、`merge_request`。
- `RunTriggerSource` 只包含 `initial_requirement`、`retry`、`ops_restart`；用户可见的“重新尝试”映射为机器值 `retry`。
- `ApprovalStatus` 至少包含 `pending`、`approved`、`rejected`、`cancelled`，其中 `pending` 只属于审批对象，不属于 `RunStatus` 或 `StageStatus`。
- `StageItemType` 至少包含 `dialogue`、`reasoning`、`decision`、`tool_call`、`diff_preview`、`result`。
- `SseEventType` 覆盖正式后端规格中的会话级 SSE 事件类型，不允许前端 reducer 自行发明第二套事件名。
- `draft` 只表示尚未创建首个 `PipelineRun` 的 `Session`，不得出现在 `RunStatus` 中。
- 测试必须断言 `RunStatus` 不包含 `draft`，`RunStatus` 与 `StageStatus` 不包含 `pending`，`system_status` 不属于 `ControlItemType`。

**测试方法**：
- `pytest backend/tests/schemas/test_enum_contracts.py -v`

<a id="c12"></a>

## C1.2 控制面 Schema 契约

**计划周期**：Week 2
**状态**：`[ ]`
**目标**：定义 Project、Session、PipelineTemplate、AgentRole、Provider 和 DeliveryChannel 的请求响应 Schema，使控制面 API 有稳定字段边界。
**实施计划**：`docs/plans/implementation/c1.2-control-plane-schemas.md`

**修改文件列表**：
- Create: `backend/app/schemas/project.py`
- Create: `backend/app/schemas/session.py`
- Create: `backend/app/schemas/template.py`
- Create: `backend/app/schemas/provider.py`
- Create: `backend/app/schemas/delivery_channel.py`
- Create: `backend/tests/schemas/test_control_plane_schemas.py`

**实现类/函数**：
- `ProjectRead`
- `SessionRead`
- `PipelineTemplateRead`
- `AgentRoleConfig`
- `ProviderRead`
- `ProjectDeliveryChannelDetailProjection`

**验收标准**：
- `Project` 包含默认交付通道引用。
- `Session` 包含 `status`、`selected_template_id`、`current_run_id`、`latest_stage_type`。
- `PipelineTemplate` 区分 `system_template` 与 `user_template`，并包含固定阶段骨架、阶段槽位到 AgentRole 的绑定、槽位内最终生效的 `role_id` / `system_prompt` / `provider_id` 和自动回归配置。
- `AgentRoleConfig` 返回 `role_name` 作为展示标签；V1 不提供 `role_name` 修改字段。
- `Provider` 区分内置 Provider 与 custom Provider，且不暴露真实密钥。
- `DeliveryChannel` 包含 `credential_ref`、`credential_status`、`readiness_status`、`readiness_message` 和 `last_validated_at`。

**测试方法**：
- `pytest backend/tests/schemas/test_control_plane_schemas.py -v`

<a id="c13"></a>

## C1.3 Run、Feed 与事件 Schema 契约

**计划周期**：Week 2
**状态**：`[ ]`
**目标**：定义 Run、Narrative Feed、Workspace Projection、Timeline Projection 与 SSE 事件载荷 Schema，使前端 mock 和增量合并基于同一契约。
**实施计划**：`docs/plans/implementation/c1.3-run-feed-event-schemas.md`

**修改文件列表**：
- Create: `backend/app/schemas/run.py`
- Create: `backend/app/schemas/feed.py`
- Create: `backend/app/schemas/events.py`
- Create: `backend/app/schemas/workspace.py`
- Create: `backend/tests/schemas/test_run_feed_event_schemas.py`

**实现类/函数**：
- `RunSummaryProjection`
- `RunTimelineProjection`
- `SessionWorkspaceProjection`
- `ComposerStateProjection`
- `FeedEntry`
- `ExecutionNodeProjection`
- `SessionEvent`

**验收标准**：
- `SessionWorkspaceProjection` 包含项目摘要、会话状态、run summaries、按 run 归属可分段的 Narrative Feed 和 Composer 状态。
- `RunTimelineProjection.entries[].type` 只允许正式顶层条目枚举。
- SSE `payload` 中的 `message_item`、`stage_node`、`approval_request`、`approval_result`、`control_item`、`delivery_result`、`system_status` 与查询投影同语义。
- Requirement Analysis 阶段内澄清问答通过阶段内部条目表达，不提升为审批条目。

**测试方法**：
- `pytest backend/tests/schemas/test_run_feed_event_schemas.py -v`

<a id="c14"></a>

## C1.4 Inspector 与 Metrics Schema 契约

**计划周期**：Week 2
**状态**：`[ ]`
**目标**：定义 Stage、ControlItem、DeliveryResult 的 Inspector 投影与量化指标 Schema，保证右栏深看信息以结构化原始记录为准。
**实施计划**：`docs/plans/implementation/c1.4-inspector-metrics-schemas.md`

**修改文件列表**：
- Create: `backend/app/schemas/inspector.py`
- Create: `backend/app/schemas/metrics.py`
- Create: `backend/tests/schemas/test_inspector_metrics_schemas.py`

**实现类/函数**：
- `StageInspectorProjection`
- `ControlItemInspectorProjection`
- `DeliveryResultDetailProjection`
- `MetricSet`
- `InspectorSection`

**验收标准**：
- Inspector 投影按 `identity/input/process/output/artifacts/metrics` 分组。
- `StageInspectorProjection.stage_type` 只允许六个正式业务阶段。
- `ControlItemInspectorProjection.control_type` 只允许控制型条目语义。
- `approval_result` 不作为独立右栏对象时，其详情可通过所属阶段 Inspector 中的关联审批信息读取。
- 不适用指标允许缺省，不使用统一空值占位。

**测试方法**：
- `pytest backend/tests/schemas/test_inspector_metrics_schemas.py -v`

<a id="c15"></a>

## C1.5 多 SQLite 连接与 session 管理

**计划周期**：Week 2
**状态**：`[ ]`
**目标**：建立 control、runtime、graph、event、log 多 SQLite 连接管理和 SQLAlchemy session 边界，不创建完整业务模型。
**实施计划**：`docs/plans/implementation/c1.5-multi-sqlite-session-management.md`

**修改文件列表**：
- Create: `backend/app/db/base.py`
- Create: `backend/app/db/session.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/tests/db/test_database_sessions.py`

**实现类/函数**：
- `DatabaseRole`
- `DatabaseManager`
- `get_control_session()`
- `get_runtime_session()`
- `get_graph_session()`
- `get_event_session()`
- `get_log_session()`

**验收标准**：
- 五类数据库角色可独立解析连接 URL。
- 测试环境可为五类数据库创建临时 SQLite 文件。
- session helper 不混用数据库角色。
- Alembic 环境能识别多数据库迁移目标。
- `log.db` 只用于日志轻量索引、审计台账、日志文件位置、载荷摘要、裁剪状态与关联标识，不承载领域事件或 Narrative Feed 投影来源数据。

**测试方法**：
- `pytest backend/tests/db/test_database_sessions.py -v`
- `alembic -c backend/alembic.ini current`

<a id="c16"></a>

## C1.6 control 模型与迁移边界

**计划周期**：Week 2
**状态**：`[ ]`
**目标**：建立 `control.db` 的首批规范模型和迁移边界，确保项目、会话、模板、Provider 与项目级交付配置只在控制面持久化。
**实施计划**：`docs/plans/implementation/c1.6-control-model-boundary.md`

**修改文件列表**：
- Create: `backend/app/db/models/control.py`
- Create: `backend/tests/db/test_control_model_boundary.py`

**实现类/函数**：
- `ControlBase`
- `ProjectModel`
- `SessionModel`
- `PipelineTemplateModel`
- `ProviderModel`
- `DeliveryChannelModel`

**验收标准**：
- `control.db` 承载 Project、Session、PipelineTemplate、Provider、DeliveryChannel 与项目级配置。
- `Session` 规范实体只存在于 control 模型。
- `DeliveryChannel` 属于项目级配置，不属于 Session、模板或 runtime 模型。
- control 模型不包含 PipelineRun、StageRun、GraphThread、DomainEvent、RunLogEntry、AuditLogEntry 或 LogPayload。

**测试方法**：
- `pytest backend/tests/db/test_control_model_boundary.py -v`
- `alembic -c backend/alembic.ini upgrade head`

<a id="c17"></a>

## C1.7 runtime 模型与迁移边界

**计划周期**：Week 2
**状态**：`[ ]`
**目标**：建立 `runtime.db` 的运行领域模型和迁移边界，确保 run、阶段、产物、审批、控制记录和交付记录作为产品级领域真源存在。
**实施计划**：`docs/plans/implementation/c1.7-runtime-model-boundary.md`

**修改文件列表**：
- Create: `backend/app/db/models/runtime.py`
- Create: `backend/tests/db/test_runtime_model_boundary.py`

**实现类/函数**：
- `RuntimeBase`
- `PipelineRunModel`
- `StageRunModel`
- `StageArtifactModel`
- `ClarificationRecordModel`
- `ApprovalRequestModel`
- `ApprovalDecisionModel`
- `RunControlRecordModel`
- `DeliveryChannelSnapshotModel`
- `DeliveryRecordModel`

**验收标准**：
- `runtime.db` 承载 PipelineRun、StageRun、StageArtifact、ClarificationRecord、ApprovalRequest、ApprovalDecision、RunControlRecord、DeliveryChannelSnapshot、DeliveryRecord、结构化产物索引与运行摘要。
- runtime 模型通过 `session_id` 关联 control Session，不复制 `Session` 实体。
- `PipelineRunModel.delivery_channel_snapshot_ref` 必须指向 `DeliveryChannelSnapshotModel` 或等价结构化快照记录，不得只是无所有权的 opaque string。
- `DeliveryChannelSnapshotModel` 必须包含 `delivery_mode`、`scm_provider_type`、`repository_identifier`、`default_branch`、`code_review_request_type`、`credential_ref`、`credential_status`、`readiness_status`、`readiness_message` 与 `last_validated_at`。
- `StageRun.stage_type` 只允许六个正式业务阶段。
- `RunControlRecord.control_type` 至少支持 `clarification_wait`、`rollback`、`retry`。
- run 尾部 `system_status` 不作为 `RunControlRecord.control_type` 持久化。
- `DeliveryRecord` 是正式领域对象，不由临时交付详情投影替代。

**测试方法**：
- `pytest backend/tests/db/test_runtime_model_boundary.py -v`
- `alembic -c backend/alembic.ini upgrade head`

<a id="c18"></a>

## C1.8 graph 模型与迁移边界

**计划周期**：Week 2
**状态**：`[ ]`
**目标**：建立 `graph.db` 的执行图状态模型和迁移边界，确保 GraphDefinition、GraphThread、GraphCheckpoint 与 GraphInterrupt 独立于产品领域模型存在。
**实施计划**：`docs/plans/implementation/c1.8-graph-model-boundary.md`

**修改文件列表**：
- Create: `backend/app/db/models/graph.py`
- Create: `backend/tests/db/test_graph_model_boundary.py`

**实现类/函数**：
- `GraphBase`
- `GraphDefinitionModel`
- `GraphThreadModel`
- `GraphCheckpointModel`
- `GraphInterruptModel`

**验收标准**：
- `graph.db` 承载 GraphDefinition、GraphThread、GraphCheckpoint、GraphInterrupt。
- GraphDefinition、GraphThread、GraphCheckpoint、GraphInterrupt 均有独立模型，不以单个 GraphThreadModel 或序列化 blob 替代执行图对象边界。
- `graph.db` 不替代 PipelineRun、StageRun、ApprovalRequest 或 DeliveryRecord 的产品级领域建模。
- GraphCheckpoint 只保存可恢复执行引用，不作为前端投影来源。
- GraphInterrupt 能表达澄清与审批中断类型，并可关联 runtime 领域对象。

**测试方法**：
- `pytest backend/tests/db/test_graph_model_boundary.py -v`
- `alembic -c backend/alembic.ini upgrade head`

<a id="c19"></a>

## C1.9 event 模型边界

**计划周期**：Week 2
**状态**：`[ ]`
**目标**：建立 `event.db` 的领域事件和 Narrative Feed 投影来源数据边界，使查询投影与 SSE 增量共享同一事件来源，并明确审计记录不属于 `event.db`。
**实施计划**：`docs/plans/implementation/c1.9-event-model-boundary.md`

**修改文件列表**：
- Create: `backend/app/db/models/event.py`
- Create: `backend/tests/db/test_event_model_boundary.py`

**实现类/函数**：
- `EventBase`
- `DomainEventModel`

**验收标准**：
- `event.db` 承载领域事件记录与 Narrative Feed 投影来源数据。
- DomainEvent 至少记录 `event_id`、`session_id`、`run_id`、`event_type`、`occurred_at`、`payload`。
- 对外事件与 SSE payload 必须能映射到 C1.3 定义的同名投影条目。
- `event.db` 不包含 `AuditLogEntry`、`RunLogEntry` 或 `LogPayload`。
- 审计记录不替代领域事件，也不作为 Narrative Feed 顶层条目来源；审计记录由 `log.db` 的 L1.2 负责。
- 原始 LangGraph 事件不得直接写成对外 DomainEvent payload。

**测试方法**：
- `pytest backend/tests/db/test_event_model_boundary.py -v`
- `alembic -c backend/alembic.ini upgrade head`

<a id="l11"></a>

## L1.1 日志审计 Schema 与 TraceContext 契约

**计划周期**：Week 2
**状态**：`[ ]`
**目标**：定义日志审计查询投影、日志审计枚举、查询参数和跨层 TraceContext，使后续 API、runtime、工具和交付切片共享同一关联语义。
**实施计划**：`docs/plans/implementation/l1.1-log-audit-schema-trace-context.md`

**修改文件列表**：
- Create: `backend/app/schemas/observability.py`
- Create: `backend/app/domain/trace_context.py`
- Create: `backend/tests/schemas/test_observability_schemas.py`

**实现类/函数**：
- `RunLogEntryProjection`
- `AuditLogEntryProjection`
- `RunLogQuery`
- `AuditLogQuery`
- `LogLevel`
- `LogCategory`
- `AuditActorType`
- `AuditResult`
- `RedactionStatus`
- `TraceContext`

**验收标准**：
- `RunLogEntryProjection` 覆盖 `log_id`、对象关联标识、`source`、`category`、`level`、`message`、文件定位、载荷摘要、裁剪状态、关联标识和时间字段。
- `AuditLogEntryProjection` 覆盖 `audit_id`、动作主体、目标、结果、原因、元数据摘要、关联标识和时间字段。
- `RunLogQuery` 支持 `level`、`category`、`source`、`since`、`until`、`cursor`、`limit`。
- `AuditLogQuery` 支持 `actor_type`、`action`、`target_type`、`target_id`、`run_id`、`result`、`since`、`until`、`cursor`、`limit`。
- `TraceContext` 固定 `request_id`、`trace_id`、`correlation_id`、`span_id`、`parent_span_id` 与产品对象标识字段。
- 日志审计 Schema 不包含完整大载荷详情查询字段；V1 不定义 `GET /api/log-payloads/{payloadId}`。
- 测试必须断言日志审计投影不等同于 `FeedEntry`、`StageInspectorProjection` 或领域事件 payload。

**测试方法**：
- `pytest backend/tests/schemas/test_observability_schemas.py -v`

<a id="l12"></a>

## L1.2 log 模型与迁移边界

**计划周期**：Week 2
**状态**：`[ ]`
**目标**：建立 `log.db` 的运行日志轻量索引、审计台账、载荷摘要和关联标识模型边界，使日志审计独立于领域事件与产品状态真源。
**实施计划**：`docs/plans/implementation/l1.2-log-model-boundary.md`

**修改文件列表**：
- Create: `backend/app/db/models/log.py`
- Create: `backend/tests/db/test_log_model_boundary.py`

**实现类/函数**：
- `LogBase`
- `RunLogEntryModel`
- `AuditLogEntryModel`
- `LogPayloadModel`

**验收标准**：
- `log.db` 承载 RunLogEntry、AuditLogEntry、LogPayload 或等价结构化载荷摘要。
- `RunLogEntryModel` 保存本地 JSONL 文件定位字段：`log_file_ref`、`line_offset`、`line_number`、`log_file_generation`。
- `RunLogEntryModel` 保存 `trace_id`、`correlation_id`、`span_id`、`parent_span_id` 和当前可用产品对象标识。
- `AuditLogEntryModel` 保存动作主体、动作、目标、结果、原因、`request_id`、`correlation_id` 和关联产品对象标识。
- `LogPayloadModel` 保存载荷类型、摘要、存储引用、内容哈希、裁剪状态和大小，不无界保存大文本。
- `log.db` 不包含 DomainEvent、Narrative Feed 投影、PipelineRun、StageRun、ApprovalRequest 或 DeliveryRecord。
- 审计记录写入失败属于安全审计失败，后续命令切片不得降级为普通运行日志失败。

**测试方法**：
- `pytest backend/tests/db/test_log_model_boundary.py -v`
- `alembic -c backend/alembic.ini upgrade head`
