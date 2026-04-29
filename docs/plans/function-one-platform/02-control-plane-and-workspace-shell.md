# 02 控制面与工作台外壳

## 范围

本分卷覆盖 Week 2-4 的控制面 API、项目与会话历史管理、平台运行设置管理服务与前端工作台外壳。完成后，前端可基于真实或 mock 契约完成 Project、Session、Template、Provider、DeliveryChannel、设置弹窗和模板空态的主要交互；后端可统一校验和管理 `PlatformRuntimeSettings`，但该能力不进入普通前端设置弹窗。

本分卷按依赖顺序拆分：先建立默认 Project 与最小默认 `demo_delivery` 通道，再建立系统模板并创建 draft Session；DeliveryChannel 的查询、保存与 readiness 校验作为独立控制面能力落地，避免一个任务同时吞掉全部控制面。

凡本分卷修改 `backend/app/api/routes/*` 的 API 切片，对应 API 测试必须在本切片内断言新增或修改的 path、method、请求 Schema、响应 Schema 和主要错误响应已进入 `/api/openapi.json`；V6.4 只做全局覆盖回归，不作为这些路由第一次发现 OpenAPI 漂移的入口。

控制面写操作必须嵌入日志审计要求。Project 加载与移除、Session 创建、重命名与删除、模板另存/覆盖/删除、Provider 创建/修改、DeliveryChannel 保存与校验、平台运行设置变更必须继承 L2.1 建立的 request/correlation 上下文，使用 L2.2 的载荷裁剪策略，经由 L2.3 的 JSONL 与索引入口落盘，并通过 L2.4 为成功、失败和被拒绝结果写入审计记录；审计记录不得替代控制面领域对象、配置对象或 API 响应真源。

<a id="l21"></a>

## L2.1 API 请求与关联上下文

**计划周期**：Week 3
**状态**：`[ ]`
**目标**：建立 API request/correlation 上下文，使统一错误响应、控制面命令和后续日志审计入口能够共享 `request_id`、`trace_id`、`correlation_id` 与 `span_id`。
**实施计划**：`docs/plans/implementation/l2.1-api-correlation-context.md`

**修改文件列表**：
- Create: `backend/app/observability/context.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/errors.py`
- Create: `backend/tests/api/test_request_correlation_context.py`

**实现类/函数**：
- `RequestCorrelationMiddleware`
- `get_trace_context()`
- `TraceContext.child_span()`

**验收标准**：
- `request_id` 由外部请求传入或由中间件生成；同一请求内服务、API 错误、审计记录和后续领域命令共享 `correlation_id`。
- `TraceContext` 能为控制面命令、服务调用、运行步骤和审计记录分配子 span，并保留 `parent_span_id`。
- API 参数校验失败和统一错误响应必须具备 `request_id` 与 `correlation_id`。
- L2.1 只负责上下文传播和错误响应挂载，不写 JSONL 文件、不写 `log.db` 索引、不创建审计记录。

**测试方法**：
- `pytest backend/tests/api/test_request_correlation_context.py -v`

<a id="l22"></a>

## L2.2 基础 RedactionPolicy 与 payload summarizer

**计划周期**：Week 3
**状态**：`[ ]`
**目标**：建立日志与审计载荷的基础裁剪、摘要和敏感字段阻断策略，作为 L2.3 JSONL 写入和 L2.4 审计记录的统一前置处理。
**实施计划**：`docs/plans/implementation/l2.2-redaction-payload-summarizer.md`

**修改文件列表**：
- Create: `backend/app/observability/redaction.py`
- Create: `backend/tests/observability/test_redaction_policy.py`

**实现类/函数**：
- `RedactionPolicy.redact_mapping()`
- `RedactionPolicy.summarize_payload()`
- `RedactionPolicy.summarize_text()`

