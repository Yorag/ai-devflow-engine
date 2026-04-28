# 01 工程基线与契约层

## 范围

本分卷覆盖 Week 1-2 的工程基线、后端契约、前端基线和持久化边界。完成后，前后端具备可运行项目骨架、基础测试命令、OpenAPI 初版、领域枚举、投影 Schema 和多 SQLite 职责拆分。

本分卷的拆分目标是先锁定契约，再进入控制面与 Run 主链。每个契约切片只处理一组稳定字段，避免单次任务同时修改所有 Schema。

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
- 通用错误响应包含稳定错误码、消息和 request id。
- `GET /api/openapi.json` 可访问。
- B0.1 中的后端测试命令可继续运行。

**测试方法**：
- `pytest backend/tests/api/test_health.py -v`
- `pytest backend/tests/api/test_error_contract.py -v`
- `python -m uvicorn backend.app.main:app --reload`

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

## C1.1 状态枚举与阶段类型契约

**计划周期**：Week 2
**状态**：`[ ]`
**目标**：固化功能一 V1 的状态枚举、阶段枚举、顶层条目枚举和交付模式枚举，为后续 Schema、投影和前端状态提供单一契约来源。
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

**验收标准**：
- `StageType` 只包含 `requirement_analysis`、`solution_design`、`code_generation`、`test_generation_execution`、`code_review`、`delivery_integration`。
- `FeedEntryType` 只包含 `user_message`、`stage_node`、`approval_request`、`control_item`、`approval_result`、`delivery_result`、`system_status`。
- `ApprovalType` 只包含 `solution_design_approval` 与 `code_review_approval`。
- `SessionStatus` 与 `RunStatus` 至少覆盖 `draft`、`running`、`paused`、`waiting_clarification`、`waiting_approval`、`completed`、`failed`、`terminated`。

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
- `PipelineTemplate` 区分 `system_template` 与 `user_template`，并包含固定阶段骨架与自动回归配置。
- `Provider` 区分内置 Provider 与 custom Provider，且不暴露真实密钥。
- `DeliveryChannel` 包含 `credential_ref`、`credential_status`、`readiness_status` 和 `readiness_message`。

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
**目标**：建立 control、runtime、graph、event 多 SQLite 连接管理和 SQLAlchemy session 边界，不创建完整业务模型。
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

**验收标准**：
- 四类数据库角色可独立解析连接 URL。
- 测试环境可为四类数据库创建临时 SQLite 文件。
- session helper 不混用数据库角色。
- Alembic 环境能识别多数据库迁移目标。

**测试方法**：
- `pytest backend/tests/db/test_database_sessions.py -v`
- `alembic -c backend/alembic.ini current`

<a id="c16"></a>

## C1.6 control/runtime/graph/event 模型与迁移边界

**计划周期**：Week 2
**状态**：`[ ]`
**目标**：建立四类数据库的首批模型和迁移边界，确保规范实体、运行记录、执行图状态和事件日志职责分离。
**实施计划**：`docs/plans/implementation/c1.6-persistence-model-boundaries.md`

**修改文件列表**：
- Create: `backend/app/db/models/control.py`
- Create: `backend/app/db/models/runtime.py`
- Create: `backend/app/db/models/graph.py`
- Create: `backend/app/db/models/event.py`
- Create: `backend/tests/db/test_database_boundaries.py`

**实现类/函数**：
- `ControlBase`
- `RuntimeBase`
- `GraphBase`
- `EventBase`
- `ProjectModel`
- `SessionModel`
- `PipelineRunModel`
- `StageRunModel`
- `GraphDefinitionModel`
- `GraphThreadModel`
- `GraphCheckpointModel`
- `GraphInterruptModel`
- `DomainEventModel`

**验收标准**：
- `control.db` 承载 Project、Session、模板、Provider 与项目级配置。
- `runtime.db` 承载 PipelineRun、StageRun、审批对象、结构化产物索引、控制条目与运行摘要。
- `graph.db` 承载 GraphDefinition、GraphThread、GraphCheckpoint、GraphInterrupt。
- `graph.db` 中的 GraphDefinition、GraphThread、GraphCheckpoint、GraphInterrupt 均有独立模型，不以单个 GraphThreadModel 或序列化 blob 替代执行图对象边界。
- `event.db` 承载领域事件日志、Narrative Feed 投影来源数据与审计记录。
- `Session` 规范实体只存在于 control 模型；runtime 模型通过 `session_id` 关联，不复制 `Session` 实体。

**测试方法**：
- `pytest backend/tests/db/test_database_boundaries.py -v`
- `alembic -c backend/alembic.ini upgrade head`
