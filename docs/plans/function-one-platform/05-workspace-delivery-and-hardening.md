# 05 工作区、真实 Git 交付与硬化

## 范围

本分卷覆盖 Week 7-12 的工作区工具、功能二扩展边界、`git_auto_delivery` 真实 Git 交付适配、前端交付展示、端到端测试、OpenAPI 一致性与系统硬化。完成后，系统具备平台级 V1 发布候选条件。

本分卷把抽象工具协议、Workspace Tools 与 Delivery Tools 拆成独立适配器切片。W5.0 必须先固定 `ToolProtocol` 与工具注册表，W5.2-W5.4 只实现 workspace 具体工具，D5.1-D5.4 再实现 delivery 具体工具，避免 runtime、Provider adapter 或交付适配层先使用临时工具接口。Workspace tools 的工作方式参考 Claude Code，正式工具契约名固定为 `bash`、`read_file`、`edit_file`、`write_file`、`glob`、`grep`。`demo_delivery` 已在 Week 7 作为正式无 Git 写动作交付适配器落地；本分卷只实现 `git_auto_delivery` 的真实 Git 交付能力。真实 Git 操作只在 `git_auto_delivery` 适配层中发生，并且测试必须使用 fixture 仓库和 mock 远端。

凡本分卷修改 `backend/app/api/routes/*` 的 API 切片，对应 API 测试必须在本切片内断言新增或修改的 path、method、请求 Schema、响应 Schema 和主要错误响应已进入 `/api/openapi.json`；V6.4 只做全局覆盖回归，不替代本地 API 契约断言。

工作区、工具、Git 交付和硬化任务必须嵌入日志审计要求。`.runtime/logs` 属于平台运行数据目录，不属于被操作项目工作区；工作区工具、`glob`、`grep`、diff、Git 自动交付、交付结果统计和 ChangeSet 计算必须默认排除该目录。所有工具调用必须通过统一 Log & Audit Service 记录运行日志；会造成工作区、Git、远端交付或配置状态变化的工具调用必须写入审计记录。

<a id="w50"></a>

## W5.0 ToolProtocol 与工具注册表

**计划周期**：Week 7
**状态**：`[ ]`
**目标**：在 workspace 文件工具、`bash` 工具、LangGraph runtime、Provider adapter 和后续 delivery tool 之前固定抽象工具协议，使所有工具绑定只依赖 `ToolProtocol` 和注册表。
**实施计划**：`docs/plans/implementation/w5.0-tool-protocol-registry.md`

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
- `ToolRegistry`
- `ToolRegistry.register()`
- `ToolRegistry.resolve()`
- `ToolRegistry.list_bindable_tools()`

**验收标准**：
- `ToolProtocol` 定义工具名称、类别、输入 Schema、结果载荷、错误结构、审计引用和可绑定工具描述。
- `ToolRegistry` 能按工具类别和名称注册、解析、列出工具，并拒绝重复注册和未知工具解析。
- LangGraph runtime、LangChain Provider adapter、workspace 工具和后续 delivery 工具只能依赖该抽象协议与注册表。
- 本切片不实现文件、`glob`、`grep`、`bash` 或 delivery 具体工具，不绑定具体业务函数。
- ToolProtocol 的审计引用必须能引用 `AuditLogEntry` 或其稳定引用，不能只是自由文本。
- ToolResult 必须能承载 `trace_id`、`correlation_id`、`span_id`、`audit_ref`、`coordination_key`、`side_effect_refs` 与 `reconciliation_status`。
- 具有副作用的工具调用必须先形成调用意图记录，后续文件、`bash` 与 delivery 工具不得在 W5.0 抽象之外自建副作用协调字段。

**测试方法**：
- `pytest backend/tests/tools/test_tool_protocol_registry.py -v`

<a id="w51"></a>

## W5.1 WorkspaceManager 隔离工作区

**计划周期**：Week 7
**状态**：`[ ]`
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

<a id="w52"></a>

## W5.2 文件工具 read_file/write_file/edit_file/glob

