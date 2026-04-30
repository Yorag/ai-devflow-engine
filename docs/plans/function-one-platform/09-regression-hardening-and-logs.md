# 09 回归、硬化与日志收尾

## 范围

本分卷覆盖 Week 11-12 的完整 API flow、Playwright E2E、OpenAPI 与前端 client 一致性、错误态回归、配置边界回归、日志轮转保留清理、日志审计回归包和发布候选清单。完成后，功能一 V1 具备端到端回归、配置边界回归、日志审计回归和发布候选验收条件。

本分卷只做跨端回归、硬化和收尾验证，不重新定义前序分卷的领域契约、工具协议、runtime 语义、交付语义或前端交互语义。发现前序任务缺口时，必须回到对应分卷任务修正，不能在本分卷通过临时语义补丁覆盖。

回归、硬化和日志收尾必须覆盖高风险工具确认、Provider retry/circuit breaker、无长期记忆边界、`.runtime/logs` 排除、审计记录裁剪、OpenAPI path/method/schema、前端错误态和发布候选清单。

<a id="v61"></a>

## V6.1 后端完整 API flow 测试

**计划周期**：Week 11
**状态**：`[ ]`
**目标**：建立后端完整 API flow 测试，覆盖从新建会话到交付结果的主要成功路径。
**实施计划**：`docs/plans/implementation/v6.1-backend-full-api-flow.md`

**修改文件列表**：
- Create: `backend/tests/e2e/test_full_api_flow.py`

**实现类/函数**：
- `seedFullFlowFixture()`
- `startDeterministicRunFixture()`
- `assertWorkspaceMatchesRunState()`

**验收标准**：
- 可从新建 Session 完整走到 `delivery_result`。
- API 返回的 Session、Run、Timeline、Inspector 和 DeliveryRecord 投影一致。
- API flow 必须覆盖 `tool_confirmation` 顶层条目、工具确认 allow / deny API 和 `ToolConfirmationInspectorProjection` 的基本一致性。
- API flow 必须覆盖 Provider 重试或熔断过程记录能进入阶段投影或 Inspector。
- 不依赖真实模型和真实远端托管平台。

**测试方法**：
- `pytest backend/tests/e2e/test_full_api_flow.py -v`

<a id="v62"></a>

## V6.2 Playwright 成功路径

**计划周期**：Week 11
**状态**：`[ ]`
**目标**：建立跨端成功路径 E2E，验证用户可在单一控制台完成输入、审批和交付结果回看。
**实施计划**：`docs/plans/implementation/v6.2-playwright-success-flow.md`

**修改文件列表**：
- Create: `e2e/package.json`
- Create: `e2e/playwright.config.ts`
- Create: `e2e/tests/function-one-full-flow.spec.ts`

**实现类/函数**：
- Playwright scenario for new requirement, clarification, approvals, delivery result.

**验收标准**：
- `e2e/package.json` 定义 `test` 脚本，使 `npm --prefix e2e run test` 可执行 Playwright。
- 用户可新建会话、发送首条需求、完成澄清、通过两次审批并看到 `delivery_result`。
- 前端显示与后端投影一致。
- Narrative Feed、Run Switcher、Composer 和 Inspector 关键交互可用。

**前端设计质量门**：
- 不新增风格输入；验证完整流程继承同一项目级主基调。
- 成功路径必须检查 Narrative Feed、Run Switcher、Composer、Approval Block、Inspector 和 DeliveryResultBlock 的 UI 状态一致性。
- Playwright 断言或截图检查必须覆盖关键 UI 状态稳定性、文本不溢出、窄屏可用性和焦点路径。

**测试方法**：
- `npm --prefix e2e run test -- function-one-full-flow.spec.ts`

<a id="v63"></a>

## V6.3 Playwright 人工介入路径

**计划周期**：Week 11
**状态**：`[ ]`
**目标**：建立跨端人工介入与工具确认 E2E，覆盖拒绝回退、高风险工具确认、暂停恢复、终止和重新尝试。
**实施计划**：`docs/plans/implementation/v6.3-playwright-control-flow.md`

**修改文件列表**：
- Create: `e2e/tests/function-one-control-flow.spec.ts`

