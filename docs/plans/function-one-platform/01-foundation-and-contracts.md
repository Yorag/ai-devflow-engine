# 01 工程基线与契约层

## 范围

本分卷覆盖 Week 1-2 的工程基线、后端契约、前端基线、配置边界和持久化边界。完成后，前后端具备可运行项目骨架、基础测试命令、`EnvironmentSettings`、`PlatformRuntimeSettings`、领域枚举、投影 Schema、事件载荷 Schema、日志审计契约和多 SQLite 职责拆分。

本分卷的拆分目标是先锁定契约，再进入控制面与 Run 主链。每个契约切片只处理一组稳定字段，避免单次任务同时修改所有 Schema。配置边界在本分卷只固定启动配置、可热重载运行设置、运行快照 Schema 和校验口径；具体管理服务、快照固化和 runtime 消费由后续分卷实现。日志审计能力在本分卷只固定启动前置条件、Schema、TraceContext、`log.db` 边界和 `event.db` 分离边界；具体采集点随后续控制面、Run、runtime、工具和交付切片嵌入实现。

<a id="b01"></a>

## B0.1 工程与开发命令基线

**计划周期**：Week 1
**状态**：`[x]`
**目标**：建立前后端最小工程依赖、测试命令和开发脚本入口，不实现具体 API 与页面业务。
**实施计划**：`docs/plans/implementation/b0.1-engineering-command-baseline.md`
**验证摘要**：激活 `.venv` 后，`python -m pip show langchain langgraph langchain-openai` 显示 `langchain==1.2.17`、`langgraph==1.1.10`、`langchain-openai==1.2.1`，且 PyPI index 显示三者均为 latest；`python -m pip install -e ".[dev]"` 通过；`pytest backend/tests/test_engineering_baseline.py -q` 通过；`pytest --collect-only` 收集 1 个 B0.1 backend baseline test；`npm --prefix frontend install` 通过并生成 lockfile；`npm --prefix frontend run test -- --run` 通过；`npm --prefix frontend run build` 通过；`npm --prefix frontend audit --audit-level=moderate` 返回 0 vulnerabilities；`rg -n "Activate.ps1|pytest|npm --prefix frontend|Python 3\.11|开发命令" README.md README.zh.md` 通过。

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
**状态**：`[x]`
**目标**：建立 FastAPI 应用入口、路由聚合、健康检查和统一错误响应契约，使后续 API 可以在一致服务骨架上扩展。
**实施计划**：`docs/plans/implementation/b0.2-fastapi-error-contract.md`
**验证摘要**：`uv run --no-sync python -m pytest backend/tests/api/test_health.py backend/tests/api/test_error_contract.py -q` 通过；`uv run --no-sync python -m pytest backend/tests/test_engineering_baseline.py backend/tests/api/test_health.py backend/tests/api/test_error_contract.py -q` 通过；`uv run --no-sync python -m pytest --collect-only` 收集 9 个 backend tests；`uv run --no-sync python -m uvicorn backend.app.main:app --help` 退出码 0。OpenAPI 断言覆盖 `/api/health`、`HealthResponse` 与 `ErrorResponse`；错误契约断言覆盖 `ApiError`、404、请求校验、未处理异常、`X-Request-ID` 传播和配置错误码预留。

**修改文件列表**：
- Create: `backend/app/main.py`
- Create: `backend/app/api/router.py`
- Create: `backend/app/api/errors.py`
- Create: `backend/app/api/error_codes.py`
- Create: `backend/app/core/config.py`
- Create: `backend/tests/api/test_health.py`
- Create: `backend/tests/api/test_error_contract.py`

**实现类/函数**：
- `create_app() -> FastAPI`
- `build_api_router() -> APIRouter`
- `ApiError`
- `ErrorCode`
- `register_error_handlers(app: FastAPI) -> None`

**验收标准**：
- `GET /api/health` 返回服务状态。
- `build_api_router()` 采用统一路由装配模式：各 `backend/app/api/routes/*.py` 模块导出模块级 `router`，由 `build_api_router()` 统一 `include_router()`；后续切片不得混用额外的 `register_*_routes(router)` 函数模式。
- 通用错误响应包含稳定错误码、消息和 request id。
- 错误码集中定义在 `backend/app/api/error_codes.py`，后续切片只能扩展稳定 machine value，不得在路由中散落字符串错误码。
- 配置相关错误码预留并测试：`config_invalid_value`、`config_hard_limit_exceeded`、`config_version_conflict`、`config_storage_unavailable`、`config_snapshot_unavailable`、`config_credential_env_not_allowed`。
- `GET /api/openapi.json` 可访问。
- B0.1 中的后端测试命令可继续运行。

**测试方法**：
- `pytest backend/tests/api/test_health.py -v`
- `pytest backend/tests/api/test_error_contract.py -v`
- `python -m uvicorn backend.app.main:app --reload`

<a id="b03"></a>

## B0.3 EnvironmentSettings 启动配置边界

**计划周期**：Week 1
**状态**：`[x]`
**目标**：建立服务启动前配置加载边界，使环境变量只服务启动、路径落点、前后端连接和凭据引用解析，不承载业务配置或运行上限。
**实施计划**：`docs/plans/implementation/b0.3-environment-settings.md`
**验证摘要**：`uv run --no-sync python -m pytest backend/tests/core/test_environment_settings.py -q` 通过；`uv run --no-sync python -m pytest backend/tests/test_engineering_baseline.py backend/tests/api/test_health.py backend/tests/api/test_error_contract.py backend/tests/core/test_environment_settings.py -q` 通过；`uv run --no-sync python -m pytest --collect-only` 收集 17 个 backend tests。测试覆盖 `pydantic-settings` 环境加载、默认工作区路径派生、默认运行数据根目录按 settings 构造时当前工作目录派生、显式工作区路径、凭据环境变量名前缀限制、默认凭据前缀不允许普通启动环境变量名、业务 / runtime / prompt / SQLite 逐库字段排除，以及测试专用 settings override 构造。

**修改文件列表**：
- Modify: `backend/app/core/config.py`
- Create: `backend/tests/support/settings.py`
- Create: `backend/tests/core/test_environment_settings.py`

**实现类/函数**：
- `EnvironmentSettings`
- `EnvironmentSettings.resolve_platform_runtime_root()`
- `EnvironmentSettings.resolve_workspace_root()`
- `EnvironmentSettings.is_allowed_credential_env_name(name: str) -> bool`
- `override_environment_settings(**values)`

**验收标准**：
- `EnvironmentSettings` 由 `pydantic-settings` 加载。
- 至少覆盖 `platform_runtime_root`、`default_project_root`、`workspace_root`、`backend_cors_origins`、`frontend_api_base_url` 和 `credential_env_prefixes`。
- `workspace_root` 未配置时默认派生为 `{platform_runtime_root}/workspaces`。
- 多 SQLite 职责库路径不逐个暴露为环境变量或用户配置；后续 C1.5 只能从 `platform_runtime_root` 派生默认路径。
- 不包含 Provider 的 `base_url`、`model_id`、能力声明、模板角色绑定、`system_prompt`、交付仓库、目标分支、代码评审请求类型、交付模式、Agent 循环上限、日志保留策略、上下文压缩阈值比例或 `compression_prompt`。
- 环境变量不得逐项展开 Provider 模型能力字段、`compression_threshold_ratio` 或其他业务配置。
- 不包含系统内置提示词正文、提示词资产版本切换、`prompt_id` 或 `prompt_version` 覆盖项。
- `credential_ref = env:<NAME>` 与 `api_key_ref = env:<NAME>` 只能解析受 `credential_env_prefixes` 允许的环境变量名。
- `override_environment_settings(**values)` 只能在测试中构造隔离 settings，不作为正式产品 API、环境变量矩阵或前端配置入口。
- 环境变量变更不要求热重载；测试环境替换路径通过 settings override 或 fixture 完成，并必须在测试结束后恢复全局 settings。