**验收标准**：
- 基础脱敏策略必须阻断字段名命中 `api_key`、`token`、`secret`、`password`、`authorization`、`cookie`、`private_key`、`credential` 或等价敏感含义的字段值。
- 日志和审计载荷必须先生成摘要和裁剪片段，不能无界写入大文本或真实凭据。
- 裁剪结果必须标记 `redaction_status`，区分未裁剪、已裁剪、已阻断和载荷不可序列化。
- L2.2 不决定日志写入位置和审计失败语义；写入位置由 L2.3 固定，审计失败语义由 L2.4 与 L4.1 固定。

**测试方法**：
- `pytest backend/tests/observability/test_redaction_policy.py -v`

<a id="l23"></a>

## L2.3 JSONL writer 与 log index

**计划周期**：Week 3
**状态**：`[ ]`
**目标**：建立本地 JSONL 日志写入与 `log.db` 轻量索引入口，使服务日志、run 日志和审计副本具备统一落盘格式和可查询定位信息。
**实施计划**：`docs/plans/implementation/l2.3-jsonl-writer-log-index.md`

**修改文件列表**：
- Create: `backend/app/observability/log_writer.py`
- Create: `backend/app/observability/log_index.py`
- Create: `backend/tests/observability/test_jsonl_log_writer.py`

**实现类/函数**：
- `JsonlLogWriter.write()`
- `JsonlLogWriter.write_run_log()`
- `JsonlLogWriter.write_audit_copy()`
- `LogIndexRepository.append_run_log_index()`

**验收标准**：
- 服务级日志写入 `.runtime/logs/app.jsonl`，run 级日志可按 `run_id` 写入 `.runtime/logs/runs/{run_id}.jsonl`，审计文件副本写入 `.runtime/logs/audit.jsonl`。
- 每行 JSONL 是完整 JSON 对象，包含 `schema_version = 1`、`log_id`、`created_at`、`level`、`category`、`source`、`message`、`request_id`、`trace_id`、`correlation_id`、`span_id`、`parent_span_id`、`redaction_status` 和当前可用产品对象标识。
- `RunLogEntry` 索引必须记录 `log_file_ref`、`line_offset`、`line_number`、`level`、`category`、`source`、`run_id`、`stage_run_id` 与关联 trace 字段。
- JSONL writer 与 log index 不得接收或写入未经过 L2.2 处理的 raw payload；调用方只能传入已裁剪摘要、载荷片段、大小、内容哈希和 `redaction_status`。
- 普通运行日志文件写入成功但 `log.db` 索引写入失败时，不阻断已完成领域事务，但必须追加服务级错误日志。
- L2.3 不创建平台审计台账，不决定高影响动作的提交或回滚语义。

**测试方法**：
- `pytest backend/tests/observability/test_jsonl_log_writer.py -v`

<a id="l24"></a>

## L2.4 AuditService 与控制面命令审计

**计划周期**：Week 3
**状态**：`[ ]`
**目标**：建立控制面命令可复用的 AuditService 入口，使 Project、Session、Template、Provider 和 DeliveryChannel 后续切片能够按统一结构记录成功、失败和被拒绝结果。
**实施计划**：`docs/plans/implementation/l2.4-audit-service-control-plane.md`

**修改文件列表**：
- Create: `backend/app/observability/audit.py`
- Create: `backend/tests/observability/test_audit_service.py`

**实现类/函数**：
- `AuditService.record_command_result()`
- `AuditService.record_rejected_command()`
- `AuditService.record_failed_command()`

**验收标准**：
- 审计记录写入 `log.db` 的 `AuditLogEntry`，并可通过 L2.3 写入 `.runtime/logs/audit.jsonl` 副本。
- 控制面审计记录必须包含动作主体、动作名、目标类型、目标标识摘要、结果、原因摘要、`request_id`、`trace_id`、`correlation_id`、`span_id` 和创建时间。
- 控制面命令拒绝结果必须具备 `request_id` 与 `correlation_id`，且不能以审计记录替代 API 错误响应或领域状态。
- 安全审计台账写入失败时，必须向调用方返回明确错误，不得降级为普通运行日志失败。
- 本切片只建立控制面可复用审计入口；C2.1-C2.9b 在各自业务切片中完成具体命令接入，runtime、工具、模型和交付动作在后续阶段接入。

