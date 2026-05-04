# 06 LangGraph、Provider、Context 与 Stage Agent Runtime

## 范围

本分卷覆盖 Week 8-9 的正式 LangGraph runtime、Provider、Prompt、Context Management、AgentDecision、Stage Agent Runtime 和自动回归。完成后，正式用户运行只走 LangGraph runtime，阶段内执行由结构化上下文、Provider 失败策略、工具协议和 StageArtifact 过程记录共同约束。

本分卷承接 04 分卷的 runtime boundary、05 分卷的 deterministic baseline、07 分卷的 ToolProtocol / ToolRegistry，并消费 03 分卷的 Run、GraphDefinition、StageRun 和 StageArtifact 契约。Provider adapter 和 Stage Agent Runtime 只能绑定已注册 workspace/fake 工具，不绑定 08 分卷尚未实现的真实 delivery tool 实例。

LangGraph 节点、checkpoint、interrupt/resume、Provider 解析、模型请求响应、结构化输出解析、上下文压缩、工具调用、工具确认和自动回归必须写入裁剪后的运行日志摘要；审计记录由对应命令、工具、工具确认或交付适配器负责。

<a id="a45"></a>

## A4.5 LangGraph 主链与 checkpoint

**计划周期**：Week 8
**状态**：`[x]`
**目标**：接入 LangGraph 主链和 checkpoint，使正式执行路径具备固定业务阶段编排能力，并把单阶段内部执行限定为可替换的 stage runner 调用边界。
**实施计划**：`docs/plans/implementation/a4.5-langgraph-main-chain-checkpoint.md`

**修改文件列表**：
- Create: `backend/app/runtime/langgraph_engine.py`
- Create: `backend/app/runtime/nodes.py`
- Create: `backend/app/runtime/checkpoints.py`
- Create: `backend/app/runtime/stage_runner_port.py`
- Create: `backend/tests/runtime/test_langgraph_engine.py`

**实现类/函数**：
- `LangGraphRuntimeEngine`
- `StageNodeRunnerPort`
- `build_stage_graph()`
- `run_stage_node()`
- `save_graph_checkpoint()`

**验收标准**：
- LangGraph 表达固定主链、阶段节点、条件边和 checkpoint。
- GraphDefinition 的六阶段映射进入 LangGraph 构建过程。
- 每次业务阶段切换前后具备可恢复 checkpoint。
- raw graph state 不进入前端投影。
- LangGraph runtime 必须实现 A4.0 runtime boundary，不新增第二套中断、恢复或终止调用路径。
- `GraphDefinition` 映射为 LangGraph `StateGraph` 构建输入，运行时编译为 compiled graph。
- `GraphThread.graph_thread_id` 映射为 LangGraph configurable `thread_id`。
- 条件路由使用 LangGraph conditional edges 表达，不在 `RunLifecycleService` 中另写一套阶段分支状态机。
- LangGraph stage node 只把 `run_id`、`stage_run_id`、`stage_contract_ref`、`RuntimeExecutionContext` 和 `TraceContext` 交给 `StageNodeRunnerPort`；不得在 LangGraph node 内直接构建 `ContextEnvelope`、调用 Provider、解析 `AgentDecision` 或执行工具。
- A4.5 测试可使用 fake stage runner 验证主链和 checkpoint；正式 `Stage Agent Runtime` 由 A4.9d 接入。
- checkpoint 通过 LangGraph checkpointer 保存，并同步写入 `GraphCheckpoint.checkpoint_ref`。
- 测试断言 checkpoint 可用于同一 `GraphThread` 恢复，而不是只验证业务状态字段变化。
- LangGraph graph build、thread start、node start、node completed、checkpoint saved、graph failed 必须写入运行日志摘要，并继承 `TraceContext`。

**测试方法**：
- `pytest backend/tests/runtime/test_langgraph_engine.py -v`

<a id="a46"></a>

## A4.6 LangGraph interrupt resume

**计划周期**：Week 8
**状态**：`[x]`
**目标**：实现 LangGraph 澄清中断、审批中断、工具确认中断和恢复，使正式 runtime 符合人工介入与运行时权限控制语义。
**实施计划**：`docs/plans/implementation/a4.6-langgraph-interrupt-resume.md`

**修改文件列表**：
- Modify: `backend/app/runtime/langgraph_engine.py`
- Modify: `backend/app/runtime/checkpoints.py`
- Create: `backend/tests/runtime/test_langgraph_interrupts.py`

**实现类/函数**：
- `create_graph_interrupt()`
- `resume_graph_interrupt()`
- `LangGraphRuntimeEngine.resume_from_interrupt()`

**验收标准**：
- 澄清中断可恢复同一 GraphThread。
- 审批中断可恢复同一 GraphThread。
- 工具确认中断可恢复同一 GraphThread，并关联同一个 `ToolConfirmationRequest`。
- run 在暂停前停留于审批等待时，resume 后重新进入同一个 `waiting_approval` 检查点。
- run 在暂停前停留于工具确认等待时，resume 后重新进入同一个 `waiting_tool_confirmation` 检查点。
- 审批命令在 run 未暂停时通过恢复对应 GraphInterrupt 继续执行图。
- 工具确认命令在 run 未暂停时通过恢复对应 `GraphInterrupt(type=tool_confirmation)` 继续执行图。
- 澄清、审批与工具确认等待必须通过 LangGraph interrupt payload 表达，并持久化为 `GraphInterrupt`。
- resume 必须使用同一 `thread_id` 和对应 resume command 继续执行。
- `clarification_reply`、`approval approve/reject`、`tool_confirmation allow/deny` 必须通过 A4.0 runtime boundary 进入 LangGraph resume，不得由 API 或领域服务直接调用 LangGraph internals。
- `clarification_reply`、`approval approve/reject`、`tool_confirmation allow/deny` 不得绕过 `GraphInterrupt` 直接推进阶段状态。
- pause 后 resume 不创建新的 `GraphThread`，也不创建新的 `PipelineRun`。
- LangGraph interrupt、resume command、resume success 和 resume failure 必须写入运行日志；审批或澄清命令审计仍由对应 H4 命令切片负责。

**测试方法**：
- `pytest backend/tests/runtime/test_langgraph_interrupts.py -v`

<a id="a47"></a>

## A4.7 LangGraph 事件到领域产物转换

**计划周期**：Week 8
**状态**：`[x]`
**目标**：把 LangGraph 内部事件转换为领域事件、StageArtifact 和投影来源记录，防止 raw graph state 泄漏到产品 API。
**实施计划**：`docs/plans/implementation/a4.7-langgraph-event-translation.md`

**修改文件列表**：
- Create: `backend/app/runtime/event_translator.py`
- Create: `backend/tests/runtime/test_langgraph_event_translation.py`

**实现类/函数**：
- `LangGraphEventTranslator.translate_node_started()`
- `LangGraphEventTranslator.translate_node_completed()`
- `LangGraphEventTranslator.translate_interrupt()`
- `LangGraphEventTranslator.write_stage_artifact()`