**测试方法**：
- `pytest backend/tests/core/test_environment_settings.py -v`

<a id="l01"></a>

## L0.1 运行数据目录与日志启动预检

**计划周期**：Week 1
**状态**：`[x]`
**目标**：基于 B0.3 的 `EnvironmentSettings` 建立平台运行数据根目录和 `.runtime/logs` 启动预检，使后端在接受用户命令前确认日志目录存在且可写。
**实施计划**：`docs/plans/implementation/l0.1-runtime-data-log-preflight.md`
**验证摘要**：`uv run --no-sync python -m pytest backend/tests/observability/test_runtime_data_preflight.py -q` 通过；`uv run --no-sync python -m pytest backend/tests/test_engineering_baseline.py backend/tests/api/test_health.py backend/tests/api/test_error_contract.py backend/tests/core/test_environment_settings.py backend/tests/observability/test_runtime_data_preflight.py -q` 通过；`uv run --no-sync python -m pytest --collect-only` 收集 28 个 backend tests；`uv run --no-sync python -m uvicorn backend.app.main:app --help` 退出码 0。测试覆盖运行数据根目录派生、`logs` 与 `logs/runs` 目录创建、`resolve_logs_dir()`、可写性探测、写入探测失败、不可用路径启动失败、`.runtime/logs` 平台私有标记、FastAPI lifespan 启动门禁、允许的本地前端来源 CORS preflight 与 GET 响应，以及未向 `EnvironmentSettings` 添加日志路径或逐库数据库路径字段。

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
- 运行数据根目录来源只能是 B0.3 的 `platform_runtime_root`，不读取用户业务配置。
- 启动前必须确保运行数据目录、`.runtime/logs` 与 `.runtime/logs/runs` 存在且可写。
- 目录不可创建或不可写时，后端不得进入可接受用户命令的正常运行状态。
- `.runtime/logs` 被明确标记为平台运行期私有数据，不属于目标项目工作区内容。
- 本切片不实现日志写入、日志索引、审计记录或日志查询 API。

**测试方法**：
- `pytest backend/tests/observability/test_runtime_data_preflight.py -v`

<a id="f01"></a>

## F0.1 前端 SPA 骨架与测试基线

**计划周期**：Week 1
**状态**：`[x]`
**目标**：建立 React SPA、路由、QueryClient 和测试工具基线，使控制台页面可以独立于后端实现并行推进。
**实施计划**：`docs/plans/implementation/f0.1-frontend-spa-baseline.md`
**验证摘要**：`npm --prefix frontend run test -- --run src/pages/__tests__/ConsolePage.test.tsx` 通过并覆盖控制台路由、路由导航、QueryClient Provider 和 shell landmarks；`npm --prefix frontend run test -- --run src/main.test.ts` 通过并保留 B0.1 bootstrap regression；`npm --prefix frontend run test -- --run` 通过；`npm --prefix frontend run build` 通过。前端设计质量门已记录默认产品型工作台基调；本切片未实现工作台三栏、业务组件、API client、SSE 或 Zustand 状态。

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
**状态**：`[x]`
**目标**：固化功能一 V1 的状态、阶段、模板、Provider、交付、工具确认、工具风险、事件和运行触发枚举，为后续 Schema、投影、事件矩阵和前端状态提供单一 machine value 来源。
**实施计划**：`docs/plans/implementation/c1.1-enum-contracts.md`
**验证摘要**：`uv run --no-sync python -m pytest backend/tests/schemas/test_enum_contracts.py -v` 通过 8 个枚举契约测试；`uv run --no-sync python -m pytest backend/tests/test_engineering_baseline.py backend/tests/api/test_health.py backend/tests/api/test_error_contract.py backend/tests/core/test_environment_settings.py backend/tests/observability/test_runtime_data_preflight.py backend/tests/schemas/test_enum_contracts.py -q` 通过 36 个 foundation regression tests；`uv run --no-sync python -m pytest --collect-only` 收集 36 个 backend tests 且无收集错误。TDD RED 先观察到缺少 `backend.app.domain.enums`，再观察到缺少 `backend.app.schemas.common`，随后 focused tests 转绿。

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
- `RunControlRecordType`
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
- `ToolConfirmationStatus`
- `ToolRiskLevel`
- `ToolRiskCategory`
- `ProviderCircuitBreakerStatus`
- `StageItemType`
- `SseEventType`

**验收标准**：
- `StageType` 只包含 `requirement_analysis`、`solution_design`、`code_generation`、`test_generation_execution`、`code_review`、`delivery_integration`。
- `FeedEntryType` 只包含 `user_message`、`stage_node`、`approval_request`、`tool_confirmation`、`control_item`、`approval_result`、`delivery_result`、`system_status`。
- `ApprovalType` 只包含 `solution_design_approval` 与 `code_review_approval`。
- `SessionStatus` 覆盖 `draft`、`running`、`paused`、`waiting_clarification`、`waiting_approval`、`waiting_tool_confirmation`、`completed`、`failed`、`terminated`。
- `RunStatus` 只覆盖 `running`、`paused`、`waiting_clarification`、`waiting_approval`、`waiting_tool_confirmation`、`completed`、`failed`、`terminated`。
- `StageStatus` 只覆盖 `running`、`waiting_clarification`、`waiting_approval`、`waiting_tool_confirmation`、`completed`、`failed`、`terminated`、`superseded`，不得包含底层装配态 `pending`。
- `ControlItemType` 至少包含 `clarification_wait`、`rollback`、`retry`；`retry` 只表示当前 run 内自动回归或阶段内再次尝试；`tool_confirmation` 不属于可见 `control_item` 顶层条目。
- `RunControlRecordType` 至少包含 `clarification_wait`、`rollback`、`retry`、`tool_confirmation`；其中 `tool_confirmation` 只作为运行过程留痕，不改变 `FeedEntryType.tool_confirmation` 的独立顶层交互语义。
- `TemplateSource` 只包含 `system_template`、`user_template`。
- `ProviderSource` 只包含 `builtin`、`custom`。
- `ProviderProtocolType` 至少包含 `openai_completions_compatible`。
- `ScmProviderType` 至少包含 `github`、`gitlab`。
- `CodeReviewRequestType` 只包含 `pull_request`、`merge_request`。
- `RunTriggerSource` 只包含 `initial_requirement`、`retry`、`ops_restart`；用户可见的“重新尝试”映射为机器值 `retry`。
- `ApprovalStatus` 至少包含 `pending`、`approved`、`rejected`、`cancelled`，其中 `pending` 只属于审批对象，不属于 `RunStatus` 或 `StageStatus`。
- `ToolConfirmationStatus` 只表达 `pending`、`allowed`、`denied`、`cancelled`；不得复用 `ApprovalStatus`。
- `ToolRiskLevel` 只表达 `read_only`、`low_risk_write`、`high_risk`、`blocked`。
- `ToolRiskCategory` 至少覆盖 `dependency_change`、`network_download`、`file_delete_or_move`、`broad_write`、`database_migration`、`lockfile_change`、`environment_config_change`、`unknown_command`、`credential_access`、`path_escape`、`platform_runtime_mutation`、`registry_or_audit_bypass`。
- `ProviderCircuitBreakerStatus` 至少覆盖 `closed`、`open`、`half_open`。
- `StageItemType` 至少包含 `dialogue`、`reasoning`、`decision`、`provider_call`、`tool_call`、`diff_preview`、`result`。
- `SseEventType` 覆盖正式后端规格中的会话级 SSE 事件类型，不允许前端 reducer 自行发明第二套事件名。
- `draft` 只表示尚未创建首个 `PipelineRun` 的 `Session`，不得出现在 `RunStatus` 中。
- 测试必须断言 `RunStatus` 不包含 `draft`，`RunStatus` 与 `StageStatus` 不包含 `pending`，`system_status` 与 `tool_confirmation` 不属于 `ControlItemType`，`ToolConfirmationStatus` 不包含 `approved` 或 `rejected`。