**测试方法**：
- `pytest backend/tests/observability/test_audit_service.py -v`

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
- `GET /api/projects` 在未手动加载项目时也返回默认项目，并只返回未移除项目。
- `POST /api/projects` 支持通过本地 `root_path` 加载新项目，并返回可用于左栏切换的项目摘要。
- 已加载且未移除的 Project 在系统重启后继续出现在项目列表中。
- 默认 Project 创建时通过 `DeliveryChannelService.ensure_default_channel()` 同步创建最小项目级默认 `DeliveryChannel(delivery_mode=demo_delivery, credential_status=ready, readiness_status=ready, readiness_message=null)`。
- 新建 Project 记录 `root_path`、`name`、`default_delivery_channel_id` 和时间戳，且 `default_delivery_channel_id` 指向可解析的默认通道。
- 本切片不实现 Project 移除、Session、Template 或 DeliveryChannel 查询、保存、readiness 校验业务。
- 默认 Project 初始化、本地项目加载成功、本地项目加载失败和非法 `root_path` 被拒绝必须继承 L2.1 上下文并通过 L2.4 写入审计记录；审计摘要不得把本机绝对路径作为可查询主引用。
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
- Create: `backend/app/prompts/assets/roles/requirement_analyst.md`
- Create: `backend/app/prompts/assets/roles/solution_designer.md`
- Create: `backend/app/prompts/assets/roles/code_generator.md`
- Create: `backend/app/prompts/assets/roles/test_runner.md`
- Create: `backend/app/prompts/assets/roles/code_reviewer.md`
- Create: `backend/app/services/templates.py`
- Create: `backend/app/services/providers.py`
- Create: `backend/app/api/routes/templates.py`
- Create: `backend/app/api/routes/providers.py`
- Create: `backend/tests/prompts/test_agent_role_seed_assets.py`
- Create: `backend/tests/services/test_template_seed.py`
- Create: `backend/tests/services/test_provider_seed.py`
- Create: `backend/tests/api/test_template_provider_seed_api.py`

**实现类/函数**：
- `TemplateService.seed_system_templates()`
- `TemplateService.resolve_default_agent_role_prompt(role_id: str)`
- `TemplateService.list_templates()`
- `TemplateService.get_default_template()`
- `ProviderService.seed_builtin_providers()`
- `ProviderService.list_providers()`

