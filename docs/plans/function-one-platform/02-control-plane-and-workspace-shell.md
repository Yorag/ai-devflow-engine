# 02 控制面与工作台外壳

## 范围

本分卷覆盖 Week 2-4 的控制面 API 与前端工作台外壳。完成后，前端可基于真实或 mock 契约完成 Project、Session、Template、Provider、DeliveryChannel、设置弹窗和模板空态的主要交互。

本分卷按依赖顺序拆分：先建立默认 Project 与最小默认 `demo_delivery` 通道，再建立系统模板并创建 draft Session；DeliveryChannel 的查询、保存与 readiness 校验作为独立控制面能力落地，避免一个任务同时吞掉全部控制面。

凡本分卷修改 `backend/app/api/routes/*` 的 API 切片，对应 API 测试必须在本切片内断言新增或修改的 path、method、请求 Schema、响应 Schema 和主要错误响应已进入 `/api/openapi.json`；V6.4 只做全局覆盖回归，不作为这些路由第一次发现 OpenAPI 漂移的入口。

<a id="c21"></a>

## C2.1 默认 Project、项目加载与项目列表

**计划周期**：Week 3
**状态**：`[ ]`
**目标**：实现默认项目登记、本地项目加载、项目列表查询和最小默认 `demo_delivery` 通道创建，使系统首次启动后具备稳定项目上下文、可切换项目列表与默认交付通道引用。
**实施计划**：`docs/plans/implementation/c2.1-default-projects.md`

**修改文件列表**：
- Create: `backend/app/services/projects.py`
- Create: `backend/app/services/delivery_channels.py`
- Create: `backend/app/api/routes/projects.py`
- Create: `backend/tests/services/test_project_service.py`
- Create: `backend/tests/api/test_project_api.py`

**实现类/函数**：
- `ProjectService.ensure_default_project()`
- `DeliveryChannelService.ensure_default_channel()`
- `ProjectService.list_projects()`
- `ProjectService.create_project()`
- `ProjectService.load_project()`

**验收标准**：
- 首次启动存在默认项目，绑定平台仓库自身路径。
- `GET /api/projects` 在未手动加载项目时也返回默认项目。
- `POST /api/projects` 支持通过本地 `root_path` 加载新项目，并返回可用于左栏切换的项目摘要。
- 默认 Project 创建时通过 `DeliveryChannelService.ensure_default_channel()` 同步创建最小项目级默认 `DeliveryChannel(delivery_mode=demo_delivery, credential_status=ready, readiness_status=ready, readiness_message=null)`。
- 新建 Project 记录 `root_path`、`name`、`default_delivery_channel_id` 和时间戳，且 `default_delivery_channel_id` 指向可解析的默认通道。
- 本切片不实现 Session、Template 或 DeliveryChannel 查询、保存、readiness 校验业务。
- API 测试必须断言 `GET /api/projects`、`POST /api/projects` 及其请求/响应 Schema 和主要错误响应已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/services/test_project_service.py -v`
- `pytest backend/tests/api/test_project_api.py -v`

<a id="c22"></a>

## C2.2 系统模板与内置 Provider seed

**计划周期**：Week 3
**状态**：`[ ]`
**目标**：实现三个系统模板和两个内置 Provider 的初始化，使 draft Session 可以稳定关联默认模板。
**实施计划**：`docs/plans/implementation/c2.2-system-template-provider-seed.md`

**修改文件列表**：
- Create: `backend/app/services/templates.py`
- Create: `backend/app/services/providers.py`
- Create: `backend/app/api/routes/templates.py`
- Create: `backend/app/api/routes/providers.py`
- Create: `backend/tests/services/test_template_seed.py`
- Create: `backend/tests/services/test_provider_seed.py`
- Create: `backend/tests/api/test_template_provider_seed_api.py`

**实现类/函数**：
- `TemplateService.seed_system_templates()`
- `TemplateService.list_templates()`
- `TemplateService.get_default_template()`
- `ProviderService.seed_builtin_providers()`
- `ProviderService.list_providers()`

**验收标准**：
- 系统模板包含 `Bug 修复流程`、`新功能开发流程`、`重构流程`。
- 默认模板为 `新功能开发流程`。
- 三个系统模板共享固定六阶段骨架。
- 三个系统模板差异只体现在阶段槽位默认绑定的 `AgentRole`、槽位内最终生效的 `system_prompt`、Provider 绑定和自动回归默认策略。
- Provider 默认包含 `火山引擎`、`DeepSeek`。
- `OpenAI Completions compatible` 只作为 custom Provider 接入协议，不作为内置 Provider 名称。
- API 测试必须断言 `GET /api/pipeline-templates`、`GET /api/pipeline-templates/{templateId}`、`GET /api/providers` 及其响应 Schema 和主要错误响应已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/services/test_template_seed.py -v`
- `pytest backend/tests/services/test_provider_seed.py -v`
- `pytest backend/tests/api/test_template_provider_seed_api.py -v`