**验收标准**：
- 执行图内部事件不直接作为前端产品事件暴露。
- Graph node 事件转换为领域事件、阶段产物或稳定引用。
- 投影层只读取领域对象、事件和产物引用。
- Inspector 投影不需要 raw graph state 回填关键事实。
- LangGraph stream / node event 只允许进入 `LangGraphEventTranslator`。
- translator 输出领域事件、`StageArtifact`、`RunControlRecord` 或稳定引用。
- SSE、Projection、Inspector 不读取 LangGraph raw event、raw state、compiled graph 或 checkpoint 原始 payload。
- 测试覆盖 raw graph event 不会直接出现在对外事件 payload 中。
- translator 必须把底层事件先分类、裁剪、关联后再写入运行日志；raw LangGraph event 不得作为可查询日志载荷原样保存。

**测试方法**：
- `pytest backend/tests/runtime/test_langgraph_event_translation.py -v`

<a id="a48"></a>

## A4.8 Provider Registry

**计划周期**：Week 8
**状态**：`[x]`
**目标**：实现 Provider registry，使运行时能从 R3.4a 固化的 ProviderSnapshot 与 ModelBindingSnapshot 解析内置 Provider 与 custom Provider。
**实施计划**：`docs/plans/implementation/a4.8-provider-registry.md`

**修改文件列表**：
- Create: `backend/app/providers/base.py`
- Create: `backend/app/providers/provider_registry.py`
- Create: `backend/tests/providers/test_provider_registry.py`

**实现类/函数**：
- `ProviderConfig`
- `ModelProvider`
- `ProviderRegistry.resolve()`
- `ProviderRegistry.resolve_from_template_snapshot()`
- `ProviderRegistry.resolve_from_model_binding_snapshot()`

**验收标准**：
- 内置 Provider 与 custom Provider 走统一解析路径。
- 运行时读取 ModelBindingSnapshot 中已固化的 Provider 与模型绑定。
- Provider 解析必须使用 R3.4a 已固化的 `context_window_tokens`、`max_output_tokens`、`supports_tool_calling`、`supports_structured_output`、`supports_native_reasoning` 能力声明；不得读取最新 Provider 配置或配置包来覆盖当前 run。
- Provider registry 必须把五个模型能力字段放入 `ProviderConfig` 或等价运行时对象，供 A4.9 Provider Adapter、A4.9b Context Size Guard 和 A4.9d Stage Agent Runtime 消费。
- 当当前阶段需要模型驱动工具调用且模型绑定的 `supports_tool_calling = false` 时，Provider registry 或 Stage Agent Runtime 必须在绑定工具前返回结构化能力错误，不得创建不兼容的 tool binding。
- Provider 绑定单位是 AgentRole。
- Provider 配置不直接泄漏密钥内容到前端。
- Provider 解析成功、解析失败和凭据引用不可用必须写入运行日志；日志和审计摘要不得包含真实密钥。
- run 启动后 Provider 配置变化、凭据轮换或能力声明变化不得改变当前 run 已固化的模型调用语义。

**测试方法**：
- `pytest backend/tests/providers/test_provider_registry.py -v`

<a id="a48a"></a>

## A4.8a PromptValidation 边界校验

**计划周期**：Week 8
**状态**：`[x]`
**目标**：实现用户可编辑 `system_prompt` 的边界校验，使模板保存和 run 启动前都能拒绝覆盖平台指令、阶段契约、工具边界、审批边界、交付边界、审计边界或输出 Schema 的提示词。
**实施计划**：`docs/plans/implementation/a4.8a-prompt-validation-boundaries.md`

**修改文件列表**：
- Create: `backend/app/runtime/prompt_validation.py`
- Modify: `backend/app/services/templates.py`
- Modify: `backend/app/services/runs.py`
- Create: `backend/tests/runtime/test_prompt_validation.py`
- Create: `backend/tests/services/test_prompt_validation_integration.py`

**实现类/函数**：
- `PromptValidationRule`
- `PromptValidationResult`
- `PromptValidationError`
- `PromptValidationService`
- `PromptValidationService.validate_system_prompt()`
- `PromptValidationService.validate_template_prompts_before_save()`
- `PromptValidationService.validate_run_prompt_snapshots()`

**验收标准**：
- `system_prompt` 保存前必须校验长度上限、上下文预算和平台边界冲突，超过上限时返回明确错误，不得静默截断后保存。
- run 启动前必须对即将进入 `template_snapshot_ref` 的 `system_prompt` 再次执行同一套 PromptValidation，防止旧模板或并发修改绕过保存时校验。
- 校验必须拒绝要求忽略平台指令、调用未授权工具、跳过澄清或审批、绕过审计、泄露凭据、泄露 raw chain-of-thought、修改交付模式、关闭结构化输出、覆盖阶段契约或覆盖输出 Schema 的提示词。
- A4.8a 必须接管 C2.4 模板保存和 R3.2 run 启动预留的 `system_prompt` 边界校验调用点；完成后不得保留仅长度校验、前端校验或绕过 PromptValidation 的保存/启动路径。
- PromptValidation 必须读取 R3.5 `GraphDefinition.stage_contracts`；模板保存时 `GraphDefinition` 尚未生成，必须读取与 R3.5 `GraphCompiler` 生成 `stage_contracts` 相同的阶段契约来源；不得新增与 `stage_contracts` 并行的阶段规则表。
- PromptValidation 只校验提示词与平台边界、阶段契约和安全约束的冲突；不得把语言风格、技术偏好或业务判断质量作为阻塞保存或启动 run 的依据。
- 用户可编辑 `system_prompt` 通过校验后仍只能作为低权威 `agent_role_prompt` 进入后续 `ContextEnvelope`，不得升级为 `runtime_instructions`。
- 校验接受、校验拒绝和 run 启动前校验失败必须写入运行日志摘要；涉及用户保存请求的拒绝必须写入审计记录。

**测试方法**：
- `pytest backend/tests/runtime/test_prompt_validation.py -v`
- `pytest backend/tests/services/test_prompt_validation_integration.py -v`

<a id="a48b"></a>

## A4.8b ContextEnvelope 与 ContextManifest Schema

**计划周期**：Week 8
**状态**：`[x]`
**目标**：固定 `ContextEnvelope`、`ContextManifest`、上下文块和上下文可信边界的结构化 Schema，使模型调用前的上下文输入与过程记录具备统一数据契约。
**实施计划**：`docs/plans/implementation/a4.8b-context-envelope-manifest-schema.md`

**修改文件列表**：
- Create: `backend/app/context/schemas.py`
- Modify: `backend/app/schemas/prompts.py`
- Create: `backend/tests/context/test_context_schemas.py`