**实现类/函数**：
- Playwright scenarios for reject rollback, tool confirmation allow/deny, pause, resume, terminate, rerun.

**验收标准**：
- 可覆盖审批拒绝回退到正确阶段。
- 可覆盖高风险工具确认允许和拒绝，且拒绝不展示审批回退语义。
- 可覆盖暂停后审批禁用，恢复后继续等待同一审批。
- 可覆盖暂停后工具确认禁用，恢复后继续等待同一工具确认。
- 可覆盖终止后尾部 `system_status`。
- 可覆盖重新尝试创建新 run 并移动焦点。

**前端设计质量门**：
- 不新增风格输入；验证人工介入路径继承同一项目级主基调。
- 人工介入路径必须检查拒绝回退、高风险工具确认、暂停恢复、终止、重新尝试、历史审批禁用态和历史工具确认禁用态。
- Playwright 断言或截图检查必须覆盖危险操作层级、禁用态、历史态、错误态和新 run 分界。

**测试方法**：
- `npm --prefix e2e run test -- function-one-control-flow.spec.ts`

<a id="v64"></a>

## V6.4 OpenAPI 核心路由覆盖

**计划周期**：Week 11-12
**状态**：`[ ]`
**目标**：验证 OpenAPI 覆盖功能一全部核心 REST 接口、SSE 端点和事件载荷说明。
**实施计划**：`docs/plans/implementation/v6.4-openapi-route-coverage.md`

**修改文件列表**：
- Create: `docs/api/function-one-openapi-notes.md`
- Create: `backend/tests/api/test_openapi_contract.py`
- Modify: `README.md`

**实现类/函数**：
- `assert_openapi_contains_core_routes()`
- `assert_openapi_contains_event_stream_schema()`

**验收标准**：
- `/api/openapi.json` 覆盖所有核心 REST 接口。
- `/api/docs` 可读。
- OpenAPI 覆盖 `GET /api/sessions/{sessionId}/events/stream` 的事件流端点及其事件载荷结构。
- OpenAPI 覆盖 `POST /api/tool-confirmations/{toolConfirmationId}/allow`、`POST /api/tool-confirmations/{toolConfirmationId}/deny` 与 `GET /api/tool-confirmations/{toolConfirmationId}` 的请求、响应、错误和详情投影 Schema。
- OpenAPI 覆盖 `GET /api/runs/{runId}/logs`、`GET /api/stages/{stageRunId}/logs` 与 `GET /api/audit-logs` 的查询参数、响应 Schema 和主要错误响应。
- V6.4 验证各 API 切片已经提交的 OpenAPI 断言汇总结果，不作为具体路由第一次补齐 OpenAPI 契约的切片。
- 运行接口与 OpenAPI 文档同版本交付。

**测试方法**：
- `pytest backend/tests/api/test_openapi_contract.py -v`

<a id="v65"></a>

## V6.5 前端 client 与 OpenAPI 一致性

**计划周期**：Week 11-12
**状态**：`[ ]`
**目标**：验证前端 API client 与 OpenAPI 路径一致，避免前后端接口漂移。
**实施计划**：`docs/plans/implementation/v6.5-frontend-openapi-compat.md`

**修改文件列表**：
- Create: `frontend/src/api/__tests__/openapi-compat.test.ts`

**实现类/函数**：
- `assert_frontend_client_paths_match_openapi()`
- `collectFrontendApiPaths()`

**验收标准**：
- 前端 API client 路径与 OpenAPI 路径一致。
- 前端不调用未定义接口。
- OpenAPI 变更能触发 client 兼容性测试失败。

**测试方法**：
- `npm --prefix frontend run test -- openapi-compat`

<a id="v66"></a>

## V6.6 前端错误态与后端错误回归

**计划周期**：Week 12
**状态**：`[ ]`
**目标**：补齐关键 API 错误的前端展示和后端错误回归测试，使用户能理解失败原因。
**实施计划**：`docs/plans/implementation/v6.6-error-states-regression.md`

**修改文件列表**：
- Modify: `backend/app/api/error_codes.py`
- Create: `backend/tests/regression/test_error_contract_regression.py`
- Create: `frontend/src/features/errors/ErrorState.tsx`
- Create: `frontend/src/features/errors/__tests__/ErrorState.test.tsx`

