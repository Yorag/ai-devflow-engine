# 08 真实 Git 交付与执行结果展示

## 范围

本分卷覆盖 Week 9-10 的真实 Git 交付工具、`git_auto_delivery` 编排和执行结果展示。完成后，`delivery_integration` 可以基于已固化 delivery channel snapshot 读取交付配置、准备分支、创建提交、推送分支、创建代码评审请求，并在前端展示工具调用、diff、测试结果和交付结果。

本分卷承接 04 分卷的交付快照 gate、05 分卷的 demo_delivery 基线、07 分卷的 ToolProtocol / ToolRegistry / 风险门禁。D5.1-D5.4 只实现 delivery 具体工具和 `git_auto_delivery` 编排；真实 Git 操作只在 `git_auto_delivery` 适配层中发生，并且测试必须使用 fixture 仓库和 mock 远端。

Git 交付、远端交付请求、交付结果统计和前端展示必须默认排除 `.runtime/logs` 与平台运行数据目录。会造成工作区、Git 或远端交付状态变化的工具调用必须写入审计记录；高风险工具动作必须先创建 `ToolConfirmationRequest` 并等待用户允许。

<a id="d51"></a>

## D5.1 read_delivery_snapshot 与交付快照读取

**计划周期**：Week 10
**状态**：`[x]`
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
- `read_delivery_snapshot` 执行必须经过 W5.0b execution gate 与 W5.0d 风险门禁；Delivery Integration 阶段的 `allowed_tools` 未包含该工具时必须拒绝执行并返回统一错误码。
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
**状态**：`[x]`
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
- `prepare_branch` 与 `create_commit` 执行必须经过 W5.0b execution gate 与 W5.0d 风险门禁的工具名、阶段 `allowed_tools`、输入 Schema、工作区边界、风险分级、工具确认门禁、超时和审计策略校验。
- Git 操作通过本地 `git CLI` 适配层执行，不使用 GitPython。
- prepare_branch 基于 fixture 仓库创建受控分支。
- create_commit 基于工作区变更创建提交。
- prepare_branch 与 create_commit 必须写入运行日志和审计记录，记录分支名、提交引用、结果状态、错误摘要和关联 `delivery_record_id`。
- Git 操作不得把 `.runtime/logs` 或平台运行数据目录纳入 diff、提交或交付结果统计。
- 测试使用 W5.0c fixture 仓库，不影响真实仓库。

**测试方法**：
- `pytest backend/tests/delivery/test_prepare_branch_create_commit.py -v`

<a id="d53"></a>

## D5.3 push_branch 与 create_code_review_request

**计划周期**：Week 10
**状态**：`[x]`
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
- `push_branch` 与 `create_code_review_request` 执行必须经过 W5.0b execution gate 与 W5.0d 风险门禁；不得绕过注册表直接调用 Git CLI 或远端托管平台客户端。
- push_branch 使用受控 Git CLI。
- create_code_review_request 支持 `pull_request` 与 `merge_request` 类型。
- 远端托管平台调用使用 mock client 测试。
- 工具返回 MR/PR 稳定引用和错误信息。
- push_branch 与 create_code_review_request 必须写入运行日志和审计记录，记录远端目标摘要、MR/PR 引用、失败步骤和外部服务错误摘要。
- 审计记录不得包含访问令牌、授权头、Cookie 或真实密钥。
- 测试使用 W5.0c mock remote delivery client，不调用真实托管平台。

**测试方法**：
- `pytest backend/tests/delivery/test_push_branch_create_review_request.py -v`

<a id="d54"></a>

## D5.4 git_auto_delivery 编排与 snapshot readiness 测试

**计划周期**：Week 10
**状态**：`[x]`
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
- `git_auto_delivery` 编排每一步都必须通过 `ToolRegistry.execute()` 调用 delivery tool，并使用当前阶段 `allowed_tools`、工具输入 Schema、W5.0d 风险分级、工具确认门禁、超时策略和审计策略执行门；不得直接调用 `ScmDeliveryAdapter` 私有方法、Git CLI 或远端 client。
- 每个交付步骤必须继承同一 `trace_id` 与交付阶段 `correlation_id`，并具备独立 `span_id`。
- 交付失败必须能通过日志审计链路定位到失败步骤、错误摘要、审计记录和 DeliveryRecord。
- 测试使用 W5.0c fixture 仓库与 mock 远端，不影响真实仓库。