<a id="c23"></a>

## C2.3 draft Session 与模板选择更新

**计划周期**：Week 3
**状态**：`[ ]`
**目标**：实现项目下 draft Session 创建和运行前模板选择更新，使首条需求前的会话状态符合规格。
**实施计划**：`docs/plans/implementation/c2.3-draft-session-template-selection.md`

**修改文件列表**：
- Create: `backend/app/services/sessions.py`
- Create: `backend/app/api/routes/sessions.py`
- Create: `backend/tests/services/test_session_service.py`
- Create: `backend/tests/api/test_session_api.py`

**实现类/函数**：
- `SessionService.create_session()`
- `SessionService.update_selected_template()`
- `SessionService.list_project_sessions()`
- `SessionService.get_session()`

**验收标准**：
- 新建 Session 时状态为 `draft` 且 `current_run_id = null`。
- 新建 Session 默认关联 `新功能开发流程` 模板。
- 只有 `draft` 且尚未创建 run 的 Session 允许更新 `selected_template_id`。
- `latest_stage_type` 在 draft 状态下为 `null`。
- 同一 Project 下可列出近期 Session。
- API 测试必须断言 `POST /api/projects/{projectId}/sessions`、`GET /api/projects/{projectId}/sessions`、`GET /api/sessions/{sessionId}`、`PUT /api/sessions/{sessionId}/template` 及其请求/响应 Schema 和主要错误响应已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/services/test_session_service.py -v`
- `pytest backend/tests/api/test_session_api.py -v`

<a id="c24"></a>

## C2.4 用户模板保存、覆盖与删除

**计划周期**：Week 3
**状态**：`[ ]`
**目标**：实现用户模板的另存、覆盖和删除语义，保证系统模板不可被覆盖或删除。
**实施计划**：`docs/plans/implementation/c2.4-user-template-crud.md`

**修改文件列表**：
- Modify: `backend/app/services/templates.py`
- Modify: `backend/app/api/routes/templates.py`
- Create: `backend/tests/services/test_user_template_service.py`
- Create: `backend/tests/api/test_template_api.py`

**实现类/函数**：
- `TemplateService.save_as_user_template()`
- `TemplateService.patch_user_template()`
- `TemplateService.delete_user_template()`
- `TemplateService.validate_editable_fields()`

**验收标准**：
- `system_template` 允许选择和另存，不允许直接覆盖或删除。
- `user_template` 支持覆盖、另存和删除。
- 模板编辑只允许选择每个阶段槽位绑定的已有 `AgentRole`，并修改该槽位最终生效的 `system_prompt`、`provider_id`、自动回归开关和最大重试次数。
- 模板保存必须固化各阶段槽位最终生效的 `role_id`、`system_prompt` 与 `provider_id`，不得修改共享 `AgentRole.role_name`。
- 用户不能通过模板删除、禁用、重排核心阶段，不能关闭两个必需审批检查点。
- 删除当前选中的用户模板后，调用方可回退到默认系统模板。
- API 测试必须断言 `POST /api/pipeline-templates`、`PATCH /api/pipeline-templates/{templateId}`、`POST /api/pipeline-templates/{templateId}/save-as`、`DELETE /api/pipeline-templates/{templateId}` 及其请求/响应 Schema 和主要错误响应已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/services/test_user_template_service.py -v`
- `pytest backend/tests/api/test_template_api.py -v`

<a id="c25"></a>

## C2.5 custom Provider 管理

**计划周期**：Week 3
**状态**：`[ ]`
**目标**：实现 custom Provider 新增和编辑，使模板运行配置可以绑定用户自定义 Provider。
**实施计划**：`docs/plans/implementation/c2.5-custom-provider-management.md`

**修改文件列表**：
- Modify: `backend/app/services/providers.py`
- Modify: `backend/app/api/routes/providers.py`
- Create: `backend/tests/services/test_custom_provider_service.py`
- Create: `backend/tests/api/test_provider_api.py`

**实现类/函数**：
- `ProviderService.create_custom_provider()`
- `ProviderService.patch_custom_provider()`
- `ProviderService.get_provider()`