**实现类/函数**：
- `ContextEnvelope`
- `ContextManifest`
- `ContextEnvelopeSection`
- `ContextBlock`
- `ContextSourceRef`
- `ContextTrustLevel`
- `ContextBoundaryAction`
- `ContextManifestRecord`
- `PromptSectionRef`
- `ContextEnvelope.validate_section_order()`
- `ContextManifest.from_envelope()`

**验收标准**：
- `ContextEnvelope` Schema 必须按规约顺序表达 `runtime_instructions`、`stage_contract`、`agent_role_prompt`、`task_objective`、`specified_action`、`input_artifact_refs`、`context_references`、`working_observations`、`reasoning_trace`、`available_tools`、`recent_observations`、`response_schema` 和 `trace_context`。
- `ContextManifest` Schema 必须记录 `session_id`、`run_id`、`stage_run_id`、`trace_id`、`correlation_id`、`span_id`、构建时间、`template_snapshot_ref`、`system_prompt` 快照引用、系统内置 `prompt_id` / `prompt_version`、提示词资产来源、缓存属性、最终渲染提示词或消息序列引用、hash、模板版本、Provider 与模型绑定快照引用、阶段契约、输出 Schema、可用工具及 schema 版本、来源对象、可信级别、边界处理、裁剪压缩状态、完整内容稳定引用和估算规模。
- `ContextBlock` 必须区分系统可信上下文、低权威角色配置上下文和不可信业务事实或观察结果；用户消息、澄清回复、审批反馈、附件、仓库文件、测试输出、工具观察和外部交付返回不得覆盖 `runtime_instructions`、`stage_contract`、`allowed_tools` 或 `response_schema`。
- `available_tools` 只能表达来自 W5.0 `ToolProtocol` / `ToolRegistry` 的工具名称、schema 版本和可绑定描述；不得保存具体工具实例、临时工具函数或未注册工具。
- Schema 必须支持把 `context_manifest` 作为 R3.7 `StageArtifact.process` 过程记录类型引用，且不把大文本直接复制到 manifest 中。
- raw LangGraph state、raw checkpoint payload、raw node event、raw thread 对象、raw tool adapter 对象和 raw Provider adapter 对象不得通过 Schema 校验进入 `ContextEnvelope`。
- 本切片只固定 Schema 和校验，不实现上下文来源解析、尺寸守卫、压缩或模型调用；后续 A4.9a 使用本 Schema 构建实际 envelope。
- 本切片不得加载提示词文件或渲染最终消息；A4.8c 负责系统提示词资产加载，A4.8d 负责 PromptRenderer。

**测试方法**：
- `pytest backend/tests/context/test_context_schemas.py -v`

<a id="a48c"></a>

## A4.8c PromptRegistry 与系统提示词资产加载

**计划周期**：Week 8
**状态**：`[x]`
**目标**：实现系统内置提示词资产注册与加载边界，使 runtime、上下文压缩、结构化输出修复和工具使用模板通过统一 `PromptRegistry` 获取版本化提示词资产。
**实施计划**：`docs/plans/implementation/a4.8c-prompt-registry-assets.md`

**修改文件列表**：
- Create: `backend/app/prompts/__init__.py`
- Create: `backend/app/prompts/registry.py`
- Create: `backend/app/prompts/definitions.py`
- Create: `backend/app/prompts/assets/runtime/runtime_instructions.md`
- Create: `backend/app/prompts/assets/repairs/structured_output_repair.md`
- Create: `backend/app/prompts/assets/compression/compression_context.md`
- Create: `backend/app/prompts/assets/tools/tool_usage_common.md`
- Create: `backend/tests/prompts/test_prompt_registry.py`
- Create: `backend/tests/prompts/test_prompt_asset_loading.py`

**实现类/函数**：
- `PromptAsset`
- `PromptRegistry`
- `PromptRegistry.load_builtin_assets()`
- `PromptRegistry.get(prompt_id: str, prompt_version: str | None = None)`
- `PromptRegistry.list_by_type(prompt_type: PromptType)`
- `PromptRegistry.resolve_version_ref(ref: PromptVersionRef)`
- `PromptRegistry.compute_content_hash(content: str)`
- `PromptAssetMetadataError`
- `PromptAssetNotFoundError`

**验收标准**：
- `PromptRegistry` 必须消费 C1.10a 的 PromptAsset Schema；不得定义并行字段名或并行 prompt 类型。
- 内置提示词资产必须以 Markdown 文件维护，并使用 YAML front matter 声明 `prompt_id`、`prompt_version`、`prompt_type`、`authority_level`、`model_call_type`、`cache_scope` 和 `source_ref`；文件名不承载版本号，`prompt_version` 的真源是 front matter。
- `PromptRegistry` 加载时必须解析并剥离 YAML front matter，把元数据写入 `PromptAsset`，把正文作为 prompt content；导入到模板槽位、PromptRenderer 或模型消息时不得包含 front matter。
- `PromptRegistry` 加载时必须基于剥离 front matter 后的正文计算 `content_hash`，并拒绝缺失元数据、重复 `prompt_id + prompt_version`、未知 prompt 类型、非法 authority 升级和不匹配的文件路径。
- `runtime_instructions`、`structured_output_repair`、`compression_prompt`、`tool_usage_template` 必须能通过稳定 `PromptVersionRef` 解析。
- `agent_role_seed` 资产由 C2.2 使用；A4.8c 只提供加载和校验，不修改模板或用户配置。
- `PromptRegistry` 不读取环境变量、`PlatformRuntimeSettings`、前端设置或模板编辑字段来选择系统提示词资产版本。
- 资产加载失败不得退化为内联硬编码提示词；调用方必须收到结构化错误以进入运行失败或启动失败流程。
- 测试必须覆盖合法加载、front matter 剥离、正文 hash 计算、重复版本、缺失 front matter、非法 `compression_prompt` 配置化、非法 `agent_role_seed` authority 和未知资产引用。

**测试方法**：
- `pytest backend/tests/prompts/test_prompt_registry.py -v`
- `pytest backend/tests/prompts/test_prompt_asset_loading.py -v`

<a id="a48d"></a>

## A4.8d PromptRenderer 与消息序列渲染

**计划周期**：Week 8
**状态**：`[x]`
**目标**：实现 PromptRenderer，把系统内置提示词资产、run 快照、阶段契约、工具描述、任务目标和输出 Schema 按 ContextEnvelope 顺序渲染为可追踪的提示词 section 和最终消息序列。
**实施计划**：`docs/plans/implementation/a4.8d-prompt-renderer.md`

**修改文件列表**：
- Create: `backend/app/prompts/renderer.py`
- Modify: `backend/app/context/schemas.py`
- Create: `backend/tests/prompts/test_prompt_renderer.py`
- Create: `backend/tests/prompts/test_prompt_renderer_manifest_metadata.py`

**实现类/函数**：
- `PromptRenderer`
- `PromptRenderRequest`
- `PromptRenderResult`
- `PromptRenderedSection`
- `PromptRenderer.render_runtime_instructions()`
- `PromptRenderer.render_stage_contract()`
- `PromptRenderer.render_tool_usage()`
- `PromptRenderer.render_structured_output_repair()`
- `PromptRenderer.render_messages()`
- `PromptRenderer.compute_render_hash()`