**测试方法**：
- `pytest backend/tests/schemas/test_enum_contracts.py -v`

<a id="c12"></a>

## C1.2 控制面 Schema 契约

**计划周期**：Week 2
**状态**：`[x]`
**目标**：定义 Project、Session、PipelineTemplate、AgentRole、Provider 和 DeliveryChannel 的请求响应 Schema，使控制面 API 有稳定字段边界。
**实施计划**：`docs/plans/implementation/c1.2-control-plane-schemas.md`
**验证摘要**：`uv run --no-sync python -m pytest backend/tests/schemas/test_control_plane_schemas.py -v` 通过 4 个控制面 Schema 契约测试；`uv run --no-sync python -m pytest backend/tests/schemas/test_enum_contracts.py backend/tests/schemas/test_control_plane_schemas.py -q` 通过 12 个 Schema contract tests；`uv run --no-sync python -m pytest backend/tests/test_engineering_baseline.py backend/tests/api/test_health.py backend/tests/api/test_error_contract.py backend/tests/core/test_environment_settings.py backend/tests/observability/test_runtime_data_preflight.py backend/tests/schemas/test_enum_contracts.py backend/tests/schemas/test_control_plane_schemas.py -q` 通过 40 个 foundation regression tests；`uv run --no-sync python -m pytest --collect-only` 收集 40 个 backend tests 且无收集错误。TDD RED 依次观察到缺少 `project`、`template`、`delivery_channel`、`configuration_package` schema 模块；评审修复中新增 RED 覆盖 `ProjectRead.name`、删除 / 移除结果不得声明物理删除，以及配置包 Provider 能力可省略待后端默认补齐的字段。

**修改文件列表**：
- Create: `backend/app/schemas/project.py`
- Create: `backend/app/schemas/session.py`
- Create: `backend/app/schemas/template.py`
- Create: `backend/app/schemas/provider.py`
- Create: `backend/app/schemas/delivery_channel.py`
- Create: `backend/app/schemas/configuration_package.py`
- Create: `backend/tests/schemas/test_control_plane_schemas.py`

**实现类/函数**：
- `ProjectRead`
- `SessionRead`
- `SessionRenameRequest`
- `SessionDeleteResult`
- `ProjectRemoveResult`
- `PipelineTemplateRead`
- `AgentRoleConfig`
- `ProviderRead`
- `ModelRuntimeCapabilities`
- `ProjectDeliveryChannelDetailProjection`
- `ConfigurationPackageRead`
- `ConfigurationPackageImportRequest`
- `ConfigurationPackageExport`

**验收标准**：
- `Project` 包含默认交付通道引用、默认项目标识和左栏展示名称；普通项目列表响应不得返回已移除 Project。
- `Session` 包含 `display_name`、`status`、`selected_template_id`、`current_run_id`、`latest_stage_type`。
- 会话重命名请求只表达新的 `display_name`，不得携带运行历史、审批记录、产物或 run 归属修改字段。
- 会话删除和项目移除结果 Schema 必须表达产品历史可见性变化、被活动 run 阻塞时的稳定错误语义，以及不删除本地项目文件夹、目标仓库、远端仓库、远端分支、提交或代码评审请求的边界。
- `PipelineTemplate` 区分 `system_template` 与 `user_template`，并包含固定阶段骨架、阶段槽位到 AgentRole 的绑定、槽位内最终生效的 `role_id` / `system_prompt` / `provider_id` 和自动回归配置。
- `AgentRoleConfig` 返回 `role_name` 作为展示标签；V1 不提供 `role_name` 修改字段。
- `Provider` 区分内置 Provider 与 custom Provider，且不暴露真实密钥。
- `Provider` Schema 必须能按模型表达 `ModelRuntimeCapabilities`，至少包含 `context_window_tokens`、`max_output_tokens`、`supports_tool_calling`、`supports_structured_output`、`supports_native_reasoning`。
- `context_window_tokens` 必须为正整数，未提供时默认 `128000`；该字段用于 Context Size Guard 判断压缩阈值，不属于 `EnvironmentSettings`。
- `max_output_tokens` 必须为正整数，未提供时由 Provider adapter 默认能力或内置 Provider 种子补齐；`supports_tool_calling`、`supports_structured_output`、`supports_native_reasoning` 必须为布尔值，未提供且无法从 Provider adapter 或内置种子解析时默认为 `false`。
- `DeliveryChannel` 包含 `credential_ref`、`credential_status`、`readiness_status`、`readiness_message` 和 `last_validated_at`。
- `ConfigurationPackage` Schema 必须包含 `package_schema_version` 与 `scope` 元数据，并能表达用户可见 Provider、DeliveryChannel 与 PipelineTemplate 槽位运行配置；Provider 模型能力允许按模型表达 `context_window_tokens`、`max_output_tokens`、`supports_tool_calling`、`supports_structured_output`、`supports_native_reasoning`。
- `ConfigurationPackage` Schema 不得表达独立 `AgentRole` 定义、`role_name` 修改、阶段骨架修改、阶段契约修改、工具权限修改或审批检查点修改。
- `ConfigurationPackage` 不得包含真实密钥明文、`PlatformRuntimeSettings`、`compression_threshold_ratio`、系统内置提示词正文、运行快照、历史 run、日志、审计正文或平台内部数据库路径。

**测试方法**：
- `pytest backend/tests/schemas/test_control_plane_schemas.py -v`

<a id="c13"></a>

## C1.3 Run、Feed 与事件 Schema 契约

**计划周期**：Week 2
**状态**：`[x]`
**目标**：定义 Run、Narrative Feed、Workspace Projection、Timeline Projection 与 SSE 事件载荷 Schema，使前端 mock 和增量合并基于同一契约。
**实施计划**：`docs/plans/implementation/c1.3-run-feed-event-schemas.md`
**验证摘要**：`uv run --no-sync python -m pytest backend/tests/schemas/test_run_feed_event_schemas.py -v` 通过 5 个 C1.3 schema contract tests；`uv run --no-sync python -m pytest backend/tests/schemas/test_enum_contracts.py backend/tests/schemas/test_control_plane_schemas.py backend/tests/schemas/test_run_feed_event_schemas.py -q` 通过 17 个 C1.1-C1.3 schema contract tests；`uv run --no-sync python -m pytest backend/tests/test_engineering_baseline.py backend/tests/api/test_health.py backend/tests/api/test_error_contract.py backend/tests/core/test_environment_settings.py backend/tests/observability/test_runtime_data_preflight.py backend/tests/schemas/test_enum_contracts.py backend/tests/schemas/test_control_plane_schemas.py backend/tests/schemas/test_run_feed_event_schemas.py -q` 通过 45 个 foundation regression tests；`uv run --no-sync python -m pytest --collect-only` 收集 45 个 backend tests 且无收集错误。TDD RED 依次观察到缺少 `backend.app.schemas.feed`、`backend.app.schemas.run`、`backend.app.schemas.workspace`、`backend.app.schemas.events`，并在内联评审中补充混合 SSE payload 与 delivery failure 边界红绿测试。

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
- `ToolConfirmationFeedEntry`
- `ProviderCallStageItem`
- `SolutionDesignArtifactRead`
- `ExecutionNodeProjection`
- `SessionEvent`

