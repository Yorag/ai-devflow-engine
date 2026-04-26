# 功能一后端引擎与协作规格 V1

## 1. 文档目标

本文档用于定义 `AI 驱动的需求交付流程引擎` 在 `功能一` 范围内的后端引擎设计、前后端协作契约与扩展边界，作为后端实现、接口设计和前端联调的正式依据。

本文档聚焦：
- 功能一后端领域对象与状态流转
- Pipeline 编排、阶段执行、自动回归与人工审批处理
- 前端控制台消费的查询投影与实时更新契约
- REST API、事件模型与工作区能力边界
- 为功能二预留的复用对象与接口

本文档不重新定义：
- 功能一的产品范围与产品级验收边界
- 前端控制台的信息架构、交互形态与视觉层级

## 2. 文档关系与口径优先级

本文档与其他规格文档的关系如下：

1. `docs/specs/function-one-product-overview-v1.md`
定义功能一的正式产品边界、阶段边界与人工介入边界。

2. `docs/specs/frontend-workspace-global-design-v1.md`
定义前端控制台的正式交互口径。凡涉及 Narrative Feed、Inspector、Composer、审批块、澄清与审批前端行为的表述，以该文档为准。

3. `docs/specs/function-one-backend-engine-design-v1.md`
负责把产品边界与前端交互口径落到后端领域模型、状态机、投影视图、事件流与接口契约。

`docs/archive/function-one-design-v2.md` 仅保留为迁移参考，不再作为当前后端规格依据。

## 3. 后端职责范围

功能一后端必须承担以下职责：
- 管理项目上下文、需求会话与 Pipeline 运行
- 编排各阶段执行、校验、回退、重试与终止
- 持久化阶段输入、阶段输出、结构化产物与审批记录
- 提供前端控制台所需的查询投影与实时更新能力
- 管理工作区读取、代码修改、命令执行、测试运行与交付通道适配
- 为功能二保留 `ChangeSet`、`ContextReference`、`PreviewTarget`、`DeliveryRecord` 的复用边界

## 4. 总体架构

功能一后端采用以下基础结构：

`状态机编排 + 结构化产物存储 + 领域事件日志 + 查询投影 + 工作区/交付适配层`

架构边界如下：
- `Pipeline Orchestrator` 负责阶段流转与状态决策
- `Agent Runtime` 负责组装上下文、执行模型调用与工具调用
- `Artifact Store` 负责持久化结构化产物与执行记录
- `Projection Layer` 负责输出前端控制台消费的数据视图
- `Workspace & Delivery Adapter` 负责与代码仓库、测试环境和托管平台交互

### 4.1 系统模块划分

功能一后端至少包含以下核心模块：

1. `Pipeline Template Registry`
负责管理流程模板、阶段顺序、依赖关系、检查点位置与自动回归配置。

2. `Pipeline Orchestrator`
负责运行时调度，驱动阶段开始、完成、失败、回退、重试、暂停、恢复与终止。

3. `Run Context / Artifact Store`
负责持久化运行上下文、阶段输入输出、结构化产物与共享引用。

4. `Agent Role Registry`
负责管理阶段角色预设、Prompt 模板、输入输出契约与失败处理策略。

5. `Clarification & Decision Service`
负责管理需求澄清记录、设计决策、审批反馈与关键结论回注。

6. `Agent Runtime`
负责组装上下文、调用模型供应商、执行工具调用、校验结构化输出并回写产物。

7. `LLM Provider Adapter`
负责统一封装模型供应商接入与切换逻辑。

8. `Workspace & Tool Service`
负责工作区隔离、文件读取、代码修改、命令执行、diff 生成与工具接口管理。

9. `SCM & Delivery Adapter`
负责封装本地 Git、远端托管平台、交付通道与 MR/PR 创建能力。

10. `Checkpoint & Review Service`
负责审批对象创建、审批决策记录、拒绝理由回注与回退触发。

11. `Observability & Projection Service`
负责阶段状态、事件时间线、错误文本、量化指标与前端查询投影生成。

12. `REST API + Query Layer`
负责暴露命令接口、查询接口、事件流接口与 OpenAPI 文档。

### 4.2 实施原则

后端实现必须遵循以下原则：
- `状态驱动`
  阶段推进、等待澄清、等待审批、回退与终止都必须由显式状态表达。
- `产物驱动`
  后续阶段只能依赖持久化产物和契约化上下文，不允许依赖运行期隐式记忆。
- `API First`
  前端控制台只能通过命令接口、查询接口和事件流消费后端能力。
- `工具统一抽象`
  文件系统、命令执行、分支准备和代码评审请求都必须通过统一工具协议暴露。
- `前后端解耦`
  前端定义交互语义，后端负责投影与载荷；双方不得在另一侧重复定义一套口径。

### 4.3 V1 部署与运行架构

功能一 V1 采用单机本地执行架构。

V1 默认部署拓扑必须满足以下规则：
- 前端控制台、后端服务与工作区执行能力部署在同一台主机。
- 前端与后端可以是独立进程，也可以采用同机集成部署；是否同进程或同容器不属于规格约束范围。
- 前端控制台只能通过命令接口、查询接口和事件流消费后端能力，不直接访问目标仓库文件系统，不直接执行本地命令，不直接承担 Git 交付动作。
- 后端中的执行侧必须与目标仓库、本地 Git 环境以及项目依赖的构建、运行和测试工具链处于同一台主机，并共享一致的文件系统视角。
- 远端托管平台在 V1 中属于可选交付出口，不属于系统启动与本地执行的前提条件。

V1 运行环境必须满足以下约束：
- 每个 `Project.root_path` 必须对应一个可被后端直接访问的本地仓库路径。
- `Workspace & Tool Service` 必须在隔离工作区中完成文件读取、代码修改、命令执行、diff 生成与测试执行。
- 每个 `PipelineRun` 都必须使用独立隔离工作区。
- 新建 `PipelineRun` 时，工作区必须从干净基线创建，不得自动继承前一个 run 未交付的工作区改动。
- 只有已经通过明确交付路径落入仓库基线的结果，才允许成为后续 run 的输入基线；未交付的本地工作区改动不得跨 run 泄漏。
- `SCM & Delivery Adapter` 必须统一封装本地 Git 与远端托管平台差异，不向前端和编排层暴露具体命令细节。
- 当系统未配置远端托管平台时，仍必须支持 `demo_delivery` 路径下的完整本地闭环。
- 当系统配置了可用的远端托管平台与交付通道时，必须支持 `git_auto_delivery` 路径下的真实交付流程。

未来如引入远程 Runner、自定义沙箱或分布式执行能力，必须保持以下约束不变：
- 前端交互语义不变。
- 核心 `Tool` 协议不变。
- `Project`、`Session`、`PipelineRun`、`ChangeSet`、`DeliveryRecord` 等核心领域对象语义不变。

## 5. 核心领域对象

### 5.1 项目与会话对象

1. `Project`
表示一个被加载到系统中的本地项目上下文，至少包含：
- `project_id`
- `name`
- `root_path`
- `default_delivery_channel_id`
- `created_at`
- `updated_at`

`Project` 必须满足以下初始化规则：
- 系统首次启动时必须自动登记一个默认项目，绑定平台仓库自身路径
- 在用户未手动加载其他项目之前，`GET /api/projects` 也必须返回该默认项目
- 每个 `Project` 在 V1 必须能够解析一个默认 `DeliveryChannel`；未配置远端交付条件时，默认回落到 `demo_delivery`
- 每个 `Project` 在 V1 只维护一个项目级生效中的默认 `DeliveryChannel`
- `DeliveryChannel` 的编辑与校验属于项目级配置，不属于 `Session` 或模板编辑范围
- 当前活动 run 在进入 `Delivery Integration` 前必须能够从 `Project.default_delivery_channel_id` 解析当前有效交付配置，并在最终人工审批通过后固化为运行快照
- 一旦当前 run 的 `delivery_channel_snapshot_ref` 已固化，后续项目级交付配置修改不得影响该 run 或历史 run
- 前端统一设置弹窗中的 `通用配置` 页面必须以当前 `Project` 为作用对象消费项目级交付配置接口

2. `Session`
表示项目下的一次需求会话，至少包含：
- `session_id`
- `project_id`
- `title`
- `status`
- `selected_template_id`
- `current_run_id`
- `latest_stage_type`
- `created_at`
- `updated_at`

`Session.status` 必须至少支持：
- `draft`
- `running`
- `paused`
- `waiting_clarification`
- `waiting_approval`
- `completed`
- `failed`
- `terminated`

其中：
- `draft` 只在尚未创建 `PipelineRun` 时出现
- 一旦 `current_run_id` 已存在，`Session.status` 必须作为当前运行状态的会话级摘要，不得脱离 `PipelineRun.status` 独立流转
- `PipelineRun.pending` 与 `PipelineRun.running` 在会话级统一投影为 `Session.status = running`
- `PipelineRun.paused` 必须投影为 `Session.status = paused`
- `PipelineRun.waiting_clarification` 必须投影为 `Session.status = waiting_clarification`
- `PipelineRun.waiting_approval` 必须投影为 `Session.status = waiting_approval`
- `PipelineRun.completed`、`PipelineRun.failed`、`PipelineRun.terminated` 必须投影为同名 `Session.status`

