# 07 Workspace Tools、风险门禁与变更边界

## 范围

本分卷覆盖 Week 7-9 的 ToolProtocol、ToolRegistry execution gate、工具风险确认门禁、后端测试 fixture、Workspace tools、ChangeSet 和 PreviewTarget 边界。完成后，runtime、Provider adapter、workspace tools 和后续 delivery tools 都消费同一抽象工具协议与风险门禁。

本分卷把抽象工具协议与 Workspace Tools 拆成独立适配器切片。W5.0 必须先固定 `ToolProtocol` 与工具注册表，W5.0c 必须先固定 fake provider、fake tool 与 fixture 契约，W5.0d 再固定工具风险分级和高风险确认门禁，W5.2-W5.4 只实现 workspace 具体工具，避免 runtime、Provider adapter 或交付适配层先使用临时工具接口。Workspace tools 的工作方式参考 Claude Code，正式工具契约名固定为 `bash`、`read_file`、`edit_file`、`write_file`、`glob`、`grep`。

凡本分卷修改 `backend/app/api/routes/*` 的 API 切片，对应 API 测试必须在本切片内断言新增或修改的 path、method、请求 Schema、响应 Schema 和主要错误响应已进入 `/api/openapi.json`；V6.4 只做全局覆盖回归，不替代本地 API 契约断言。

工作区和工具任务必须嵌入日志审计要求。`.runtime/logs` 属于平台运行数据目录，不属于被操作项目工作区；工作区工具、`glob`、`grep`、diff 和 ChangeSet 计算必须默认排除该目录。所有工具调用必须通过统一 Log & Audit Service 记录运行日志；会造成工作区或配置状态变化的工具调用必须写入审计记录；高风险工具动作必须先创建 `ToolConfirmationRequest` 并等待用户允许，`blocked` 工具动作必须结构化拒绝且不得创建可允许的确认请求。

<a id="w50"></a>

## W5.0 ToolProtocol 与工具注册表

**计划周期**：Week 7
**状态**：`[x]`
**目标**：在 workspace 文件工具、`bash` 工具、LangGraph runtime、Provider adapter 和后续 delivery tool 之前固定抽象工具协议，使所有工具绑定只依赖 `ToolProtocol` 和注册表。
**实施计划**：`docs/plans/implementation/w5.0-tool-protocol-registry.md`
**验证摘要**：实施计划 `docs/plans/implementation/w5.0-tool-protocol-registry.md` 已完成并在 integration checkpoint 合入 `2b78be5`。`uv run python -m pytest backend/tests/services/test_template_snapshot.py backend/tests/services/test_clarification_flow.py backend/tests/api/test_clarification_reply_api.py backend/tests/projections/test_workspace_projection.py backend/tests/api/test_query_api.py backend/tests/tools/test_tool_protocol_registry.py -v` 通过 39 个 focused backend tests；`uv run python -m pytest -q` 通过 395 个 backend tests。

**修改文件列表**：
- Create: `backend/app/tools/protocol.py`
- Create: `backend/app/tools/registry.py`
- Create: `backend/tests/tools/test_tool_protocol_registry.py`

**实现类/函数**：
- `ToolProtocol`
- `ToolInput`
- `ToolResult`
- `ToolError`
- `ToolAuditRef`
- `ToolRiskLevel`
- `ToolRiskCategory`
- `ToolRegistry`
- `ToolRegistry.register()`
- `ToolRegistry.resolve()`
- `ToolRegistry.list_bindable_tools()`

**验收标准**：
- `ToolProtocol` 定义工具名称、类别、输入 Schema、结果载荷、错误结构、风险等级、风险分类、权限边界、副作用等级、审计引用和可绑定工具描述。
- `ToolRegistry` 能按工具类别和名称注册、解析、列出工具，并拒绝重复注册和未知工具解析。
- LangGraph runtime、LangChain Provider adapter、workspace 工具和后续 delivery 工具只能依赖该抽象协议与注册表。
- 本切片不实现文件、`glob`、`grep`、`bash` 或 delivery 具体工具，不绑定具体业务函数。
- ToolProtocol 的审计引用必须能引用 `AuditLogEntry` 或其稳定引用，不能只是自由文本。
- ToolResult 必须能承载 `trace_id`、`correlation_id`、`span_id`、`audit_ref`、`coordination_key`、`tool_confirmation_ref`、`side_effect_refs` 与 `reconciliation_status`。
- `ToolRiskLevel` 固定为 `read_only`、`low_risk_write`、`high_risk`、`blocked`；`ToolRiskCategory` 与 C1.1 保持同一枚举来源。
- 具有副作用的工具调用必须先形成调用意图记录，后续文件、`bash` 与 delivery 工具不得在 W5.0 抽象之外自建副作用协调字段。