**计划周期**：Week 7
**状态**：`[ ]`
**目标**：基于 W5.0 `ToolProtocol` 实现核心文件工具，使 deterministic runtime、LangGraph runtime 与 Provider adapter 可以在隔离工作区中读取文本代码文件、创建或覆盖文件、精确编辑文件并按模式匹配路径，且不需要临时工具接口。
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

**测试方法**：
- `pytest backend/tests/workspace/test_workspace_file_tools.py -v`

<a id="w53"></a>

## W5.3 grep 工具

**计划周期**：Week 7-8
**状态**：`[ ]`
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
- `grep` 只扫描当前 run 隔离工作区。
- `grep` 基于 `ripgrep` 执行正则内容搜索。
- `grep` 初始化、健康检查或运行前检查必须校验本地 `rg` 可用；缺失时返回结构化 readiness 错误，不得静默降级为未受控搜索实现。
- `grep` 返回路径、行号、匹配片段和截断状态。
- `grep` 能排除常见构建产物和依赖目录。
- `grep` 错误返回结构化错误信息。
- `grep` 必须默认排除 `.runtime/logs`、平台运行数据目录、依赖目录和构建产物。
- `grep` 调用必须写入运行日志摘要；路径越界、权限拒绝和敏感信息阻断必须写入审计记录。

**测试方法**：
- `pytest backend/tests/workspace/test_workspace_grep_tool.py -v`

<a id="w54"></a>

## W5.4 bash 工具与白名单审计

**计划周期**：Week 7-8
**状态**：`[ ]`
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
- 测试不执行破坏真实仓库的命令。

**测试方法**：
- `pytest backend/tests/workspace/test_workspace_bash.py -v`
- `pytest backend/tests/tools/test_tool_audit.py -v`

<a id="w55"></a>

## W5.5 ChangeSet 与 ContextReference

**计划周期**：Week 9
**状态**：`[ ]`
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

<a id="w56"></a>

## W5.6 PreviewTarget Schema 与查询接口

**计划周期**：Week 9
**状态**：`[ ]`
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

<a id="d51"></a>

## D5.1 read_delivery_snapshot 与交付快照读取

**计划周期**：Week 10
**状态**：`[ ]`
**目标**：基于 W5.0 `ToolProtocol` 实现 SCM / Delivery Tools 中的具体 `read_delivery_snapshot` 工具实例，使真实交付读取已固化的 delivery channel snapshot。
**实施计划**：`docs/plans/implementation/d5.1-read-delivery-snapshot-tool.md`

**修改文件列表**：
- Create: `backend/app/delivery/scm.py`
- Create: `backend/tests/delivery/test_read_delivery_snapshot_tool.py`

**实现类/函数**：
- `ScmDeliveryAdapter.read_delivery_snapshot()`
- `ToolResult`
- `ReadDeliverySnapshotTool`

**验收标准**：
- `read_delivery_snapshot` 必须实现 W5.0 定义的 `ToolProtocol` 并注册到 `ToolRegistry`。
- `read_delivery_snapshot` 读取 D4.0 已固化到当前 run 的 delivery channel snapshot。
- 不从项目级最新 DeliveryChannel 重新读取覆盖历史 run。
- snapshot 必须包含 `delivery_mode`、`scm_provider_type`、`repository_identifier`、`default_branch`、`code_review_request_type`、`credential_ref`、`credential_status`、`readiness_status`、`readiness_message` 与 `last_validated_at`。
- Delivery Integration 阶段不再次弹出配置阻塞。
- 本切片不重新定义快照固化规则，只实现交付工具读取规则。
- 读取交付快照必须写入运行日志；缺失快照、快照字段不完整和凭据状态不可用必须写入审计记录。

**测试方法**：
- `pytest backend/tests/delivery/test_read_delivery_snapshot_tool.py -v`

<a id="d52"></a>

## D5.2 prepare_branch 与 create_commit

**计划周期**：Week 10
**状态**：`[ ]`
**目标**：实现 `git_auto_delivery` 的本地分支准备和提交创建工具，使已审批变更可进入受控 Git CLI 路径。
**实施计划**：`docs/plans/implementation/d5.2-prepare-branch-create-commit.md`