`Session` 必须满足以下模板选择规则：
- 新建会话时必须关联一个当前选中的 `PipelineTemplate`
- 当会话仍处于 `draft` 且尚未创建 `PipelineRun` 时，允许更新 `selected_template_id`
- 首次启动运行后，实际执行必须以 `PipelineRun.template_snapshot_ref` 为准
- 后续模板修改不得回写影响已经启动的 `PipelineRun`
- 功能一 V1 中，一个 `Session` 只承载一条从需求输入到交付结果的主链路
- 同一 `Session` 可因重跑、重新尝试或运维重启产生多个 `PipelineRun`
- 暂停后的恢复属于当前 `PipelineRun` 的继续执行，不创建新的 run
- 同一 `Session` 下的多个 `PipelineRun` 只表示同一需求链路的不同执行尝试，不表示新的独立需求
- 新的 `PipelineRun` 只允许在前一个活动 run 处于 `failed` 或 `terminated` 后创建；`completed` 表示该会话链路已经完成，不再在同一会话中开启新的 run；同一 `Session` 在同一时刻不允许并存多个活动 run
- 若用户要发起新的独立需求，必须创建新的 `Session`，不得在已有运行历史的会话中再次提交 `new_requirement` 以开启第二条链路

`Session.latest_stage_type` 与所有下游查询投影中的阶段类型字段必须统一使用本文定义的 `stage_type` 枚举值。

当 `Session.status = draft` 且 `current_run_id = null` 时，`Session.latest_stage_type` 必须为 `null`。

### 5.2 Pipeline 与阶段对象

3. `PipelineTemplate`
定义一条可复用的流程模板，包含固定阶段骨架、必需角色槽位绑定、自动回归策略与运行前可编辑配置。至少包含：
- `template_id`
- `name`
- `description`
- `template_source`
- `base_template_id`
- `fixed_stage_sequence`
- `stage_role_bindings`
- `auto_regression_enabled`
- `max_auto_regression_retries`
- `created_at`
- `updated_at`

`PipelineTemplate` 必须满足以下规则：
- 功能一 V1 对外管理语义中的 `Pipeline` 资源由 `PipelineTemplate` 承载；`PipelineRun` 是从模板快照派生的运行实例，不作为可编辑模板资源参与 CRUD
- `template_source` 在 V1 只允许：`system_template`、`user_template`
- `fixed_stage_sequence` 在 V1 固定为：`requirement_analysis -> solution_design -> code_generation -> test_generation_execution -> code_review -> delivery_integration`
- V1 固定存在两个不可关闭的审批检查点：
  - `solution_design_approval`：位于 `solution_design` 完成之后
  - `code_review_approval`：位于 `code_review` 完成之后
- 用户不可通过模板删除、禁用或重排核心业务阶段
- 用户不可通过模板关闭上述两个固定审批检查点
- `system_template` 允许被选择和另存，但不允许被直接覆盖
- `user_template` 允许被覆盖更新、另存为新模板和删除
- `PipelineTemplate` 的完整定义服务于后端校验、运行编排与模板持久化，不等同于前端模板配置 UI 的展示载荷
- 系统启动时必须至少预置以下三个 `system_template`：
  - `Bug 修复流程`
  - `新功能开发流程`
  - `重构流程`
- 新建会话在未显式指定模板时，默认绑定 `新功能开发流程`
- 三个预置 `system_template` 必须共享同一固定阶段骨架
- 三个预置 `system_template` 的差异只允许体现在：
  - 必需角色槽位默认绑定的 `AgentRole`
  - 各 `AgentRole` 的默认 `system_prompt`
  - 各 `AgentRole` 绑定的默认 `Provider`
  - 自动回归默认策略

三个预置 `system_template` 的默认适用语义如下：
- `Bug 修复流程`：用于已有缺陷、失败测试、报错修复
- `新功能开发流程`：用于新增业务能力、接口或页面功能
- `重构流程`：用于不改变外部行为前提下的结构整理与可维护性提升

4. `AgentRole`
表示绑定到模板必需角色槽位上的 Agent 角色定义，至少包含：
- `role_id`
- `role_name`
- `system_prompt`
- `provider_id`
- `created_by`
- `created_at`
- `updated_at`

`AgentRole` 必须满足以下规则：
- `AgentRole` 在 V1 只作为模板阶段配置的预设来源，不直接充当跨模板共享的运行时真源
- `provider_id` 绑定发生在 `AgentRole` 上，而不是直接绑定在阶段上
- V1 用户可编辑字段只包括：`system_prompt`、`provider_id`
- `role_name` 在 V1 只作为角色定义与前端展示标签返回，不作为用户可编辑字段
- 模板保存时，必须把各阶段槽位最终生效的角色绑定、`system_prompt` 与 `provider_id` 固化到模板自身配置中；run 启动后再固化到 `template_snapshot_ref`
- 输入契约、输出契约、结构化产物要求与工具权限边界仍由平台固定，不向用户开放编辑

5. `LLMProvider`
表示一个可被 `AgentRole` 绑定的模型提供商配置，至少包含：
- `provider_id`
- `display_name`
- `provider_source`
- `protocol_type`
- `base_url`
- `api_key_ref`
- `default_model_id`
- `supported_model_ids`
- `created_at`
- `updated_at`

`LLMProvider` 必须满足以下规则：
- `provider_source` 在 V1 至少支持：`builtin`、`custom`
- `protocol_type` 在 V1 至少支持：`volcengine_native`、`openai_completions_compatible`
- `display_name` 是前端展示和模板配置时使用的 Provider 名称
- 协议类型是接入实现细节，不作为产品层 Provider 名称直接对外呈现
- V1 默认内置两个 `builtin` Provider：
  - `火山引擎`
  - `DeepSeek`
- V1 允许用户新增 `custom` Provider
- `custom` Provider 在 V1 统一使用 `openai_completions_compatible` 协议接入
- `OpenAI Completions compatible` 是自定义 Provider 的接入协议，不是独立 Provider 名称

6. `PipelineRun`
表示某个会话的一次具体运行，至少包含：
- `run_id`
- `session_id`
- `template_id`
- `template_snapshot_ref`
- `delivery_channel_snapshot_ref`
- `status`
- `current_stage_run_id`
- `attempt_index`
- `started_at`
- `ended_at`

`PipelineRun` 必须满足以下运行快照规则：
- 每次运行开始前都必须固化一份模板快照
- 交付通道快照不在 run 启动时固化，而是在最终人工审批通过后、进入 `Delivery Integration` 前固化
- 运行期间实际读取的角色绑定、Provider 绑定和自动回归配置必须来自模板快照
- `Delivery Integration` 阶段实际读取的 `delivery_mode`、仓库标识、默认分支与代码评审请求类型必须来自 `delivery_channel_snapshot_ref`
- 模板快照与交付通道快照一旦绑定到某次运行，不得再被运行外部修改

`PipelineRun.status` 必须至少支持：
- `pending`
- `running`
- `paused`
- `waiting_clarification`
- `waiting_approval`
- `completed`
- `failed`
- `terminated`

7. `StageDefinition`
定义某个阶段的标准契约，包含：
- `stage_type`
- `order_index`
- `input_contract`
- `output_contract`
- `allowed_retry_policy`
- `allowed_rollback_targets`

`stage_type` 在功能一 V1 中必须统一使用以下机器可读枚举：
- `requirement_analysis`
- `solution_design`
- `code_generation`
- `test_generation_execution`
- `code_review`
- `delivery_integration`
- `rollback_or_retry`

文档中的 `Requirement Analysis`、`Solution Design`、`Code Generation` 等名称仅作为展示标签，不作为 API、事件和持久化层取值。

审批检查点属于编排控制语义，不创建独立 `StageDefinition`，也不占用 `stage_type` 枚举值。

8. `StageRun`
表示某次运行中的具体阶段实例，至少包含：
- `stage_run_id`
- `run_id`
- `stage_type`
- `status`
- `attempt_index`
- `started_at`
- `ended_at`
- `input_ref`
- `output_ref`

`StageRun.status` 必须至少支持：
- `pending`
- `running`
- `waiting_clarification`
- `waiting_approval`
- `completed`
- `failed`
- `rolled_back`

当运行进入审批等待时，保持触发审批的源阶段 `StageRun` 处于 `waiting_approval`，审批过程通过 `approval_request` 与 `approval_result` 顶层条目表达。

### 5.3 产物与审批对象

9. `StageArtifact`
表示阶段级结构化产物，是阶段流转、审批展示与历史回看的基础容器。

10. `ClarificationRecord`
表示 `Requirement Analysis` 阶段内部的澄清问答记录，至少包含：
- `clarification_id`
- `stage_run_id`
- `question`
- `answer`
- `impact_scope`
- `resolution_summary`
- `status`
- `asked_at`
- `answered_at`
- `resolved_at`

`ClarificationRecord.status` 必须至少支持：
- `asked`
- `answered`
- `resolved`

其中：
- `impact_scope` 用于标识本轮澄清影响的需求点、约束项或验收标准
- `resolution_summary` 用于沉淀本轮澄清形成的规范化结论，并回写到 `Requirement Analysis` 阶段产物

11. `ApprovalRequest`
表示正式人工审批对象，至少包含：
- `approval_id`
- `run_id`
- `approval_type`
- `source_stage_run_id`
- `status`
- `approval_object_excerpt`
- `payload_ref`
- `rollback_target_stage_type`
- `requested_at`
- `responded_at`

`ApprovalRequest.approval_type` 在功能一 V1 中只允许：
- `solution_design_approval`
- `code_review_approval`

`ApprovalRequest.status` 必须至少支持：
- `pending`
- `approved`
- `rejected`