**测试方法**：
- `pytest backend/tests/tools/test_tool_protocol_registry.py -v`

<a id="w50a"></a>

## W5.0a 统一错误码字典与错误响应契约

**计划周期**：Week 7
**状态**：`[x]`
**目标**：扩展 B0.2 已建立的后端错误码体系，使 API 错误、工具错误、交付错误、日志审计错误和回归断言共享稳定 `error_code` 来源，避免各切片用自由文本或局部常量定义错误兼容边界。
**实施计划**：`docs/plans/implementation/w5.0a-error-code-catalog-contract.md`
**验证摘要**：实施计划 `docs/plans/implementation/w5.0a-error-code-catalog-contract.md` 已完成并在 integration checkpoint 合入 `e2c777c`。`uv run pytest backend/tests/api/test_query_api.py backend/tests/projections/test_timeline_projection.py backend/tests/projections/test_approval_projection.py backend/tests/services/test_approval_creation.py backend/tests/errors/test_error_code_catalog.py` 通过 34 个 focused backend tests。

**修改文件列表**：
- Modify: `backend/app/api/error_codes.py`
- Modify: `backend/app/api/errors.py`
- Create: `backend/app/schemas/errors.py`
- Modify: `backend/app/tools/protocol.py`
- Create: `backend/tests/errors/test_error_code_catalog.py`

**实现类/函数**：
- `ErrorCode`
- `ErrorCategory`
- `ErrorCatalogEntry`
- `ApiErrorResponse`
- `lookup_error_code()`
- `ToolError.from_code()`
- `assert_error_code_registered()`

**验收标准**：
- 所有对外 API 错误、`ToolError`、delivery tool 错误和日志审计查询错误必须使用 B0.2 `backend/app/api/error_codes.py` 中的稳定 `error_code`。
- 错误码体系必须记录错误码、分类、默认 HTTP 状态、是否可重试、是否可向用户展示、默认安全标题和默认安全说明。
- 错误码体系至少覆盖 `tool_unknown`、`tool_not_allowed`、`tool_input_schema_invalid`、`tool_workspace_boundary_violation`、`tool_timeout`、`tool_audit_required_failed`、`tool_confirmation_required`、`tool_confirmation_denied`、`tool_confirmation_not_actionable`、`tool_risk_blocked`、`bash_command_not_allowed`、`provider_retry_exhausted`、`provider_circuit_open`、`delivery_snapshot_missing`、`delivery_snapshot_not_ready`、`delivery_git_cli_failed`、`delivery_remote_request_failed`、`runtime_data_dir_unavailable`、`audit_write_failed`、`log_query_invalid`、`log_payload_blocked`、`config_snapshot_mutation_blocked`。
- `ToolError` 只引用错误码、结构化安全详情、`trace_id`、`correlation_id`、`span_id` 和审计引用；不得把异常堆栈、凭据、授权头、Cookie、API Key 或私钥放入错误详情。
- API 错误响应必须包含稳定 `error_code`、安全 `message`、可选 `detail_ref` 和 trace 关联字段；HTTP 状态只表达传输层结果，不替代领域错误码。
- 本切片不得创建与 B0.2 并行的第二套错误码模块、第二个 `ErrorCode` 枚举或第二套 API 错误响应模型。
- 错误码扩展不得引入新的阶段状态、投影字段、事件类型或交付语义；只为既有错误场景提供稳定编码。

**测试方法**：
- `pytest backend/tests/errors/test_error_code_catalog.py -v`

<a id="w51"></a>

## W5.1 WorkspaceManager 隔离工作区

**计划周期**：Week 7
**状态**：`[x]`
**目标**：实现每个 PipelineRun 的独立工作区创建、定位和清理，避免 run 之间泄漏未交付改动。
**实施计划**：`docs/plans/implementation/w5.1-workspace-manager.md`