**验收标准**：
- 内置 Provider 只读，不允许修改供应商类型。
- custom Provider 使用用户自定义展示名。
- custom Provider 接入协议为 `OpenAI Completions compatible`。
- API 返回 Provider 状态，不返回真实密钥内容。
- API 测试必须断言 `POST /api/providers`、`PATCH /api/providers/{providerId}`、`GET /api/providers/{providerId}` 及其请求/响应 Schema 和主要错误响应已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/services/test_custom_provider_service.py -v`
- `pytest backend/tests/api/test_provider_api.py -v`

<a id="c26"></a>

## C2.6 DeliveryChannel 查询与保存

**计划周期**：Week 3
**状态**：`[ ]`
**目标**：实现项目级默认 DeliveryChannel 的查询和保存，使交付配置独立于 Session 与模板，并复用 C2.1 已创建的默认通道。
**实施计划**：`docs/plans/implementation/c2.6-delivery-channel-crud.md`

**修改文件列表**：
- Modify: `backend/app/services/delivery_channels.py`
- Modify: `backend/app/api/routes/projects.py`
- Create: `backend/tests/services/test_delivery_channel_service.py`
- Create: `backend/tests/api/test_delivery_channel_api.py`

**实现类/函数**：
- `DeliveryChannelService.get_project_channel()`
- `DeliveryChannelService.update_project_channel()`
- `DeliveryChannelService.ensure_default_channel()`

**验收标准**：
- 每个 Project 在 V1 只维护一个项目级默认 DeliveryChannel。
- `get_project_channel()` 必须返回 C2.1 创建的默认通道，不得在查询时隐式创建第二条通道。
- 未配置远端交付条件时默认回落到 `demo_delivery`。
- `demo_delivery` 下 Git 字段允许为 `null`。
- `git_auto_delivery` 保存时接收托管平台类型、仓库标识、默认分支、代码评审请求类型和 `credential_ref`。
- DeliveryChannel 配置不属于 Session 或模板。
- API 测试必须断言 `GET /api/projects/{projectId}/delivery-channel`、`PUT /api/projects/{projectId}/delivery-channel` 及其请求/响应 Schema 和主要错误响应已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/services/test_delivery_channel_service.py -v`
- `pytest backend/tests/api/test_delivery_channel_api.py -v`

<a id="c27"></a>

## C2.7 DeliveryChannel readiness 校验

**计划周期**：Week 3
**状态**：`[ ]`
**目标**：实现项目级交付配置校验，统一输出 `readiness_status`、`credential_status` 和阻塞原因。
**实施计划**：`docs/plans/implementation/c2.7-delivery-channel-readiness.md`

**修改文件列表**：
- Modify: `backend/app/services/delivery_channels.py`
- Modify: `backend/app/api/routes/projects.py`
- Create: `backend/tests/services/test_delivery_channel_readiness.py`
- Create: `backend/tests/api/test_delivery_channel_validate_api.py`

**实现类/函数**：
- `DeliveryChannelService.validate_project_channel()`
- `DeliveryChannelService.compute_readiness()`
- `DeliveryChannelService.resolve_credential_status()`

**验收标准**：
- `demo_delivery` 默认可用。
- `git_auto_delivery` 字段不完整时 `readiness_status != ready`。
- `git_auto_delivery` 缺少可用凭据时 `credential_status` 为 `unbound` 或 `invalid`，且 `readiness_status != ready`。
- 校验接口不修改已固化到历史 run 的交付快照。
- 返回的 `readiness_message` 能表达主阻塞原因。
- API 测试必须断言 `POST /api/projects/{projectId}/delivery-channel/validate` 的请求 Schema、响应 Schema、`validated_at` 字段和主要错误响应已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/services/test_delivery_channel_readiness.py -v`
- `pytest backend/tests/api/test_delivery_channel_validate_api.py -v`

<a id="f21"></a>

## F2.1 API Client 路径与类型入口

**计划周期**：Week 2-3
**状态**：`[ ]`
**目标**：建立前端 API client 基础请求封装和控制面路径入口，使页面开发不直接拼接 URL。
**实施计划**：`docs/plans/implementation/f2.1-api-client-paths.md`

**修改文件列表**：
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/projects.ts`
- Create: `frontend/src/api/sessions.ts`
- Create: `frontend/src/api/templates.ts`
- Create: `frontend/src/api/providers.ts`
- Create: `frontend/src/api/delivery-channels.ts`
- Create: `frontend/src/api/runs.ts`
- Create: `frontend/src/api/approvals.ts`
- Create: `frontend/src/api/query.ts`
- Create: `frontend/src/api/events.ts`
- Create: `frontend/src/api/__tests__/client.test.ts`