**验收标准**：
- 系统模板包含 `Bug 修复流程`、`新功能开发流程`、`重构流程`。
- 默认模板为 `新功能开发流程`。
- 三个系统模板共享固定六阶段骨架。
- 三个系统模板差异只体现在阶段槽位默认绑定的 `AgentRole`、槽位内最终生效的 `system_prompt`、Provider 绑定和自动回归默认策略。
- 默认 `AgentRole.system_prompt` 必须来自系统内置 `agent_role_seed` 提示词资产；模板种子写入后，运行时真源是模板槽位内固化的 `system_prompt`，不得在已启动 run 中回读最新提示词资产。
- `agent_role_seed` 提示词资产必须具有稳定 `prompt_id`、`prompt_version` 和 `content_hash`，并通过 C1.10a Schema 校验。
- `agent_role_seed` 文件名不承载版本号；`prompt_version` 只从 Markdown front matter 读取，写入模板槽位时只写入剥离元数据后的提示词正文。
- Provider 默认包含 `火山引擎`、`DeepSeek`。
- `OpenAI Completions compatible` 只作为 custom Provider 接入协议，不作为内置 Provider 名称。
- API 测试必须断言 `GET /api/pipeline-templates`、`GET /api/pipeline-templates/{templateId}`、`GET /api/providers` 及其响应 Schema 和主要错误响应已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/prompts/test_agent_role_seed_assets.py -v`
- `pytest backend/tests/services/test_template_seed.py -v`
- `pytest backend/tests/services/test_provider_seed.py -v`
- `pytest backend/tests/api/test_template_provider_seed_api.py -v`

<a id="c23"></a>

## C2.3 draft Session、重命名与模板选择更新

**计划周期**：Week 3
**状态**：`[ ]`
**目标**：实现项目下 draft Session 创建、左栏展示名重命名和运行前模板选择更新，使首条需求前的会话状态符合规格。
**实施计划**：`docs/plans/implementation/c2.3-draft-session-template-selection.md`

**修改文件列表**：
- Create: `backend/app/services/sessions.py`
- Create: `backend/app/api/routes/sessions.py`
- Create: `backend/tests/services/test_session_service.py`
- Create: `backend/tests/api/test_session_api.py`

**实现类/函数**：
- `SessionService.create_session()`
- `SessionService.rename_session()`
- `SessionService.update_selected_template()`
- `SessionService.list_project_sessions()`
- `SessionService.get_session()`

**验收标准**：
- 新建 Session 时状态为 `draft` 且 `current_run_id = null`。
- 新建 Session 生成稳定 `display_name`，用于左栏展示和后续重命名。
- 新建 Session 默认关联 `新功能开发流程` 模板。
- 只有 `draft` 且尚未创建 run 的 Session 允许更新 `selected_template_id`。
- `PATCH /api/sessions/{sessionId}` 只允许修改 `display_name`；重命名不得改变原始需求、运行历史、审批记录、产物、交付记录、事件归属或 `PipelineRun` 归属。
- `latest_stage_type` 在 draft 状态下为 `null`。
- 同一 Project 下可列出近期未删除 Session。
- Session 创建、重命名、非法模板更新和成功模板更新必须继承 L2.1 上下文并通过 L2.4 写入审计记录，且不以审计记录替代 `Session` 领域状态。
- API 测试必须断言 `POST /api/projects/{projectId}/sessions`、`GET /api/projects/{projectId}/sessions`、`GET /api/sessions/{sessionId}`、`PATCH /api/sessions/{sessionId}`、`PUT /api/sessions/{sessionId}/template` 及其请求/响应 Schema 和主要错误响应已进入 `/api/openapi.json`。

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
- 模板保存服务必须在 `system_prompt` 持久化前经过单一边界校验调用点；A4.8a 完成后该调用点由 `PromptValidationService.validate_template_prompts_before_save()` 承接，不得另建绕过该调用点的保存路径。
- 模板 CRUD 不得写入、覆盖或切换后端系统内置提示词资产；用户编辑后的 `system_prompt` 只保存为模板槽位运行配置。
- 用户不能通过模板删除、禁用、重排核心阶段，不能关闭两个必需审批检查点。
- 删除当前选中的用户模板后，调用方可回退到默认系统模板。
- 用户模板另存、覆盖、删除、非法覆盖系统模板和非法删除系统模板必须继承 L2.1 上下文并通过 L2.4 写入审计记录。
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
- custom Provider 创建、修改、内置 Provider 修改被拒绝和凭据引用变更必须继承 L2.1 上下文，使用 L2.2 裁剪载荷，并通过 L2.4 写入审计记录；审计摘要不得包含真实密钥。
- API 测试必须断言 `POST /api/providers`、`PATCH /api/providers/{providerId}`、`GET /api/providers/{providerId}` 及其请求/响应 Schema 和主要错误响应已进入 `/api/openapi.json`。
- Provider 保存结果只影响后续新建 Session、后续新启动 run 或尚未启动 run 的模板选择；不得回写已启动 run 的 ProviderSnapshot 或 ModelBindingSnapshot。

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
- DeliveryChannel 保存成功、保存失败、字段非法和凭据引用变更必须继承 L2.1 上下文，使用 L2.2 裁剪载荷，并通过 L2.4 写入审计记录；审计元数据只保存摘要和凭据引用，不保存真实凭据。
- API 测试必须断言 `GET /api/projects/{projectId}/delivery-channel`、`PUT /api/projects/{projectId}/delivery-channel` 及其请求/响应 Schema 和主要错误响应已进入 `/api/openapi.json`。
- DeliveryChannel 保存结果至少影响后续新启动 run；对尚未进入 `Delivery Integration` 且尚未固化交付通道快照的当前活动 run，只能用于后续交付就绪校验和交付快照固化。

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
- DeliveryChannel readiness 校验必须继承 L2.1 上下文，使用 L2.2 裁剪载荷，经由 L2.3 写入运行日志，并通过 L2.4 写入审计记录；记录内容包含校验结果、阻塞原因摘要和 `validated_at`，不得改写历史 run 的交付快照。
- API 测试必须断言 `POST /api/projects/{projectId}/delivery-channel/validate` 的请求 Schema、响应 Schema、`validated_at` 字段和主要错误响应已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/services/test_delivery_channel_readiness.py -v`
- `pytest backend/tests/api/test_delivery_channel_validate_api.py -v`