**修改文件列表**：
- Create: `backend/app/workspace/manager.py`
- Create: `backend/tests/workspace/test_workspace_manager.py`

**实现类/函数**：
- `WorkspaceManager.create_for_run()`
- `WorkspaceManager.get_run_workspace()`
- `WorkspaceManager.cleanup_run_workspace()`
- `WorkspaceManager.assert_inside_workspace()`

**验收标准**：
- 每个 PipelineRun 使用独立工作区。
- 新 run 从干净基线创建，不继承前一 run 未交付改动。
- 工作区路径必须处于受控根目录下。
- 工作区管理不执行业务文件读写或 `bash` 命令。
- 工作区根目录不得包含平台运行数据目录；若平台运行数据目录落在平台仓库路径下，WorkspaceManager 必须把 `.runtime/logs` 标记为排除路径。
- 工作区创建、定位失败、路径越界和清理必须写入运行日志；路径越界属于安全敏感失败并写入审计记录。

**测试方法**：
- `pytest backend/tests/workspace/test_workspace_manager.py -v`

<a id="w50b"></a>

## W5.0b ToolRegistry execution gate

**计划周期**：Week 7-8
**状态**：`[x]`
**目标**：在具体 workspace tools、delivery tools、LangGraph runtime 和 Provider adapter 之间建立唯一工具执行入口，集中校验工具名、阶段 `allowed_tools`、输入 Schema、工作区边界、超时策略和审计策略。
**实施计划**：`docs/plans/implementation/w5.0b-tool-registry-execution-gate.md`

**修改文件列表**：
- Modify: `backend/app/tools/protocol.py`
- Modify: `backend/app/tools/registry.py`
- Create: `backend/app/tools/execution_gate.py`
- Create: `backend/tests/tools/test_tool_execution_gate.py`

**实现类/函数**：
- `ToolExecutionRequest`
- `ToolExecutionContext`
- `ToolExecutionGate`
- `ToolExecutionGate.validate()`
- `ToolExecutionGate.execute()`
- `ToolInputSchemaValidator`
- `ToolTimeoutPolicy.resolve_timeout()`
- `ToolAuditPolicy.resolve_requirement()`
- `ToolRegistry.execute()`

**验收标准**：
- LangGraph runtime、Provider adapter、deterministic test runtime、workspace tool 调用方和 delivery adapter 必须通过 `ToolRegistry.execute()` 发起工具执行；不得绕过注册表直接调用具体工具函数、Git CLI 或远端交付接口。
- execution gate 必须先校验工具名已注册且与 `ToolProtocol.name` 完全一致；未知工具、重复注册冲突和名称大小写漂移必须返回 W5.0a 字典中的结构化错误。
- execution gate 必须基于当前 `GraphDefinition.stage_contracts[stage_type].allowed_tools` 校验阶段工具权限；`allowed_tools = []` 时不得执行任何工具调用，未列入 `allowed_tools` 的工具不得进入 `available_tools` 或执行路径。
- execution gate 必须在工具执行前校验输入 Schema；缺失字段、额外字段、类型错误和不满足约束的值必须返回 `tool_input_schema_invalid`，不得把无效输入交给具体工具自行解释。
- 对 workspace tools，execution gate 必须调用 WorkspaceManager 的工作区边界校验，阻止绝对路径越界、相对路径逃逸、平台运行数据目录和 `.runtime/logs` 访问。
- execution gate 必须预留 W5.0d 的 `ToolRiskClassifier` 调用点；本切片只固定执行门入口、校验顺序和可测试端口，不实现风险分级规则。
- execution gate 必须从当前 run 的 `RuntimeLimitSnapshot`、工具默认值和平台硬上限解析工具调用超时；超时必须返回 `tool_timeout` 并写入运行日志摘要。
- execution gate 必须在有副作用或高影响工具执行前解析审计策略并形成调用意图；审计策略要求写入但审计不可用时，工具不得执行，必须返回 `tool_audit_required_failed`。
- `bash` 命令白名单校验仍属于 W5.4 的 `BashCommandAllowlist`；本切片只校验 `bash` 工具是否允许被调用、输入是否符合 `bash` 工具 Schema、工作区和超时是否合规，并把具体命令交给 W5.4 白名单校验。
- delivery tools 的执行同样经过 execution gate；Delivery Integration 阶段只能调用 `read_delivery_snapshot`、`prepare_branch`、`create_commit`、`push_branch`、`create_code_review_request` 中已注册且列入 `allowed_tools` 的工具。
- 所有拒绝执行的结果必须使用 W5.0a 错误码、保留 trace 关联字段，并写入运行日志；安全敏感拒绝必须写入审计记录。