**验收标准**：
- `SessionWorkspaceProjection` 包含项目摘要、会话状态、run summaries、按 run 归属可分段的 Narrative Feed 和 Composer 状态。
- `RunTimelineProjection.entries[].type` 只允许正式顶层条目枚举。
- SSE `payload` 中的 `message_item`、`stage_node`、`approval_request`、`approval_result`、`tool_confirmation`、`control_item`、`delivery_result`、`system_status` 与查询投影同语义。
- `SolutionDesignArtifactRead` 必须包含 `implementation_plan`，并能表达稳定任务标识、任务顺序、依赖关系、修改范围、测试策略和下游引用所需字段；`Code Generation`、`Test Generation & Execution` 与 `Code Review` 的 Schema 必须能引用同一 `implementation_plan`。
- `tool_confirmation_requested` 与 `tool_confirmation_result` 事件载荷必须携带同名 `tool_confirmation` 投影，不得携带 `approval_id`、`approval_type`、`approve_action` 或 `reject_action`。
- `tool_confirmation` 必须是独立顶层 Narrative Feed 条目，不得作为 `approval_request` 或 `control_item` 的替代结构。
- 阶段内部 `provider_call` 条目必须能表达 Provider 调用状态、重试次数、指数退避等待摘要、熔断状态、失败原因摘要和对应过程记录引用。
- Requirement Analysis 阶段内澄清问答通过阶段内部条目表达，不提升为审批条目。

**测试方法**：
- `pytest backend/tests/schemas/test_run_feed_event_schemas.py -v`

<a id="c14"></a>

## C1.4 Inspector 与 Metrics Schema 契约

**计划周期**：Week 2
**状态**：`[x]`
**目标**：定义 Stage、ControlItem、DeliveryResult 的 Inspector 投影与量化指标 Schema，保证右栏深看信息以结构化原始记录为准。
**实施计划**：`docs/plans/implementation/c1.4-inspector-metrics-schemas.md`
**验证摘要**：`uv run --no-sync python -m pytest backend/tests/schemas/test_inspector_metrics_schemas.py -v` 通过 4 个 C1.4 Inspector / Metrics schema contract tests；`uv run --no-sync python -m pytest backend/tests/schemas/test_enum_contracts.py backend/tests/schemas/test_control_plane_schemas.py backend/tests/schemas/test_run_feed_event_schemas.py backend/tests/schemas/test_inspector_metrics_schemas.py -q` 通过 21 个 C1.1-C1.4 schema contract tests；`uv run --no-sync python -m pytest backend/tests/test_engineering_baseline.py backend/tests/api/test_health.py backend/tests/api/test_error_contract.py backend/tests/core/test_environment_settings.py backend/tests/observability/test_runtime_data_preflight.py backend/tests/schemas/test_enum_contracts.py backend/tests/schemas/test_control_plane_schemas.py backend/tests/schemas/test_run_feed_event_schemas.py backend/tests/schemas/test_inspector_metrics_schemas.py -q` 通过 49 个 foundation regression tests；`uv run --no-sync python -m pytest --collect-only` 收集 49 个 backend tests 且无收集错误。TDD RED 先观察到缺少 `backend.app.schemas.inspector`，新增 `MetricSet` 后仍保持缺少 Inspector 的预期 RED，再新增 Inspector schemas 后 focused tests 转绿。内联评审未发现 Critical 或 Important 问题。

**修改文件列表**：
- Create: `backend/app/schemas/inspector.py`
- Create: `backend/app/schemas/metrics.py`
- Create: `backend/tests/schemas/test_inspector_metrics_schemas.py`

**实现类/函数**：
- `StageInspectorProjection`
- `ControlItemInspectorProjection`
- `ToolConfirmationInspectorProjection`
- `DeliveryResultDetailProjection`
- `MetricSet`
- `InspectorSection`

**验收标准**：
- Inspector 投影按 `identity/input/process/output/artifacts/metrics` 分组。
- `StageInspectorProjection.stage_type` 只允许六个正式业务阶段。
- `ControlItemInspectorProjection.control_type` 只允许控制型条目语义。
- `ToolConfirmationInspectorProjection` 只用于高风险工具确认详情，不得返回 `ApprovalRequest` 或 `ControlItemInspectorProjection` 的替代结构。
- `StageInspectorProjection` 必须能展示 `SolutionDesignArtifact.implementation_plan`、`tool_confirmation_trace`、`provider_retry_trace` 与 `provider_circuit_breaker_trace` 的稳定引用。
- `approval_result` 不作为独立右栏对象时，其详情可通过所属阶段 Inspector 中的关联审批信息读取。
- 不适用指标允许缺省，不使用统一空值占位。

**测试方法**：
- `pytest backend/tests/schemas/test_inspector_metrics_schemas.py -v`

<a id="c15"></a>

## C1.5 多 SQLite 连接与 session 管理

**计划周期**：Week 2
**状态**：`[x]`
**目标**：建立 control、runtime、graph、event、log 多 SQLite 连接管理和 SQLAlchemy session 边界，不创建完整业务模型。
**实施计划**：`docs/plans/implementation/c1.5-multi-sqlite-session-management.md`
**验证摘要**：TDD RED 先观察到 `ModuleNotFoundError: No module named 'backend.app.db.base'`；实现数据库 role、session helper 与 Alembic 多库环境后，`uv run --no-sync python -m pytest backend/tests/db/test_database_sessions.py -q` 通过 5 个 C1.5 tests；`uv run --no-sync alembic -c backend/alembic.ini current` 退出码 0，并对五个 SQLite role 打印 `SQLiteImpl` 上下文；`uv run --no-sync python -m pytest backend/tests/db/test_database_sessions.py backend/tests/core/test_environment_settings.py backend/tests/observability/test_runtime_data_preflight.py -q` 通过 23 个 focused regression tests；`uv run --no-sync python -m pytest backend/tests/test_engineering_baseline.py backend/tests/api/test_health.py backend/tests/api/test_error_contract.py backend/tests/core/test_environment_settings.py backend/tests/observability/test_runtime_data_preflight.py backend/tests/schemas/test_enum_contracts.py backend/tests/schemas/test_control_plane_schemas.py backend/tests/schemas/test_run_feed_event_schemas.py backend/tests/schemas/test_inspector_metrics_schemas.py backend/tests/schemas/test_runtime_settings_schemas.py backend/tests/schemas/test_prompt_asset_schemas.py backend/tests/schemas/test_observability_schemas.py backend/tests/db/test_database_sessions.py -q` 通过 71 个 foundation regression tests；`uv run --no-sync python -m pytest --collect-only` 收集 71 个 tests。内联评审发现并修正默认 `.runtime/` 运行数据未被 Git 忽略的问题，未发现未解决 Critical 或 Important 问题。

**修改文件列表**：
- Modify: `.gitignore`
- Create: `backend/app/db/base.py`
- Create: `backend/app/db/session.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/versions/.gitkeep`
- Modify: `backend/tests/support/settings.py`
- Create: `backend/tests/db/test_database_sessions.py`

**实现类/函数**：
- `DatabaseRole`
- `DatabaseManager`
- `DatabaseManager.from_environment_settings(settings: EnvironmentSettings)`
- `get_control_session()`
- `get_runtime_session()`
- `get_graph_session()`
- `get_event_session()`
- `get_log_session()`
- `runtime_database_paths_fixture`

