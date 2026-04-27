# 05 工作区、真实 Git 交付与硬化

## 范围

本分卷覆盖 Week 9-12 的工作区工具、功能二扩展边界、`git_auto_delivery` 真实 Git 交付适配、前端交付展示、端到端测试、OpenAPI 一致性与系统硬化。完成后，系统具备平台级 V1 发布候选条件。

本分卷把 Workspace Tools 与 Delivery Tools 拆成独立适配器切片。`demo_delivery` 已在 Week 7 作为正式无 Git 写动作交付适配器落地；本分卷只实现 `git_auto_delivery` 的真实 Git 交付能力。真实 Git 操作只在 `git_auto_delivery` 适配层中发生，并且测试必须使用 fixture 仓库和 mock 远端。

<a id="w51"></a>

## W5.1 WorkspaceManager 隔离工作区

**计划周期**：Week 9
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
- 工作区管理不执行业务文件读写或 shell 命令。

**测试方法**：
- `pytest backend/tests/workspace/test_workspace_manager.py -v`

<a id="w52"></a>

## W5.2 文件工具 read/write/edit/list

**计划周期**：Week 9
**状态**：`[ ]`
**目标**：实现核心文件工具，使 runtime 可以在隔离工作区中读写、编辑和列出文件。
**实施计划**：`docs/plans/implementation/w5.2-workspace-file-tools.md`

**修改文件列表**：
- Create: `backend/app/workspace/tools.py`
- Create: `backend/tests/workspace/test_workspace_file_tools.py`

**实现类/函数**：
- `read_file()`
- `write_file()`
- `edit_file()`
- `list_files()`
- `WorkspaceToolResult`

**验收标准**：
- 工具只允许访问当前 run 的隔离工作区。
- `read_file`、`write_file`、`edit_file`、`list_files` 都返回结构化结果和错误信息。
- 文件编辑可生成变更记录引用，供 StageArtifact 或 ChangeSet 使用。
- 本切片不实现搜索和 shell。

**测试方法**：
- `pytest backend/tests/workspace/test_workspace_file_tools.py -v`

<a id="w53"></a>

## W5.3 search 工具

**计划周期**：Week 9
**状态**：`[ ]`
**目标**：实现工作区 search 工具，使 runtime 可以受控搜索当前 run 工作区内容。
**实施计划**：`docs/plans/implementation/w5.3-workspace-search-tool.md`

**修改文件列表**：
- Modify: `backend/app/workspace/tools.py`
- Create: `backend/tests/workspace/test_workspace_search_tool.py`

**实现类/函数**：
- `search()`
- `SearchResultItem`
- `WorkspaceSearchOptions`

**验收标准**：
- search 只扫描当前 run 隔离工作区。
- search 返回路径、行号和匹配片段。
- search 能排除常见构建产物和依赖目录。
- 搜索错误返回结构化错误信息。

**测试方法**：
- `pytest backend/tests/workspace/test_workspace_search_tool.py -v`

<a id="w54"></a>

## W5.4 shell 工具与审计记录

**计划周期**：Week 9
**状态**：`[ ]`
**目标**：实现受控 shell 工具和工具调用审计记录，使测试执行和命令执行可追踪。
**实施计划**：`docs/plans/implementation/w5.4-workspace-shell-audit.md`

**修改文件列表**：
- Create: `backend/app/workspace/shell.py`
- Create: `backend/app/workspace/audit.py`
- Create: `backend/tests/workspace/test_workspace_shell.py`
- Create: `backend/tests/workspace/test_tool_audit.py`

**实现类/函数**：
- `run_shell_command()`
- `ShellExecutionResult`
- `ToolAuditLogger.record_tool_call()`
- `ToolAuditLogger.record_tool_error()`

**验收标准**：
- shell 命令通过受控子进程执行。
- shell 工作目录被限制在当前 run 工作区。
- 命令输出、退出码、耗时和错误被结构化记录。
- 工具调用产生日志和审计记录。
- 测试不执行破坏真实仓库的命令。

**测试方法**：
- `pytest backend/tests/workspace/test_workspace_shell.py -v`
- `pytest backend/tests/workspace/test_tool_audit.py -v`

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
- `register_preview_target_routes(router: APIRouter) -> None`

**验收标准**：
- `GET /api/preview-targets/{previewTargetId}` 提供查询接口。
- PreviewTarget 提供稳定标识、项目/run 关联、目标类型和引用信息。
- V1 仅定义对象和查询接口，不实现预览启动与热更新。

**测试方法**：
- `pytest backend/tests/api/test_preview_target_api.py -v`

<a id="d51"></a>

## D5.1 read_delivery_channel 与交付快照读取

**计划周期**：Week 10
**状态**：`[ ]`
**目标**：实现 SCM / Delivery Tools 中的 `read_delivery_channel`，使真实交付读取已固化的 delivery channel snapshot。
**实施计划**：`docs/plans/implementation/d5.1-read-delivery-channel-tool.md`

**修改文件列表**：
- Create: `backend/app/delivery/scm.py`
- Create: `backend/tests/delivery/test_read_delivery_channel_tool.py`