`ApprovalRequest.rollback_target_stage_type` 必须使用本文定义的 `stage_type` 枚举值。
并满足以下规则：
- 当 `approval_type = solution_design_approval` 时，`rollback_target_stage_type` 固定为 `solution_design`
- 当 `approval_type = code_review_approval` 时，`rollback_target_stage_type` 固定为 `code_generation`

12. `ApprovalDecision`
表示审批结果，至少包含：
- `approval_id`
- `decision`
- `reason`
- `operator_id`
- `created_at`

### 5.4 代码与交付对象

13. `ChangeSet`
表示一次代码变更集合，记录受影响文件、补丁、说明文本、变更统计和来源阶段。

14. `ChangeRisk`
表示变更风险分级与风险说明。

15. `DeliveryChannel`
表示目标托管平台、仓库标识、默认分支、代码评审请求类型及交付策略，至少包含：
- `channel_id`
- `delivery_mode`
- `provider_type`
- `host_base_url`
- `repository_ref`
- `default_branch`
- `review_request_type`
- `credential_ref`

`DeliveryChannel.delivery_mode` 在功能一 V1 中至少支持：
- `demo_delivery`
- `git_auto_delivery`

`DeliveryChannel.delivery_mode` 必须满足以下规则：
- `demo_delivery` 是功能一 V1 的演示交付模式。
- `git_auto_delivery` 是功能一 V1 的正式交付模式，不属于仅为后续版本预留的增强能力。
- 当交付通道可用时，后端必须能够基于 `git_auto_delivery` 执行真实分支准备、提交创建、分支推送与代码评审请求创建。
- `demo_delivery` 只要求最小交付语义成立；`provider_type`、`repository_ref`、`default_branch`、`review_request_type` 与 `credential_ref` 可以为空。
- `git_auto_delivery` 必须要求 `provider_type`、`repository_ref`、`default_branch`、`review_request_type` 与 `credential_ref` 全部有效。
- `host_base_url` 用于兼容不同托管平台或私有部署地址；当供应商接入不需要自定义地址时可以为空。
- `DeliveryChannel` 的解析来源属于项目上下文或运行上下文，不属于前端模板编辑载荷的一部分。
- 项目级默认 `DeliveryChannel` 是后续新启动 run 以及尚未固化交付快照的当前活动 run 的交付来源；最终交付快照只在进入 `Delivery Integration` 前复制为只读快照。

16. `DeliveryRecord`
表示最终交付结果，记录：
- 交付说明
- 变更结果
- 测试结论
- 评审结论
- 交付模式
- 分支信息
- 提交信息或提交说明展示
- MR/PR 信息

### 5.5 上下文与扩展对象

17. `ContextReference`
表示阶段执行时引用的上下文来源。功能一 V1 至少支持：
- `requirement_text`
- `repo_path`
- `directory_path`
- `file_path`
- `artifact_ref`
- `approval_feedback`

18. `PreviewTarget`
表示工作区对应的预览目标对象。V1 只定义对象与查询接口，不实现预览启动与热更新。

19. `ToolCallRecord`
表示单次工具调用记录，用于审查、回放与前端执行条目展示。

20. `DomainEvent`
表示驱动状态流转与投影视图更新的领域事件。

## 6. 阶段编排与生命周期

### 6.1 正式阶段序列

功能一 V1 的正式阶段序列如下：

1. `requirement_analysis`
2. `solution_design`
3. `code_generation`
4. `test_generation_execution`
5. `code_review`
6. `delivery_integration`

其中：
- `Solution Validation Agent` 是 `solution_design` 阶段内部的第二个 Agent，不形成独立 `StageRun`
- `solution_design_approval` 与 `code_review_approval` 是固定审批检查点，位于对应源阶段完成之后，不属于正式业务阶段，不创建独立 `StageDefinition`
- 当系统进入审批等待时，源 `StageRun.status` 必须置为 `waiting_approval`
- `rollback_or_retry` 是运行时按需插入的控制型阶段，必须创建独立 `StageRun`、独立 `execution_node` 与独立 Inspector 载荷，但不替代正式业务阶段序列

### 6.2 Requirement Analysis 生命周期

`Requirement Analysis` 必须按以下规则运行：
- 接收用户原始需求输入
- 产出结构化需求、验收标准、约束与待确认事项
- 当信息不足时，创建 `ClarificationRecord` 并将 `StageRun.status` 置为 `waiting_clarification`
- 前端通过会话消息接口提交补充信息
- 补充信息回写到同一个 `StageRun`
- 本阶段恢复执行后继续分析，直到产出完整结果

本阶段禁止创建 `ApprovalRequest`。

### 6.3 Solution Design 生命周期

`Solution Design` 必须按以下规则运行：
- 本阶段内部必须采用 `Solution Design Agent -> Solution Validation Agent` 的串行子步骤
- `Solution Design Agent` 先产出技术方案、影响范围与关键设计决策
- `Solution Validation Agent` 在同一个 `Solution Design` 阶段内对方案做独立校验
- 方案校验结果必须作为 `Solution Design` 阶段产物的一部分持久化
- 校验失败时，不得创建新的独立 `Solution Validation` 阶段；系统必须依据校验结论重新进入 `Solution Design` 阶段的设计子步骤
- 校验通过后，创建 `ApprovalRequest(type=solution_design_approval)`
- 创建 `ApprovalRequest(type=solution_design_approval)` 后，当前 `solution_design` 的 `StageRun.status` 必须置为 `waiting_approval`
- 审批通过后，进入 `Code Generation`
- 审批拒绝后，记录拒绝理由并回退到 `Solution Design`

### 6.4 Code Generation 到 Code Review 生命周期

`Code Generation`、`Test Generation & Execution`、`Code Review` 必须保持串行执行：
- 先执行代码生成
- 再执行测试生成与执行
- 最后执行代码评审

`Code Review` 完成后：
- 若需要自动回归，则根据问题根因回退到 `Code Generation` 或 `Solution Design`
- 自动回归循环结束且得到稳定评审产物后，创建 `ApprovalRequest(type=code_review_approval)`
- 创建 `ApprovalRequest(type=code_review_approval)` 后，当前 `code_review` 的 `StageRun.status` 必须置为 `waiting_approval`
- 当当前项目 `delivery_mode = git_auto_delivery` 时，审批通过前必须校验交付配置与凭据是否达到 `ready`；通过后先固化 `delivery_channel_snapshot_ref`，再进入 `Delivery Integration`
- 当当前项目 `delivery_mode = demo_delivery` 时，不执行上述交付配置阻塞校验；审批通过后直接进入 `Delivery Integration`
- 审批拒绝后，记录拒绝理由并回退到 `Code Generation`

### 6.5 Delivery Integration 生命周期

`Delivery Integration` 必须完成以下工作：
- 汇总最终变更结果、测试结论与评审结论
- 读取当前 run 已固化的交付通道快照信息
- 准备分支信息与提交说明意图
- 当 `delivery_mode = demo_delivery` 时，仅生成用于演示的交付说明、分支信息展示和 `commit_message_preview`，不得执行真实提交、推送或 MR/PR 创建
- 当 `delivery_mode = git_auto_delivery` 时，必须执行真实交付流程：`prepare_branch -> create_commit -> push_branch -> create_code_review_request`
- 按交付策略生成 MR/PR 信息或交付描述
- 产出 `DeliveryRecord`

本阶段不创建新的人工审批检查点。

### 6.6 流程引擎实施约束

Pipeline 引擎必须满足以下实施约束：

1. `可配置阶段结构`
- 支持 `StageDefinition` 定义
- 支持顺序与依赖关系
- 平台内部保留阶段类型扩展与检查点扩展能力
- V1 面向用户开放的模板编辑不支持阶段增删、重排或审批检查点开关
- 支持按模板定义是否允许自动回归、最大重试次数和回退策略
- 平台必须为 `PipelineTemplate.max_auto_regression_retries` 设定统一上限，模板只能在该上限内取值

2. `阶段绑定 Agent`
- 每个阶段必须暴露固定的必需角色槽位，并由模板绑定一个或多个 `AgentRole`
- `Requirement Analysis` 使用单 Agent
- `Solution Design` 使用双 Agent 串行结构，其中第二个 Agent 负责阶段内方案校验
- `Code Generation` 使用单 Agent
- `Test Generation & Execution` 使用单 Agent
- `Code Review` 使用单 Agent
- `Delivery Integration` 使用单 Agent

3. `模板用户编辑边界`
- 用户可编辑模板只开放以下字段：
  - 必需角色槽位到 `AgentRole` 的绑定关系
  - `AgentRole.system_prompt`
  - `AgentRole.provider_id`
  - `auto_regression_enabled`
  - `max_auto_regression_retries`
- 上述字段属于运行前配置，直接服务于后续阶段 Agent 的实际执行行为，不是只用于前端展示的说明性字段
- 模板编辑修改的是当前模板各阶段槽位最终生效配置，不是回写一个会同时影响其他模板的共享运行对象
- `AgentRole.role_name` 在模板编辑中只作为只读展示标签返回，不提供修改入口
- 用户不可编辑核心阶段顺序、审批检查点存在性、阶段输入输出契约、结构化产物要求和工具权限边界
- 保存模板时，必须校验所有必需角色槽位都已完成 `AgentRole` 与 `Provider` 绑定
- 保存模板时，必须校验 `max_auto_regression_retries` 落在平台允许范围内
- 后端面向前端输出的模板编辑载荷只返回允许字段，不返回固定阶段骨架、审批检查点、阶段输入输出契约、结构化产物要求和工具权限边界
- 运行启动后，这些配置必须固化到 `PipelineRun.template_snapshot_ref`，后续查询只读返回，不可回写正在执行或已结束的 run