**修改文件列表**：
- Modify: `backend/app/delivery/scm.py`
- Create: `backend/tests/delivery/test_prepare_branch_create_commit.py`

**实现类/函数**：
- `ScmDeliveryAdapter.prepare_branch()`
- `ScmDeliveryAdapter.create_commit()`
- `ScmDeliveryAdapter.run_git_cli()`

**验收标准**：
- `prepare_branch` 与 `create_commit` 必须实现 W5.0 定义的 `ToolProtocol` 并注册到 `ToolRegistry`。
- Git 操作通过本地 `git CLI` 适配层执行，不使用 GitPython。
- prepare_branch 基于 fixture 仓库创建受控分支。
- create_commit 基于工作区变更创建提交。
- prepare_branch 与 create_commit 必须写入运行日志和审计记录，记录分支名、提交引用、结果状态、错误摘要和关联 `delivery_record_id`。
- Git 操作不得把 `.runtime/logs` 或平台运行数据目录纳入 diff、提交或交付结果统计。
- 测试使用 fixture 仓库，不影响真实仓库。

**测试方法**：
- `pytest backend/tests/delivery/test_prepare_branch_create_commit.py -v`

<a id="d53"></a>

## D5.3 push_branch 与 create_code_review_request

**计划周期**：Week 10
**状态**：`[ ]`
**目标**：实现 `git_auto_delivery` 的分支推送和代码评审请求创建工具，并通过 mock 远端客户端测试。
**实施计划**：`docs/plans/implementation/d5.3-push-branch-create-review-request.md`

**修改文件列表**：
- Modify: `backend/app/delivery/scm.py`
- Create: `backend/tests/delivery/test_push_branch_create_review_request.py`

**实现类/函数**：
- `ScmDeliveryAdapter.push_branch()`
- `ScmDeliveryAdapter.create_code_review_request()`
- `ScmDeliveryAdapter.resolve_remote_client()`

**验收标准**：
- `push_branch` 与 `create_code_review_request` 必须实现 W5.0 定义的 `ToolProtocol` 并注册到 `ToolRegistry`。
- push_branch 使用受控 Git CLI。
- create_code_review_request 支持 `pull_request` 与 `merge_request` 类型。
- 远端托管平台调用使用 mock client 测试。
- 工具返回 MR/PR 稳定引用和错误信息。
- push_branch 与 create_code_review_request 必须写入运行日志和审计记录，记录远端目标摘要、MR/PR 引用、失败步骤和外部服务错误摘要。
- 审计记录不得包含访问令牌、授权头、Cookie 或真实密钥。

**测试方法**：
- `pytest backend/tests/delivery/test_push_branch_create_review_request.py -v`

<a id="d54"></a>

## D5.4 git_auto_delivery 编排与 snapshot readiness 测试

**计划周期**：Week 10
**状态**：`[ ]`
**目标**：实现 `git_auto_delivery` 编排，把 `read_delivery_snapshot`、prepare branch、commit、push、MR/PR request 串成受控交付路径，并验证交付只依赖已固化 snapshot readiness。
**实施计划**：`docs/plans/implementation/d5.4-git-auto-delivery-snapshot-readiness.md`

**修改文件列表**：
- Create: `backend/app/delivery/git_auto.py`
- Create: `backend/tests/delivery/test_git_auto_delivery.py`
- Create: `backend/tests/delivery/test_git_auto_delivery_snapshot_readiness.py`

**实现类/函数**：
- `GitAutoDeliveryAdapter.deliver()`
- `GitAutoDeliveryAdapter.assert_snapshot_ready()`
- `GitAutoDeliveryAdapter.build_delivery_record()`