**实现类/函数**：
- `apiRequest<T>()`
- `listProjects()`
- `createSession()`
- `listPipelineTemplates()`
- `listProviders()`
- `getProjectDeliveryChannel()`
- `updateProjectDeliveryChannel()`
- `validateProjectDeliveryChannel()`
- `saveAsPipelineTemplate()`
- `patchPipelineTemplate()`
- `deletePipelineTemplate()`
- `appendSessionMessage()`
- `pauseRun()`
- `resumeRun()`
- `terminateRun()`
- `createRerun()`
- `approveApproval()`
- `rejectApproval()`
- `getSessionWorkspace()`
- `getRunTimeline()`
- `createSessionEventSource()`

**验收标准**：
- 前端 API client 覆盖 `projects`、`sessions`、`templates`、`providers`、`deliveryChannels`、`runs`、`approvals`、`query` 与 `events` 的资源边界。
- 错误响应进入统一错误处理。
- UI 组件不得直接手写核心 API 路径；后续展示切片只能通过本切片建立的 client 模块补充类型和 hook。

**测试方法**：
- `npm --prefix frontend run test -- client`

<a id="f22"></a>

## F2.2 Mock Fixtures 与 Query Hooks

**计划周期**：Week 2-3
**状态**：`[ ]`
**目标**：建立由后端 Schema 派生的 mock fixtures 和 TanStack Query hooks，使前端可在无后端时推进控制台流程。
**实施计划**：`docs/plans/implementation/f2.2-mock-fixtures-query-hooks.md`

**修改文件列表**：
- Create: `frontend/src/api/hooks.ts`
- Create: `frontend/src/mocks/fixtures.ts`
- Create: `frontend/src/mocks/handlers.ts`
- Create: `frontend/src/api/__tests__/hooks.test.ts`

**实现类/函数**：
- `getSessionWorkspace()`
- `getRunTimeline()`
- `useProjectsQuery()`
- `useSessionWorkspaceQuery()`
- `mockSessionWorkspace`

**验收标准**：
- mock fixtures 覆盖空白会话、运行中会话、等待澄清、等待审批、完成、失败、终止。
- mock feed 条目类型与 C1.3 契约一致。
- TanStack Query hooks 可以在无后端时支撑页面开发。

**测试方法**：
- `npm --prefix frontend run test -- hooks`

<a id="f23"></a>

## F2.3 Workspace Shell 与 Project Sidebar

**计划周期**：Week 3
**状态**：`[ ]`
**目标**：实现控制台三栏外壳和左侧 Project / Session Sidebar，为后续 Narrative Workspace 提供页面骨架。
**实施计划**：`docs/plans/implementation/f2.3-workspace-shell-sidebar.md`

**修改文件列表**：
- Create: `frontend/src/features/workspace/WorkspaceShell.tsx`
- Create: `frontend/src/features/workspace/ProjectSidebar.tsx`
- Create: `frontend/src/features/workspace/SessionList.tsx`
- Create: `frontend/src/features/workspace/__tests__/WorkspaceShell.test.tsx`

**实现类/函数**：
- `WorkspaceShell`
- `ProjectSidebar`
- `ProjectSwitcher`
- `LoadProjectEntry`
- `SessionList`

**验收标准**：
- 左栏展示 Project Switcher、Load Project Entry、当前 Project 摘要、New Session Entry、Session 列表和默认交付模式摘要。
- 用户加载本地项目后，该项目进入 Project Switcher；切换项目后中栏进入该项目最近会话，若无会话则展示项目空态。
- 中栏保留 Narrative Workspace 插槽。
- 右栏保留 Inspector 插槽并默认关闭。
- 三栏布局在窄屏下可退化为抽屉占位。

**前端设计质量门**：
- 实施计划必须继承项目级前端主基调；若主基调尚未记录，则本切片先记录主基调再实现。
- 实现前必须梳理三栏信息层级、侧栏密度、主区留白和窄屏抽屉策略。
- 实现后必须检查可访问性、文本溢出、焦点态、响应式和视觉反模式。
- Shell、侧栏、主工作区和 Inspector 占位必须保持产品型工作台气质，不引入营销页 hero 或装饰性卡片堆叠。

**测试方法**：
- `npm --prefix frontend run test -- WorkspaceShell`

<a id="f24"></a>

## F2.4 统一设置弹窗

**计划周期**：Week 3
**状态**：`[ ]`
**目标**：实现统一设置入口、通用配置页和模型提供商页，使项目级 DeliveryChannel 与 Provider 配置不进入模板编辑区。
**实施计划**：`docs/plans/implementation/f2.4-settings-modal.md`