<a id="c28"></a>

## C2.8 PlatformRuntimeSettings 管理服务

**计划周期**：Week 3
**状态**：`[ ]`
**目标**：实现后端统一平台运行设置管理服务，校验运行上限、Provider 调用策略、上下文裁剪限制、日志策略和诊断查询分页上限，并为后续 run 启动快照提供稳定配置版本。
**实施计划**：`docs/plans/implementation/c2.8-platform-runtime-settings-service.md`

**修改文件列表**：
- Create: `backend/app/services/runtime_settings.py`
- Create: `backend/app/repositories/runtime_settings.py`
- Create: `backend/app/api/routes/runtime_settings.py`
- Create: `backend/tests/services/test_runtime_settings_service.py`
- Create: `backend/tests/api/test_runtime_settings_admin_api.py`

**实现类/函数**：
- `PlatformRuntimeSettingsRepository.get_current()`
- `PlatformRuntimeSettingsRepository.save_new_version()`
- `PlatformRuntimeSettingsService.get_current_settings()`
- `PlatformRuntimeSettingsService.update_settings()`
- `PlatformRuntimeSettingsService.validate_against_hard_limits()`
- `PlatformRuntimeSettingsService.current_version()`
- `build_runtime_settings_router()`

**验收标准**：
- 服务通过 `PlatformRuntimeSettingsRepository` 读取和保存 C1.6 的 `PlatformRuntimeSettingsModel`，并维护单调递增配置版本。
- 首次读取时若 control.db 中不存在记录，服务以 C1.10 默认值和当前平台硬上限版本初始化一条设置记录；初始化结果必须持久化，不能每次请求临时拼装。
- `PlatformRuntimeSettingsModel` 保存 C1.10 定义的 `agent_limits`、`provider_call_policy`、`context_limits`、`log_policy`、schema 版本、配置版本、平台硬上限版本和更新时间。
- 运行上限、Provider 调用策略、上下文裁剪限制、日志策略和诊断查询分页上限保存前必须校验。
- 超过平台硬上限时拒绝保存，并返回 `config_hard_limit_exceeded`。
- 非法字段值、版本冲突和配置存储不可用分别返回 `config_invalid_value`、`config_version_conflict`、`config_storage_unavailable`。
- 更新接口必须要求或支持 `expected_version`；当客户端基于旧版本提交时不得覆盖最新配置。
- 配置设置允许热重载，但服务层不得尝试修改已启动 run 的模板快照、Provider 与模型绑定快照、运行上限快照或交付通道快照。
- 配置设置变更必须继承 L2.1 上下文，使用 L2.2 裁剪载荷，经由 L2.3 写入运行日志，并通过 L2.4 写入审计记录；审计摘要记录变更字段、旧值摘要、新值摘要、生效范围和 `correlation_id`。
- 本切片实现后端管理服务和内部管理 API 边界；内部管理 API 必须进入 OpenAPI 并复用统一错误响应，但不得被 F2.4 普通前端设置弹窗调用或展示为用户可编辑表单。
- API 测试必须断言运行设置读取、更新、硬上限拒绝、版本冲突、非法字段和主要错误响应已进入 `/api/openapi.json`。
- `compression_prompt` 不属于该服务的可写配置项；系统内置提示词资产版本引用只由压缩过程记录使用。