**验收标准**：
- 五类数据库角色可从 B0.3 的 `platform_runtime_root` 默认派生连接 URL，默认文件名为 `control.db`、`runtime.db`、`graph.db`、`event.db` 与 `log.db`。
- 测试环境可为五类数据库创建临时 SQLite 文件。
- session helper 不混用数据库角色。
- Alembic 环境能识别多数据库迁移目标。
- `log.db` 只用于日志轻量索引、审计台账、日志文件位置、载荷摘要、裁剪状态与关联标识，不承载领域事件或 Narrative Feed 投影来源数据。
- 正式产品配置面、前端设置和普通环境变量不得要求用户逐个配置五类 SQLite 文件路径；测试替换路径只能通过 fixture 或 settings override。
- `runtime_database_paths_fixture` 使用 B0.3 的 settings override 派生五类临时数据库路径，不允许引入逐库环境变量或测试专用业务配置字段。

**测试方法**：
- `pytest backend/tests/db/test_database_sessions.py -v`
- `alembic -c backend/alembic.ini current`

<a id="c16"></a>

## C1.6 control 模型与迁移边界

**计划周期**：Week 2
**状态**：`[x]`
**目标**：建立 `control.db` 的首批规范模型和迁移边界，确保项目、会话、模板、Provider 与项目级交付配置只在控制面持久化。
**验证摘要**：实施计划 `docs/plans/implementation/c1.6-control-model-boundary.md` 已完成。TDD RED 先观察到 `ModuleNotFoundError: No module named 'backend.app.db.models.control'`；实现 `backend/app/db/models/control.py` 并接入 Alembic metadata 后，`uv run --no-sync python -m pytest backend/tests/db/test_control_model_boundary.py -q` 通过 5 个 C1.6 tests；`uv run --no-sync alembic -c backend/alembic.ini current` 退出码 0，并对五个 SQLite role 打印 `SQLiteImpl` 上下文；经用户批准后，`uv run --no-sync alembic -c backend/alembic.ini upgrade head` 退出码 0，并对五个 SQLite role 打印 `SQLiteImpl` 上下文；`uv run --no-sync python -m pytest backend/tests/db/test_control_model_boundary.py -v` 通过 5 个 focused tests；`uv run --no-sync python -m pytest backend/tests/db/test_database_sessions.py backend/tests/db/test_control_model_boundary.py backend/tests/core/test_environment_settings.py backend/tests/observability/test_runtime_data_preflight.py -q` 通过 28 个 persistence regression tests；`uv run --no-sync python -m pytest backend/tests/test_engineering_baseline.py backend/tests/api/test_health.py backend/tests/api/test_error_contract.py backend/tests/core/test_environment_settings.py backend/tests/observability/test_runtime_data_preflight.py backend/tests/schemas/test_enum_contracts.py backend/tests/schemas/test_control_plane_schemas.py backend/tests/schemas/test_run_feed_event_schemas.py backend/tests/schemas/test_inspector_metrics_schemas.py backend/tests/schemas/test_runtime_settings_schemas.py backend/tests/schemas/test_prompt_asset_schemas.py backend/tests/schemas/test_observability_schemas.py backend/tests/db/test_database_sessions.py backend/tests/db/test_control_model_boundary.py -q` 通过 76 个 foundation regression tests；`uv run --no-sync python -m pytest --collect-only` 收集 76 个 backend tests。
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
- `PlatformRuntimeSettingsModel`

**验收标准**：
- `control.db` 承载 Project、Session、PipelineTemplate、Provider、DeliveryChannel 与项目级配置。
- `control.db` 承载 `PlatformRuntimeSettingsModel`，用于保存当前平台运行设置、配置版本、schema 版本、平台硬上限版本、创建时间、更新时间和审计关联字段。
- `PlatformRuntimeSettingsModel` 只保存 C1.10 定义的运行设置分组和版本元数据，不保存真实凭据、不保存 `compression_prompt`，也不保存逐库 SQLite 文件路径。
- `ProviderModel` 必须能按模型保存 `context_window_tokens`、`max_output_tokens`、`supports_tool_calling`、`supports_structured_output`、`supports_native_reasoning` 等运行时能力声明；缺省能力值在写入控制面模型前完成默认填充，不得在 run 启动或模型调用时临时推导。
- `Session` 规范实体只存在于 control 模型。
- control 模型必须能表达已加载 Project 的产品可见性、默认 Project 不可移除边界、Session 展示名和 Session 产品可见性。
- 会话删除和项目移除只能改变普通项目/会话历史、回看入口和产品查询投影的可见性；control 模型不得要求删除本地项目文件夹、目标仓库、远端仓库、远端分支、提交、代码评审请求或日志审计记录。
- `DeliveryChannel` 属于项目级配置，不属于 Session、模板或 runtime 模型。
- control 模型不包含 PipelineRun、StageRun、GraphThread、DomainEvent、RunLogEntry、AuditLogEntry 或 LogPayload。

**测试方法**：
- `pytest backend/tests/db/test_control_model_boundary.py -v`
- `alembic -c backend/alembic.ini upgrade head`

<a id="c17"></a>

## C1.7 runtime 模型与迁移边界

**计划周期**：Week 2
**状态**：`[x]`
**目标**：建立 `runtime.db` 的运行领域模型和迁移边界，确保 run、阶段、产物、审批、控制记录和交付记录作为产品级领域真源存在。
**实施计划**：`docs/plans/implementation/c1.7-runtime-model-boundary.md`
**验证摘要**：实施计划 `docs/plans/implementation/c1.7-runtime-model-boundary.md` 已完成。TDD RED 先观察到 `ModuleNotFoundError: No module named 'backend.app.db.models.runtime'`；实现 `backend/app/db/models/runtime.py` 并接入 Alembic metadata 后，`uv run --no-sync python -m pytest backend/tests/db/test_runtime_model_boundary.py -q` 通过 5 个 C1.7 tests。初次 GREEN 暴露 `PipelineRunModel` 与快照表之间的 SQLAlchemy sorted table 循环 warning，随后修正为 `PipelineRunModel` 持有结构化快照 FK、快照 `run_id` 保持非 FK 关联字段，focused tests 复跑无 warning。`uv run --no-sync alembic -c backend/alembic.ini current` 退出码 0，并对五个 SQLite role 打印 `SQLiteImpl` 上下文；经用户批准后，`uv run --no-sync alembic -c backend/alembic.ini upgrade head` 退出码 0，并对五个 SQLite role 打印 `SQLiteImpl` 上下文；`uv run --no-sync python -m pytest backend/tests/db/test_runtime_model_boundary.py -v` 通过 5 个 focused tests；`uv run --no-sync python -m pytest backend/tests/db/test_database_sessions.py backend/tests/db/test_control_model_boundary.py backend/tests/db/test_runtime_model_boundary.py backend/tests/core/test_environment_settings.py backend/tests/observability/test_runtime_data_preflight.py -q` 通过 33 个 persistence regression tests；`uv run --no-sync python -m pytest backend/tests/test_engineering_baseline.py backend/tests/api/test_health.py backend/tests/api/test_error_contract.py backend/tests/core/test_environment_settings.py backend/tests/observability/test_runtime_data_preflight.py backend/tests/schemas/test_enum_contracts.py backend/tests/schemas/test_control_plane_schemas.py backend/tests/schemas/test_run_feed_event_schemas.py backend/tests/schemas/test_inspector_metrics_schemas.py backend/tests/schemas/test_runtime_settings_schemas.py backend/tests/schemas/test_prompt_asset_schemas.py backend/tests/schemas/test_observability_schemas.py backend/tests/db/test_database_sessions.py backend/tests/db/test_control_model_boundary.py backend/tests/db/test_runtime_model_boundary.py -q` 通过 81 个 foundation regression tests；`uv run --no-sync python -m pytest --collect-only` 收集 81 个 backend tests。内联评审修正测试数据未创建对应 StageRun 的关系覆盖缺口，未发现未解决 Critical 或 Important 问题。

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
- `ToolConfirmationRequestModel`
- `RunControlRecordModel`
- `RuntimeLimitSnapshotModel`
- `ProviderCallPolicySnapshotModel`
- `ProviderSnapshotModel`
- `ModelBindingSnapshotModel`
- `DeliveryChannelSnapshotModel`
- `DeliveryRecordModel`