4. `阶段间数据流转`
- 上一阶段输出必须以 `StageArtifact` 形式持久化
- 后续阶段必须通过契约化引用读取产物
- 不允许仅依赖内存态临时传参
- `acceptance_criteria`、澄清结论、设计决策、审批反馈、评审意见等关键上下文必须可跨阶段传递

5. `生命周期管理`
- 支持启动、暂停、恢复、终止
- 支持阶段失败后终止或重试
- 支持审批拒绝后回退到指定阶段重跑
- 支持代码评审失败后进入自动回归循环
- 自动回归结束后，进入代码评审人工审批或失败状态

6. `运行可观测`
- 可查询当前运行状态
- 可查询各阶段状态
- 可查询关键事件时间线
- 可查询每阶段产物与错误信息
- 可查询每阶段是否通过、失败、等待澄清或等待审批
- 可查询澄清记录是否已得到回复与收敛

## 7. 澄清、审批与回退语义

### 7.1 需求澄清语义

需求澄清必须满足以下规则：
- 需求澄清不是审批
- 需求澄清不提供 `Approve / Reject`
- 需求澄清通过统一会话消息接口提交
- 需求澄清必须保留问题、回答、影响范围与最终结论
- 同一 `Requirement Analysis` 结点允许多轮澄清
- `waiting_clarification` 只表示当前 run 正在等待用户补充信息，不表示 Agent 已停止在该结点内继续分析的整个会话阶段
- 当用户提交 `clarification_reply` 后，当前 run 必须恢复为 `running` 并继续同一个 `Requirement Analysis` 结点
- 用户回复后的 Agent 连续分析、继续追问或继续输出，仍属于同一澄清链路；若信息仍不足，可再次切回 `waiting_clarification`

### 7.2 人工审批语义

人工审批必须满足以下规则：
- 仅存在 `solution_design_approval` 与 `code_review_approval`
- 审批对象必须引用稳定产物快照，而不是运行中间态
- `Approve` 可以直接提交
- `Reject` 必须携带理由
- 拒绝理由必须进入后续上下文，供重新生成与审查使用
- 审批结果必须进入事件流与 Narrative Feed 投影
- 审批等待期间，会话级 `current_stage_type` 与源阶段 `stage_type` 保持不变；是否待审批由 `Session.status = waiting_approval`、`pending_action_type = approval` 与 `ApprovalRequest.status = pending` 共同表达
- `solution_design_approval` 的 `Reject` 固定回到 `Solution Design`
- `code_review_approval` 的 `Reject` 固定回到 `Code Generation`
- 当 `approval_type = code_review_approval` 且当前项目 `delivery_mode = git_auto_delivery` 时，`Approve` 前必须校验交付配置与凭据是否达到 `ready`
- 当上述校验不通过时，系统不得进入 `Delivery Integration`，必须继续保持该审批对象待处理，并向前端返回明确的交付配置阻塞信息
- 当当前项目 `delivery_mode = demo_delivery` 时，不因交付配置或凭据缺失额外阻塞 `code_review_approval`

### 7.3 自动回归与回退语义

自动回归必须满足以下规则：
- 默认回退目标为 `Code Generation`
- 当根因属于方案错误、影响范围遗漏或接口路径错误时，允许回退到 `Solution Design`
- 自动回归最大次数由模板配置控制，且必须落在平台定义的统一上限内
- 自动回归结束后，才能进入代码评审人工审批
- 自动回归超限后，必须输出明确的失败或高风险状态，不得静默推进

### 7.4 Agent 编排与执行约束

Agent 编排必须满足以下规则：

1. `阶段角色明确`
每个阶段都必须配置明确的 `AgentRole`，至少包含：
- 角色名称
- System Prompt
- 输入契约
- 输出契约
- 失败处理策略

功能一 V1 的核心 Agent 固定为：
- `Requirement Analysis Agent`
- `Solution Design Agent`
- `Solution Validation Agent`
- `Code Generation Agent`
- `Test Generation & Execution Agent`
- `Code Review Agent`
- `Delivery Integration Agent`

每个阶段的必需角色槽位固定如下：
- `Requirement Analysis`：`requirement_analysis_role`
- `Solution Design`：`solution_design_role`、`solution_validation_role`
- `Code Generation`：`code_generation_role`
- `Test Generation & Execution`：`test_generation_execution_role`
- `Code Review`：`code_review_role`
- `Delivery Integration`：`delivery_integration_role`

2. `上下文感知能力`
Agent 至少支持以下上下文输入方式：
- 目标仓库路径
- 指定目录路径
- 指定文件路径
- 前序阶段产物引用
- 结构化验收标准引用
- 需求澄清结论引用
- 设计审批反馈引用
- 历史评审意见引用

3. `工具调用模型`
Agent 不直接绑定零散函数签名，而是通过统一 `Tool` 协议调用能力。

`Workspace Tools`
- `read_file`
- `write_file`
- `edit_file`
- `list_files`
- `search`
- `shell`

`SCM / Delivery Tools`
- `prepare_branch`
- `create_commit`
- `push_branch`
- `create_code_review_request`
- `read_delivery_channel`

工具系统必须满足以下要求：
- 每个工具都通过统一接口暴露元数据、输入参数、执行结果和错误信息
- `Agent Runtime` 只依赖统一 Tool 协议，不依赖具体实现细节
- 工作区工具支持本地执行，并为未来远程或沙箱执行保留一致接口
- 交付工具负责封装本地 Git 与远端托管平台差异，规格层不直接暴露具体命令名
- 工具调用结果必须记录到运行上下文和事件流中

4. `模型供应商可切换`
- V1 默认内置两个 `builtin` Provider：
  - `火山引擎`
  - `DeepSeek`
- V1 允许用户新增 `custom` Provider
- `custom` Provider 的接入协议统一采用 `OpenAI Completions compatible`
- `OpenAI Completions compatible` 是接入协议，不作为独立 Provider 名称对外呈现
- Provider 绑定单位是 `AgentRole`
- 运行时可切换的含义是：不同 `AgentRole` 可以在同一模板中绑定不同 Provider，或在运行开始前通过模板编辑修改 `AgentRole` 到 Provider 的绑定关系
- V1 不以阶段为单位直接绑定 Provider
- 自动故障切换到备用 Provider 不属于 V1 的必需能力
- Provider 差异不得泄漏到上层流程逻辑

5. `输出结构化`
- Agent 输出必须转换为结构化领域对象
- 必须执行格式校验与错误处理
- 非法输出不得直接推进下一阶段

6. `执行与编排解耦`
- `Agent Runtime` 只负责执行
- `Pipeline Orchestrator` 负责决定何时执行、何时暂停、何时回退

7. `多 Agent 使用原则`
- `Solution Design` 阶段必须采用 `Solution Design Agent -> Solution Validation Agent` 串行结构，且 `Solution Validation Agent` 只作为该阶段内部第二个 Agent，不形成独立 `StageRun`
- `Code Generation` 与 `Test Generation & Execution` 在 V1 必须保持阶段串行执行，不采用并行多 Agent
- 其余阶段使用单 Agent

### 7.5 核心 Agent 契约

各核心 Agent 必须具备明确的目标、输入、输出、可用工具和失败处理规则。

`Requirement Analysis Agent`
- 目标：将自然语言需求转换为结构化需求、验收标准、约束与澄清问题
- 输入：原始需求文本、历史会话上下文、必要仓库上下文
- 输出：`structured_requirement`、`acceptance_criteria`、`clarification_records`
- 可用工具：`list_files`、`search`、`read_file`
- 失败处理：输出不完整或无法形成结构化结果时停留在本阶段重试；存在信息缺口时创建澄清记录并等待用户回复

当该 Agent 由新的 `PipelineRun` 重新启动时：
- `历史会话上下文` 只允许引用已经持久化的结构化产物与结论
- 至少包括：原始需求文本、澄清结论、设计审批反馈、历史评审意见与其他已持久化关键产物引用
- 不得读取前一个 run 未交付的临时工作区改动作为输入

`Solution Design Agent`
- 目标：输出技术方案、影响范围、关键设计决策与文件变更范围
- 输入：`structured_requirement`、`acceptance_criteria`、澄清结论、仓库上下文
- 输出：`solution_design`、`design_decisions`、`impacted_files`
- 可用工具：`list_files`、`search`、`read_file`
- 失败处理：无法定位影响范围、无法形成方案或缺少关键设计决策时回到本阶段重试

`Solution Validation Agent`
- 目标：作为 `Solution Design` 阶段内部第二个 Agent，独立校验技术方案是否偏离需求、遗漏影响范围、缺少测试策略或引入过高风险
- 输入：`solution_design`、`design_decisions`、`acceptance_criteria`
- 输出：`solution_validation_report`
- 可用工具：`read_file`、`search`
- 失败处理：校验不通过时回到同一个 `Solution Design` 阶段内的设计子步骤，不创建独立阶段

`Code Generation Agent`
- 目标：根据已通过校验且经审批通过的方案生成或修改代码，并输出变更集合
- 输入：`solution_design`、`design_decisions`、设计审批反馈、仓库上下文
- 输出：`code_changeset`、`change_description`
- 可用工具：`read_file`、`write_file`、`edit_file`、`list_files`、`search`、`shell`
- 失败处理：生成结果不满足结构约束、修改失败或无法形成有效变更时回到本阶段重试