**实现类/函数**：
- `ScmDeliveryAdapter.read_delivery_channel()`
- `DeliveryChannelSnapshot`
- `DeliveryToolResult`

**验收标准**：
- `read_delivery_channel` 读取当前 run 已固化的 delivery channel snapshot。
- 不从项目级最新 DeliveryChannel 重新读取覆盖历史 run。
- snapshot 至少包含 `delivery_mode`、`scm_provider_type`、`repository_identifier`、`default_branch`、`code_review_request_type` 与 `credential_ref`。
- Delivery Integration 阶段不再次弹出配置阻塞。

**测试方法**：
- `pytest backend/tests/delivery/test_read_delivery_channel_tool.py -v`

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
- Git 操作通过本地 `git CLI` 适配层执行，不使用 GitPython。
- prepare_branch 基于 fixture 仓库创建受控分支。
- create_commit 基于工作区变更创建提交。
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
- push_branch 使用受控 Git CLI。
- create_code_review_request 支持 `pull_request` 与 `merge_request` 类型。
- 远端托管平台调用使用 mock client 测试。
- 工具返回 MR/PR 稳定引用和错误信息。

**测试方法**：
- `pytest backend/tests/delivery/test_push_branch_create_review_request.py -v`

<a id="d54"></a>

## D5.4 git_auto_delivery 编排与 gate 测试

**计划周期**：Week 10
**状态**：`[ ]`
**目标**：实现 `git_auto_delivery` 编排，把 read channel、prepare branch、commit、push、MR/PR request 串成受控交付路径。
**实施计划**：`docs/plans/implementation/d5.4-git-auto-delivery-orchestration.md`

**修改文件列表**：
- Create: `backend/app/delivery/git_auto.py`
- Create: `backend/tests/delivery/test_git_auto_delivery.py`
- Create: `backend/tests/delivery/test_delivery_readiness_gate.py`

**实现类/函数**：
- `GitAutoDeliveryAdapter.deliver()`
- `GitAutoDeliveryAdapter.assert_snapshot_ready()`
- `GitAutoDeliveryAdapter.build_delivery_record()`

**验收标准**：
- `git_auto_delivery` 读取已固化的 delivery channel snapshot。
- 审批通过前完成 readiness gate。
- Delivery Integration 阶段不再次弹出配置阻塞。
- 真实交付流程为 `read_delivery_channel -> prepare_branch -> create_commit -> push_branch -> create_code_review_request`。
- 测试使用 fixture 仓库与 mock 远端，不影响真实仓库。

**测试方法**：
- `pytest backend/tests/delivery/test_git_auto_delivery.py -v`
- `pytest backend/tests/delivery/test_delivery_readiness_gate.py -v`

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

**测试方法**：
- `npm --prefix frontend run test -- ToolDiffTestItems`

<a id="f52"></a>

## F5.2 DeliveryResultBlock 与交付详情展示

**计划周期**：Week 9-10
**状态**：`[ ]`
**目标**：实现交付结果块和交付详情展示，使最终交付结果在 Narrative Feed 与 Inspector 中可读。
**实施计划**：`docs/plans/implementation/f5.2-delivery-result-ui.md`

**修改文件列表**：
- Create: `frontend/src/features/delivery/DeliveryResultBlock.tsx`
- Create: `frontend/src/features/delivery/__tests__/DeliveryResultBlock.test.tsx`

**实现类/函数**：
- `DeliveryResultBlock`
- `formatDeliveryTarget()`
- `formatDeliveryArtifacts()`

**验收标准**：
- `delivery_result` 展示交付模式、目标、变更、测试、评审和产物。
- `delivery_result` 可打开 Inspector 查看完整交付详情。
- `delivery_integration` 阶段展示交付执行过程，`delivery_result` 作为最终结果条目。
- 不适用的交付字段隐藏，不显示空占位。

**测试方法**：
- `npm --prefix frontend run test -- DeliveryResultBlock`

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
- Create: `e2e/playwright.config.ts`
- Create: `e2e/tests/function-one-full-flow.spec.ts`

**实现类/函数**：
- Playwright scenario for new requirement, clarification, approvals, delivery result.

**验收标准**：
- 用户可新建会话、发送首条需求、完成澄清、通过两次审批并看到 `delivery_result`。
- 前端显示与后端投影一致。
- Narrative Feed、Run Switcher、Composer 和 Inspector 关键交互可用。

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
- Playwright scenarios for reject rollback, pause, resume, terminate, retry.

**验收标准**：
- 可覆盖审批拒绝回退到正确阶段。
- 可覆盖暂停后审批禁用，恢复后继续等待同一审批。
- 可覆盖终止后尾部 `system_status`。
- 可覆盖重新尝试创建新 run 并移动焦点。

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
- paused 审批提交、非法 retry、DeliveryChannel 未 ready 等错误有稳定错误码。
- 前端不展示真实凭据内容。

**测试方法**：
- `pytest backend/tests/regression/test_error_contract_regression.py -v`
- `npm --prefix frontend run test -- ErrorState`

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

**测试方法**：
- `pytest backend/tests/regression -v`
- `npm --prefix e2e run test`