**测试方法**：
- `pytest backend/tests/tools/test_tool_execution_gate.py -v`

<a id="w50c"></a>

## W5.0c 后端测试 fixture、fake provider 与 fake tool 契约

**计划周期**：Week 7-8
**状态**：`[x]`
**目标**：建立后端跨切片测试 fixture 契约，使 deterministic test runtime、Provider adapter、ToolRegistry、workspace tools、delivery tools、配置快照回归和完整 API flow 测试共享正式抽象，不再各自定义临时 fake 字段、临时设置入口或临时工具调用路径。
**实施计划**：`docs/plans/implementation/w5.0c-backend-test-fixtures-contract.md`

**修改文件列表**：
- Create: `backend/tests/fixtures/__init__.py`
- Create: `backend/tests/fixtures/settings.py`
- Create: `backend/tests/fixtures/providers.py`
- Create: `backend/tests/fixtures/tools.py`
- Create: `backend/tests/fixtures/workspace.py`
- Create: `backend/tests/fixtures/delivery.py`
- Modify: `backend/tests/conftest.py`
- Create: `backend/tests/fixtures/test_fixture_contracts.py`

**实现类/函数**：
- `settings_override_fixture()`
- `runtime_settings_snapshot_fixture()`
- `fake_provider_fixture()`
- `FakeProvider`
- `FakeChatModel`
- `fake_tool_fixture()`
- `FakeTool`
- `fixture_workspace_repo()`
- `fixture_git_repository()`
- `mock_remote_delivery_client()`
- `delivery_channel_snapshot_fixture()`

**验收标准**：
- 所有 fake provider 必须消费正式 Provider registry、ProviderSnapshot、ModelBindingSnapshot 和 LangChain adapter 边界；不得定义临时模型字段、临时能力字段或绕过 Provider 能力校验。
- `FakeProvider` 必须能模拟结构化输出成功、结构化输出失败、tool call 请求、Provider 超时、限流和网络错误，并返回 W5.0a 统一错误码或正式 Provider 错误结构。
- 所有 fake tool 必须实现 W5.0 `ToolProtocol` 并注册到 `ToolRegistry`；测试调用 fake tool 时仍必须经过 W5.0b execution gate 的工具名、阶段 `allowed_tools`、输入 Schema、超时和审计策略校验。
- fake tool 只能用于测试未落地的下游工具或隔离上游 runtime 行为；不得成为 runtime、Provider adapter、workspace tools 或 delivery adapter 的生产替代路径。
- `settings_override_fixture()` 只能在测试中覆盖数据库路径、平台运行数据根目录、工作区根目录、日志落点、凭据引用解析和本次测试需要的运行设置版本；不得把这些 override 暴露到正式配置 API、前端设置或普通环境变量语义中。
- fixture 仓库必须在临时目录初始化，包含可提交基线、工作区变更样本、`.runtime/logs` 排除样本和 mock remote；测试结束后不得影响真实仓库。
- delivery fixture 必须能构造已固化的 delivery channel snapshot、未 ready snapshot、缺失 snapshot、mock remote 成功和 mock remote 失败场景，且字段形状与 D4.0 / D5.1 使用的正式 snapshot 一致。
- fixture 数据必须来源于后端 Schema、领域对象和投影契约；不得创建仅测试可见的状态枚举、事件类型、投影字段或阶段语义。
- fixture 契约必须支持 W5.0b、W5.0d、D5.2-D5.4、A4.8c-A4.9e、V6.1、V6.6、V6.8 和 L6.2 复用。

**测试方法**：
- `pytest backend/tests/fixtures/test_fixture_contracts.py -v`

<a id="w50d"></a>

## W5.0d Tool risk classifier 与 confirmation gate