`Test Generation & Execution Agent`
- 目标：生成测试、执行测试，并输出测试结果与测试缺口分析
- 输入：`code_changeset`、`acceptance_criteria`、相关仓库上下文
- 输出：`test_bundle`、`test_execution_result`、`test_gap_report`
- 可用工具：`read_file`、`write_file`、`edit_file`、`list_files`、`search`、`shell`
- 失败处理：测试生成失败或执行失败时回到 `Code Generation`，并携带失败信息

`Code Review Agent`
- 目标：独立审查代码变更、方案一致性、测试充分性与变更风险
- 输入：`code_changeset`、`solution_design`、`design_decisions`、`test_execution_result`、`test_gap_report`
- 输出：`review_report`、`change_risk`、`rollback_decision`
- 可用工具：`read_file`、`list_files`、`search`
- 失败处理：发现可修复问题时触发自动回归；发现根因属于方案错误时回退到 `Solution Design`

`Delivery Integration Agent`
- 目标：整理交付物、交付说明、分支信息与 MR/PR 信息
- 输入：已通过审批的 `code_changeset`、`review_report`、`test_execution_result`、`delivery_channel`
- 输出：`delivery_record`、`delivery_description`、`branch_info`、`commit_info`、`merge_request_info`
- 可用工具：`read_file`、`list_files`、`search`、`read_delivery_channel`、`prepare_branch`、`create_commit`、`push_branch`、`create_code_review_request`
- 失败处理：交付物不完整、交付通道信息缺失或无法生成交付记录时停留在本阶段并返回错误信息

## 8. 前端查询投影契约

后端必须为 `frontend-workspace-global-design-v1.md` 提供稳定的查询投影视图。

### 8.1 左栏投影

后端必须提供以下投影：

1. `ProjectSidebarProjection`
- `project_id`
- `name`
- `root_path_excerpt`
- `session_count`
- `last_activity_at`
- `current_delivery_mode`
- `delivery_channel_status`

其中 `delivery_channel_status` 至少支持：
- `unconfigured`
- `invalid`
- `ready`

2. `ProjectDeliveryChannelProjection`
- `project_id`
- `delivery_mode`
- `provider_type`
- `host_base_url`
- `repository_ref`
- `default_branch`
- `review_request_type`
- `credential_ref`
- `credential_status`
- `delivery_channel_status`
- `last_validated_at`

`ProjectDeliveryChannelProjection` 用于项目级交付设置查看与编辑。
并满足以下规则：
- 当 `delivery_mode = demo_delivery` 时，不适用的 Git 交付字段不返回
- 当 `delivery_mode = git_auto_delivery` 时，必须返回前端完成校验与保存所需的全部项目级交付字段
- `credential_ref` 表示当前项目默认交付配置所绑定的凭据引用，可作为前端编辑和保存输入，但不得回传任何密钥明文
- `credential_status` 只用于表达当前凭据绑定的可用性或校验状态，不承担可编辑字段语义
- `delivery_channel_status` 至少支持：`unconfigured`、`invalid`、`ready`
- 后端必须仅根据 `credential_ref` 解析真实凭据；真实密钥不得进入 `ProjectDeliveryChannelProjection`、工作台投影或事件流
- 投影只表达当前项目的默认交付配置，不表达任何已启动 run 的快照内容
- 该投影服务于前端统一设置弹窗中的 `通用配置` 页面，而不是模板编辑区或左栏局部编辑入口

3. `SessionListItemProjection`
- `session_id`
- `title`
- `status`
- `updated_at`
- `current_stage_type`
- `pending_action_type`

其中 `pending_action_type` 至少支持：
- `none`
- `clarification`
- `approval`

### 8.2 中栏 Narrative Feed 投影

后端必须提供 `SessionWorkspaceProjection`，至少包含：
- `session_id`
- `project_id`
- `session_status`
- `current_run_id`
- `current_stage_type`
- `selected_template_id`
- `selected_template_summary`
- `available_runs`
- `narrative_entries`
- `composer_mode`

`composer_mode` 至少支持：
- `new_requirement`
- `clarification_reply`
- `readonly`

`composer_mode` 必须满足以下状态映射规则：
- 当 `Session.status = draft` 且尚未创建首个 `PipelineRun` 时，返回 `new_requirement`
- 当当前活动 run 处于 `waiting_clarification` 且当前阶段为 `requirement_analysis` 时，返回 `clarification_reply`
- 当当前活动 run 处于 `running`、`waiting_approval`、`paused`、`completed`、`failed` 或 `terminated` 时，返回 `readonly`
- `composer_mode` 只约束输入框语义，不负责表达 `发送`、`暂停`、`恢复` 等生命周期按钮的视觉状态
- 当 `current_stage_type = requirement_analysis` 且 `Session.status = running` 时，前端应将其理解为澄清对话中的 Agent 连续分析 / 连续回复回合，而不是等待用户输入的回合

`selected_template_summary` 表示当前会话选中模板或当前运行所用模板的只读摘要，不承担模板编辑载荷职责。至少包含：
- `template_id`
- `name`
- `template_source`
- `template_use_case`
- `auto_regression_enabled`
- `max_auto_regression_retries`
- `role_summary`

当 `session_status = draft` 且尚未开始运行时：
- 前端必须能够基于 `selected_template_id` 通过独立模板编辑查询拉取 `TemplateEditorProjection`
- 工作台必须能够区分当前模板是否为系统模板或用户模板
- 工作台必须能够据此决定是否展示 `覆盖当前模板` 入口

当 `session_status != draft` 或 `PipelineRun` 已启动时：
- `SessionWorkspaceProjection` 只返回 `selected_template_summary`
- 工作台不得依赖 workspace 载荷渲染模板编辑区
- `selected_template_summary` 必须表示当前活动 run 绑定的模板快照摘要，而不是可继续编辑的共享配置

`SessionWorkspaceProjection` 必须满足以下 run 视图规则：
- `current_run_id` 表示该会话当前有效的运行，通常为最新 run 或当前活跃 run
- `narrative_entries` 必须返回该会话下按时间顺序组织的完整多 run 主流，而不是只返回单个 run 的条目集合
- `composer_mode`、当前审批状态与 `current_stage_type` 都必须基于 `current_run_id` 计算，而不是基于历史 run 焦点计算
- `available_runs` 用于支撑前端 `Run Switcher`，至少包含 `run_id`、`status`、`attempt_index`、`started_at`、`ended_at`
- 历史 run 只读语义通过 `narrative_entries` 中各条目所属的 run 标识和可操作标记表达，不通过把整个页面切换为只读实现
- `narrative_entries` 中不同 run 之间必须存在显式分界条目或等价结构，以支撑前端展示强分界的 run 分段

`SessionWorkspaceProjection.current_stage_type`、`SessionListItemProjection.current_stage_type`、`approval_result.next_stage_type` 与所有 `rollback_target_stage_type` 字段必须共用同一 `stage_type` 枚举；当会话处于审批等待时，这些字段保持为触发审批的源阶段类型。

当 `Session.status = draft` 且 `current_run_id = null` 时，`SessionWorkspaceProjection.current_stage_type` 与 `SessionListItemProjection.current_stage_type` 必须返回 `null`。

后端必须提供 `TemplateEditorProjection`，只用于启动前模板配置，至少包含：
- `template_id`
- `name`
- `template_source`
- `template_use_case`
- `editable_role_bindings`
- `editable_agent_roles`
- `available_providers`
- `auto_regression_enabled`
- `max_auto_regression_retries`
- `can_overwrite`
- `can_save_as`

`TemplateEditorProjection` 必须满足以下规则：
- 只返回功能一 V1 已开放的模板可编辑字段
- 不返回固定阶段骨架、审批检查点、阶段输入输出契约、结构化产物要求和工具权限边界
- 只在 `Session.status = draft` 且尚未创建 `PipelineRun` 的上下文中被前端消费
- `editable_role_bindings` 用于表达阶段必需角色槽位到具体 `AgentRole` 的可编辑绑定关系
- `editable_agent_roles` 只返回所选或可选 `AgentRole` 的只读 `role_name` 与可编辑 `system_prompt`、`provider_id`
- `editable_role_bindings` 与 `editable_agent_roles` 共同表达的是“当前模板的阶段生效配置编辑面”，而不是一个独立共享角色注册表的直接编辑面
- `available_providers` 必须至少包含两个内置 Provider：`火山引擎`、`DeepSeek`
- `available_providers` 可以包含用户新增的 `custom` Provider
- `available_providers` 对前端返回的是 Provider 展示名和必要标识，不返回把协议名当作 Provider 名称的展示结果
- 其返回值表达的是运行前配置，而不是只用于展示的元信息

`narrative_entries` 必须支持以下条目类型：
- `run_boundary`
- `user_message`
- `execution_node`
- `approval_request`
- `approval_result`
- `delivery_result`
- `system_status`

`narrative_entries` 采用前端规格要求的 `结点 + 条目` 两层模型：
- `run_boundary` 用于标记同一会话中不同 `PipelineRun` 的显式分界
- `execution_node` 是阶段级顶层结点
- 结点内部条目通过 `execution_node.items` 表达
- 不允许把结点内部条目直接摊平成无阶段归属的顶层瀑布流
- `user_message` 用于会话起始需求输入等独立顶层用户消息
- `Requirement Analysis` 阶段内的澄清问答通过 `execution_node.items` 表达
- `approval_request`、`approval_result`、`delivery_result` 作为顶层条目追加到主流中
- `system_status` 用于表达暂停、恢复、失败、终止等运行控制结果
- `completed` run 以 `delivery_result` 作为尾部收束条目，不追加完成态 `system_status`
- `failed` 与 `terminated` run 必须在各自 run 尾部追加顶层 `system_status` 终态条目
- 不同 `PipelineRun` 的条目必须在主流中保留原有时间顺序，但 run 与 run 之间必须插入显式分界条目