**验收标准**：
- `PromptRenderer` 必须从 A4.8c `PromptRegistry` 读取系统内置提示词资产，并从 R3.5 `GraphDefinition.stage_contracts` 读取阶段契约；不得维护并行阶段规则、工具权限表或输出 Schema。
- `PromptRenderer` 只能渲染 A4.8c 已剥离 front matter 的提示词正文；`prompt_id`、`prompt_version`、`source_ref`、`cache_scope`、`content_hash` 和 `render_hash` 只能进入渲染元数据、`ContextManifest` 或过程记录，不得进入模型可见消息正文。
- 渲染顺序必须保持 `ContextEnvelope` 权威层级：`runtime_instructions` 高于 `stage_contract`，`stage_contract` 高于 `agent_role_prompt`，`agent_role_prompt` 高于业务事实和工具观察。
- 本切片依赖 A4.8b 已首次创建并固定 `backend/app/context/schemas.py` 中的 `ContextEnvelope`、`ContextManifest` 与 `PromptSectionRef` Schema；A4.8d 只能在该边界上补充渲染所需元数据，不得抢占 context schema 的首次建模。
- 工具说明必须从 W5.0 `ToolProtocol` / `ToolRegistry` 的可绑定描述渲染；提示词资产只能定义展示模板和通用使用准则，不得授予、扩大或隐藏工具权限。
- 结构化输出修复提示词必须引用当前 `response_schema`、解析错误和可修复范围；不得允许模型改变阶段契约、关闭结构化输出或修改工具边界。
- 渲染结果必须返回 section 级 `prompt_id`、`prompt_version`、`source_ref`、`cache_scope`、`content_hash`、`render_hash` 和最终消息序列引用所需元数据。
- 当提示词资产缺失、版本不可解析、hash 不匹配或与阶段契约冲突时，`PromptRenderer` 必须返回结构化错误，不得回退到内联硬编码提示词。
- 测试必须覆盖标准 stage agent 调用、结构化输出修复调用、工具描述渲染、PromptRegistry 缺失、阶段契约冲突和 manifest 元数据完整性。

**测试方法**：
- `pytest backend/tests/prompts/test_prompt_renderer.py -v`
- `pytest backend/tests/prompts/test_prompt_renderer_manifest_metadata.py -v`
**验证摘要**：实施计划 `docs/plans/implementation/a4.8d-prompt-renderer.md` 已完成并在 integration checkpoint 合入 `a9d28f3`，且本次 checkpoint 手工融合了 candidate-a 在 `backend/app/context/schemas.py` 上的 provenance 与 trace hardening。`uv run pytest backend/tests/prompts/test_prompt_renderer.py backend/tests/prompts/test_prompt_renderer_manifest_metadata.py backend/tests/context/test_context_schemas.py backend/tests/prompts/test_prompt_registry.py backend/tests/schemas/test_prompt_asset_schemas.py -v` 通过 21 个 focused prompt/context tests；本次批量 integration verification 中后端聚合回归通过 59 个 tests。

<a id="a49"></a>

## A4.9 LangChain Provider Adapter

**计划周期**：Week 8
**状态**：`[x]`
**目标**：实现 LangChain 适配层，使正式 runtime 可以创建模型调用对象和结构化输出边界。
**实施计划**：`docs/plans/implementation/a4.9-langchain-provider-adapter.md`

**修改文件列表**：
- Create: `backend/app/providers/langchain_adapter.py`
- Create: `backend/tests/providers/test_langchain_adapter.py`

**实现类/函数**：
- `LangChainProviderAdapter`
- `ModelCallResult`
- `LangChainProviderAdapter.create_chat_model()`
- `LangChainProviderAdapter.bind_tools()`
- `LangChainProviderAdapter.with_structured_output()`
- `LangChainProviderAdapter.invoke_structured()`

**验收标准**：
- LangChain 封装模型供应商、消息对象、结构化输出与内部工具绑定。
- custom Provider 使用 `OpenAI Completions compatible` 接入协议。
- 测试使用 fake model，不调用真实远端模型。
- LangChain adapter 只创建 chat model、绑定工具、声明结构化输出，不表达业务阶段流转。
- LangChain adapter 只消费调用方传入的消息序列、可绑定工具描述和结构化输出 Schema；不得自行解析业务上下文、读取 StageArtifact 或修改 `ContextManifest`。
- 工具绑定对象来自 W5.0 定义的抽象 `ToolProtocol` 与工具注册表；Week 8 只能绑定已注册 `bash`、`read_file`、`edit_file`、`write_file`、`glob`、`grep` 或 fake 工具，不得在 D5.1-D5.4 前绑定具体 delivery tool 实例。
- 工具绑定前必须检查当前模型绑定快照中的 `supports_tool_calling`；该能力为 `false` 时不得调用 LangChain tool/function calling 绑定接口，必须返回结构化能力错误。
- `invoke_structured()` 必须读取当前模型绑定快照中的 `max_output_tokens` 作为请求输出 token 上限或更严格输出预算的上界；调用方传入更小预算时使用更小值，调用方不得超过快照能力声明。
- `with_structured_output()` 与 `invoke_structured()` 必须读取 `supports_structured_output`；该能力为 `true` 时可以走 Provider 原生结构化输出路径，为 `false` 时必须走兼容解析、Schema 校验与结构化输出修复路径，不得调用该模型的原生结构化输出接口。
- `ModelCallResult` 只能在 `supports_native_reasoning = true` 且 Provider 响应确实包含原生推理字段时记录原生推理引用或裁剪摘要；该能力为 `false` 或响应缺失时不得伪造 raw chain-of-thought 或原生推理内容。
- 结构化输出失败必须返回可处理错误，不得直接推进 LangGraph 节点成功完成。
- `ModelCallResult` 必须返回原始响应引用、结构化输出候选、tool call request 候选、Provider 错误、token 用量摘要和 `model_call_trace` 写入所需元数据；不得把自由文本直接标记为阶段成功。
- 模型请求、模型响应、结构化输出解析和模型错误必须写入运行日志摘要；模型输入输出进入日志前必须裁剪、阻断敏感字段并限制长度。
- Provider 调用策略参数必须来自当前 run 的 `RuntimeLimitSnapshot` 或其引用的配置版本，不得读取最新 `PlatformRuntimeSettings`；指数退避重试和熔断由 A4.9e 在本适配器边界上实现。
- 上下文压缩使用系统内置 `compression_prompt`；Adapter 只能记录系统内置提示词资产的 prompt id/version 引用，不得把 `compression_prompt` 作为用户配置、环境变量或热重载设置读取。