**测试方法**：
- `pytest backend/tests/delivery/test_git_auto_delivery.py -v`
- `pytest backend/tests/delivery/test_git_auto_delivery_snapshot_readiness.py -v`
**验证摘要**：实施计划 `docs/plans/implementation/d5.4-git-auto-delivery-snapshot-readiness.md` 已在 integration checkpoint 合入 `bbab5d9`。Worker verification 中 focused D5.4 tests 通过 11 个 tests，D5 delivery regression 通过 44 个 tests，impacted delivery/runtime regression 通过 36 个 tests，full backend suite 通过 1245 个 tests。本次 integration verification 在 `integration/function-one-acceleration` 上运行 D5 delivery regression、delivery service/demo delivery regression 和 deterministic runtime regression，共 80 个 tests 通过。

<a id="f51"></a>

## F5.1 工具调用、Diff 与测试结果展示

**计划周期**：Week 9-10
**状态**：`[/]`
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
**验证摘要**：实施计划 `docs/plans/implementation/f5.1-tool-diff-test-ui.md` 已在 integration checkpoint 合入 `060cda4`。`npm --prefix frontend run test -- ToolDiffTestItems`、`npm --prefix frontend run test -- StageNode`、`npm --prefix frontend run test -- InspectorSections` 与 `npm --prefix frontend run build` 在 worker checkpoint 已通过；本次批量 integration verification 中 `npm --prefix frontend test` 通过 23 个 test files、194 个 tests，`npm --prefix frontend run build` 成功完成 TypeScript 检查与生产构建。该切片当前仍按 mock-first 部分完成收敛，后续 checkpoint 还需要用真实后端 `code_generation` / `test_generation_execution` payload 证明 feed 与 Inspector 细节契约。

<a id="f52a"></a>

## F5.2a demo_delivery 结果展示

**计划周期**：Week 9
**状态**：`[/]`
**目标**：基于正式 `delivery_result` 顶层条目契约与 `DeliveryResultDetailProjection` 实现 `demo_delivery` 的交付结果块和交付详情展示，使无 Git 写动作交付结果在 Narrative Feed 与 Inspector 中可读。
**实施计划**：`docs/plans/implementation/f5.2a-demo-delivery-result-ui.md`

**修改文件列表**：
- Create: `frontend/src/features/delivery/DeliveryResultBlock.tsx`
- Create: `frontend/src/features/delivery/__tests__/DeliveryResultBlock.test.tsx`

**实现类/函数**：
- `DeliveryResultBlock`
- `buildDeliveryResultViewModel()`
- `formatDeliveryTarget()`
- `formatDeliveryArtifacts()`

**验收标准**：
- `delivery_result` 展示 `demo_delivery` 的交付模式、最终交付摘要、已公开的结果要点和 Inspector 深看入口。
- `delivery_result` 可打开 Inspector 查看完整交付详情。
- `delivery_integration` 阶段展示交付执行过程，`delivery_result` 作为最终结果条目。
- 不适用的交付字段隐藏，不显示空占位。
- 中栏摘要必须来自正式 `delivery_result` 顶层条目契约；完整输入、过程、输出、产物与量化信息必须来自 `DeliveryResultDetailProjection`。
- `demo_delivery` 与 `git_auto_delivery` 必须共用前端内部 `DeliveryResultViewModel` / `DeliveryResultBlock` 主结构，不得把 demo-only 字段形状固化为最终通用 UI 契约，也不得引入新的后端公开投影名。