**计划周期**：Week 7-8
**状态**：`[x]`
**目标**：实现工具风险分级和高风险确认门禁，使所有工具动作在执行前统一判定 `read_only`、`low_risk_write`、`high_risk` 或 `blocked`，并把高风险动作转入 H4.4a 工具确认流程。
**实施计划**：`docs/plans/implementation/w5.0d-tool-risk-confirmation-gate.md`
**验证摘要**：实施计划 `docs/plans/implementation/w5.0d-tool-risk-confirmation-gate.md` 已完成并在 integration checkpoint 合入 `c01767d`。`uv run pytest backend/tests/tools/test_tool_risk_classifier.py backend/tests/tools/test_tool_execution_gate.py backend/tests/tools/test_tool_protocol_registry.py backend/tests/errors/test_error_code_catalog.py backend/tests/services/test_tool_confirmation_commands.py -v` 通过 97 个 focused / impacted tool-confirmation tests；`uv run pytest backend/tests/runtime/test_runtime_engine_contract.py backend/tests/providers/test_provider_registry.py -v` 通过 16 个 runtime/provider regressions；`uv run pytest backend/tests/services/test_delivery_snapshot_gate.py backend/tests/services/test_delivery_channel_readiness.py -v` 通过 31 个 delivery gate regressions；`uv run pytest backend/tests -q` 通过 771 个 backend tests。

**修改文件列表**：
- Modify: `backend/app/tools/protocol.py`
- Modify: `backend/app/tools/execution_gate.py`
- Create: `backend/app/tools/risk.py`
- Modify: `backend/app/services/tool_confirmations.py`
- Create: `backend/tests/tools/test_tool_risk_classifier.py`
- Modify: `backend/tests/tools/test_tool_execution_gate.py`

**实现类/函数**：
- `ToolRiskClassifier`
- `ToolRiskAssessment`
- `ToolRiskClassifier.classify()`
- `ToolExecutionGate.require_confirmation_if_high_risk()`
- `ToolExecutionGate.block_if_disallowed()`
- `ToolExecutionGate.attach_tool_confirmation_ref()`

**验收标准**：
- `read_only` 覆盖工作区内只读读取、`glob`、`grep` 和不产生副作用的查询动作。
- `low_risk_write` 覆盖精确、小范围、命中阶段允许范围且目标明确的文件写入或编辑动作。
- 安装或升级依赖、联网下载、删除或移动文件、大范围生成或覆盖文件、数据库迁移、修改锁文件、修改环境配置、执行不在项目说明或脚本配置中的未知命令，必须判定为 `high_risk`。
- 读取凭据、泄露密钥、越权访问工作区外路径、修改平台运行数据目录、绕过 `ToolRegistry`、绕过审计或绕过工具确认边界的动作必须判定为 `blocked`。
- `high_risk` 工具动作在执行前必须通过 H4.4a 创建 `ToolConfirmationRequest`，返回等待状态并写入 `tool_confirmation_ref`；用户允许前不得执行具体工具。
- `blocked` 工具动作不得创建可允许的工具确认请求，必须返回 `tool_risk_blocked` 并写入安全审计记录。
- 用户允许后，execution gate 只能执行该确认请求覆盖的同一个工具名称、输入摘要、目标资源和风险评估结果；任一字段漂移必须拒绝执行。
- 风险分级测试必须使用 W5.0c 的 fake tool、settings override 和受控 fixture，不得在测试内创建第二套临时工具协议或临时执行入口。
- 风险分级过程必须写入 `tool_trace` 或 `tool_confirmation_trace`，并继承 `TraceContext`。

**测试方法**：
- `pytest backend/tests/tools/test_tool_risk_classifier.py -v`
- `pytest backend/tests/tools/test_tool_execution_gate.py -v`

<a id="w52"></a>

## W5.2 文件工具 read_file/write_file/edit_file/glob

**计划周期**：Week 7-8
**状态**：`[x]`
**目标**：基于 W5.0 `ToolProtocol` 实现核心文件工具，使 `deterministic test runtime`、LangGraph runtime 与 Provider adapter 可以在隔离工作区中读取文本代码文件、创建或覆盖文件、精确编辑文件并按模式匹配路径，且不需要临时工具接口。
**实施计划**：`docs/plans/implementation/w5.2-workspace-file-tools.md`