**测试方法**：
- `pytest backend/tests/services/test_runtime_settings_service.py -v`
- `pytest backend/tests/api/test_runtime_settings_admin_api.py -v`

<a id="c29a"></a>

## C2.9a Session 删除命令与历史可见性

**计划周期**：Week 4
**状态**：`[ ]`
**目标**：实现无活动 run 的 Session 删除语义，使左栏历史管理只改变产品历史可见性，不替代运行终止、暂停、回退或重新尝试。
**实施计划**：`docs/plans/implementation/c2.9a-session-delete-history.md`

**修改文件列表**：
- Modify: `backend/app/services/sessions.py`
- Modify: `backend/app/api/routes/sessions.py`
- Create: `backend/tests/services/test_session_history_commands.py`
- Create: `backend/tests/api/test_session_history_api.py`

**实现类/函数**：
- `SessionService.delete_session()`
- `SessionService.assert_session_deletable()`
- `SessionService.list_visible_sessions()`

**验收标准**：
- 本切片依赖 R3.1 固定的 run 终态枚举和活动 run 判定，不自行定义第二套活动状态规则。
- 只有不存在活动 run 的 Session 可以删除；活动 run 指尚未进入 `completed`、`failed` 或 `terminated` 的 `PipelineRun`，draft Session 没有活动 run。
- 删除 Session 后，该 Session 不再出现在项目会话列表、常规回看入口或 `SessionWorkspaceProjection` 可打开入口中。
- 删除 Session 不删除 `PipelineRun`、StageArtifact、审批记录、交付记录、领域事件或日志审计记录；后端以软删除产品可见性标记实现。
- 删除 Session 不得隐式触发 `terminate`、`rollback`、`retry`、暂停或恢复。
- 删除成功、活动 run 阻塞、Session 不存在和重复删除必须返回稳定错误语义并写入审计记录。
- API 测试必须断言 `DELETE /api/sessions/{sessionId}` 的请求/响应 Schema 和主要错误响应已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/services/test_session_history_commands.py -v`
- `pytest backend/tests/api/test_session_history_api.py -v`

<a id="c29b"></a>

## C2.9b Project 移除命令与级联历史可见性

**计划周期**：Week 4
**状态**：`[ ]`
**目标**：实现已加载 Project 的移除语义，使非默认项目可从产品历史中移除，并级联隐藏该项目下用于产品回看的 Session 历史。
**实施计划**：`docs/plans/implementation/c2.9b-project-remove-history.md`

**修改文件列表**：
- Modify: `backend/app/services/projects.py`
- Modify: `backend/app/api/routes/projects.py`
- Modify: `backend/app/services/sessions.py`
- Create: `backend/tests/services/test_project_remove_history.py`
- Create: `backend/tests/api/test_project_remove_api.py`

**实现类/函数**：
- `ProjectService.remove_project()`
- `ProjectService.assert_project_removable()`
- `ProjectService.hide_project_sessions()`

**验收标准**：
- 本切片依赖 R3.1 固定的 run 终态枚举和活动 run 判定，不自行定义第二套活动状态规则。
- 默认 Project 不允许移除。
- 存在活动 run 的 Project 不允许移除；活动 run 判定与 C2.9a 一致。
- Project 移除后不再出现在 Project Switcher、项目列表、常规产品查询和回看入口中；该项目下未删除 Session 一并从产品历史可见性中隐藏。
- Project 移除不得删除本地项目文件夹、目标仓库文件、远端仓库、远端分支、提交或代码评审请求。
- Project 移除不得删除日志审计边界要求保留的安全审计事实。
- 移除成功、默认项目阻塞、活动 run 阻塞、Project 不存在和重复移除必须返回稳定错误语义并写入审计记录。
- API 测试必须断言 `DELETE /api/projects/{projectId}` 的请求/响应 Schema 和主要错误响应已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/services/test_project_remove_history.py -v`
- `pytest backend/tests/api/test_project_remove_api.py -v`

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
- `ApiErrorResponse`
- `listProjects()`
- `removeProject()`
- `createSession()`
- `renameSession()`
- `deleteSession()`
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
- Project client 覆盖列表、加载和移除路径；Session client 覆盖创建、重命名、删除、模板更新和详情读取路径。
- 错误响应进入统一错误处理，并保留后端返回的稳定 `code`、`message`、`request_id` 与可选字段错误详情。
- 前端 API client 必须能识别并透传 `config_invalid_value`、`config_hard_limit_exceeded`、`config_version_conflict`、`config_storage_unavailable`、`config_snapshot_unavailable`，但本切片不新增普通用户可编辑的平台运行设置 client。
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
- `mockProjectList`
- `mockSessionList`
- `mockApiError()`