其中以下条目必须定义明确字段契约：

`approval_result`
- `approval_id`
- `approval_type`
- `decision`
- `reason`
- `source_stage_run_id`
- `next_stage_type`
- `next_action_text`
- `waiting_duration_ms`
- `response_duration_ms`
- `occurred_at`

规则如下：
- 当 `decision = reject` 时，`reason` 不得为空
- `next_stage_type` 必须能表达审批后进入的下一阶段或回退目标
- `next_action_text` 必须可直接用于前端 Narrative Feed 展示审批后链路如何继续推进
- `next_stage_type` 必须使用本文定义的 `stage_type` 枚举值
- `approval_result` 必须作为独立 Narrative Feed 条目追加到主流中

`delivery_result`
- `delivery_record_id`
- `delivery_excerpt`
- `delivery_status`
- `delivery_artifact_count`
- `changed_file_count`
- `occurred_at`
- `delivery_record_ref`

`system_status`
- `status_code`
- `title`
- `message`
- `run_status`
- `occurred_at`
- `is_terminal`
- `can_retry`
- `retry_action`

规则如下：
- `system_status` 只用于表达运行控制反馈或非交付型终态，不替代 `delivery_result`
- 当 `run_status = failed` 或 `run_status = terminated` 时，`is_terminal` 必须返回 `true`
- 当 `run_status = failed` 或 `run_status = terminated` 时，该条目必须位于所属 run 尾部
- `can_retry` 只允许在当前活动 run 已进入 `failed` 或 `terminated` 时返回 `true`
- 当 `can_retry = true` 时，`retry_action` 必须明确对应 `POST /api/sessions/{sessionId}/runs`
- 历史 run、`completed` run 和非终态 `system_status` 条目不得返回可执行的 `retry_action`

`run_boundary`
- `run_id`
- `attempt_index`
- `run_status`
- `trigger_type`
- `started_at`
- `ended_at`
- `is_current_run`
- `entry_type`

规则如下：
- 每个 `PipelineRun` 的首条运行内容之前都必须插入一个 `run_boundary`
- `trigger_type` 至少支持：`initial_run`、`retry_run`、`ops_restart`
- `run_boundary` 用于支撑前端 run 分界头部与页面内导航，不承担审批或输入操作

### 8.3 执行结点投影

`execution_node` 投影必须满足前端 Narrative Feed 与 Inspector 的共同需求，至少包含：
- `node_id`
- `stage_run_id`
- `stage_type`
- `status`
- `sequence_index`
- `attempt_index`
- `started_at`
- `ended_at`
- `is_expandable`
- `items`
- `metrics_preview`
- `inspector_ref`

`execution_node.stage_type` 在功能一 V1 至少支持：
- `requirement_analysis`
- `solution_design`
- `code_generation`
- `test_generation_execution`
- `code_review`
- `rollback_or_retry`
- `delivery_integration`

`execution_node.items` 至少支持以下内部条目类型：
- `clarification_question`
- `clarification_answer`
- `reasoning_item`
- `decision_item`
- `tool_call_item`
- `diff_preview_item`
- `stage_result_item`
- `rollback_item`

其中 `rollback_item` 只用于在触发回退的源阶段中记录“为何触发回退”的摘要信息。
完整的回退或重试过程必须通过独立的 `rollback_or_retry` 执行结点表达，不得与其重复承载同一批详细信息。

结点内部条目字段契约必须符合前端 `10.5` 的显示规则，并遵守以下原则：
- 中栏正文以原生内容为主，不另造摘要文本
- 内容过长时使用截断显示
- 截断信息必须通过显式字段表达，而不是依赖前端自行猜测

`clarification_question` / `clarification_answer` 至少包含：
- `item_id`
- `item_type`
- `content`
- `occurred_at`

`reasoning_item` 至少包含：
- `item_id`
- `item_type`
- `content`
- `is_truncated`
- `preview_line_count`
- `expandable`

`decision_item` 至少包含：
- `item_id`
- `item_type`
- `content`
- `rationale`
- `impact`
- `is_truncated`
- `expandable`

`tool_call_item` 至少包含：
- `item_id`
- `item_type`
- `tool_name`
- `target`
- `command_or_args`
- `output_excerpt`
- `is_truncated`
- `detail_ref`

`diff_preview_item` 至少包含：
- `item_id`
- `item_type`
- `changed_files`
- `diff_chunks`
- `is_truncated`
- `detail_ref`

`stage_result_item` 至少包含：
- `item_id`
- `item_type`
- `result_type`
- `content`
- `is_truncated`
- `attachments_ref`

`rollback_item` 至少包含：
- `item_id`
- `item_type`
- `reason`
- `target_stage_type`
- `next_action_text`

`metrics_preview` 只用于中栏显示少量指标，不替代完整指标集合；`inspector_ref` 用于拉取完整结构化详情。

### 8.4 Inspector 投影

后端必须提供两类详情载荷：
- `StageInspectorProjection`
  用于 `GET /api/stages/{stageRunId}/inspector`
- `DeliveryResultDetailProjection`
  用于 `GET /api/delivery-records/{deliveryRecordId}`

`StageInspectorProjection` 必须按阶段类型区分载荷，并至少包含：
- `title`
- `stage_type`
- `status`
- `structured_input`
- `structured_output`
- `reasoning_trace`
- `decision_trace`
- `activity_trace`
- `full_metrics`
- `attachments`

并且必须针对不同阶段补齐前端文档要求的完整信息：
- `requirement_analysis` 至少包含：
  - `structured_requirement`
  - `acceptance_criteria`
  - `constraints`
  - `assumptions`
  - `clarification_items`
  - `clarification_records`
  - `decision_trace`
  - `context_references`
- `solution_design` 至少包含：
  - `solution_design`
  - `impact_scope`
  - `design_decisions`
  - `key_files`
  - `risk_analysis`
  - `solution_validation_report`
  - `validation_conclusion`
  - `validation_checks`
  - `validation_issues`
  - `passed_checks`
  - `failed_checks`
  - `fix_direction`
  - `decision_trace`
- `code_generation` 至少包含：
  - `change_description`
  - `changed_files`
  - `diff_snippets`
  - `implementation_decisions`
  - `design_trace_links`
  - `activity_records`
- `test_generation_execution` 至少包含：
  - `test_targets`
  - `test_execution_details`
  - `failed_tests`
  - `test_gap_report`
  - `test_decision_trace`
- `code_review` 至少包含：
  - `review_conclusion`
  - `review_issues`
  - `issue_evidence`
  - `risk_assessment`
  - `rollback_reason`
- `rollback_or_retry` 至少包含：
  - `rollback_source`
  - `rollback_context`
  - `target_stage_type`
  - `attempt_history`
- `approval_result` 字段组在所属阶段结点 Inspector 中至少包含：
  - `approval_id`
  - `approval_type`
  - `decision`
  - `reason`
  - `next_stage_type`
  - `next_action_text`
  - `waiting_duration_ms`
  - `response_duration_ms`

`DeliveryResultDetailProjection` 至少包含：
- `delivery_record_id`
- `delivery_status`
- `delivery_description`
- `change_result`
- `test_result`
- `review_result`
- `branch_info`
- `commit_info`
- `merge_request_info`
- `delivery_target`
- `full_metrics`
- `attachments`

`DeliveryResultDetailProjection` 不要求提供 `stage_type`、`structured_input`、`structured_output`、`reasoning_trace` 或 `decision_trace` 等阶段结点专属字段。

### 8.5 审批块投影

`approval_request` 投影至少包含：
- `approval_id`
- `approval_type`
- `status`
- `title`
- `approval_object_excerpt`
- `risk_excerpt`
- `approval_object_preview`
- `approve_action`
- `reject_action`
- `is_actionable`
- `requested_at`
- `waiting_duration_ms`
- `response_duration_ms`
- `delivery_readiness_status`
- `delivery_readiness_message`
- `open_settings_action`

`reject_action` 必须声明需要补充理由输入。

`delivery_readiness_status` 必须满足以下规则：
- 当 `approval_type = code_review_approval` 且当前项目 `delivery_mode = git_auto_delivery` 时，至少支持：`ready`、`blocked`
- 当 `delivery_readiness_status = blocked` 时，`delivery_readiness_message` 必须给出明确阻塞原因，`open_settings_action` 必须指向前端统一设置弹窗中的 `通用配置` 页面
- 当 `approval_type = solution_design_approval`，或当前项目 `delivery_mode = demo_delivery` 时，`delivery_readiness_status` 可以为空且不得额外阻塞审批

`approval_request.is_actionable` 必须满足以下规则：
- 当该审批块属于当前活动 run、审批仍待处理，且当前 run 未进入 `terminated` 时，返回 `true`
- 当该审批块属于当前活动 run 且当前 run 处于 `paused`，若审批仍待处理，仍返回 `true`
- 当该审批块属于历史 run、当前 run 已进入 `terminated`，或审批已结束时，返回 `false`

审批时长字段统一按以下规则解释：
- `waiting_duration_ms`：从 `requested_at` 到当前投影时刻或 `responded_at` 的等待时长
- `response_duration_ms`：仅在审批已响应时输出，值为 `responded_at - requested_at`；未响应时为 `null`
- 当 `approval_result` 已生成时，`waiting_duration_ms` 与 `response_duration_ms` 数值相同属于合法情况