**修改文件列表**：
- Create: `backend/app/workspace/tools.py`
- Create: `backend/tests/workspace/test_workspace_file_tools.py`

**实现类/函数**：
- `WorkspaceFileTool`
- `read_file()`
- `write_file()`
- `edit_file()`
- `glob()`
- `FileReadTool`
- `FileWriteTool`
- `FileEditTool`
- `GlobTool`

**验收标准**：
- 文件工具必须实现 W5.0 定义的 `ToolProtocol` 并注册到 `ToolRegistry`。
- 文件工具执行必须经过 W5.0b execution gate 与 W5.0d 风险门禁的工具名、阶段 `allowed_tools`、输入 Schema、工作区边界、风险分级、超时和审计策略校验。
- 工具只允许访问当前 run 的隔离工作区。
- 正式工具契约名必须为 `read_file`、`write_file`、`edit_file`、`glob`；`FileReadTool`、`FileWriteTool`、`FileEditTool`、`GlobTool` 只作为实现类名或参考工具名。
- `read_file` 只读取文本和代码类文件，不处理图片、PDF、压缩包、音视频或其他二进制 / 富媒体内容。
- `edit_file` 采用精确字符串替换；目标字符串不存在、匹配次数不唯一或替换后内容不一致时必须返回结构化错误，不得执行模糊 patch。
- `write_file` 只用于创建或完整覆盖文件。
- `glob` 按路径模式匹配文件，返回相对路径、文件类型和必要排序信息，不读取文件正文。
- `read_file`、`write_file`、`edit_file`、`glob` 都返回结构化结果和错误信息。
- `write_file` 与 `edit_file` 必须生成 `file_edit_trace` 或等价稳定过程记录，并把副作用引用写入 `ToolResult.side_effect_refs`。
- diff 生成、文件 hash 采集和 `ChangeSet` 构建属于 Workspace & Tool Service / ChangeSet 服务侧能力，不作为独立模型可调用工具加入本切片。
- 本切片不重新定义工具协议，不实现 `grep`、`bash` 或 delivery 具体工具。
- 文件工具必须默认排除 `.runtime/logs` 和平台运行数据目录，不能把日志文件作为业务文件读写、编辑、列出或纳入变更引用。
- 每次文件工具调用必须写入运行日志；`write_file` 与 `edit_file` 必须写入审计记录。
- 文件工具输入输出摘要必须裁剪敏感字段和大文本。
- 文件不存在、路径越界、二进制文件拒绝、输入 Schema 非法、写入冲突和审计必需但写入失败必须返回 W5.0a 统一错误码。

**测试方法**：
- `pytest backend/tests/workspace/test_workspace_file_tools.py -v`

<a id="w53"></a>

## W5.3 grep 工具

**计划周期**：Week 7-8
**状态**：`[x]`
**目标**：实现基于 ripgrep 的工作区 `grep` 工具，使 runtime 可以受控正则搜索当前 run 工作区内容。
**实施计划**：`docs/plans/implementation/w5.3-workspace-grep-tool.md`

**修改文件列表**：
- Modify: `backend/app/workspace/tools.py`
- Create: `backend/tests/workspace/test_workspace_grep_tool.py`

**实现类/函数**：
- `grep()`
- `GrepTool`
- `GrepResultItem`
- `WorkspaceGrepOptions`

**验收标准**：
- `grep` 工具必须实现 W5.0 定义的 `ToolProtocol` 并注册到 `ToolRegistry`。
- `grep` 执行必须经过 W5.0b execution gate 与 W5.0d 风险门禁的工具名、阶段 `allowed_tools`、输入 Schema、工作区边界、风险分级、超时和审计策略校验。
- `grep` 只扫描当前 run 隔离工作区。
- `grep` 基于 `ripgrep` 执行正则内容搜索。
- `grep` 初始化、健康检查或运行前检查必须校验本地 `rg` 可用；缺失时返回结构化 readiness 错误，不得静默降级为未受控搜索实现。
- `grep` 返回路径、行号、匹配片段和截断状态。
- `grep` 能排除常见构建产物和依赖目录。
- `grep` 错误返回结构化错误信息。
- `grep` 必须默认排除 `.runtime/logs`、平台运行数据目录、依赖目录和构建产物。
- `grep` 调用必须写入运行日志摘要；路径越界、权限拒绝和敏感信息阻断必须写入审计记录。
- `rg` 缺失、输入 Schema 非法、路径越界、超时和结果被裁剪必须返回 W5.0a 统一错误码或结构化裁剪状态。