**测试方法**：
- `pytest backend/tests/providers/test_langchain_adapter.py -v`
**验证摘要**：实施计划 `docs/plans/implementation/a4.9-langchain-provider-adapter.md` 已完成并在 integration checkpoint 合入 `aca5a8c`。`uv run pytest backend/tests/providers/test_langchain_adapter.py -v` 通过 17 个 focused tests；`uv run pytest backend/tests/providers/test_langchain_adapter.py backend/tests/providers/test_provider_registry.py backend/tests/fixtures/test_fixture_contracts.py -v` 在 worker checkpoint 通过 50 个 impacted tests；本次 integration verification 中 `uv run pytest backend/tests/domain/test_change_set.py backend/tests/context/test_context_schemas.py backend/tests/providers/test_langchain_adapter.py backend/tests/providers/test_provider_registry.py backend/tests/fixtures/test_fixture_contracts.py -v` 通过 67 个 tests，覆盖 provider adapter、registry、fixture contract 和相邻 ChangeSet/context 契约。

<a id="a49a"></a>

## A4.9a ContextEnvelope Builder 与 ContextManifest 记录

**计划周期**：Week 8
**状态**：`[x]`
**目标**：实现上下文来源解析和 `ContextEnvelope` 构建，把阶段契约、角色提示词、阶段产物、工具观察和不可信上下文按固定顺序组装，并把实际上下文使用记录写入 `StageArtifact.process`。
**实施计划**：`docs/plans/implementation/a4.9a-context-envelope-builder.md`

**修改文件列表**：
- Create: `backend/app/context/source_resolver.py`
- Create: `backend/app/context/builder.py`
- Modify: `backend/app/context/__init__.py`
- Create: `backend/tests/context/test_context_source_resolver.py`
- Create: `backend/tests/context/test_context_envelope_builder.py`

**实现类/函数**：
- `ContextSourceResolver`
- `ContextEnvelopeBuilder`
- `ContextBuildRequest`
- `ContextBuildResult`
- `ContextEnvelopeBuilder.build_for_stage_call()`
- `ContextEnvelopeBuilder.render_messages()`
- `ContextEnvelopeBuilder.append_manifest_record()`
- `ContextSourceResolver.resolve_stage_inputs()`
- `ContextSourceResolver.resolve_context_references()`
- `ArtifactStore.append_process_record()`

**验收标准**：
- Builder 必须消费 A4.8b `ContextEnvelope` / `ContextManifest` Schema，不得输出临时 dict 或前端投影专用载荷。
- Builder 必须通过 A4.8d `PromptRenderer` 渲染 `runtime_instructions`、阶段提示词固定片段、结构化输出修复提示词和工具使用说明；不得在 builder 内临时拼接系统内置提示词正文。
- Builder 必须从 R3.5 `GraphDefinition.stage_contracts` 读取当前阶段职责、输入契约、输出契约、`allowed_tools`、结构化产物要求和运行上限引用；不得再引入 `stage_execution_mode` 或并行权限表。
- Builder 必须从 R3.7 `StageArtifact`、`ContextReference`、ClarificationRecord、ApprovalDecision、`SolutionDesignArtifact.implementation_plan`、工具结果、ChangeSet 和工作区稳定引用解析上下文来源；不得从运行日志反推业务事实。
- `code_generation`、`test_generation_execution` 和 `code_review` 阶段的 `ContextEnvelope` 必须包含已批准方案中的 `implementation_plan` 稳定引用、任务标识、任务顺序和依赖关系。
- Builder 不得把其他 Session 的历史 run、历史产物、历史审批、历史工具确认或历史工具过程作为新 Session 的隐式长期记忆来源；同一 Session 下历史 run 只能按当前需求链路和稳定引用显式进入上下文。
- `agent_role_prompt` 必须来自已通过 A4.8a PromptValidation 并固化到当前 run `template_snapshot_ref` 的提示词；Builder 不得读取最新模板或最新 AgentRole 配置。
- `available_tools` 必须通过 W5.0 `ToolRegistry.list_bindable_tools()` 按当前 `stage_contract.allowed_tools` 过滤生成；未注册工具、未授权工具和具体工具实例不得进入 `ContextEnvelope`。
- 用户消息、澄清回复、审批反馈、附件、仓库文件、测试输出、工具观察和外部交付返回必须作为不可信 `ContextBlock` 进入，并记录来源标识、可信级别、边界说明和稳定引用。
- 每次构建必须生成 `ContextManifest`，并通过 R3.7 已提供的 `ArtifactStore.append_process_record(process_key="context_manifest", ...)` 写入当前 `StageArtifact.process` 或其稳定引用；A4.9a 不新增 `ArtifactStore` helper，运行日志只保存摘要和定位信息。
- Builder 必须记录最终渲染提示词或消息序列引用、hash、模板版本、系统内置 prompt 版本、提示词片段来源、Provider 与模型绑定快照引用和可用工具 schema 版本。
- raw LangGraph state、raw checkpoint payload、raw node event、raw thread 对象、raw Provider response 和 raw tool adapter 对象不得进入 envelope 或 manifest。

**测试方法**：
- `pytest backend/tests/context/test_context_source_resolver.py -v`
- `pytest backend/tests/context/test_context_envelope_builder.py -v`
**验证摘要**：实施计划 `docs/plans/implementation/a4.9a-context-envelope-builder.md` 已完成并在 integration checkpoint 合入 `d349599`。Worker focused verification 中 `uv run pytest backend/tests/context/test_context_source_resolver.py backend/tests/context/test_context_envelope_builder.py -v` 通过 14 个 tests；worker impacted verification 中 `uv run pytest backend/tests/context/test_context_source_resolver.py backend/tests/context/test_context_envelope_builder.py backend/tests/context/test_context_schemas.py backend/tests/prompts/test_prompt_renderer.py backend/tests/prompts/test_prompt_renderer_manifest_metadata.py backend/tests/services/test_artifact_store.py backend/tests/services/test_graph_compiler.py -v` 通过 63 个 tests。本次 integration verification 使用同一 impacted command 在 `integration/function-one-acceleration` 上通过 63 个 tests，覆盖 context builder、source resolver、prompt rendering、manifest metadata、ArtifactStore shared append entry 和 graph compiler 相邻契约。

<a id="a49e"></a>

## A4.9e Provider retry、backoff 与 circuit breaker

**计划周期**：Week 8
**状态**：`[x]`
**目标**：实现 Provider 调用失败的指数退避重试、连续失败熔断和过程记录，使 Provider 失败可解释、可投影，并且不改变已启动 run 的 Provider 快照语义。
**实施计划**：`docs/plans/implementation/a4.9e-provider-retry-circuit-breaker.md`

**修改文件列表**：
- Create: `backend/app/providers/retry_policy.py`
- Modify: `backend/app/providers/langchain_adapter.py`
- Create: `backend/tests/providers/test_provider_retry_policy.py`
- Create: `backend/tests/providers/test_provider_circuit_breaker.py`
- Modify: `backend/tests/providers/test_langchain_adapter.py`