**前端设计质量门**：
- 继承项目级前端主基调，不单独询问交付结果风格。
- 实现前必须梳理 `demo_delivery`、DeliveryRecord、历史回看，以及交付过程失败与 `delivery_integration` / `system_status` 的分层。
- 实现后必须检查交付模式区分、长目标地址、产物列表、成功态空字段隐藏和 Inspector 深看入口。
- `delivery_result` 必须作为最终顶层结果条目呈现，不得替代 `delivery_integration` 阶段过程展示。

**测试方法**：
- `npm --prefix frontend run test -- DeliveryResultBlock`
**验证摘要**：实施计划 `docs/plans/implementation/f5.2a-demo-delivery-result-ui.md` 已在 integration checkpoint 合入 `48264fc`。`npm --prefix frontend run test -- DeliveryResultBlock`、`npm --prefix frontend run test -- FeedEntryRenderer`、`npm --prefix frontend run test -- InspectorSections` 和 `npm --prefix frontend run build` 均在 worker branch 与 integration merge 后通过。本切片当前按 mock-first 部分完成收敛，后续 checkpoint 还需要用真实后端 `delivery_result` 与 `DeliveryResultDetailProjection` payload 证明前端展示契约。

<a id="f52b"></a>

## F5.2b git_auto_delivery 结果展示

**计划周期**：Week 10
**状态**：`[/]`
**目标**：在共享前端 `DeliveryResultViewModel` / `DeliveryResultBlock` 结构上扩展 `git_auto_delivery` 的真实交付结果展示，使分支、提交与远端评审请求结果和 demo 结果保持同一信息层级。
**实施计划**：`docs/plans/implementation/f5.2b-git-auto-delivery-result-ui.md`

**修改文件列表**：
- Modify: `frontend/src/features/delivery/DeliveryResultBlock.tsx`
- Create: `frontend/src/features/delivery/__tests__/GitAutoDeliveryResultBlock.test.tsx`

**实现类/函数**：
- `DeliveryResultBlock`
- `formatCodeReviewRequestTarget()`
- `formatDeliveryHighlights()`

**验收标准**：
- `git_auto_delivery` 展示交付模式、最终交付摘要，以及当前正式顶层条目已公开的目标分支、提交引用、MR/PR 链接、测试摘要等结果要点。
- `demo_delivery` 与 `git_auto_delivery` 共用前端内部 `DeliveryResultViewModel` 和 `DeliveryResultBlock` 主结构，只在模式特定字段上分支展示。
- 不显示空 MR/PR 或空提交占位。
- `delivery_integration` 失败时不生成 `delivery_result`；失败步骤、错误摘要和可深看引用由阶段过程记录与尾部 `system_status` 承载，不在成功态交付结果块中伪造失败结果。
- 历史 run 的交付结果可只读回看，不重新读取当前项目级 DeliveryChannel。

**前端设计质量门**：
- 继承项目级前端主基调，并保持交付结果、执行过程和 Inspector 深看的层级一致。
- 实现前必须梳理真实仓库地址、长分支名、长 commit hash、MR/PR 链接、历史回看，以及交付过程失败与 `delivery_integration` / `system_status` 的分层。
- 实现后必须检查长目标地址、移动端换行、链接可点击区域、成功态空字段隐藏，并确认交付过程失败不会被误渲染为成功态交付结果块。

**测试方法**：
- `npm --prefix frontend run test -- GitAutoDeliveryResultBlock`
**验证摘要**：实施计划 `docs/plans/implementation/f5.2b-git-auto-delivery-result-ui.md` 已在 integration checkpoint 合入 `4071e82`。Worker verification 中 `npm --prefix frontend run test -- GitAutoDeliveryResultBlock` 通过 7 个 tests，`npm --prefix frontend run test -- DeliveryResultBlock` 通过 13 个 tests，`npm --prefix frontend run build` 成功完成 TypeScript 检查与生产构建。本次 integration verification 在 `integration/function-one-acceleration` 上重复运行同三条命令并通过。本切片当前按前端契约部分完成收敛，后续 checkpoint 还需要用真实后端 `git_auto_delivery` / `delivery_result` payload 证明前端展示契约，完成后再收敛为 `[x]`。