**实现类/函数**：
- `ErrorState`
- `formatApiError()`
- `assertApiErrorContractStable()`
- `assertErrorCodeCatalogCoversRuntimeAndToolErrors()`

**验收标准**：
- 关键 API 错误在前端有清晰状态。
- paused 审批提交、非法重新尝试、DeliveryChannel 未 ready 等错误有稳定错误码。
- 运行数据目录不可写、审计写入失败、日志查询参数非法和日志载荷被阻断等后端错误有稳定错误码。
- ToolRegistry 拒绝、工具输入 Schema 非法、工作区越界、工具超时、高风险工具确认未允许、工具确认不可提交、blocked 风险、bash allowlist 拒绝、Provider 重试耗尽、Provider 熔断开启、delivery snapshot 缺失 / 未 ready、Git CLI 失败和远端交付请求失败必须进入 W5.0a 统一错误码回归。
- 错误码回归必须断言每个错误响应的 `error_code` 已注册、HTTP 状态匹配字典、用户可见消息不包含堆栈或凭据，且 trace 关联字段保留。
- 前端不展示真实凭据内容。

**前端设计质量门**：
- 不新增风格输入；错误态继承项目级主基调。
- 实现后必须检查错误标题、错误详情、恢复动作、敏感信息隐藏、长错误消息、焦点恢复和移动端布局。
- 前端错误态必须解释用户可采取的下一步，不得暴露真实凭据内容或后端内部堆栈。

**测试方法**：
- `pytest backend/tests/regression/test_error_contract_regression.py -v`
- `npm --prefix frontend run test -- ErrorState`

<a id="v68"></a>

## V6.8 配置边界与运行快照回归

**计划周期**：Week 12
**状态**：`[ ]`
**目标**：补齐环境变量、平台运行设置、业务配置、系统内置提示词资产、前端设置边界和运行快照的跨链路回归，确保后续热重载或配置变更不破坏已启动 run 的语义。
**实施计划**：`docs/plans/implementation/v6.8-config-snapshot-regression.md`

**修改文件列表**：
- Create: `backend/tests/regression/test_config_snapshot_regression.py`
- Create: `backend/tests/regression/test_prompt_asset_boundary_regression.py`
- Create: `backend/tests/regression/test_project_session_history_regression.py`
- Create: `frontend/src/features/settings/__tests__/SettingsBoundary.test.tsx`
- Create: `frontend/src/features/workspace/__tests__/ProjectSessionHistory.test.tsx`

**实现类/函数**：
- `assertEnvironmentSettingsBoundary()`
- `assertRuntimeSettingsDoNotMutateStartedRun()`
- `assertPromptAssetsDoNotMutateStartedRun()`
- `assertPromptAssetsNotUserConfigurable()`
- `assertSettingsModalBoundary()`
- `assertProjectSessionHistoryBoundary()`
- `assertSettingsOverrideFixtureBoundary()`