**实现类/函数**：
- `ProviderCallPolicySnapshot`
- `ProviderRetryPolicy`
- `ProviderCircuitBreaker`
- `ProviderRetryDecision`
- `ProviderCircuitBreakerState`
- `LangChainProviderAdapter.invoke_with_retry()`

**验收标准**：
- A4.9e 必须在 A4.9 `LangChainProviderAdapter` 和 W5.0c `FakeProvider` / `FakeChatModel` 可用后实施；它是 A4.9b 上下文压缩模型调用和 A4.9d Stage Agent Runtime 模型调用的前置，不是 A4.9a ContextEnvelope Builder 的前置。
- Provider 请求超时、网络错误和限流错误必须按当前 run 固化的 `ProviderCallPolicySnapshot` 执行指数退避重试。
- 重试次数、退避基准、退避上限、下一次尝试等待摘要和最终状态必须写入 `provider_retry_trace` 与运行日志摘要。
- 连续失败达到熔断阈值时必须打开 `ProviderCircuitBreaker`，写入 `provider_circuit_breaker_trace`，并阻止当前阶段继续调用同一已熔断模型绑定。
- `provider_retry_trace` 与 `provider_circuit_breaker_trace` 必须通过 R3.7 已提供的 `ArtifactStore.append_process_record()` 或等价 AL01 owner 共享追加入口写入 `StageArtifact.process`；A4.9e 不得新增或修改 `backend/app/services/artifacts.py` 的共享入口。
- 熔断恢复条件只来自当前 run 固化的策略快照；不得读取最新 `PlatformRuntimeSettings` 或运行外 Provider 配置改变当前 run。
- 鉴权失败、模型不存在、能力不支持、模型绑定快照不可解析、空响应和无法解析结构化输出不得进入可恢复重试循环，必须形成结构化失败。
- Provider 重试和熔断结果必须能通过 Q3.3 / F3.4 / F3.7 进入阶段内部 `provider_call` 状态和 Inspector，不得只停留在日志中。
- 不得自动切换到运行外最新 Provider、模型或凭据；同一 run 内的替代调用路径只能来自本次快照已定义且阶段允许的配置。

**测试方法**：
- `pytest backend/tests/providers/test_provider_retry_policy.py -v`
- `pytest backend/tests/providers/test_provider_circuit_breaker.py -v`
- `pytest backend/tests/providers/test_langchain_adapter.py -v`
**验证摘要**：实施计划 `docs/plans/implementation/a4.9e-provider-retry-circuit-breaker.md` 已完成并在 integration checkpoint 合入 `0ec0305`。Worker focused / impacted verification 中 `uv run pytest backend/tests/providers/test_provider_retry_policy.py backend/tests/providers/test_provider_circuit_breaker.py backend/tests/providers/test_langchain_adapter.py backend/tests/providers/test_provider_registry.py backend/tests/fixtures/test_fixture_contracts.py -v` 通过 65 个 tests；`uv run pytest backend/tests/services/test_artifact_store.py -v` 通过 22 个 tests。本次 integration verification 在 `integration/function-one-acceleration` 上运行 `uv run pytest backend/tests/providers/test_provider_retry_policy.py backend/tests/providers/test_provider_circuit_breaker.py backend/tests/providers/test_langchain_adapter.py backend/tests/providers/test_provider_registry.py backend/tests/fixtures/test_fixture_contracts.py backend/tests/services/test_artifact_store.py -v`，通过 87 个 tests，覆盖 Provider retry/circuit breaker、LangChain adapter、Provider registry、fixture contracts 和 ArtifactStore 既有 `append_process_record()` 共享入口。

<a id="a49b"></a>

## A4.9b Context Size Guard 与压缩过程记录

**计划周期**：Week 8
**状态**：`[x]`
**目标**：实现单次模型调用前的上下文尺寸守卫、观察结果预算、滑动工作窗口和上下文压缩记录，防止大文件、工具输出、测试输出或长链路过程无界进入模型上下文。
**实施计划**：`docs/plans/implementation/a4.9b-context-size-guard.md`
**验证摘要**：实施计划 `docs/plans/implementation/a4.9b-context-size-guard.md` 已在 integration checkpoint 合入 `c37d0fd`。Worker verification 中 focused context guard / compression 命令通过 26 个 tests，impacted context / prompt / provider / ArtifactStore 命令通过 97 个 tests。本次 integration verification 在 `integration/function-one-acceleration` 上重复运行 focused 与 impacted backend 命令并通过，`uv run pytest -q` 通过 1094 个 backend tests，保留既有 LangChain adapter `temperature` warning。

**修改文件列表**：
- Create: `backend/app/context/size_guard.py`
- Create: `backend/app/context/compression.py`
- Modify: `backend/app/context/builder.py`
- Modify: `backend/app/context/__init__.py`
- Modify: `backend/app/prompts/renderer.py`
- Create: `backend/tests/context/test_context_size_guard.py`
- Create: `backend/tests/context/test_context_compression.py`

**实现类/函数**：
- `ContextTokenEstimator`
- `ContextSizeGuard`
- `ContextCompressionRunner`
- `CompressedContextBlock`
- `ContextOverflowError`
- `ContextSizeGuard.apply_observation_budget()`
- `ContextSizeGuard.apply_sliding_window()`
- `ContextSizeGuard.ensure_within_model_window()`
- `ContextCompressionRunner.compress()`
- `ArtifactStore.append_process_record(process_key="compressed_context_block", ...)`
- `ArtifactStore.append_process_record(process_key="context_compression_model_call_trace", ...)`