**验收标准**：
- `runtime.db` 承载 PipelineRun、StageRun、StageArtifact、ClarificationRecord、ApprovalRequest、ApprovalDecision、ToolConfirmationRequest、RunControlRecord、DeliveryChannelSnapshot、DeliveryRecord、结构化产物索引与运行摘要。
- runtime 模型通过 `session_id` 关联 control Session，不复制 `Session` 实体。
- `PipelineRunModel.delivery_channel_snapshot_ref` 必须指向 `DeliveryChannelSnapshotModel` 结构化快照记录，不得只是无所有权的 opaque string。
- `DeliveryChannelSnapshotModel` 必须包含 `delivery_mode`、`scm_provider_type`、`repository_identifier`、`default_branch`、`code_review_request_type`、`credential_ref`、`credential_status`、`readiness_status`、`readiness_message` 与 `last_validated_at`。
- `StageRun.stage_type` 只允许六个正式业务阶段。
- `StageRun.status` 必须支持 C1.1 定义的全部 `StageStatus`，包括运行终止时使用的 `terminated`。
- `RunControlRecord.control_type` 至少支持 `clarification_wait`、`rollback`、`retry`、`tool_confirmation`；`tool_confirmation` 只作为过程留痕，不作为可见 `ControlItemType`。
- `ToolConfirmationRequestModel` 必须记录确认对象、工具名称、命令或参数摘要、目标资源、风险等级、风险分类、预期副作用、替代路径判断、用户决定、状态、关联 StageRun、关联 GraphInterrupt、审计引用和过程记录引用。
- `ToolConfirmationRequestModel.status` 使用 `ToolConfirmationStatus`，不得复用 `ApprovalStatus` 或创建 `ApprovalDecisionModel`。
- run 尾部 `system_status` 不作为 `RunControlRecord.control_type` 持久化。
- `DeliveryRecord` 是正式领域对象，不由临时交付详情投影替代。
- `PipelineRunModel` 必须包含 `runtime_limit_snapshot_ref`。
- runtime 模型必须能持久化 `RuntimeLimitSnapshotModel`、`ProviderCallPolicySnapshotModel`、`ProviderSnapshotModel` 与 `ModelBindingSnapshotModel` 结构化快照；`PipelineRunModel` 持久化指向这些结构化快照的外键引用。
- `RuntimeLimitSnapshotModel` 必须保存实际生效值、来源配置版本、平台硬上限版本、schema 版本和固化时间，包括 `context_limits.compression_threshold_ratio`；不读取或引用最新 `PlatformRuntimeSettingsModel` 来解释历史 run。
- `ProviderCallPolicySnapshotModel` 必须保存请求超时、网络错误重试次数、限流重试次数、指数退避基准、指数退避上限、连续失败熔断阈值、熔断恢复条件、来源配置版本和 schema 版本。
- `ProviderSnapshotModel` 与 `ModelBindingSnapshotModel` 只保存凭据引用和能力声明快照，不保存真实密钥；能力声明快照必须包含实际模型的 `context_window_tokens`、`max_output_tokens`、`supports_tool_calling`、`supports_structured_output`、`supports_native_reasoning`。

**测试方法**：
- `pytest backend/tests/db/test_runtime_model_boundary.py -v`
- `alembic -c backend/alembic.ini upgrade head`

<a id="c18"></a>

## C1.8 graph 模型与迁移边界

**计划周期**：Week 2
**状态**：`[x]`
**目标**：建立 `graph.db` 的执行图状态模型和迁移边界，确保 GraphDefinition、GraphThread、GraphCheckpoint 与 GraphInterrupt 独立于产品领域模型存在。
**实施计划**：`docs/plans/implementation/c1.8-graph-model-boundary.md`
**验证摘要**：实施计划 `docs/plans/implementation/c1.8-graph-model-boundary.md` 已完成。TDD RED 先观察到 `ModuleNotFoundError: No module named 'backend.app.db.models.graph'`；实现 `backend/app/db/models/graph.py` 后，`uv run --no-sync python -m pytest backend/tests/db/test_graph_model_boundary.py -q` 通过 4 个初始 C1.8 tests。随后新增 Alembic metadata 导入测试，先观察到 `backend/alembic/env.py` 缺少 `backend.app.db.models.graph` 导入，再接入导入后 focused tests 通过 5 个 C1.8 tests。`uv run --no-sync alembic -c backend/alembic.ini current` 退出码 0，并对五个 SQLite role 打印 `SQLiteImpl` 上下文；经用户批准后，`uv run --no-sync alembic -c backend/alembic.ini upgrade head` 退出码 0，并对五个 SQLite role 打印 `SQLiteImpl` 上下文；`uv run --no-sync python -m pytest backend/tests/db/test_graph_model_boundary.py -v` 通过 5 个 focused tests；`uv run --no-sync python -m pytest backend/tests/db/test_database_sessions.py backend/tests/db/test_control_model_boundary.py backend/tests/db/test_runtime_model_boundary.py backend/tests/db/test_graph_model_boundary.py backend/tests/core/test_environment_settings.py backend/tests/observability/test_runtime_data_preflight.py -q` 通过 38 个 persistence regression tests；`uv run --no-sync python -m pytest backend/tests/test_engineering_baseline.py backend/tests/api/test_health.py backend/tests/api/test_error_contract.py backend/tests/core/test_environment_settings.py backend/tests/observability/test_runtime_data_preflight.py backend/tests/schemas/test_enum_contracts.py backend/tests/schemas/test_control_plane_schemas.py backend/tests/schemas/test_run_feed_event_schemas.py backend/tests/schemas/test_inspector_metrics_schemas.py backend/tests/schemas/test_runtime_settings_schemas.py backend/tests/schemas/test_prompt_asset_schemas.py backend/tests/schemas/test_observability_schemas.py backend/tests/db/test_database_sessions.py backend/tests/db/test_control_model_boundary.py backend/tests/db/test_runtime_model_boundary.py backend/tests/db/test_graph_model_boundary.py -q` 通过 86 个 foundation regression tests；`uv run --no-sync python -m pytest --collect-only` 收集 86 个 backend tests。内联评审未发现未解决 Critical 或 Important 问题。

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
- GraphInterrupt 能表达澄清、审批与工具确认中断类型，并可关联 runtime 领域对象。
- `GraphInterrupt.interrupt_type = tool_confirmation` 必须能关联 `ToolConfirmationRequestModel`，不得关联 `ApprovalRequestModel` 或 `ApprovalDecisionModel`。

**测试方法**：
- `pytest backend/tests/db/test_graph_model_boundary.py -v`
- `alembic -c backend/alembic.ini upgrade head`

<a id="c19"></a>

## C1.9 event 模型边界