### 8.6 量化指标投影

所有适用执行结点至少支持以下通用量化指标：
- `duration_ms`
- `input_tokens`
- `output_tokens`
- `total_tokens`
- `attempt_index`

顶层非阶段条目中的审批与交付对象必须输出各自约定的量化指标。

不同类型对象的专项指标必须按前端文档定义输出，并遵守以下规则：
- 不适用的指标不输出
- 中栏只返回高信号指标子集
- Inspector 返回完整指标集

不同结点类型的专项量化指标清单固定如下：

- `requirement_analysis`
  - `context_file_count`
  - `reasoning_step_count`
  - `tool_call_count`
- `solution_design`
  - `context_file_count`
  - `reasoning_step_count`
  - `tool_call_count`
- `code_generation`
  - `context_file_count`
  - `tool_call_count`
  - `changed_file_count`
  - `added_line_count`
  - `removed_line_count`
- `test_generation_execution`
  - `tool_call_count`
  - `generated_test_count`
  - `executed_test_count`
  - `passed_test_count`
  - `failed_test_count`
  - `skipped_test_count`
  - `test_gap_count`
- `code_review`
  - `context_file_count`
  - `reasoning_step_count`
  - `tool_call_count`
- `rollback_or_retry`
  - `retry_index`
  - `source_attempt_index`
- `approval_request`
  - `waiting_duration_ms`
  - `response_duration_ms`
- `approval_result`
  - `waiting_duration_ms`
  - `response_duration_ms`
- `delivery_result`
  - `delivery_artifact_count`
  - `changed_file_count`

## 9. API 契约

功能一后端必须通过 REST API 暴露所有核心能力。V1 接口分为四类。

### 9.1 Project、Session、Template 与 Project Delivery Command API

至少提供以下命令接口：
- `POST /api/projects`
加载新的本地项目上下文
- `GET /api/projects`
获取项目列表
- `PUT /api/projects/{projectId}/delivery-channel`
更新项目默认交付配置
- `POST /api/projects/{projectId}/delivery-channel/validate`
校验项目交付配置
- `POST /api/projects/{projectId}/sessions`
创建新会话
- `PUT /api/sessions/{sessionId}/template`
更新草稿会话当前选中的模板
- `POST /api/sessions/{sessionId}/messages`
提交会话消息
- `POST /api/pipeline-templates`
创建新的用户模板
- `PATCH /api/pipeline-templates/{templateId}`
更新已有用户模板
- `POST /api/pipeline-templates/{templateId}/save-as`
基于现有模板另存为新的用户模板
- `DELETE /api/pipeline-templates/{templateId}`
删除已有用户模板
- `POST /api/providers`
创建新的自定义 Provider
- `PATCH /api/providers/{providerId}`
更新自定义 Provider

`POST /api/sessions/{sessionId}/messages` 只允许两类语义：
- 新需求输入
- 澄清回复

该接口必须满足以下行为：
- 当消息语义为 `new_requirement` 时，只允许在 `Session.status = draft` 且 `current_run_id = null` 时调用；后端必须基于当前 `selected_template_id` 创建 `PipelineRun`，固化模板快照，并进入 `requirement_analysis`
- 当消息语义为 `new_requirement` 且会话已有运行历史时，后端必须拒绝该调用并返回明确错误，提示用户创建新的 `Session`
- 当消息语义为 `clarification_reply` 时，只允许在当前会话处于 `waiting_clarification` 且当前阶段为 `requirement_analysis` 时调用；后端必须把补充信息回写到当前 `Requirement Analysis` 阶段并恢复执行

该接口不承担审批提交职责。

`POST /api/projects/{projectId}/sessions` 必须满足以下规则：
- 当请求未显式指定模板时，后端必须为新会话绑定默认系统模板 `新功能开发流程`
- 当请求显式指定模板时，必须校验该模板存在且可用

项目级交付配置接口必须满足以下规则：
- `PUT /api/projects/{projectId}/delivery-channel` 更新项目默认 `DeliveryChannel`；该更新必须影响后续新启动的 run，以及尚未固化交付快照的当前活动 run
- 当 `delivery_mode = demo_delivery` 时，后端只校验最小演示交付语义
- 当 `delivery_mode = git_auto_delivery` 时，后端必须校验 `provider_type`、`repository_ref`、`default_branch`、`review_request_type` 与 `credential_ref` 的完整性
- 请求中的 `credential_ref` 表示用户选择的凭据绑定引用；交付配置查询投影中的 `credential_status` 只作为绑定状态展示字段返回
- 后端必须仅在服务端安全域内根据 `credential_ref` 解析真实凭据，前端请求与响应都不得承载密钥明文
- 校验不通过时，不得把项目切换到伪可用的 `git_auto_delivery` 状态
- `POST /api/projects/{projectId}/delivery-channel/validate` 只承担配置校验职责，不产生持久化副作用

`PUT /api/sessions/{sessionId}/template` 必须满足以下规则：
- 只允许在 `Session.status = draft` 且尚未创建 `PipelineRun` 时调用
- 更新成功后，会话的 `selected_template_id` 必须立即可查询
- 不得用于修改已经启动运行所使用的模板快照

模板保存接口必须满足以下规则：
- `PATCH /api/pipeline-templates/{templateId}` 只允许更新 `user_template`
- `POST /api/pipeline-templates/{templateId}/save-as` 允许基于 `system_template` 或 `user_template` 创建新的 `user_template`
- `DELETE /api/pipeline-templates/{templateId}` 只允许删除 `user_template`
- 删除模板不得影响任何已启动运行所绑定的 `template_snapshot_ref`
- 删除当前会话选中的用户模板后，后端必须为该草稿会话重新绑定一个可用模板；未显式指定时回退到默认系统模板 `新功能开发流程`
- 模板保存前必须执行模板字段和角色绑定完整性校验
- 保存结果必须返回最终生效的 `template_id`
- 模板保存接口服务于启动前模板配置，不用于修改任何已启动运行的模板快照

Provider 管理接口必须满足以下规则：
- `POST /api/providers` 只用于创建 `custom` Provider
- `PATCH /api/providers/{providerId}` 只允许更新 `custom` Provider
- `builtin` Provider 不通过该接口修改其供应商类型
- `custom` Provider 在 V1 必须使用 `openai_completions_compatible` 协议
- 上述接口服务于前端统一设置弹窗中的 `模型提供商` 页面

### 9.2 Run 与 Approval Command API

至少提供以下命令接口：
- `POST /api/sessions/{sessionId}/runs`
显式创建一次新的运行尝试
- `POST /api/runs/{runId}/pause`
- `POST /api/runs/{runId}/resume`
- `POST /api/runs/{runId}/terminate`
- `POST /api/approvals/{approvalId}/approve`
- `POST /api/approvals/{approvalId}/reject`

`POST /api/sessions/{sessionId}/runs` 只用于显式重跑、重新尝试或后台运维重启场景，不应作为新建会话后首次需求输入的必需前置调用。

该接口仅用于对当前会话所承载的同一需求链路执行显式重跑、重新尝试或运维重启，不用于承接新的独立需求文本。

该接口必须满足以下规则：
- 只有当当前活动 run 已处于 `failed` 或 `terminated` 终态时，才允许创建新的 `PipelineRun`
- 新建 `PipelineRun` 必须从 `requirement_analysis` 重新开始完整链路，而不是从上一个 run 的中间阶段断点续跑
- 新建 `PipelineRun` 必须创建新的隔离工作区
- 上一个 run 未交付的本地工作区改动不得自动带入新的 `PipelineRun`
- 该接口对应前端 `重新尝试` 动作，不对应暂停 run 的继续执行

`POST /api/runs/{runId}/resume` 只用于继续当前已暂停的同一个 `PipelineRun`，不得创建新的 run。

`POST /api/runs/{runId}/pause`、`POST /api/runs/{runId}/resume`、`POST /api/runs/{runId}/terminate` 属于前端工作台可直接触发的正式用户能力，不只是后台运维接口。

`POST /api/runs/{runId}/pause` 必须满足以下规则：
- 只允许作用于当前活动 run
- 只要当前活动 run 仍处于链路运行过程中，就允许调用，不因当前处于哪个阶段而受限
- 至少允许从 `pending`、`running`、`waiting_clarification` 与 `waiting_approval` 进入 `paused`
- 调用成功后，run 级状态必须切换为 `paused`，并同步投影为 `Session.status = paused`
- 调用成功后，必须记录本次暂停前的源状态、源阶段与必要运行上下文快照，用于后续 `resume` 原位恢复
- 当暂停发生在结点执行中途时，后端必须为当前 run 临时固化可续接的工作快照；该快照至少覆盖当前阶段上下文、已生成的中间产物引用、工作区当前改动状态与必要的执行历史
- 调用成功后，不得删除、重建或改写当前 run 已经产生的阶段记录、审批请求、审批结果、澄清记录与交付记录
- 若暂停发生在 `waiting_approval`，待处理审批对象必须继续保留为可提交状态，不因 run 进入 `paused` 而自动关闭或转只读