**验收标准**：
- `git_auto_delivery` 读取已固化的 delivery channel snapshot。
- `git_auto_delivery` 只断言当前 run 的 `delivery_channel_snapshot_ref` 已固化且完整，其中 `credential_status = ready` 且 `readiness_status = ready`。
- 本切片不重新读取项目级最新 DeliveryChannel，不重新执行审批就绪校验。
- 本切片不固化 snapshot；snapshot 固化唯一发生在 D4.0 / H4.4 的 `code_review_approval` Approve 路径。
- Delivery Integration 阶段不再次弹出配置阻塞。
- 真实交付流程为 `read_delivery_snapshot -> prepare_branch -> create_commit -> push_branch -> create_code_review_request`。
- 每个交付步骤必须继承同一 `trace_id` 与交付阶段 `correlation_id`，并具备独立 `span_id`。
- 交付失败必须能通过日志审计链路定位到失败步骤、错误摘要、审计记录和 DeliveryRecord。
- 测试使用 fixture 仓库与 mock 远端，不影响真实仓库。

**测试方法**：
- `pytest backend/tests/delivery/test_git_auto_delivery.py -v`
- `pytest backend/tests/delivery/test_git_auto_delivery_snapshot_readiness.py -v`

<a id="f51"></a>

## F5.1 工具调用、Diff 与测试结果展示

**计划周期**：Week 9-10
**状态**：`[ ]`
**目标**：实现工具调用、diff 和测试结果的前端展示，使执行过程在 Narrative Feed 与 Inspector 中可读。
**实施计划**：`docs/plans/implementation/f5.1-tool-diff-test-ui.md`

**修改文件列表**：
- Create: `frontend/src/features/feed/ToolCallItem.tsx`
- Create: `frontend/src/features/feed/DiffPreview.tsx`
- Create: `frontend/src/features/feed/TestResultSummary.tsx`
- Create: `frontend/src/features/feed/__tests__/ToolDiffTestItems.test.tsx`

**实现类/函数**：
- `ToolCallItem`
- `DiffPreview`
- `TestResultSummary`

**验收标准**：
- code_generation 展示 diff 预览。
- test_generation_execution 展示测试数量、通过、失败、跳过和缺口。
- 工具调用展示命令、状态、耗时和输出摘要。
- 完整 diff、测试记录和工具过程可通过 Inspector 深看。

**前端设计质量门**：
- 继承项目级前端主基调，并在主基调内采用高密度工程工具呈现。
- 实现前必须梳理工具调用、diff、测试结果、摘要与 Inspector 深看的层级关系。
- 实现后必须检查长文件路径、长日志、失败输出、横向滚动、代码块对比度、窄屏布局和可复制性。
- diff 与测试结果必须保留工程信息密度，不得用装饰性卡片网格替代实际输出。

**测试方法**：
- `npm --prefix frontend run test -- ToolDiffTestItems`

<a id="f52a"></a>

## F5.2a demo_delivery 结果展示

**计划周期**：Week 9
**状态**：`[ ]`
**目标**：基于正式 `DeliveryResultProjection` 实现 `demo_delivery` 的交付结果块和交付详情展示，使无 Git 写动作交付结果在 Narrative Feed 与 Inspector 中可读。
**实施计划**：`docs/plans/implementation/f5.2a-demo-delivery-result-ui.md`

**修改文件列表**：
- Create: `frontend/src/features/delivery/DeliveryResultBlock.tsx`
- Create: `frontend/src/features/delivery/__tests__/DeliveryResultBlock.test.tsx`

**实现类/函数**：
- `DeliveryResultBlock`
- `DeliveryResultProjection`
- `formatDeliveryTarget()`
- `formatDeliveryArtifacts()`

**验收标准**：
- `delivery_result` 展示 `demo_delivery` 的交付模式、目标、变更、测试、评审和产物。
- `delivery_result` 可打开 Inspector 查看完整交付详情。
- `delivery_integration` 阶段展示交付执行过程，`delivery_result` 作为最终结果条目。
- 不适用的交付字段隐藏，不显示空占位。
- UI 数据入口必须是共享 `DeliveryResultProjection`，不得把 demo-only 字段形状固化为最终通用 UI 契约。

**前端设计质量门**：
- 继承项目级前端主基调，不单独询问交付结果风格。
- 实现前必须梳理 `demo_delivery`、DeliveryRecord、失败原因和历史回看的信息层级。
- 实现后必须检查交付模式区分、长目标地址、产物列表、失败态、空字段隐藏和 Inspector 深看入口。
- `delivery_result` 必须作为最终顶层结果条目呈现，不得替代 `delivery_integration` 阶段过程展示。