**测试方法**：
- `pytest backend/tests/workspace/test_workspace_grep_tool.py -v`

<a id="w54"></a>

## W5.4 bash 工具与白名单审计

**计划周期**：Week 7-8
**状态**：`[x]`
**目标**：实现受控 `bash` 工具、命令白名单和工具调用日志审计记录，使测试执行和命令执行可追踪。
**实施计划**：`docs/plans/implementation/w5.4-workspace-bash-audit.md`

**修改文件列表**：
- Create: `backend/app/workspace/bash.py`
- Modify: `backend/app/observability/audit.py`
- Create: `backend/tests/workspace/test_workspace_bash.py`
- Create: `backend/tests/tools/test_tool_audit.py`

**实现类/函数**：
- `run_bash_command()`
- `BashTool`
- `BashExecutionResult`
- `BashCommandAllowlist`
- `AuditService.record_tool_call()`
- `AuditService.record_tool_error()`

**验收标准**：
- `bash` 命令通过受控子进程执行。
- `bash` 是正式工具契约名，底层实现是平台受控子进程 / 命令适配器；实现不得假定运行环境一定存在 Unix bash，也不得把 PowerShell、cmd 或其他 shell 的自由能力直接暴露给模型。
- `bash` 命令必须经过命令白名单校验。
- `bash` 工具执行必须先通过 W5.0b execution gate 与 W5.0d 风险门禁的工具名、阶段 `allowed_tools`、输入 Schema、工作区边界、风险分级、工具确认门禁、超时和审计策略校验；W5.4 只实现命令级 allowlist 与受控子进程执行，不另建并行工具权限表。
- `BashCommandAllowlist` 必须能从项目 README、package 脚本、依赖声明、测试配置或等价项目说明中识别测试、构建、格式化和环境探测命令；不在项目说明或脚本配置中的未知命令必须进入 `unknown_command` 风险分类。
- 安装或升级依赖、联网下载、删除或移动文件、数据库迁移、修改锁文件、修改环境配置和大范围生成或覆盖文件的 `bash` 命令必须判定为 `high_risk`，执行前必须获得 H4.4a 工具确认。
- 读取凭据、输出密钥、越权访问工作区外路径、修改平台运行数据目录、绕过 ToolRegistry、绕过审计或绕过工具确认的 `bash` 命令必须判定为 `blocked`，不得创建可允许的工具确认请求。
- `bash` 工作目录被限制在当前 run 工作区。
- 命令输出、退出码、耗时和错误被结构化记录。
- 工具调用产生日志和审计记录。
- 每次被审计的工具调用都必须生成并持久化 W5.0 `ToolAuditRef`，且 `ToolResult.audit_ref` 必须能与 `AuditService` 记录一一对应。
- `bash` 执行前必须形成调用意图记录与 `coordination_key`；执行后必须写入 `command_trace`、`ToolResult.side_effect_refs` 和 `reconciliation_status`。
- 当 `bash` 导致工作区内容变化时，执行前后必须采集工作区 diff、受影响文件列表、文件 hash 或等价变更引用，并把变化纳入 `file_edit_trace`、`command_trace` 与 `ChangeSet` 构建输入。
- `bash` 工具实现 W5.0 定义的 `ToolProtocol` 并注册到 `ToolRegistry`。
- `bash` 命令输出必须裁剪、摘要化并限制大小；异常堆栈和环境变量不得泄漏凭据、API Key、Cookie、授权头或私钥。
- `bash` 工作目录、命令、退出码、耗时、输出摘要、错误摘要、`trace_id`、`correlation_id` 和 `span_id` 必须进入运行日志。
- 会改变工作区、执行测试、触发外部服务或可能影响交付目标的 `bash` 调用必须写入审计记录。
- allowlist 拒绝、命令超时、工作区越界、高风险确认未允许、blocked 风险、审计必需但写入失败和输出被阻断必须返回 W5.0a 统一错误码。
- 测试不执行破坏真实仓库的命令。