**验收标准**：
- Size guard 必须读取当前 run 的 `RuntimeLimitSnapshot`、Provider 与模型绑定快照能力声明；不得读取 A4.9 Provider Adapter 运行期返回的模型窗口信息、最新 `PlatformRuntimeSettings`、最新 Provider 配置或配置包改变当前 run。
- Size guard 必须使用 `compression_trigger_tokens = floor(context_window_tokens * compression_threshold_ratio)` 计算压缩触发阈值；`context_window_tokens` 来自模型绑定快照能力声明，`compression_threshold_ratio` 来自 `RuntimeLimitSnapshot.context_limits`。
- 若实现需要预留输出 token，可以使用更保守的 `floor((context_window_tokens - reserved_output_tokens) * compression_threshold_ratio)`，但不得产生高于基础公式的触发阈值。
- `reserved_output_tokens` 可以由当前模型绑定快照中的 `max_output_tokens`、阶段输出 Schema 或调用方预算共同决定；该预留只允许降低压缩触发阈值，不得放宽基础阈值。
- 默认能力和阈值组合为 `context_window_tokens = 128000`、`compression_threshold_ratio = 0.8`，对应基础压缩触发阈值 `102400` token。
- 大文件读取、`grep` 结果、测试输出、diff、`bash` stdout / stderr、工具错误和远端交付返回进入 `ContextEnvelope` 前必须被预算化，只保留预览、摘要、路径、hash、行号、退出码、错误摘要和稳定引用。
- 阶段内 ReAct 循环必须应用滑动工作窗口，保留最近必要过程，并把更早过程转为结构化索引或引用；不得删除 R3.7 `StageArtifact.process` 中的原始过程记录。
- `pinned_context` 包含 `runtime_instructions`、`stage_contract`、`task_objective`、`response_schema`、`system_prompt` 快照引用、结构化需求、已批准方案、当前审批或拒绝理由、当前 active file task 和可用工具 schema，压缩时不得丢失。
- 上下文压缩必须通过 A4.9 `LangChainProviderAdapter.invoke_structured()` 发起 `model_call_type = context_compression` 的模型调用，并使用系统内置 `compression_prompt` 引用；不得把压缩提示词作为用户配置、环境变量或热重载设置读取。
- 上下文压缩必须通过 A4.8d `PromptRenderer.render_messages()` 获取 `compression_prompt` 的版本化消息序列；压缩过程记录必须写入 `compression_prompt_id`、`compression_prompt_version` 和渲染 hash。
- 压缩输出必须形成结构化 `CompressedContextBlock`，并写入 `StageArtifact.process` 的 `compressed_context_block` 和对应 `model_call_trace`；自由文本摘要不得作为唯一结果。
- 压缩失败不得伪造摘要；若仍能构建 envelope，必须记录 warning 和 manifest 处理结果；若无法构建 envelope，当前 `StageRun.status` 与 `PipelineRun.status` 必须进入 `failed`，并通过尾部 `system_status` 暴露 `context_overflow` 原因。
- 连续压缩失败必须按当前 run 的运行上限熔断，不得无限重试。

**测试方法**：
- `pytest backend/tests/context/test_context_size_guard.py -v`
- `pytest backend/tests/context/test_context_compression.py -v`

<a id="a49c"></a>

## A4.9c AgentDecision Schema 与解析器

**计划周期**：Week 8
**状态**：`[x]`
**目标**：固定 Stage Agent 每轮模型调用的结构化决策协议和解析器，使工具请求、阶段产物提交、澄清请求、结构化修复、重试计划和阶段失败都通过可校验的 `AgentDecision` 表达。
**实施计划**：`docs/plans/implementation/a4.9c-agent-decision-parser.md`

**修改文件列表**：
- Create: `backend/app/runtime/agent_decision.py`
- Create: `backend/tests/runtime/test_agent_decision_parser.py`

**实现类/函数**：
- `AgentDecision`
- `AgentDecisionType`
- `ToolCallDecision`
- `ToolConfirmationDecision`
- `SubmitStageArtifactDecision`
- `ClarificationDecision`
- `StructuredRepairDecision`
- `RetryWithRevisedPlanDecision`
- `FailStageDecision`
- `AgentDecisionParser`
- `AgentDecisionParser.parse_model_result()`
- `AgentDecisionParser.validate_against_stage_contract()`

**验收标准**：
- `AgentDecision.decision_type` 至少支持 `request_tool_call`、`request_tool_confirmation`、`submit_stage_artifact`、`request_clarification`、`repair_structured_output`、`retry_with_revised_plan` 和 `fail_stage`。
- 解析器必须消费 A4.9 `ModelCallResult` 的结构化输出候选和 tool call request 候选；不得用自由文本、正则、字符串命令解析或 JSON 猜测触发工具、推进状态、创建审批或交付动作。
- `request_tool_call` 只能引用当前 `ContextEnvelope.available_tools` 中存在的工具名称和 schema 版本；未知工具、未授权工具、schema 不匹配或重复无效 tool call 不得执行，必须形成结构化模型调用错误。
- `request_tool_confirmation` 只能引用当前阶段允许的工具动作，必须携带工具名称、命令或参数摘要、目标资源、风险等级、风险分类、预期副作用和替代路径判断；解析器不得把该决策直接转成工具执行。
- `submit_stage_artifact` 必须按 R3.5 当前 `stage_contract` 的输出契约和 R3.7 `StageArtifact.output` 要求校验证据引用、失败/风险字段和必填结构化产物；缺失时只能进入结构化输出修复或阶段失败。
- `request_clarification` 只允许在当前阶段契约声明可澄清且缺失信息阻塞阶段输出时使用，并必须携带缺失事实、影响范围、关联引用和回答后需更新的结构化字段。
- `fail_stage` 必须携带失败原因、已执行证据引用、未完成事项和可展示错误摘要；不得只返回模型自由文本。
- 解析成功、解析失败、结构化输出修复请求、非法 tool call、工具确认请求和无效阶段产物提交必须写入 `decision_trace` 或 `model_call_trace` 过程记录引用。

**测试方法**：
- `pytest backend/tests/runtime/test_agent_decision_parser.py -v`

<a id="a49d"></a>

## A4.9d Stage Agent Runtime 执行循环

**计划周期**：Week 8
**状态**：`[x]`
**目标**：实现正式阶段内执行循环，把 Context Management、Provider Adapter、AgentDecision、ToolRegistry、StageArtifact 和阶段恢复游标串成单阶段 runner，供 LangGraph stage node 调用。
**实施计划**：`docs/plans/implementation/a4.9d-stage-agent-runtime-loop.md`

**修改文件列表**：
- Create: `backend/app/runtime/stage_agent.py`
- Modify: `backend/app/runtime/stage_runner_port.py`
- Modify: `backend/app/runtime/nodes.py`
- Modify: `backend/app/services/artifacts.py`
- Create: `backend/tests/runtime/test_stage_agent_runtime.py`
- Create: `backend/tests/runtime/test_stage_agent_process_records.py`

**实现类/函数**：
- `StageAgentRuntime`
- `StageExecutionRequest`
- `StageExecutionResult`
- `StageRecoveryCursor`
- `StageAgentRuntime.run_stage()`
- `StageAgentRuntime.run_iteration()`
- `StageAgentRuntime.execute_tool_decision()`
- `StageAgentRuntime.submit_stage_artifact()`
- `StageAgentRuntime.persist_recovery_checkpoint()`