**修改文件列表**：
- Create: `frontend/src/features/settings/SettingsModal.tsx`
- Create: `frontend/src/features/settings/DeliveryChannelSettings.tsx`
- Create: `frontend/src/features/settings/ProviderSettings.tsx`
- Create: `frontend/src/features/settings/__tests__/SettingsModal.test.tsx`

**实现类/函数**：
- `SettingsModal`
- `DeliveryChannelSettings`
- `ProviderSettings`

**验收标准**：
- 设置入口位于全局工具区。
- 设置弹窗包含 `通用配置` 与 `模型提供商`。
- `通用配置` 页面显示当前 Project，并编辑项目级 DeliveryChannel。
- `模型提供商` 页面展示内置 Provider 和 custom Provider。
- DeliveryChannel 配置不出现在模板编辑区。

**前端设计质量门**：
- 继承项目级前端主基调，不单独询问新的设置页风格。
- 实现后必须检查表单错误、禁用态、加载态、长 Provider 名称、凭据状态说明、键盘焦点和窄屏布局。
- 设置弹窗用于配置，不承担模板编辑或交付结果展示；视觉层级必须让 DeliveryChannel 与 Provider 的职责边界可扫描。

**测试方法**：
- `npm --prefix frontend run test -- SettingsModal`

<a id="f25"></a>

## F2.5 模板空态与模板选择

**计划周期**：Week 3-4
**状态**：`[ ]`
**目标**：实现 draft 会话中的模板空态、系统模板列表和模板选择，使空白会话属于 Narrative Feed 空态内容。
**实施计划**：`docs/plans/implementation/f2.5-template-empty-state-selector.md`

**修改文件列表**：
- Create: `frontend/src/features/templates/TemplateEmptyState.tsx`
- Create: `frontend/src/features/templates/TemplateSelector.tsx`
- Create: `frontend/src/features/templates/__tests__/TemplateSelector.test.tsx`

**实现类/函数**：
- `TemplateEmptyState`
- `TemplateSelector`

**验收标准**：
- 新建会话默认预选 `新功能开发流程`。
- 用户可在空白会话中切换 `system_template` 与 `user_template`。
- 三个系统模板的适用场景可区分。
- 模板区域作为 Narrative Feed 空态内容，不构成独立第三主区。

**前端设计质量门**：
- 继承项目级前端主基调，不单独询问模板空态风格。
- 实现后必须检查空态信息层级、模板名称长文本、选择态、禁用态和移动端可读性。
- 模板空态必须属于 Narrative Feed 的空内容状态，不做成独立营销式引导页。

**测试方法**：
- `npm --prefix frontend run test -- TemplateSelector`

<a id="f26"></a>

## F2.6 模板编辑与脏状态守卫

**计划周期**：Week 3-4
**状态**：`[ ]`
**目标**：实现模板允许字段编辑、另存/覆盖/删除和脏状态拦截，使首条需求启动前的运行配置可控。
**实施计划**：`docs/plans/implementation/f2.6-template-editor-dirty-guard.md`

**修改文件列表**：
- Create: `frontend/src/features/templates/TemplateEditor.tsx`
- Create: `frontend/src/features/templates/template-state.ts`
- Create: `frontend/src/features/templates/__tests__/TemplateEditor.test.tsx`

**实现类/函数**：
- `TemplateEditor`
- `useTemplateDraftState()`
- `isTemplateDirty()`
- `resolveTemplateStartGuard()`

**验收标准**：
- 模板编辑只开放阶段槽位的 `AgentRole` 选择、槽位内最终生效的 `system_prompt`、`provider_id`、自动回归开关和最大重试次数。
- 模板编辑不得提供 `AgentRole.role_name` 修改入口，也不得把槽位配置保存为会影响其他模板的共享运行对象。
- 系统模板修改后只能另存。
- 用户模板支持覆盖、另存、删除。
- 脏模板不得直接启动运行。
- 模板编辑区不暴露阶段顺序、审批检查点、阶段输入输出契约或项目级 DeliveryChannel。

**前端设计质量门**：
- 继承项目级前端主基调，不单独询问模板编辑器风格。
- 实现后必须检查脏状态提示、另存/覆盖/删除按钮层级、长 prompt、长角色名称、错误态、禁用态和键盘操作。
- 模板编辑器必须强调“运行前配置”边界，不用视觉方式暗示用户可以改阶段顺序、审批检查点或 DeliveryChannel。

**测试方法**：
- `npm --prefix frontend run test -- TemplateEditor`