**验收标准**：
- 环境变量只覆盖启动路径、前后端连接、工作区根目录、日志落点和凭据引用解析；不得承载 Provider、Provider 模型能力字段、DeliveryChannel、模板运行配置、Agent 运行上限、日志策略、`compression_threshold_ratio`、系统内置提示词正文、提示词资产版本切换、`prompt_id`、`prompt_version` 或 `compression_prompt`。
- 配置包只允许作为项目作用域用户可见配置的备份、迁移和环境复制入口；Agent Runtime、Context Management、Provider adapter 和历史回放不得直接读取配置包。
- 五类 SQLite 文件路径从平台运行数据根目录默认派生；普通前端设置和用户配置不得逐个配置数据库路径。
- 更新 `PlatformRuntimeSettings` 后，新 run 使用新版本，已启动 run 继续使用自身 `RuntimeLimitSnapshot`；配置包不得写入 `compression_threshold_ratio`。
- 更新 Provider 配置、凭据引用、`context_window_tokens`、`max_output_tokens`、`supports_tool_calling`、`supports_structured_output`、`supports_native_reasoning` 或其他能力声明后，新 run 使用新 Provider/模型绑定快照，已启动 run 不改变 ProviderSnapshot 或 ModelBindingSnapshot。
- DeliveryChannel 更新只影响后续新启动 run；对尚未固化交付通道快照的当前活动 run，只能用于后续交付就绪校验和交付快照固化。
- 前端设置弹窗不展示环境变量、平台运行数据目录、SQLite 路径、平台运行上限、日志策略、系统内置提示词资产、提示词版本切换、`runtime_instructions`、结构化输出修复提示词、`compression_prompt` 或 `deterministic test runtime`；Provider 模型能力只在折叠 `高级设置` 中展示，配置包导出不得包含真实密钥、平台隐性运行设置、系统内置提示词正文、运行快照、历史 run、日志或审计正文。
- 模板编辑器不展示系统内置提示词资产、提示词版本切换、`runtime_instructions`、结构化输出修复提示词或 `compression_prompt`；用户编辑的 `system_prompt` 只作为模板槽位运行配置保存。
- `compression_prompt` 只作为系统内置提示词资产的 `prompt_id`、`prompt_version` 和渲染 hash 出现在压缩过程记录中，不进入环境变量、配置 API、前端设置或模板编辑字段。
- Context Size Guard 回归必须验证默认 `context_window_tokens = 128000` 与 `compression_threshold_ratio = 0.8` 计算出 `102400` token 基础压缩触发阈值，验证 `max_output_tokens` 只能收紧输出预算或预留输出 token，验证 `supports_tool_calling`、`supports_structured_output`、`supports_native_reasoning` 分别影响工具绑定、结构化输出路径和原生推理记录边界，并验证已启动 run 不受后续 Provider 能力或阈值配置变更影响。
- 已启动 run 的 `ContextManifest`、压缩过程记录和模型调用过程必须能通过提示词版本引用、`content_hash` 与 `render_hash` 解释；最新提示词资产版本不得改变既有 run 的模板快照、ContextManifest 或压缩记录语义。
- `PromptRegistry` 不接受环境变量、平台运行设置、前端设置、模板编辑字段或用户消息作为系统内置提示词资产来源。
- W5.0c `settings_override_fixture()` 只能影响测试创建的新 app/session/run 依赖图；不得改变正式配置 API、前端设置字段、环境变量语义或已启动 run 的快照。
- 新建 `Session` 不得自动读取其他会话的历史 run、历史产物、历史审批、历史工具确认、历史工具过程或历史 Provider 过程作为 Agent 长期记忆；历史会话只作为回看、追溯、诊断和审计对象。
- 已加载且未移除的 Project 与未删除 Session 在重启后仍可见；Session 重命名只改变展示名。
- Session 删除和 Project 移除只改变产品历史可见性、常规查询入口和对应查询投影，不删除运行记录、产物、交付记录或审计事实。
- 存在活动 run 的 Session 删除和 Project 移除必须被拒绝；默认 Project 移除必须被拒绝。

**测试方法**：
- `pytest backend/tests/regression/test_config_snapshot_regression.py -v`
- `pytest backend/tests/regression/test_prompt_asset_boundary_regression.py -v`
- `pytest backend/tests/regression/test_project_session_history_regression.py -v`
- `npm --prefix frontend run test -- SettingsBoundary`
- `npm --prefix frontend run test -- ProjectSessionHistory`

<a id="l61"></a>

## L6.1 日志轮转与保留清理

**计划周期**：Week 12
**状态**：`[ ]`
**目标**：补齐平台日志文件轮转、运行日志保留清理和审计保留差异，使运行日志生命周期不会破坏领域对象、投影查询和交付记录。
**实施计划**：`docs/plans/implementation/l6.1-log-rotation-retention-cleanup.md`

**修改文件列表**：
- Create: `backend/app/observability/retention.py`
- Create: `backend/tests/observability/test_log_retention.py`

**实现类/函数**：
- `LogRetentionService.rotate_if_needed()`
- `LogRetentionService.cleanup_run_logs()`
- `LogRetentionService.mark_log_expired()`