**验收标准**：
- `StageAgentRuntime` 必须实现 A4.5 `StageNodeRunnerPort`，由 LangGraph stage node 调用；阶段 runner 不得直接修改 `PipelineRun` 主链状态。
- 每次阶段执行、ReAct iteration、结构化输出修复、validation pass 或上下文压缩调用前，必须通过 A4.8d/A4.9a/A4.9b 生成 `ContextEnvelope` 和 `ContextManifest`。
- 模型调用必须通过 A4.9 `LangChainProviderAdapter`，并使用 A4.9c `AgentDecisionParser` 解析决策；自由文本不得作为运行时状态推进、工具执行、审批创建或交付动作依据。
- 阶段执行进入模型调用前必须读取当前模型绑定快照能力；需要工具调用而 `supports_tool_calling = false`、需要原生结构化输出而 `supports_structured_output = false` 且无兼容解析路径、或 `max_output_tokens` 无法满足阶段最小输出预算时，必须形成结构化失败，不得继续调用不兼容模型。
- 工具执行必须经过 W5.0 `ToolRegistry`、当前 `stage_contract.allowed_tools`、输入 Schema、工作区边界、超时策略和审计策略校验；模型不得动态声明新工具或绕过工具注册表调用本地函数。
- 当工具风险分级结果为 `high_risk`，`StageAgentRuntime` 必须转交 H4.4a 创建 `ToolConfirmationRequest` 并进入 `waiting_tool_confirmation`，不得直接执行工具。
- 当工具风险分级结果为 `blocked`，`StageAgentRuntime` 必须记录结构化拒绝错误、安全审计和 `tool_trace`，不得创建可允许的工具确认请求。
- 阶段结果必须写入 R3.7 `StageArtifact.input`、`StageArtifact.process`、`StageArtifact.output`、metrics 和稳定引用；下游阶段不得只依赖上一阶段摘要文本。
- `StageArtifact.process` 必须记录 `context_manifest`、`reasoning_trace`、`decision_trace`、`tool_trace`、`model_call_trace`、`file_edit_trace`、`command_trace`、`validation_trace`、`compressed_context_block`、`structured_output_repair_trace`、`recovery_checkpoint`、`side_effect_reconciliation_trace` 和 `untrusted_context_trace` 中本阶段实际发生的记录类型。
- `StageArtifact.process` 必须记录 `tool_confirmation_trace`、`provider_retry_trace` 和 `provider_circuit_breaker_trace` 中本阶段实际发生的记录类型。
- `request_clarification` 决策必须转交 H4.1 澄清服务和 A4.0 runtime boundary；`request_tool_confirmation` 或 execution gate 判定的高风险工具动作必须转交 H4.4a 工具确认服务和 A4.0 runtime boundary；`submit_stage_artifact` 达到审批点时必须转交 H4.3 审批对象创建或 LangGraph 后续路由，不得由 Stage Agent Runtime 自建审批状态或工具确认状态。
- `delivery_integration` 的确定性交付执行不得由模型自由文本决定真实 Git 写动作；真实交付工具仍由后续 D5.1-D5.4 通过 W5.0 ToolProtocol 实现。
- `test_generation_execution` 阶段必须通过项目 README、依赖声明和脚本配置识别测试环境与依赖缺失；安装依赖、联网下载、数据库迁移、锁文件或环境配置修改等高风险命令必须先进入工具确认。
- `code_generation`、`test_generation_execution` 和 `code_review` 阶段必须按 `SolutionDesignArtifact.implementation_plan` 的稳定任务标识、顺序和依赖关系推进，不得把模型自由生成的临时计划替代已批准方案产物。
- ReAct iteration、tool call 数、文件编辑次数、结构化输出修复次数、自动回归次数和无进展次数必须受当前 run `RuntimeLimitSnapshot` 约束，超限后进入结构化失败或 run failed 语义。
- 每次 iteration 完成后必须持久化 `StageRecoveryCursor`、最近 `ContextManifest`、工具结果引用、模型调用引用、文件编辑引用和 `recovery_checkpoint`；恢复时不得重新执行已确认成功且具有副作用的工具调用。
- 无法协调的工具副作用、文件写入、`bash` 命令或交付动作必须记录 `side_effect_reconciliation_trace`，并使当前 `StageRun.status` 与 `PipelineRun.status` 进入 `failed`。
- Stage Agent 执行开始、模型调用、Provider 重试与熔断、工具调用、工具确认、阶段产物提交、结构化修复、澄清请求、失败、恢复和副作用协调必须写入运行日志摘要并继承 `TraceContext`；审计记录仍由对应工具、命令、工具确认或交付适配器负责。

**测试方法**：
- `pytest backend/tests/runtime/test_stage_agent_runtime.py -v`
- `pytest backend/tests/runtime/test_stage_agent_process_records.py -v`

<a id="a410"></a>

## A4.10 自动回归策略

**计划周期**：Week 8-9
**状态**：`[x]`
**目标**：实现代码评审自动回归策略，使受控 retry 能按模板快照配置运行。
**实施计划**：`docs/plans/implementation/a4.10-auto-regression-policy.md`

**修改文件列表**：
- Create: `backend/app/runtime/auto_regression.py`
- Create: `backend/tests/runtime/test_auto_regression_policy.py`

**实现类/函数**：
- `AutoRegressionPolicy`
- `should_retry_review_issue()`
- `resolve_max_auto_regression_retries()`

**验收标准**：
- 自动回归配置来自模板快照。
- 最大重试次数同时受模板快照和当前 run 的 `RuntimeLimitSnapshot` 约束，并落在平台定义统一硬上限内。
- Code Review 相关自动回归统一回到 `code_generation`。
- 自动回归结束后才能进入 code review approval。
- 自动回归策略判定、跳过、进入重试和超限必须写入运行日志，并继承当前 run 的 `trace_id`。
- C2.8 后续热重载运行设置不得改变当前 run 的自动回归上限。

**测试方法**：
- `pytest backend/tests/runtime/test_auto_regression_policy.py -v`

<a id="a411"></a>

## A4.11 自动回归控制条目与超限失败

**计划周期**：Week 8-9
**状态**：`[x]`
**目标**：实现自动回归过程记录、retry 控制条目和超限失败语义，使前端能解释为何回退和为何停止。
**实施计划**：`docs/plans/implementation/a4.11-auto-regression-control-items.md`

**修改文件列表**：
- Modify: `backend/app/runtime/auto_regression.py`
- Modify: `backend/app/services/control_records.py`
- Create: `backend/tests/runtime/test_auto_regression_control_items.py`

**实现类/函数**：
- `AutoRegressionRunner.run()`
- `AutoRegressionRunner.append_retry_control_item()`
- `AutoRegressionRunner.mark_retry_exhausted()`

**验收标准**：
- retry 控制条目进入事件流和投影。
- 本切片中的 `retry` 指当前 run 内自动回归或阶段内再次尝试，不表示 failed / terminated 后创建新 PipelineRun 的“重新尝试”。
- 控制条目包含 `retry_index` 与 `source_attempt_index`。
- 自动回归超限后输出明确失败或高风险状态，不静默推进。
- 自动回归结束且得到稳定评审产物后，创建 `code_review_approval`。
- 自动回归产生的 retry 控制条目仍由领域对象和事件驱动投影；运行日志只记录诊断摘要和关联标识。

**测试方法**：
- `pytest backend/tests/runtime/test_auto_regression_control_items.py -v`
**验证摘要**：实施计划 `docs/plans/implementation/a4.11-auto-regression-control-items.md` 已在 integration checkpoint 合入 `30088c8`。Worker focused verification 中 `backend/tests/runtime/test_auto_regression_control_items.py` 通过 10 个 tests，final impacted verification 中 auto regression control items、policy 和 control item detail projection tests 共 37 个 tests 通过。本次 integration verification 在 `integration/function-one-acceleration` 上重复运行同一 impacted backend command，共 37 个 tests 通过。