**验收标准**：
- mock fixtures 覆盖空白会话、运行中会话、等待澄清、等待审批、完成、失败、终止。
- mock fixtures 覆盖已加载项目、被移除项目不可见、历史 Session、重命名后的 Session 展示名，以及删除后不在常规列表出现的 Session。
- mock feed 条目类型与 C1.3 契约一致。
- mock error fixtures 必须覆盖后端配置校验和平台硬上限错误，用于模板编辑、DeliveryChannel 和 Provider 表单展示错误；mock fixtures 不得定义临时配置字段、临时状态或前端专用投影。
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
- 已加载且未移除的 Project 在刷新或重启后继续展示；移除 Project 后，该 Project 及其 Session 不再出现在常规左栏历史入口。
- 默认 Project 的移除入口禁用或不展示；存在活动 run 的 Project 移除入口必须进入阻塞态。
- Session 列表支持重命名展示名和删除没有活动 run 的 Session；存在活动 run 的 Session 删除入口必须进入阻塞态。
- Session 重命名只改变左栏展示名，不刷新或重建当前运行历史。
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
- 设置弹窗不展示或编辑环境变量、平台运行数据目录、SQLite 文件路径、CORS、日志文件路径、后端平台硬上限、全局 ReAct 循环上限、日志保留策略、日志裁剪策略、诊断查询分页上限或 `deterministic test runtime`。
- 设置弹窗不展示或编辑后端系统内置提示词资产、`prompt_id`、`prompt_version`、`runtime_instructions`、结构化输出修复提示词或 `compression_prompt`。
- 设置弹窗不得调用 C2.8 的内部运行设置管理 API；若 DeliveryChannel 或 Provider 保存返回配置类错误，只展示后端错误原因，不把平台运行设置补成可编辑入口。
- Provider 密钥只以 `api_key_ref` 或等价引用形式展示和提交，不展示真实密钥内容。
- Provider 配置变更的 UI 文案不得暗示会修改已经启动 run 的 Provider 与模型绑定快照。
- DeliveryChannel 在交付快照固化前可用于当前活动 run 后续交付就绪校验；已固化快照的 run 必须按只读状态展示。

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
- 模板编辑区不暴露环境变量、运行数据目录、平台运行上限、日志策略或 `deterministic test runtime`。
- 模板编辑区不暴露后端系统内置提示词资产、提示词版本切换、`runtime_instructions`、结构化输出修复提示词或 `compression_prompt`。
- `最大自动回归重试次数` 输入超过后端平台硬上限或保存被拒绝时，前端必须展示明确错误，不得自行截断后保存。
- 当后端返回 `config_hard_limit_exceeded` 或 `config_invalid_value` 时，模板编辑器只提示当前字段保存失败和后端原因，不展示或编辑 C2.8 的平台硬上限值。

**前端设计质量门**：
- 继承项目级前端主基调，不单独询问模板编辑器风格。
- 实现后必须检查脏状态提示、另存/覆盖/删除按钮层级、长 prompt、长角色名称、错误态、禁用态和键盘操作。
- 模板编辑器必须强调“运行前配置”边界，不用视觉方式暗示用户可以改阶段顺序、审批检查点或 DeliveryChannel。

**测试方法**：
- `npm --prefix frontend run test -- TemplateEditor`