**测试方法**：
- `npm --prefix frontend run test -- DeliveryResultBlock`

<a id="f52b"></a>

## F5.2b git_auto_delivery 结果展示

**计划周期**：Week 10
**状态**：`[ ]`
**目标**：在共享 `DeliveryResultProjection` 上扩展 `git_auto_delivery` 的真实交付结果展示，使分支、提交、远端评审请求和交付失败原因与 demo 结果保持同一信息层级。
**实施计划**：`docs/plans/implementation/f5.2b-git-auto-delivery-result-ui.md`

**修改文件列表**：
- Modify: `frontend/src/features/delivery/DeliveryResultBlock.tsx`
- Create: `frontend/src/features/delivery/__tests__/GitAutoDeliveryResultBlock.test.tsx`

**实现类/函数**：
- `DeliveryResultBlock`
- `formatCodeReviewRequestTarget()`
- `formatDeliveryFailureReason()`

**验收标准**：
- `git_auto_delivery` 展示交付模式、目标仓库、目标分支、提交引用、MR/PR 链接、测试结论、评审结论和产物引用。
- `demo_delivery` 与 `git_auto_delivery` 共用 `DeliveryResultProjection` 和 `DeliveryResultBlock` 主结构，只在模式特定字段上分支展示。
- 交付失败态展示失败步骤、错误摘要和可深看引用，不显示空 MR/PR 或空提交占位。
- 历史 run 的交付结果可只读回看，不重新读取当前项目级 DeliveryChannel。

**前端设计质量门**：
- 继承项目级前端主基调，并保持交付结果、执行过程和 Inspector 深看的层级一致。
- 实现前必须梳理真实仓库地址、长分支名、长 commit hash、MR/PR 链接、失败原因和历史回看的信息层级。
- 实现后必须检查长目标地址、移动端换行、链接可点击区域、失败态和空字段隐藏。

**测试方法**：
- `npm --prefix frontend run test -- GitAutoDeliveryResultBlock`

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
**目标**：建立跨端人工介入 E2E，覆盖拒绝回退、暂停恢复、终止和重新尝试。
**实施计划**：`docs/plans/implementation/v6.3-playwright-control-flow.md`

**修改文件列表**：
- Create: `e2e/tests/function-one-control-flow.spec.ts`

**实现类/函数**：
- Playwright scenarios for reject rollback, pause, resume, terminate, rerun.

**验收标准**：
- 可覆盖审批拒绝回退到正确阶段。
- 可覆盖暂停后审批禁用，恢复后继续等待同一审批。
- 可覆盖终止后尾部 `system_status`。
- 可覆盖重新尝试创建新 run 并移动焦点。

**前端设计质量门**：
- 不新增风格输入；验证人工介入路径继承同一项目级主基调。
- 人工介入路径必须检查拒绝回退、暂停恢复、终止、重新尝试和历史审批禁用态。
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
- Create: `backend/tests/regression/test_error_contract_regression.py`
- Create: `frontend/src/features/errors/ErrorState.tsx`
- Create: `frontend/src/features/errors/__tests__/ErrorState.test.tsx`

**实现类/函数**：
- `ErrorState`
- `formatApiError()`
- `assertApiErrorContractStable()`

**验收标准**：
- 关键 API 错误在前端有清晰状态。
- paused 审批提交、非法重新尝试、DeliveryChannel 未 ready 等错误有稳定错误码。
- 运行数据目录不可写、审计写入失败、日志查询参数非法和日志载荷被阻断等后端错误有稳定错误码。
- 前端不展示真实凭据内容。

**前端设计质量门**：
- 不新增风格输入；错误态继承项目级主基调。
- 实现后必须检查错误标题、错误详情、恢复动作、敏感信息隐藏、长错误消息、焦点恢复和移动端布局。
- 前端错误态必须解释用户可采取的下一步，不得暴露真实凭据内容或后端内部堆栈。

**测试方法**：
- `pytest backend/tests/regression/test_error_contract_regression.py -v`
- `npm --prefix frontend run test -- ErrorState`

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