`POST /api/runs/{runId}/resume` 必须满足以下规则：
- 只允许从 `paused` 恢复
- 恢复后必须优先回到暂停前记录的源状态，而不是统一恢复为某个固定状态
- 若暂停前源状态为 `waiting_clarification`，恢复后必须回到 `waiting_clarification`
- 若暂停前源状态为 `waiting_approval`，恢复后必须回到 `waiting_approval`
- 若暂停前源状态为 `running` 或 `pending`，恢复后必须在原阶段继续执行
- 恢复后继续同一个 `PipelineRun` 的既有链路上下文，不得新建 run，不得把恢复语义投影为 `retry_run`
- 若暂停前已有临时工作快照，恢复时必须优先基于该快照续接，而不是丢弃已完成的一半结点内工作并从空白状态重做

`POST /api/runs/{runId}/terminate` 必须满足以下规则：
- 只允许作用于当前活动 run
- 只要当前活动 run 尚未进入 `completed`、`failed` 或 `terminated` 终态，就允许调用
- 调用成功后，run 级状态必须切换为 `terminated`，并同步投影为 `Session.status = terminated`
- 调用成功后，不得关闭、删除或隐式完成当前 run 已存在的审批对象、澄清对象或其他历史执行记录
- 调用成功后，当前 run 上仍为 `pending` 的审批对象必须转为不可操作视图；前端不得再允许提交 `Approve` 或 `Reject`
- 调用成功后，必须在该 run 的 Narrative Feed 尾部追加一个顶层 `system_status` 终止提示条目，用于明确表达该 run 已被用户终止

`POST /api/approvals/{approvalId}/reject` 必须要求：
- `reason`

系统不得提供把需求澄清提交为审批决定的接口。

### 9.3 Query API

至少提供以下查询接口：
- `GET /api/providers`
- `GET /api/pipeline-templates`
- `GET /api/pipeline-templates/{templateId}`
- `GET /api/projects/{projectId}/delivery-channel`
- `GET /api/projects/{projectId}/sessions`
- `GET /api/sessions/{sessionId}/workspace`
- `GET /api/runs/{runId}`
- `GET /api/runs/{runId}/timeline`
- `GET /api/stages/{stageRunId}/inspector`
- `GET /api/approvals/{approvalId}`
- `GET /api/delivery-records/{deliveryRecordId}`
- `GET /api/preview-targets/{previewTargetId}`

其中：
- `GET /api/providers` 用于拉取内置 Provider 和用户新增的自定义 Provider 列表
- `GET /api/providers` 的返回结果服务于前端统一设置弹窗中的 `模型提供商` 页面，以及模板编辑区中的 Provider 选择列表
- `GET /api/pipeline-templates` 用于拉取系统模板和用户模板列表；返回结果中必须至少包含三个预置 `system_template`
- `GET /api/pipeline-templates/{templateId}` 用于拉取 `TemplateEditorProjection`，即启动前模板配置所需的允许字段
- `GET /api/projects/{projectId}/delivery-channel` 用于拉取 `ProjectDeliveryChannelProjection`
- `GET /api/sessions/{sessionId}/workspace` 用于拉取当前会话工作台视图；该接口返回完整会话的多 run 主流，而不是单 run 视图，run 之间的浏览与定位由前端页面内导航完成
- `GET /api/runs/{runId}` 用于拉取单个 run 的基础状态与摘要信息
- `GET /api/runs/{runId}/timeline` 用于拉取该 run 独立的 Narrative Feed 时间线，不混入同一会话其他 run 的条目
- `GET /api/stages/{stageRunId}/inspector` 只用于拉取 `StageInspectorProjection`
- `GET /api/delivery-records/{deliveryRecordId}` 只用于拉取 `DeliveryResultDetailProjection`
- `GET /api/approvals/{approvalId}` 只用于审批块自身的状态刷新、审批对象显示文本补全和操作结果回读，不用于驱动右侧 Inspector 打开

### 9.4 API 文档契约

后端必须把 API 文档作为正式交付物提供。

至少提供以下文档接口：
- `GET /api/openapi.json`
- `GET /api/docs`

并满足以下规则：
- `GET /api/openapi.json` 必须返回与当前服务实现一致的 machine-readable OpenAPI 文档
- `GET /api/docs` 必须提供 human-readable API 文档页面
- OpenAPI 文档必须覆盖功能一全部核心 REST 接口，包括 `Project`、`Session`、`PipelineTemplate`、`Provider`、项目级 `DeliveryChannel`、`PipelineRun` 生命周期、审批、Inspector、交付结果与预览目标查询
- OpenAPI 文档必须覆盖 `GET /api/sessions/{sessionId}/events/stream` 的事件流端点及其事件载荷结构
- API 文档必须定义请求参数、请求体 Schema、响应体 Schema、枚举值、通用错误响应与关键接口示例
- 运行接口与 OpenAPI 文档必须同版本交付，不允许文档落后于已发布接口

## 10. 实时更新契约

V1 的实时更新机制定义为：

`快照查询 + 会话级事件流`

后端必须提供：
- `GET /api/sessions/{sessionId}/workspace`
用于首次加载与断线重建
- `GET /api/sessions/{sessionId}/events/stream`
用于持续接收增量事件

V1 实时推送协议采用 `SSE`。

SSE 事件至少包含：
- `event_id`
- `session_id`
- `run_id`
- `event_type`
- `occurred_at`
- `payload`

前端收到增量事件后，必须能够：
- 追加 Narrative Feed 条目
- 更新会话状态
- 更新当前审批块状态
- 更新结点条目内容与量化指标
- 在需要时重新拉取 Inspector 详情

## 11. 领域事件模型

功能一 V1 至少定义以下关键事件：
- `ProjectLoaded`
- `SessionCreated`
- `SessionMessageAppended`
- `PipelineRunCreated`
- `StageStarted`
- `RequirementParsed`
- `ClarificationRequested`
- `ClarificationAnswered`
- `ClarificationResolved`
- `SolutionProposed`
- `SolutionValidationCompleted`
- `SolutionValidationFailedWithinDesign`
- `ApprovalRequested`
- `ApprovalApproved`
- `ApprovalRejected`
- `CodePatchGenerated`
- `TestsGenerated`
- `TestsExecuted`
- `TestGapAnalyzed`
- `ReviewCompleted`
- `AutoRegressionTriggered`
- `AutoRegressionExhausted`
- `RollbackTriggered`
- `StageCompleted`
- `StageFailed`
- `DeliveryPrepared`
- `BranchPrepared`
- `CommitCreated`
- `BranchPushed`
- `MergeRequestCreated`
- `RunCompleted`
- `RunFailed`
- `RunPaused`
- `RunResumed`
- `RunTerminated`

事件模型必须满足以下规则：
- 事件既服务于编排，也服务于前端投影更新
- 事件必须能映射到 Narrative Feed 条目或状态变化
- 审批结果与澄清结果必须进入同一条会话事件流

## 12. 工作区、工具与交付适配

后端必须通过统一工具接口暴露能力，分为两类。

### 12.1 Workspace Tools

V1 仅实现以下六个核心工具：
- `read_file`
- `write_file`
- `edit_file`
- `list_files`
- `search`
- `shell`

### 12.2 SCM / Delivery Tools

V1 仅实现以下五个核心工具：
- `prepare_branch`
- `create_commit`
- `push_branch`
- `create_code_review_request`
- `read_delivery_channel`

上述五个工具共同构成功能一 V1 的 Git 集成最小实现面，用于支撑 `git_auto_delivery` 的真实交付链路。

工具接口必须统一表达：
- 工具名称与描述
- 输入参数 Schema
- 执行结果载荷
- 错误信息
- 审计记录

## 13. 为功能二预留的接口边界

功能一后端必须保留以下复用边界：

1. `ChangeSet`
未来页面圈选驱动的改动也必须统一落到该对象。

2. `ContextReference`
未来需要扩展：
- `page_selection`
- `dom_anchor`
- `preview_snapshot`

3. `PreviewTarget`
V1 仅定义对象和查询接口，不实现预览启动与热更新。

4. `DeliveryRecord`
统一文本需求驱动与未来页面交互驱动的交付出口。

## 14. 后端验收标准

功能一后端至少满足以下验收标准：

1. 能创建项目、会话与完整 Pipeline 运行。
2. 能在 `Requirement Analysis` 阶段内部处理多轮需求澄清。
3. 不把需求澄清建模为人工审批。
4. 只在 `Solution Design` 与 `Code Review` 创建正式 `ApprovalRequest`。
5. 审批 `Reject` 理由能够进入后续上下文并驱动回退重跑。
6. 能为前端输出项目列表、会话列表、Narrative Feed、Inspector、审批块和交付结果投影。
7. 能通过 SSE 提供会话级增量事件流。
8. 能在历史会话中回放结构化产物、审批记录、回退记录与交付结果。
9. 能在代码评审失败时执行受控自动回归。
10. 能列出系统模板与用户模板，并在不破坏固定主干阶段的前提下编辑允许字段。
11. 能把模板修改保存为覆盖现有用户模板、另存为新用户模板或删除用户模板，并在运行开始时固化模板快照。
12. 能在项目级配置默认 `DeliveryChannel`，并在最终人工审批通过后、进入 `Delivery Integration` 前固化 `delivery_channel_snapshot_ref`。
13. 能提供与运行接口一致的 `OpenAPI` 文档 JSON 与可读 API 文档页。
14. 当 `delivery_mode = demo_delivery` 时，能生成仅用于展示的分支信息与提交说明预览，而不执行真实 Git 写操作。
15. 当 `delivery_mode = git_auto_delivery` 时，能自动创建分支、创建提交并发起 MR/PR。
16. 能为功能二保留 `ChangeSet`、`ContextReference`、`PreviewTarget`、`DeliveryRecord` 的复用边界。