**测试方法**：
- `pytest backend/tests/workspace/test_workspace_bash.py -v`
- `pytest backend/tests/tools/test_tool_audit.py -v`
**验证摘要**：实施计划 `docs/plans/implementation/w5.4-workspace-bash-audit.md` 已完成并在 integration checkpoint 合入 `6798ce9`。`uv run pytest backend/tests/workspace/test_workspace_bash.py -v` 通过 15 个 focused bash tests；`uv run pytest backend/tests/tools/test_tool_audit.py -v` 通过 2 个 focused audit tests；本次批量 integration verification 中后端聚合回归通过 59 个 tests，覆盖 bash allowlist、审计持久化、prompt renderer 与 project-history 相关切片。

<a id="w55"></a>

## W5.5 ChangeSet 与 ContextReference

**计划周期**：Week 9
**状态**：`[x]`
**目标**：落地 ChangeSet 和 ContextReference 领域边界，为功能二选择驱动网页编辑保留复用对象。
**实施计划**：`docs/plans/implementation/w5.5-change-set-context-reference.md`

**修改文件列表**：
- Create: `backend/app/domain/changes.py`
- Create: `backend/tests/domain/test_change_set.py`

**实现类/函数**：
- `ChangeSet`
- `ChangeOperation`
- `ContextReference`
- `ContextReferenceKind`

**验收标准**：
- Code Generation 输出能引用 ChangeSet。
- ChangeSet 能表达变更文件、变更类型、diff 引用和上下文引用。
- ContextReference 预留 `page_selection`、`dom_anchor`、`preview_snapshot`。
- 功能一不实现功能二的圈选交互。
- ChangeSet 计算和 diff 引用必须默认排除 `.runtime/logs` 与平台运行数据目录。

**测试方法**：
- `pytest backend/tests/domain/test_change_set.py -v`
**验证摘要**：实施计划 `docs/plans/implementation/w5.5-change-set-context-reference.md` 已完成并在 integration checkpoint 合入 `14f5b52`。`uv run pytest backend/tests/domain/test_change_set.py -v` 通过 11 个 focused tests；`uv run pytest backend/tests/domain/test_change_set.py backend/tests/context/test_context_schemas.py -v` 在 worker checkpoint 通过 17 个 impacted tests；本次 integration verification 中 `uv run pytest backend/tests/domain/test_change_set.py backend/tests/context/test_context_schemas.py backend/tests/providers/test_langchain_adapter.py backend/tests/providers/test_provider_registry.py backend/tests/fixtures/test_fixture_contracts.py -v` 通过 67 个 tests，覆盖 ChangeSet 边界与相邻 context/provider 契约。

<a id="w56"></a>

## W5.6 PreviewTarget Schema 与查询接口

**计划周期**：Week 9
**状态**：`[x]`
**目标**：定义 PreviewTarget 对象和查询接口，为功能二预览能力保留稳定 API 边界。
**实施计划**：`docs/plans/implementation/w5.6-preview-target-query.md`

**修改文件列表**：
- Create: `backend/app/schemas/preview.py`
- Create: `backend/app/api/routes/preview_targets.py`
- Create: `backend/tests/api/test_preview_target_api.py`

**实现类/函数**：
- `PreviewTarget`
- `PreviewTargetService.get_preview_target()`

**验收标准**：
- `GET /api/preview-targets/{previewTargetId}` 提供查询接口。
- PreviewTarget 提供稳定标识、项目/run 关联、目标类型和引用信息。
- V1 仅定义对象和查询接口，不实现预览启动与热更新。
- API 测试必须断言 `GET /api/preview-targets/{previewTargetId}` 的响应 Schema、主要错误响应和 OpenAPI path/method 已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/api/test_preview_target_api.py -v`
**验证摘要**：实施计划 `docs/plans/implementation/w5.6-preview-target-query.md` 已完成并在 integration checkpoint 合入 `7a8911a`。本次 integration verification 中 `uv run pytest backend/tests/api/test_preview_target_api.py -v` 通过 5 个 focused tests，`uv run pytest backend/tests/api/test_preview_target_api.py backend/tests/api/test_query_api.py -v` 通过 22 个 impacted API tests，`uv run pytest backend/tests -q` 通过 1003 个 backend tests，保留 3 个既有 LangChain adapter `temperature` 参数 warning。