**计划周期**：Week 2
**状态**：`[x]`
**目标**：建立 `event.db` 的领域事件和 Narrative Feed 投影来源数据边界，使查询投影与 SSE 增量共享同一事件来源，并明确审计记录不属于 `event.db`。
**实施计划**：`docs/plans/implementation/c1.9-event-model-boundary.md`
**验证摘要**：实施计划 `docs/plans/implementation/c1.9-event-model-boundary.md` 已完成。TDD RED 先观察到缺少 `backend.app.db.models.event`，以及 Alembic env 缺少 event 模型导入；实现 `backend/app/db/models/event.py` 后，focused tests 剩余 Alembic 导入断言失败；接入 `backend/alembic/env.py` 导入后，`uv run --no-sync python -m pytest backend/tests/db/test_event_model_boundary.py -q` 通过 5 个 C1.9 tests。`uv run --no-sync alembic -c backend/alembic.ini current` 退出码 0；经用户批准后，`uv run --no-sync alembic -c backend/alembic.ini upgrade head` 退出码 0；`uv run --no-sync python -m pytest backend/tests/db/test_event_model_boundary.py -v` 通过 5 个 focused tests；`uv run --no-sync python -m pytest backend/tests/db/test_database_sessions.py backend/tests/db/test_control_model_boundary.py backend/tests/db/test_runtime_model_boundary.py backend/tests/db/test_graph_model_boundary.py backend/tests/db/test_event_model_boundary.py backend/tests/core/test_environment_settings.py backend/tests/observability/test_runtime_data_preflight.py -q` 通过 43 个 persistence regression tests；`uv run --no-sync python -m pytest backend/tests/test_engineering_baseline.py backend/tests/api/test_health.py backend/tests/api/test_error_contract.py backend/tests/core/test_environment_settings.py backend/tests/observability/test_runtime_data_preflight.py backend/tests/schemas/test_enum_contracts.py backend/tests/schemas/test_control_plane_schemas.py backend/tests/schemas/test_run_feed_event_schemas.py backend/tests/schemas/test_inspector_metrics_schemas.py backend/tests/schemas/test_runtime_settings_schemas.py backend/tests/schemas/test_prompt_asset_schemas.py backend/tests/schemas/test_observability_schemas.py backend/tests/db/test_database_sessions.py backend/tests/db/test_control_model_boundary.py backend/tests/db/test_runtime_model_boundary.py backend/tests/db/test_graph_model_boundary.py backend/tests/db/test_event_model_boundary.py -q` 通过 91 个 foundation regression tests；`uv run --no-sync python -m pytest --collect-only` 收集 91 个 backend tests。内联评审未发现未解决 Critical 或 Important 问题。

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

<a id="c110"></a>

## C1.10 PlatformRuntimeSettings 与运行快照 Schema 契约

**计划周期**：Week 2
**状态**：`[x]`
**目标**：定义可热重载平台运行设置、运行上限快照、Provider 快照与模型绑定快照 Schema，使后续控制面、Run 启动和 runtime 消费共享同一配置边界。
**实施计划**：`docs/plans/implementation/c1.10-platform-runtime-settings-snapshots.md`
**验证摘要**：`uv run --no-sync python -m pytest backend/tests/schemas/test_runtime_settings_schemas.py -v` 通过 5 个 C1.10 runtime settings schema contract tests；`uv run --no-sync python -m pytest backend/tests/schemas/test_enum_contracts.py backend/tests/schemas/test_control_plane_schemas.py backend/tests/schemas/test_run_feed_event_schemas.py backend/tests/schemas/test_inspector_metrics_schemas.py backend/tests/schemas/test_runtime_settings_schemas.py -q` 通过 28 个 C1.1-C1.4 + C1.10 schema contract tests；`uv run --no-sync python -m pytest backend/tests/test_engineering_baseline.py backend/tests/api/test_health.py backend/tests/api/test_error_contract.py backend/tests/core/test_environment_settings.py backend/tests/observability/test_runtime_data_preflight.py backend/tests/schemas/test_enum_contracts.py backend/tests/schemas/test_control_plane_schemas.py backend/tests/schemas/test_run_feed_event_schemas.py backend/tests/schemas/test_inspector_metrics_schemas.py backend/tests/schemas/test_runtime_settings_schemas.py -q` 通过 56 个 foundation regression tests；`uv run --no-sync python -m pytest --collect-only` 收集 56 个 backend tests 且无收集错误。TDD RED 先观察到缺少 `backend.app.schemas.runtime_settings`、`RuntimeSettingsErrorCode` 和 `RunConfigurationSnapshotRead`，再按错误码适配、runtime settings schema、run configuration snapshot 聚合 schema 顺序转绿。内联评审未发现 Critical 或 Important 问题。

**修改文件列表**：
- Modify: `backend/app/api/error_codes.py`
- Create: `backend/app/schemas/runtime_settings.py`
- Modify: `backend/app/schemas/run.py`
- Create: `backend/tests/schemas/test_runtime_settings_schemas.py`

**实现类/函数**：
- `RuntimeSettingsErrorCode`
- `PlatformRuntimeSettingsRead`
- `PlatformRuntimeSettingsUpdate`
- `PlatformRuntimeSettingsVersion`
- `AgentRuntimeLimits`
- `ProviderCallPolicy`
- `ProviderCallPolicySnapshotRead`
- `ContextLimits`
- `LogPolicy`
- `PlatformHardLimits`
- `RuntimeLimitSnapshotRead`
- `ProviderSnapshotRead`
- `ModelBindingSnapshotRead`

**验收标准**：
- `PlatformRuntimeSettingsRead` 至少包含 `agent_limits`、`provider_call_policy`、`context_limits`、`log_policy` 四个分组。
- `agent_limits` 至少包含 `max_react_iterations_per_stage`、`max_tool_calls_per_stage`、`max_file_edit_count`、`max_patch_attempts_per_file`、`max_structured_output_repair_attempts`、`max_auto_regression_retries`、`max_clarification_rounds`、`max_no_progress_iterations`。
- `provider_call_policy` 覆盖 Provider 请求超时、网络错误重试次数、限流重试次数、指数退避基准、指数退避上限、连续失败熔断阈值和熔断恢复条件。
- `context_limits` 覆盖工具输出、`bash` stdout / stderr、`grep` 返回、文件读取、模型输出进入日志或过程记录的裁剪限制，以及 `compression_threshold_ratio`。
- `compression_threshold_ratio` 默认值为 `0.8`，必须大于 `0` 且小于 `1`，用于与模型能力快照中的 `context_window_tokens` 共同计算上下文压缩触发阈值。
- `log_policy` 覆盖普通运行日志保留周期、审计日志保留周期、日志轮转大小、日志查询默认 `limit` 与最大 `limit`。
- 所有可写运行上限 Schema 均表达平台硬上限校验所需字段，超过硬上限时由 C2.8 拒绝保存。
- `PlatformRuntimeSettingsRead` 必须包含当前配置版本、schema 版本、平台硬上限版本、更新时间和只读硬上限摘要；`PlatformRuntimeSettingsUpdate` 必须支持携带期望配置版本用于并发冲突检测。
- `RuntimeSettingsErrorCode` 必须复用 B0.2 的错误码体系，并固定 `config_invalid_value`、`config_hard_limit_exceeded`、`config_version_conflict`、`config_storage_unavailable`、`config_snapshot_unavailable`。
- `RuntimeLimitSnapshotRead` 记录实际生效值、来源配置版本和平台硬上限版本，并包含固化后的 `compression_threshold_ratio`。
- `ProviderCallPolicySnapshotRead` 记录本次 run 固化的请求超时、重试次数、指数退避参数、熔断阈值、熔断恢复条件、来源配置版本和 schema 版本。
- `ProviderSnapshotRead` 与 `ModelBindingSnapshotRead` 能表达 run 启动时实际使用的 Provider、模型、凭据引用、能力声明和 schema 版本；能力声明必须包含 `context_window_tokens`、`max_output_tokens`、`supports_tool_calling`、`supports_structured_output`、`supports_native_reasoning`。
- `compression_prompt` 不出现在 `EnvironmentSettings`、`PlatformRuntimeSettingsRead`、`PlatformRuntimeSettingsUpdate` 或前端可写配置 Schema 中；若压缩过程需要记录提示词，只能记录系统内置提示词资产版本引用。