**验收标准**：
- 本地日志文件支持按大小或日期轮转，轮转后的文件命名保留可排序时间或 run 标识。
- `RunLogEntry` 通过 `log_file_ref`、`line_offset`、`line_number` 与 `log_file_generation` 定位本地 JSONL 日志原文，并在日志轮转后保持定位语义清晰。
- V1 支持按时间和 run 维度清理本地运行日志文件与 `log.db` 运行日志索引。
- 审计日志、审计索引和高影响动作记录不得与普通 debug 运行日志使用同一自动清理阈值。
- 清理运行日志不得删除领域对象、领域事件、阶段产物、审批记录或交付记录。
- 当日志已过保留期而领域对象仍引用其摘要时，查询必须稳定返回“日志已过保留期”或等价状态，不导致产品查询失败。
- L6.1 不负责敏感信息裁剪和跨链路日志审计回归；这些验证由 L6.2 覆盖。

**测试方法**：
- `pytest backend/tests/observability/test_log_retention.py -v`

<a id="l62"></a>

## L6.2 日志审计回归包

**计划周期**：Week 12
**状态**：`[ ]`
**目标**：补齐敏感信息裁剪、审计失败回滚、日志查询退化、`.runtime/logs` 排除和跨链路日志审计主路径回归，使日志审计能力达到发布候选要求。
**实施计划**：`docs/plans/implementation/l6.2-observability-regression-pack.md`

**修改文件列表**：
- Modify: `backend/app/observability/redaction.py`
- Create: `backend/tests/observability/test_log_redaction.py`
- Create: `backend/tests/regression/test_observability_regression.py`

**实现类/函数**：
- `RedactionPolicy.redact_mapping()`
- `RedactionPolicy.summarize_payload()`
- `ObservabilityRegressionScenarios`

**验收标准**：
- 在 L2.2 基础脱敏策略之上，补齐模型输入输出、工具输入输出、命令输出、异常堆栈和审计元数据的脱敏回归。
- 字段名命中 `api_key`、`token`、`secret`、`password`、`authorization`、`cookie`、`private_key`、`credential` 或等价敏感含义时，字段值必须持续阻断写入日志。
- 模型输入输出、工具输入输出、命令输出和异常堆栈必须先摘要化、裁剪并限制长度。
- 测试必须断言 `.runtime/logs` 不被工作区工具、diff、Git 自动交付或交付结果统计当作目标项目内容处理。
- 审计台账写入失败时，高影响动作必须拒绝或回滚；普通运行日志失败不得破坏已提交领域状态。
- run/stage 日志查询和审计日志查询在日志已过保留期、查询参数非法、日志索引缺失和载荷被阻断时必须返回稳定错误或退化状态。

**测试方法**：
- `pytest backend/tests/observability/test_log_redaction.py -v`
- `pytest backend/tests/regression/test_observability_regression.py -v`

<a id="v67"></a>

## V6.7 回归场景与发布候选清单

**计划周期**：Week 12
**状态**：`[ ]`
**目标**：补齐系统回归场景和发布候选验收清单，使平台级 V1 达到可评审发布状态。
**实施计划**：`docs/plans/implementation/v6.7-regression-release-candidate.md`

**修改文件列表**：
- Create: `backend/tests/regression/test_run_lifecycle_regression.py`
- Create: `backend/tests/regression/test_projection_regression.py`
- Create: `docs/plans/function-one-platform-acceptance-checklist.md`

**实现类/函数**：
- `runRegressionScenario()`
- `assertProjectionDoesNotDuplicateEntries()`
- `assertSessionHistoryReplayStable()`

**验收标准**：
- 历史会话回放稳定。
- 投影和 SSE 不出现重复条目或状态倒退。
- 回归清单覆盖产品、前端、后端三份规格的核心验收项。
- 发布候选验收清单完成。
- 发布候选验收清单覆盖日志审计基础能力：JSONL 写入、`log.db` 索引、审计记录、TraceContext、日志查询、审计查询、轮转、保留、裁剪、`.runtime/logs` 排除和审计失败回滚。

**前端设计质量门**：
- 不新增风格输入；只允许修正一致性、状态覆盖和可用性问题。
- 发布候选必须检查空态、错误态、历史回放、响应式、长文本、焦点态和可访问性。
- 必要时修正视觉一致性，但不得引入新的业务语义或重排已验收流程。
- 发布候选清单必须记录设计质量门发现项、修复项、保留风险和对应验证命令。

**测试方法**：
- `pytest backend/tests/regression -v`
- `npm --prefix e2e run test`