**测试方法**：
- `pytest backend/tests/schemas/test_runtime_settings_schemas.py -v`

<a id="c110a"></a>

## C1.10a PromptAsset Schema 契约

**计划周期**：Week 2
**状态**：`[x]`
**目标**：固定系统内置提示词资产的结构化 Schema、版本字段、权威级别和缓存属性，使后续 PromptRegistry、模板种子、ContextManifest 和压缩过程引用同一契约。
**实施计划**：`docs/plans/implementation/c1.10a-prompt-asset-schemas.md`
**验证摘要**：`uv run --no-sync python -m pytest backend/tests/schemas/test_prompt_asset_schemas.py -v` 通过 5 个 C1.10a PromptAsset schema contract tests；`uv run --no-sync python -m pytest backend/tests/schemas/test_enum_contracts.py backend/tests/schemas/test_control_plane_schemas.py backend/tests/schemas/test_run_feed_event_schemas.py backend/tests/schemas/test_inspector_metrics_schemas.py backend/tests/schemas/test_runtime_settings_schemas.py backend/tests/schemas/test_prompt_asset_schemas.py -q` 通过 33 个 schema contract tests；`uv run --no-sync python -m pytest backend/tests/test_engineering_baseline.py backend/tests/api/test_health.py backend/tests/api/test_error_contract.py backend/tests/core/test_environment_settings.py backend/tests/observability/test_runtime_data_preflight.py backend/tests/schemas/test_enum_contracts.py backend/tests/schemas/test_control_plane_schemas.py backend/tests/schemas/test_run_feed_event_schemas.py backend/tests/schemas/test_inspector_metrics_schemas.py backend/tests/schemas/test_runtime_settings_schemas.py backend/tests/schemas/test_prompt_asset_schemas.py -q` 通过 61 个 foundation regression tests；`uv run --no-sync python -m pytest --collect-only` 收集 61 个 backend tests 且无收集错误。TDD RED 先观察到缺少 `backend.app.schemas.prompts`，再按 PromptAsset 枚举、引用、正文 hash 和系统资产边界转绿。内联评审未发现 Critical 或 Important 问题。

**修改文件列表**：
- Create: `backend/app/schemas/prompts.py`
- Create: `backend/tests/schemas/test_prompt_asset_schemas.py`

**实现类/函数**：
- `PromptType`
- `PromptAuthorityLevel`
- `PromptCacheScope`
- `ModelCallType`
- `PromptAssetRef`
- `PromptAssetRead`
- `PromptSectionRead`
- `PromptVersionRef`
- `PromptRenderMetadata`
- `PromptAssetRead.validate_prompt_identity()`
- `PromptAssetRead.validate_system_asset_boundary()`

**验收标准**：
- `PromptAssetRead` 必须包含 `prompt_id`、`prompt_version`、`prompt_type`、`authority_level`、`model_call_type`、`cache_scope`、`source_ref`、`content_hash` 和可选 `applies_to_stage_types`。
- Markdown 文件名不承载版本号；`prompt_version` 必须来自 YAML front matter，并作为版本真源进入 `PromptAssetRead`、`PromptVersionRef`、`ContextManifest` 和过程记录。
- `PromptType` 至少支持 `runtime_instructions`、`stage_prompt_fragment`、`structured_output_repair`、`compression_prompt`、`agent_role_seed`、`tool_usage_template`。
- `PromptAuthorityLevel` 必须区分 `system_trusted`、`stage_contract_rendered`、`agent_role_prompt`、`tool_description_rendered`。
- `PromptCacheScope` 至少支持 `global_static`、`run_static`、`dynamic_uncached`，并用于后续 ContextManifest 记录，不作为 Provider cache API 直接承诺。
- `PromptVersionRef` 必须能进入 run 快照引用、`ContextManifest` 和 `CompressedContextBlock` 过程记录。
- `content_hash` 必须基于剥离 YAML front matter 后的提示词正文计算；front matter 元数据不得作为模型可见提示词正文导入或渲染。
- `agent_role_seed` 只能作为系统模板初始化来源；Schema 不允许把用户编辑后的 `system_prompt` 标记为 `system_trusted`。
- `compression_prompt` 只能通过 `prompt_id` / `prompt_version` 表达；不得出现在 `EnvironmentSettings`、`PlatformRuntimeSettingsRead` 或任何前端可写配置 Schema 中。
- Schema 测试必须覆盖合法资产、缺失版本、非法 authority 升级、非法 `compression_prompt` 配置化和 `agent_role_seed` 被误标为系统可信的失败场景。

**测试方法**：
- `pytest backend/tests/schemas/test_prompt_asset_schemas.py -v`

<a id="l11"></a>

## L1.1 日志审计 Schema 与 TraceContext 契约

**计划周期**：Week 2
**状态**：`[x]`
**目标**：定义日志审计查询投影、日志审计枚举、查询参数和跨层 TraceContext，使后续 API、runtime、工具和交付切片共享同一关联语义。
**实施计划**：`docs/plans/implementation/l1.1-log-audit-schema-trace-context.md`
**验证摘要**：`uv run --no-sync python -m pytest backend/tests/schemas/test_observability_schemas.py -v` 通过 5 个 L1.1 observability schema contract tests；`uv run --no-sync python -m pytest backend/tests/schemas/test_enum_contracts.py backend/tests/schemas/test_control_plane_schemas.py backend/tests/schemas/test_run_feed_event_schemas.py backend/tests/schemas/test_inspector_metrics_schemas.py backend/tests/schemas/test_runtime_settings_schemas.py backend/tests/schemas/test_prompt_asset_schemas.py backend/tests/schemas/test_observability_schemas.py -q` 通过 38 个 schema contract regression tests；`uv run --no-sync python -m pytest backend/tests/test_engineering_baseline.py backend/tests/api/test_health.py backend/tests/api/test_error_contract.py backend/tests/core/test_environment_settings.py backend/tests/observability/test_runtime_data_preflight.py backend/tests/schemas/test_enum_contracts.py backend/tests/schemas/test_control_plane_schemas.py backend/tests/schemas/test_run_feed_event_schemas.py backend/tests/schemas/test_inspector_metrics_schemas.py backend/tests/schemas/test_runtime_settings_schemas.py backend/tests/schemas/test_prompt_asset_schemas.py backend/tests/schemas/test_observability_schemas.py -q` 通过 66 个 foundation regression tests；`uv run --no-sync python -m pytest --collect-only` 收集 66 个 backend tests 且无收集错误。TDD RED 先观察到缺少 `backend.app.schemas.observability` / `backend.app.domain.trace_context`，再按日志审计投影、查询参数和 TraceContext 继承契约转绿；内联评审修正 `RedactionStatus` 枚举口径、`log_file_ref` 路径边界和子 span 继承保护后未发现未解决 Critical 或 Important 问题。

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
