# 功能一后端引擎与协作规格 V1

## 1. 文档目标

本文档用于定义 `AI 驱动的需求交付流程引擎` 在 `功能一` 范围内的后端引擎设计、执行图模型、领域对象、前后端协作契约与扩展边界，作为后端实现、接口设计和前端联调的正式依据。

本文档聚焦：
- 功能一后端领域对象与执行图对象
- Pipeline 模板编译、运行生命周期、阶段执行与人工介入处理
- 前端控制台消费的查询投影与实时更新契约
- REST API、事件模型与工作区能力边界
- 为功能二预留的复用对象与接口

本文档不重新定义：
- 功能一的产品范围与产品级验收边界
- 前端控制台的信息架构、交互形态与视觉层级

## 2. 文档关系与口径优先级

本文档与其他规格文档的关系如下：

1. `docs/specs/function-one-product-overview-v1.md`
定义功能一的正式产品边界、业务阶段边界与运行时控制点边界。

2. `docs/specs/frontend-workspace-global-design-v1.md`
定义前端控制台的正式交互口径。凡涉及 Narrative Feed、Inspector、Composer、审批块、澄清与审批前端行为的表述，以该文档为准。

3. `docs/specs/function-one-backend-engine-design-v1.md`
负责把产品边界与前端交互口径落到后端执行图模型、领域模型、状态机、投影视图、事件流与接口契约。

`docs/archive/function-one-design-v2.md` 仅保留为迁移参考，不再作为当前后端规格依据。

## 2.1 后端技术选型

功能一 V1 后端技术方向固定如下：
- 运行时语言：`Python`
- API 框架：`FastAPI`
- Agent 编排内核：`LangGraph`
- 模型与工具适配层：`LangChain`
- 接口形态：`REST + SSE`
- 本地部署形态：`浏览器访问 localhost + 单个本地 Python 服务`

该技术选型必须满足以下规则：
- `FastAPI` 必须作为 `REST API`、`SSE` 端点与 `OpenAPI` 文档暴露的统一入口
- `LangGraph + LangChain` 必须作为功能一 V1 的正式执行内核，负责阶段内执行图、节点执行、工具循环、检查点与中断恢复
- 前端控制台只通过本地 Python 服务暴露的 HTTP 能力消费后端，不直接访问工作区文件系统
- 当前版本不以多服务、分布式队列或远程执行集群作为落地前提

功能一 V1 的持久化方向固定为 `多 SQLite 文件，按职责拆分`，而不是单一大库。

后端至少按以下边界拆分存储职责：
- `control.db`
  承载 `Project`、`Session`、模板、Provider 与项目级配置；其中 `Session` 是规范归属对象，包含会话级摘要字段，如 `status`、`current_run_id`、`latest_stage_type`、`selected_template_id`、`title` 与时间戳
- `runtime.db`
  承载 `PipelineRun`、`StageRun`、审批对象、结构化产物索引、控制条目与运行状态摘要
- `graph.db`
  承载 `GraphDefinition`、`GraphThread`、`GraphCheckpoint`、`GraphInterrupt` 以及执行图状态引用
- `event.db`
  承载领域事件日志、Narrative Feed 投影来源数据与审计记录

该存储策略必须满足以下规则：
- 不允许把全部领域对象、运行记录、执行图状态与事件流混入同一个 `SQLite` 文件
- `graph.db` 只承载执行内核相关对象，不直接充当对前端暴露的产品级查询真源
- 领域拆分必须服务于后续迁移到更重数据库时的平滑替换，而不是只为当前版本制造额外复杂度
- 各库之间的边界以职责分离为目标，不要求当前版本过度追求数据库级分布式事务
- `runtime.db` 不重复持有第二份规范 `Session` 实体；其会话相关数据通过 `session_id` 关联到 `PipelineRun`、`StageRun`、审批对象与运行记录
- `PipelineRun` 生命周期推进导致的会话级摘要变化，必须由运行生命周期服务回写 `control.db` 中的 `Session`
- 当 `Session.status = draft` 且 `current_run_id = null` 时，表示该会话尚未启动首个 run；该语义以 `control.db.Session` 为准

### 2.1.1 后端核心依赖基线

功能一 V1 后端核心依赖基线固定如下：
- Python 版本基线：`Python 3.11+`
- ASGI 服务基线：`Uvicorn`
- 数据建模与接口 Schema 基线：`Pydantic v2`
- 配置加载基线：`pydantic-settings`
- 数据访问基线：`SQLAlchemy 2.x`
- 数据库迁移基线：`Alembic`
- 执行图编排基线：`LangGraph`
- 模型与工具适配基线：`LangChain`
- 外部 HTTP 调用基线：`httpx`
- 测试基线：`pytest`、`pytest-asyncio`
- 本地命令执行与 Git 交付基线：Python 标准库 `subprocess` + 本地 `git CLI`

该依赖基线必须满足以下规则：
- 上述依赖构成功能一 V1 的正式实现基线；如需偏离，必须先更新规格或等效技术决策记录
- `FastAPI`、`Uvicorn`、`Pydantic v2`、`SQLAlchemy 2.x`、`Alembic`、`LangGraph`、`LangChain` 必须共同构成后端主路径，不得在相同职责上再引入第二套并行主框架
- `REST API`、`SSE` 端点、请求响应 Schema 与 `OpenAPI` 文档必须直接建立在 `FastAPI` 与 `Pydantic v2` 之上，不得额外包裹一层自定义通用接口框架
- `SQLite` 的访问、会话管理与模型映射必须统一收敛到 `SQLAlchemy 2.x`；数据库结构演进必须通过 `Alembic` 管理，不得以手工散落脚本作为主迁移机制
- `LangGraph` 必须用于表达固定业务主链的执行图、阶段内子图、条件边、中断点与检查点恢复
- `LangChain` 必须用于统一封装模型供应商、消息对象、结构化输出与内部工具绑定
- 与模型供应商、远端托管平台或其他 HTTP 服务的交互必须优先使用 `httpx`
- 与工作区、构建、测试和 Git 交付相关的受控执行必须优先使用标准库 `subprocess` 和本地 `git CLI`
- `SSE` 实现必须优先采用 `FastAPI` / `Starlette` 原生流式响应能力；只有在原生能力无法满足协议与维护要求时，才允许引入小型专用补充库

### 2.1.2 技术选型原则与禁止项

功能一 V1 的后端技术选型必须遵循以下原则：
- 以成熟、主流、文档完善、社区使用广泛的通用库为优先，而不是以抽象完整性或框架新颖性为优先
- 以降低项目开发期的理解成本、调试成本、联调成本与维护成本为优先，而不是为潜在远期扩展预先引入额外基础设施
- `LangGraph state` 是执行内核真源，`Project`、`Session`、`PipelineRun`、`StageRun`、`ApprovalRequest`、`DeliveryRecord` 是产品级领域真源，两者必须同时存在且职责分离
- 前端和外部 API 只消费领域对象、领域事件和查询投影，不直接消费 `LangGraph` 原始 `thread`、`checkpoint` 或节点流事件
- 能直接复用 `FastAPI`、`Pydantic`、`SQLAlchemy`、`Alembic`、`LangGraph`、`LangChain`、`httpx`、标准库 `subprocess` 与本地 `git CLI` 已提供能力的场景，不得重复造轮子

功能一 V1 明确禁止以下做法：
- 不以 `Redis`、消息队列、任务队列、分布式调度器或多服务拆分作为 V1 正式落地前提
- 不以 `GitPython` 或同类 Git 二次封装库作为主交付链路；本地 `git CLI` 是唯一标准实现路径
- 不直接把 `LangGraph` 原始状态对象暴露为前端查询模型或产品 API 模型
- 不用 `graph.db` 的底层 checkpoint 记录替代 `PipelineRun`、`StageRun`、`ApprovalRequest` 与 `DeliveryRecord` 的正式领域建模
- 不允许前端直接消费 `LangGraph` 原始事件流并自行拼装产品语义

## 3. 后端职责范围

功能一后端必须承担以下职责：
- 管理项目上下文、需求会话、模板与 Provider
- 把模板编译为固定业务主链对应的执行图定义
- 管理 run 生命周期、中断点、检查点、暂停恢复与终止
- 持久化阶段输入、阶段输出、结构化产物、控制条目与审批记录
- 提供前端控制台所需的查询投影与实时更新能力
- 管理工作区读取、代码修改、命令执行、测试运行与交付通道适配
- 为功能二保留 `ChangeSet`、`ContextReference`、`PreviewTarget`、`DeliveryRecord` 的复用边界

## 4. 总体架构

功能一后端采用以下基础结构：

`FastAPI Gateway / Control Plane + LangGraph Agent Orchestration Plane + Projection / Event Plane + Workspace / Delivery Adapter`

架构边界如下：
- `Gateway / Control Plane` 负责 REST API、会话管理、模板管理、Provider 管理、审批命令与查询聚合
- `Agent Orchestration Plane` 负责执行图编译、节点执行、中断恢复、检查点持久化与阶段内 Agent 编排
- `Projection / Event Plane` 负责把执行图事件翻译为领域事件、Narrative Feed 条目与查询投影
- `Workspace & Delivery Adapter` 负责与代码仓库、测试环境和托管平台交互

### 4.1 系统模块划分

功能一后端至少包含以下核心模块：

1. `Pipeline Template Registry`
负责管理流程模板、固定业务阶段骨架、阶段角色绑定、审批检查点配置与自动回归配置。

2. `Graph Compiler`
负责把模板快照编译成 `GraphDefinition`，并生成业务阶段节点组、内部子图、条件边与中断点。

3. `Run Lifecycle Service`
负责创建 `PipelineRun`、启动 `GraphThread`、维护 run 状态、处理暂停恢复终止与重新尝试。

4. `Agent Orchestration Runtime`
负责执行 `LangGraph` 节点、驱动阶段内 Agent、执行工具调用、保存检查点并处理中断恢复。

5. `Approval & Interrupt Service`
负责创建审批对象、处理中断载荷、记录审批决策、回写拒绝理由并恢复执行图。

6. `Run Context / Artifact Store`
负责持久化运行上下文、阶段输入输出、结构化产物与共享引用。

7. `Projection & Event Translator`
负责把执行图内部事件翻译成领域事件、Narrative Feed 条目、Inspector 投影与会话级状态摘要。

8. `LLM Provider Adapter`
负责统一封装模型供应商接入与切换逻辑。

9. `Workspace & Tool Service`
负责工作区隔离、文件读取、代码修改、命令执行、diff 生成与工具接口管理。

10. `SCM & Delivery Adapter`
负责封装本地 Git、远端托管平台、交付通道与 MR/PR 创建能力。

11. `REST API + Query Layer`
负责暴露命令接口、查询接口、事件流接口与 OpenAPI 文档。

### 4.2 实施原则

后端实现必须遵循以下原则：
- `图驱动执行`
  正式业务主链、阶段内子步骤、审批中断、回退与重试都必须由显式执行图表达。
- `领域契约先于框架细节`
  `LangGraph` 是执行内核，不是产品 API；产品级外部契约仍由领域对象和投影定义。
- `产物驱动`
  后续阶段只能依赖持久化产物和契约化上下文，不允许依赖运行期隐式记忆。
- `API First`
  前端控制台只能通过命令接口、查询接口和事件流消费后端能力。
- `工具统一抽象`
  文件系统、命令执行、分支准备和代码评审请求都必须通过统一工具协议暴露。
- `前后端解耦`
  前端定义交互语义，后端负责投影与载荷；双方不得在另一侧重复定义一套口径。

### 4.3 V1 部署与运行架构

功能一 V1 采用单机本地执行架构，但逻辑上分为 `Control Plane` 与 `Orchestration Plane` 两层。

V1 默认部署拓扑必须满足以下规则：
- 前端控制台、后端服务与工作区执行能力部署在同一台主机
- 前端以浏览器访问 `localhost` 的方式运行，后端以单个本地 Python 服务方式运行
- 在单个进程或单服务内部，必须能清晰区分 `Gateway / Control Plane` 与 `Agent Orchestration Plane` 的职责边界
- 前端控制台只能通过命令接口、查询接口和事件流消费后端能力，不直接访问目标仓库文件系统，不直接执行本地命令，不直接承担 Git 交付动作
- 后端中的执行侧必须与目标仓库、本地 Git 环境以及项目依赖的构建、运行和测试工具链处于同一台主机，并共享一致的文件系统视角
- 远端托管平台在 V1 中属于可选交付出口，不属于系统启动与本地执行的前提条件

V1 运行环境必须满足以下约束：
- 每个 `Project.root_path` 必须对应一个可被后端直接访问的本地仓库路径
- `Workspace & Tool Service` 必须在隔离工作区中完成文件读取、代码修改、命令执行、diff 生成与测试执行
- 与工作区、测试、Git 交付相关的长任务必须通过受控子进程执行，而不是阻塞 HTTP 请求处理主路径
- 每个 `PipelineRun` 都必须使用独立隔离工作区
- 新建 `PipelineRun` 时，工作区必须从干净基线创建，不得自动继承前一个 run 未交付的工作区改动
- 只有已经通过明确交付路径落入仓库基线的结果，才允许成为后续 run 的输入基线；未交付的本地工作区改动不得跨 run 泄漏
- `SCM & Delivery Adapter` 必须统一封装本地 Git 与远端托管平台差异，不向前端和上层领域服务暴露具体命令细节
- 当系统未配置远端托管平台时，仍必须支持 `demo_delivery` 路径下的完整本地闭环
- 当系统配置了可用的远端托管平台与交付通道时，必须支持 `git_auto_delivery` 路径下的真实交付流程

未来如引入远程 Runner、自定义沙箱或分布式执行能力，必须保持以下约束不变：
- 前端交互语义不变
- 核心 `Tool` 协议不变
- `Project`、`Session`、`PipelineRun`、`StageRun`、`ApprovalRequest`、`DeliveryRecord` 等核心领域对象语义不变
- API 层、执行图层与工作区执行层之间的职责边界不变

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

`DeliveryChannel` 表示某个 `Project` 当前生效中的项目级默认交付配置，至少包含：
- `delivery_channel_id`
- `project_id`
- `delivery_mode`
- `scm_provider_type`
- `repository_identifier`
- `default_branch`
- `code_review_request_type`
- `credential_ref`
- `credential_status`
- `readiness_status`
- `readiness_message`
- `last_validated_at`
- `created_at`
- `updated_at`

`DeliveryChannel` 必须满足以下规则：
- `delivery_mode` 在功能一 V1 中只允许：`demo_delivery`、`git_auto_delivery`
- `scm_provider_type` 在 `delivery_mode = git_auto_delivery` 时至少支持：`github`、`gitlab`
- `code_review_request_type` 在 V1 至少支持：`pull_request`、`merge_request`
- `credential_status` 在 V1 至少支持：`unbound`、`invalid`、`ready`
- `readiness_status` 在 V1 至少支持：`unconfigured`、`invalid`、`ready`
- 当 `delivery_mode = demo_delivery` 时，`scm_provider_type`、`repository_identifier`、`default_branch`、`code_review_request_type` 与 `credential_ref` 允许为 `null`
- 当 `delivery_mode = git_auto_delivery` 时，`scm_provider_type`、`repository_identifier`、`default_branch`、`code_review_request_type` 与 `credential_ref` 都必须具备有效值，且 `credential_status = ready` 才能使 `readiness_status = ready`
- `readiness_status` 是项目级交付配置对外暴露的统一就绪状态；审批阻塞判断与设置页状态展示都必须使用同一状态语义
- `readiness_message` 用于返回当前配置的主阻塞原因或校验结果摘要
- 当前 run 固化的 `delivery_channel_snapshot_ref` 必须包含 `delivery_mode`、`scm_provider_type`、`repository_identifier`、`default_branch`、`code_review_request_type`、`credential_ref`、`credential_status`、`readiness_status`、`readiness_message` 与 `last_validated_at`
- 项目级校验接口响应中的动作时间字段使用 `validated_at`；一旦写入交付快照，字段名统一固化为 `last_validated_at`

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
- `PipelineRun.running` 必须投影为 `Session.status = running`
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
- 同一 `Session` 可因重新尝试或运维重启产生多个 `PipelineRun`
- 暂停后的恢复属于当前 `PipelineRun` 的继续执行，不创建新的 run
- 同一 `Session` 下的多个 `PipelineRun` 只表示同一需求链路的不同执行尝试，不表示新的独立需求
- 新的 `PipelineRun` 只允许在前一个活动 run 处于 `failed` 或 `terminated` 后创建；`completed` 表示该会话链路已经完成，不再在同一会话中开启新的 run；同一 `Session` 在同一时刻不允许并存多个活动 run
- 若用户要发起新的独立需求，必须创建新的 `Session`，不得在已有运行历史的会话中再次提交 `new_requirement` 以开启第二条链路

`Session.latest_stage_type` 与所有下游查询投影中的阶段类型字段必须统一使用本文定义的 `stage_type` 枚举值。

当 `Session.status = draft` 且 `current_run_id = null` 时，`Session.latest_stage_type` 必须为 `null`。

### 5.2 模板、运行与执行图对象

3. `PipelineTemplate`
定义一条可复用的流程模板，包含固定业务阶段骨架、角色槽位绑定、自动回归策略、运行前可编辑配置与图编译源。至少包含：
- `template_id`
- `name`
- `description`
- `template_source`
- `base_template_id`
- `fixed_stage_sequence`
- `stage_role_bindings`
- `interrupt_policy`
- `auto_regression_enabled`
- `max_auto_regression_retries`
- `created_at`
- `updated_at`

`PipelineTemplate` 必须满足以下规则：
- 功能一 V1 对外管理语义中的 `Pipeline` 资源由 `PipelineTemplate` 承载；`PipelineRun` 是从模板快照派生的运行实例，不作为可编辑模板资源参与 CRUD
- `template_source` 在 V1 只允许：`system_template`、`user_template`
- `fixed_stage_sequence` 在 V1 固定为：`requirement_analysis -> solution_design -> code_generation -> test_generation_execution -> code_review -> delivery_integration`
- V1 固定存在两个不可关闭的审批检查点：
  - `solution_design_approval`：位于 `solution_design` 阶段内部方案校验通过之后
  - `code_review_approval`：位于 `code_review` 产出稳定评审结果之后
- 用户不可通过模板删除、禁用或重排核心业务阶段
- 用户不可通过模板关闭上述两个固定审批检查点
- `system_template` 允许被选择和另存，但不允许被直接覆盖
- `user_template` 允许被覆盖更新、另存为新模板和删除
- `PipelineTemplate` 的完整定义服务于后端校验、图编译与模板持久化，不等同于前端模板配置 UI 的展示载荷
- 系统启动时必须至少预置以下三个 `system_template`：
  - `Bug 修复流程`
  - `新功能开发流程`
  - `重构流程`
- 新建会话在未显式指定模板时，默认绑定 `新功能开发流程`
- 三个预置 `system_template` 必须共享同一固定业务阶段骨架
- 三个预置 `system_template` 的差异只允许体现在：
  - 必需角色槽位默认绑定的 `AgentRole`
  - 各 `AgentRole` 的默认 `system_prompt`
  - 各 `AgentRole` 绑定的默认 `Provider`
  - 自动回归默认策略

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

6. `GraphDefinition`
表示由某次模板快照编译得到的正式执行图定义，至少包含：
- `graph_definition_id`
- `template_snapshot_ref`
- `graph_version`
- `stage_node_groups`
- `interrupt_policy`
- `retry_policy`
- `created_at`

`GraphDefinition` 必须满足以下规则：
- 每次 `PipelineRun` 启动前都必须生成一份绑定该次模板快照的 `GraphDefinition`
- `GraphDefinition` 必须显式表达六个正式业务阶段对应的节点组、阶段内子图、条件边与中断点
- `GraphDefinition` 可以在底层包含多个节点，但这些节点必须可映射回正式业务阶段
- `GraphDefinition` 不直接暴露给前端作为产品查询对象

7. `GraphThread`
表示某次运行对应的正式执行图线程实例，至少包含：
- `graph_thread_id`
- `run_id`
- `graph_definition_id`
- `checkpoint_namespace`
- `current_node_key`
- `current_interrupt_id`
- `status`
- `last_checkpoint_ref`
- `created_at`
- `updated_at`

`GraphThread.status` 必须至少支持：
- `pending`
- `running`
- `interrupted`
- `paused`
- `completed`
- `failed`
- `terminated`

8. `GraphCheckpoint`
表示执行图在某个节点边界上持久化的一次状态快照，至少包含：
- `checkpoint_id`
- `graph_thread_id`
- `checkpoint_ref`
- `node_key`
- `state_ref`
- `created_at`

`GraphCheckpoint` 必须满足以下规则：
- 每次业务阶段切换、人工中断前后、暂停恢复前后都必须具备可恢复的 checkpoint
- `state_ref` 指向图状态存储或序列化快照，不作为前端直接消费对象

9. `GraphInterrupt`
表示执行图中等待人工输入或审批决策的正式中断点，至少包含：
- `interrupt_id`
- `graph_thread_id`
- `interrupt_type`
- `source_stage_type`
- `source_node_key`
- `payload_ref`
- `status`
- `requested_at`
- `responded_at`

`interrupt_type` 在功能一 V1 中至少支持：
- `clarification_request`
- `solution_design_approval`
- `code_review_approval`

`GraphInterrupt.status` 至少支持：
- `pending`
- `responded`
- `cancelled`

10. `PipelineRun`
表示某个会话的一次具体运行，至少包含：
- `run_id`
- `session_id`
- `template_id`
- `template_snapshot_ref`
- `graph_definition_ref`
- `graph_thread_id`
- `delivery_channel_snapshot_ref`
- `status`
- `current_stage_run_id`
- `attempt_index`
- `trigger_source`
- `started_at`
- `ended_at`

`PipelineRun` 必须满足以下运行快照规则：
- 每次运行开始前都必须固化一份模板快照
- 每次运行开始前都必须从模板快照编译出一份 `GraphDefinition`
- 交付通道快照不在 run 启动时固化，而是在最终人工审批通过后、进入 `Delivery Integration` 前固化
- 运行期间实际读取的角色绑定、Provider 绑定和自动回归配置必须来自模板快照
- `Delivery Integration` 阶段实际读取的 `delivery_mode`、仓库标识、默认分支、代码评审请求类型、凭据状态与配置就绪状态必须来自 `delivery_channel_snapshot_ref`
- `delivery_channel_snapshot_ref` 必须指向 runtime 侧正式持久化的 `DeliveryChannelSnapshot` 或等价结构化快照记录，不得只是无所有权的 opaque string
- 模板快照、执行图定义与交付通道快照一旦绑定到某次运行，不得再被运行外部修改
- `trigger_source` 在 V1 只允许：`initial_requirement`、`retry`、`ops_restart`
- 会话首个 run 的 `trigger_source` 必须为 `initial_requirement`
- 由 `重新尝试` 创建的新 run 的 `trigger_source` 必须为 `retry`
- 因运维恢复或系统修复而新建的 run，其 `trigger_source` 必须为 `ops_restart`

`PipelineRun.status` 必须至少支持：
- `running`
- `paused`
- `waiting_clarification`
- `waiting_approval`
- `completed`
- `failed`
- `terminated`

`PipelineRun` 作为产品级运行对象，不暴露仅属于执行内核启动瞬间的 `pending`。

11. `StageRun`
表示某次运行中的一个正式业务阶段执行切片，至少包含：
- `stage_run_id`
- `run_id`
- `stage_type`
- `status`
- `attempt_index`
- `started_at`
- `ended_at`
- `input_ref`
- `output_ref`
- `source_node_group`

`stage_type` 在功能一 V1 中必须统一使用以下机器可读枚举：
- `requirement_analysis`
- `solution_design`
- `code_generation`
- `test_generation_execution`
- `code_review`
- `delivery_integration`

`StageRun.status` 必须至少支持：
- `running`
- `waiting_clarification`
- `waiting_approval`
- `completed`
- `failed`
- `superseded`

其中：
- `StageRun` 是对外可见的业务阶段执行切片，不要求与底层 graph node 一一对应
- `StageRun` 不暴露仅属于底层节点装配过程的 `pending`
- 当运行进入审批等待时，保持触发审批的源阶段 `StageRun` 处于 `waiting_approval`
- 当同一业务阶段因回退或重试再次执行时，必须创建新的 `StageRun` 记录；被替换的旧尝试可标记为 `superseded`

### 5.3 产物、控制与审批对象

12. `StageArtifact`
表示阶段级结构化产物，是阶段流转、审批展示与历史回看的基础容器。

`StageArtifact` 必须满足以下规则：
- 作为运行期结构化产物、阶段输入输出快照与稳定引用目标的统一索引对象
- 默认持久化在 `runtime.db`
- 如无特别说明，`StageRun.input_ref`、`StageRun.output_ref`、`GraphInterrupt.payload_ref` 与 `ApprovalRequest.payload_ref` 默认指向 `StageArtifact` 或其派生快照记录
- `StageArtifact` 可通过 `artifact_ref`、`attachments_ref`、`delivery_record_ref` 等查询层稳定引用被前端或其他领域对象间接访问
- `StageArtifact` 必须能够承载供 Inspector 打开的原始阶段信息，包括输入快照、过程记录、输出快照、附件引用与量化信息

13. `ClarificationRecord`
表示 `Requirement Analysis` 阶段内部的澄清问答记录，至少包含：
- `clarification_id`
- `stage_run_id`
- `question`
- `answer`
- `status`
- `created_at`
- `answered_at`

14. `RunControlRecord`
表示主链中的控制型条目，至少包含：
- `control_record_id`
- `run_id`
- `control_type`
- `source_stage_type`
- `target_stage_type`
- `payload_ref`
- `created_at`

`control_type` 在功能一 V1 中至少支持：
- `clarification_wait`
- `rollback`
- `retry`

`RunControlRecord` 必须满足以下规则：
- 控制型条目用于驱动 Narrative Feed 中的控制语义展示，不替代正式业务阶段
- 回退与重试必须通过 `RunControlRecord` 被显式记录与投影
- 回退记录必须表达“保留既有执行历史前提下的订正性重执行”，不得表达为撤销、删除或覆盖既有链路
- run 尾部的 `system_status` 顶层条目必须由 run 终态直接投影生成，不作为 `RunControlRecord.control_type` 持久化

15. `ApprovalRequest`
表示一条正式人工审批请求，至少包含：
- `approval_id`
- `run_id`
- `source_stage_run_id`
- `interrupt_id`
- `approval_type`
- `status`
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
- `cancelled`

16. `ApprovalDecision`
表示一条审批响应结果，至少包含：
- `approval_decision_id`
- `approval_id`
- `decision`
- `reason`
- `created_at`

`ApprovalDecision` 必须满足以下规则：
- `created_at` 表示用户提交审批决定并被系统持久化的时间
- `reason` 在 `Reject` 场景下必须提供；在 `Approve` 场景下允许为 `null`
- `ApprovalDecision` 只在审批实际被提交并被系统接受时创建；处于 `paused` 的待审批 run 不得创建新的 `ApprovalDecision`

17. `DeliveryRecord`
表示一次运行最终交付过程与结果的统一记录，至少包含：
- `delivery_record_id`
- `run_id`
- `delivery_mode`
- `delivery_snapshot_ref`
- `result_ref`
- `status`
- `created_at`

### 5.4 代码与扩展对象

18. `ChangeSet`
表示一次代码变更结果的统一抽象对象，未来功能二的页面驱动改动也必须统一落到该对象。

19. `ContextReference`
表示跨阶段、跨运行的上下文引用对象，未来必须能够扩展：
- `page_selection`
- `dom_anchor`
- `preview_snapshot`

20. `PreviewTarget`
表示可供前端查询的预览对象。V1 只定义对象和查询接口，不实现预览启动与热更新。

## 6. 模板编译、执行图与运行生命周期

### 6.1 正式业务阶段序列

功能一 V1 的正式业务阶段序列如下：

1. `requirement_analysis`
2. `solution_design`
3. `code_generation`
4. `test_generation_execution`
5. `code_review`
6. `delivery_integration`

其中：
- `Solution Validation` 是 `solution_design` 阶段内部的第二个执行节点组，不形成独立 `StageRun`
- `solution_design_approval` 与 `code_review_approval` 是固定审批中断点，位于对应源阶段完成之后，不属于正式业务阶段
- 回退、重试、暂停、恢复与终止属于运行控制语义，不属于正式业务阶段

### 6.2 模板到执行图的编译规则

模板编译必须满足以下规则：
- 每次 `PipelineRun` 启动前，必须基于该次模板快照编译出一份 `GraphDefinition`
- `GraphDefinition` 必须显式表达六个正式业务阶段对应的节点组
- `Requirement Analysis` 子图必须支持“分析 -> 需要澄清时中断 -> 恢复后继续分析”的循环
- `Solution Design` 子图必须支持“方案生成 -> 方案校验 -> 校验失败回到设计 -> 校验通过进入审批中断”的循环
- `Code Generation`、`Test Generation & Execution`、`Code Review` 必须保持业务阶段串行推进
- `Code Review` 子图必须支持自动回归路由
- `Delivery Integration` 子图必须支持按交付模式分流
- 图编译结果必须记录稳定的 `source_node_group` 到 `stage_type` 映射关系

### 6.3 Requirement Analysis 生命周期

`Requirement Analysis` 必须按以下规则运行：
- 接收用户原始需求输入
- 产出结构化需求、验收标准、约束与待确认事项
- 当信息不足时，创建 `ClarificationRecord` 与 `GraphInterrupt(type=clarification_request)`，并把 `PipelineRun.status` 与 `StageRun.status` 投影为 `waiting_clarification`
- 前端通过会话消息接口提交补充信息
- 补充信息回写到同一个业务阶段上下文并恢复同一个 `GraphThread`
- 本阶段恢复执行后继续分析，直到产出完整结果

本阶段禁止创建 `ApprovalRequest`。

### 6.4 Solution Design 生命周期

`Solution Design` 必须按以下规则运行：
- 本阶段内部必须采用 `Solution Design Agent -> Solution Validation Agent` 的串行结构
- `Solution Design Agent` 先产出技术方案、影响范围与关键设计决策
- `Solution Validation Agent` 在同一个业务阶段内对方案做独立校验
- 方案校验结果必须作为 `Solution Design` 阶段产物的一部分持久化
- 校验失败时，不得创建新的独立 `Solution Validation` 阶段；系统必须依据校验结论重新进入 `Solution Design` 阶段内部的设计节点
- 校验通过后，创建 `ApprovalRequest(type=solution_design_approval)` 与对应 `GraphInterrupt`
- 创建审批请求后，当前 `solution_design` 的 `StageRun.status` 必须置为 `waiting_approval`
- 审批通过后，进入 `Code Generation`
- 审批拒绝后，记录拒绝理由并回到 `Solution Design`

### 6.5 Code Generation 到 Code Review 生命周期

`Code Generation`、`Test Generation & Execution`、`Code Review` 必须保持正式业务阶段串行执行：
- 先执行代码生成
- 再执行测试生成与执行
- 最后执行代码评审

`Code Review` 完成后：
- 若需要自动回归，则统一回退到 `Code Generation`
- 回退与重试必须记录 `RunControlRecord`
- 自动回归循环结束且得到稳定评审产物后，创建 `ApprovalRequest(type=code_review_approval)`
- 创建审批请求后，当前 `code_review` 的 `StageRun.status` 必须置为 `waiting_approval`
- 当当前项目 `delivery_mode = git_auto_delivery` 时，审批通过前必须校验交付配置与凭据是否达到 `ready`；通过时必须在同一服务事务中完成审批决策、顶层 `approval_result` 事件、完整 `delivery_channel_snapshot_ref` 固化与进入 `Delivery Integration` 的执行恢复，外部不得观察到已通过审批但交付快照尚未固化的中间态
- 当当前项目 `delivery_mode = demo_delivery` 时，不执行上述交付配置阻塞校验；审批通过后仍必须在同一公开语义中固化交付快照，再进入 `Delivery Integration`
- 审批拒绝后，记录拒绝理由并回退到 `Code Generation`

### 6.6 Delivery Integration 生命周期

`Delivery Integration` 必须完成以下工作：
- 汇总最终变更结果、测试结论与评审结论
- 读取当前 run 已固化的交付通道快照信息
- 当 `delivery_mode = demo_delivery` 时，仅生成用于演示的交付说明、分支信息展示和 `commit_message_preview`，不得执行真实提交、推送或 MR/PR 创建
- 当 `delivery_mode = git_auto_delivery` 时，必须执行真实交付流程：`read_delivery_channel -> prepare_branch -> create_commit -> push_branch -> create_code_review_request`
- 按交付策略生成 MR/PR 信息或交付描述
- 产出 `DeliveryRecord`

本阶段不创建新的人工审批检查点。

## 7. Human-in-the-loop 与运行时控制语义

### 7.1 需求澄清语义

需求澄清必须满足以下规则：
- 需求澄清不是审批
- 需求澄清不提供 `Approve / Reject`
- 需求澄清通过统一会话消息接口提交
- 需求澄清必须保留问题、回答、影响范围与最终结论
- 同一 `Requirement Analysis` 业务阶段允许多轮澄清
- `waiting_clarification` 只表示当前 run 正在等待用户补充信息
- 当用户提交 `clarification_reply` 后，当前 run 必须恢复为 `running` 并继续同一个 `Requirement Analysis` 业务阶段

### 7.2 人工审批语义

人工审批必须满足以下规则：
- 仅存在 `solution_design_approval` 与 `code_review_approval`
- 审批对象必须引用稳定产物快照，而不是运行中间态
- `Approve` 可以直接提交
- `Reject` 必须携带理由
- 拒绝理由必须进入后续上下文，供重新生成与审查使用
- 审批结果必须进入事件流与 Narrative Feed 投影
- 审批等待期间，会话级 `latest_stage_type` 以及面向前端投影的 `current_stage_type` 都必须保持源阶段 `stage_type` 不变
- `solution_design_approval` 的 `Reject` 固定回到 `Solution Design`
- `code_review_approval` 的 `Reject` 固定回到 `Code Generation`
- 当 `approval_type = code_review_approval` 且当前项目 `delivery_mode = git_auto_delivery` 时，`Approve` 前必须校验交付配置与凭据是否达到 `ready`
- 当上述校验不通过时，系统不得进入 `Delivery Integration`，必须继续保持该审批对象待处理，并向前端返回明确的交付配置阻塞信息
- 当当前项目 `delivery_mode = demo_delivery` 时，不因交付配置或凭据缺失额外阻塞 `code_review_approval`
- 若当前 `PipelineRun.status = paused`，待处理审批必须保持 `ApprovalRequest.status = pending` 且不可提交；后端必须拒绝新的审批提交命令
- `resume` 调用成功后，若 run 在暂停前停留于审批等待，则必须恢复到同一个 `waiting_approval` 检查点继续等待审批，而不是自动推进后续阶段

### 7.3 暂停、恢复与终止语义

运行控制必须满足以下规则：
- `pause` 作用于当前活动 run 对应的 `GraphThread`
- `pause` 调用成功后，必须保存可恢复的 `GraphCheckpoint` 与工作区快照引用
- `resume` 只允许继续同一个 `PipelineRun` 与同一个 `GraphThread`
- `resume` 调用成功后，必须从最后可用 checkpoint 继续
- `terminate` 调用成功后，必须终止当前 `GraphThread`
- `terminate` 不得删除、关闭或隐式完成当前 run 已存在的审批对象、澄清对象或其他历史执行记录
- 当 run 因审批等待而被 `pause` 时，`PipelineRun.status` 必须投影为 `paused`；对应 `ApprovalRequest` 继续保持待处理状态，但投影必须标记为不可提交
- 当上述 run 被 `resume` 后，系统必须恢复到同一个 `waiting_approval` 状态，等待用户提交审批决定

### 7.4 回退与重试语义

自动回归与回退必须满足以下规则：
- 回退的正式语义是：在保留既有执行历史、产物、问题记录与审批记录的前提下，退回到既定业务阶段并开始订正性重执行
- `Code Review` 相关的自动回归与人工审批拒绝后修正，都必须统一进入 `Code Generation`
- `Solution Design` 只允许被其自身审批拒绝重新打开，不作为 `Code Review` 的回退目标
- 自动回归最大次数由模板配置控制，且必须落在平台定义的统一上限内
- 回退与重试必须产生显式 `RunControlRecord`
- 自动回归结束后，才能进入代码评审人工审批
- 自动回归超限后，必须输出明确的失败或高风险状态，不得静默推进

### 7.5 Agent 编排与执行约束

Agent 编排必须满足以下规则：

1. `阶段角色明确`
每个正式业务阶段都必须配置明确的 `AgentRole`。

功能一 V1 的核心 Agent 固定为：
- `Requirement Analysis Agent`
- `Solution Design Agent`
- `Solution Validation Agent`
- `Code Generation Agent`
- `Test Generation & Execution Agent`
- `Code Review Agent`
- `Delivery Integration Agent`

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

4. `模型供应商可切换`
- V1 默认内置两个 `builtin` Provider：`火山引擎`、`DeepSeek`
- V1 允许用户新增 `custom` Provider
- `custom` Provider 的接入协议统一采用 `OpenAI Completions compatible`
- Provider 绑定单位是 `AgentRole`
- Provider 差异不得泄漏到上层业务流程逻辑

5. `输出结构化`
- Agent 输出必须转换为结构化领域对象
- 必须执行格式校验与错误处理
- 非法输出不得直接推进下一阶段

6. `执行与查询解耦`
- `LangGraph` 负责执行内核状态
- 领域对象与投影负责对外查询契约

## 8. 前端查询投影契约

### 8.1 左栏投影

左栏至少需要以下投影：
- `ProjectListItemProjection`
- `SessionListItemProjection`
- `ProjectDeliveryChannelProjection`

其中：
- `SessionListItemProjection.current_stage_type` 只允许取六个正式业务阶段之一，或在 `draft` 时为 `null`
- `SessionListItemProjection.status` 必须与产品语义一致，不暴露 `GraphThread.status`
- `ProjectDeliveryChannelProjection` 至少包含：
  - `project_id`
  - `delivery_channel_id`
  - `delivery_mode`
  - `readiness_status`
  - `readiness_message`
  - `credential_status`
  - `updated_at`

### 8.1.1 会话工作台聚合投影

`GET /api/sessions/{sessionId}/workspace` 对应的 `SessionWorkspaceProjection` 至少包含：
- `session`
- `project`
- `delivery_channel`
- `runs`
- `narrative_feed`
- `current_run_id`
- `current_stage_type`
- `composer_state`

其中：
- `runs` 必须按启动时间顺序返回同一 `Session` 下的全部 `PipelineRun`
- 后端不要求为前端专门建模 `Run Switcher` 对象，但必须返回足以支撑前端同页多 run 展示与导航的 run 级元数据
- `narrative_feed` 必须保留条目所属 `run_id`，以便前端在同一会话页面内做 run 分段渲染

`SessionWorkspaceProjection.runs[]` 中的 `RunSummaryProjection` 至少包含：
- `run_id`
- `attempt_index`
- `status`
- `trigger_source`
- `started_at`
- `ended_at`
- `current_stage_type`
- `is_active`

其中：
- `trigger_source` 直接服务于前端 run 分界头部中的“触发来源”展示
- `current_stage_type` 在审批等待或澄清等待时必须保持源阶段类型
- `is_active = true` 只允许在当前活动 run 上出现

`SessionWorkspaceProjection.composer_state` 至少包含：
- `mode`
- `is_input_enabled`
- `primary_action`
- `secondary_actions`
- `bound_run_id`

其中：
- `primary_action` 在 V1 只允许：`send`、`pause`、`resume`、`disabled`
- `secondary_actions` 至少支持：`pause`、`terminate`
- `bound_run_id` 必须始终指向当前活动 run；历史 run 不得改变 Composer 绑定目标

### 8.2 中栏 Narrative Feed 投影

Narrative Feed 顶层条目必须至少支持以下类型：
- `user_message`
- `stage_node`
- `approval_request`
- `control_item`
- `approval_result`
- `delivery_result`
- `system_status`

其中：
- `stage_node.stage_type` 只允许取六个正式业务阶段之一
- `control_item.control_type` 至少支持：`clarification_wait`、`rollback`、`retry`
- `system_status` 只用于 `failed` 与 `terminated` run 的尾部终态条目，不属于 `control_item.control_type`
- `Requirement Analysis` 阶段内的澄清问答挂载为阶段内部条目，不单独提升为顶层审批类条目
- 审批结果和交付结果以顶层条目出现
- 底层 graph node 事件不得直接作为顶层条目类型暴露给前端

### 8.3 执行结点投影

`ExecutionNodeProjection` 至少包含：
- `stage_run_id`
- `run_id`
- `stage_type`
- `status`
- `attempt_index`
- `started_at`
- `ended_at`
- `summary`
- `items`
- `metrics`

`items` 至少支持以下内部条目类型：
- `dialogue`
- `reasoning`
- `decision`
- `tool_call`
- `diff_preview`
- `result`

### 8.4 Inspector 投影

至少提供以下详情投影：
- `StageInspectorProjection`
- `ControlItemInspectorProjection`
- `DeliveryResultDetailProjection`

其中：
- `StageInspectorProjection.stage_type` 只允许六个正式业务阶段
- `ControlItemInspectorProjection.control_type` 只允许控制型条目语义
- `approval_result` 顶层条目不作为独立右栏对象时，其详情必须通过所属阶段 Inspector 中的关联审批信息读取

Inspector 投影必须满足以下总规则：
- Inspector 投影不是摘要 API，而是面向前端展示的 `后端原始信息公开盒子`
- 这里的“原始信息”指后端领域对象、`StageArtifact`、`RunControlRecord.payload_ref`、`ApprovalRequest.payload_ref`、`DeliveryRecord.result_ref` 等已标准化、已流通或已持久化的原始记录
- Inspector 投影必须以适合前端呈现的分组方式，近乎无损地暴露当前对象的 `input`、`process`、`output`、`artifacts` 与 `metrics`
- 前端不负责为 Inspector 回填关键事实；与当前对象直接相关的关键原始信息必须已经包含在 Inspector 投影或其稳定引用中
- 上述规则不等同于直接暴露 `LangGraph` 原始状态、原始 thread 对象或原始节点事件流；执行内核内部状态仍需先转换为领域层稳定记录后才能进入 Inspector 投影

`StageInspectorProjection` 必须至少按以下分组提供内容：
- `identity`
  至少包含阶段标识、所属 run、状态、开始时间、结束时间
- `input`
  至少包含本阶段接收的原始输入快照、上下文引用与前序产物引用
- `process`
  至少包含本阶段的原始过程记录，如推理、决策、工具调用、校验、diff、测试执行、评审或交付步骤记录
- `output`
  至少包含本阶段的完整结构化输出、结果快照与结果引用
- `artifacts`
  至少包含相关附件、变更引用、测试结果引用、审批结果引用或其他稳定引用
- `metrics`
  至少包含适用的全量量化指标

`ControlItemInspectorProjection` 必须至少按以下分组提供内容：
- `identity`
  至少包含控制条目标识、所属 run、控制类型与时间信息
- `input`
  至少包含控制动作接收的原始上下文与触发原因
- `process`
  至少包含控制动作的原始触发载荷、过程记录与历史尝试记录
- `output`
  至少包含控制动作产出的目标阶段、结果状态、终态说明或等价结果快照
- `artifacts`
  至少包含相关附件与稳定引用
- `metrics`
  至少包含适用的全量量化指标

`DeliveryResultDetailProjection` 必须至少按以下分组提供内容：
- `identity`
  至少包含交付结果标识、所属 run 与时间信息
- `input`
  至少包含最终交付结果接收的上游输入来源、交付快照与相关引用
- `process`
  至少包含与最终交付结果直接相关的原始交付过程记录，或指向 `delivery_integration` 过程记录的稳定引用
- `output`
  至少包含最终交付说明、最终变更结果、最终测试结论、最终评审结论与目标对象结果
- `artifacts`
  至少包含交付产物、分支、提交、MR/PR 与其他稳定引用
- `metrics`
  至少包含适用的全量量化指标

### 8.5 审批块投影

`approval_request` 投影至少包含：
- `run_id`
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
- `delivery_readiness_status`
- `delivery_readiness_message`
- `open_settings_action`
- `disabled_reason`

其中：
- 当当前 run 因暂停而暂时不可审批时，`is_actionable = false`，且 `disabled_reason` 必须返回“当前运行已暂停，恢复后继续等待审批”或等价明确信息

`approval_result` 顶层条目至少包含：
- `run_id`
- `approval_id`
- `approval_type`
- `decision`
- `reason`
- `created_at`
- `next_stage_type`

其中：
- `reason` 在 `Reject` 场景下必须返回用户拒绝理由；在 `Approve` 场景下允许为 `null`
- `next_stage_type` 用于表达本次审批结果生效后主链将进入的下一正式业务阶段；若为 `Reject`，则返回回退目标阶段

### 8.5.1 Run 时间线投影

`GET /api/runs/{runId}/timeline` 返回的 `RunTimelineProjection` 至少包含：
- `run_id`
- `session_id`
- `attempt_index`
- `trigger_source`
- `status`
- `started_at`
- `ended_at`
- `current_stage_type`
- `entries`

其中：
- `entries` 必须按发生时间顺序返回该 run 的全部顶层 Narrative Feed 条目
- `entries[].type` 只允许取：`user_message`、`stage_node`、`approval_request`、`control_item`、`approval_result`、`delivery_result`、`system_status`
- `RunTimelineProjection` 是单 run 视角的只读链路回放结构；其条目语义必须与 `SessionWorkspaceProjection.narrative_feed` 保持一致
- 若同一会话存在多个 run，`GET /api/runs/{runId}/timeline` 只返回目标 run 本身的链路条目，不拼接其他 run 内容

### 8.5.2 项目级交付配置查询与校验投影

`GET /api/projects/{projectId}/delivery-channel` 返回的 `ProjectDeliveryChannelDetailProjection` 至少包含：
- `project_id`
- `delivery_channel_id`
- `delivery_mode`
- `scm_provider_type`
- `repository_identifier`
- `default_branch`
- `code_review_request_type`
- `credential_ref`
- `credential_status`
- `readiness_status`
- `readiness_message`
- `last_validated_at`
- `updated_at`

`PUT /api/projects/{projectId}/delivery-channel` 的请求体至少支持：
- `delivery_mode`
- `scm_provider_type`
- `repository_identifier`
- `default_branch`
- `code_review_request_type`
- `credential_ref`

其规则如下：
- 当 `delivery_mode = demo_delivery` 时，允许只提交 `delivery_mode`
- 当 `delivery_mode = git_auto_delivery` 时，请求体必须提交全部 Git 自动交付所需字段
- 前端提交的是 `credential_ref`，后端返回的是 `credential_status` 与 `readiness_status`

`POST /api/projects/{projectId}/delivery-channel/validate` 的响应体至少包含：
- `readiness_status`
- `readiness_message`
- `credential_status`
- `validated_fields`
- `validated_at`

### 8.6 量化指标投影

所有适用执行结点至少支持以下通用量化指标：
- `duration_ms`
- `input_tokens`
- `output_tokens`
- `total_tokens`
- `attempt_index`

不同类型对象的专项指标必须按前端文档定义输出。

## 9. API 契约

功能一后端必须通过 REST API 暴露所有核心能力。V1 接口分为四类。

### 9.1 Project、Session、Template 与 Project Delivery Command API

至少提供以下命令接口：
- `POST /api/projects`
- `GET /api/projects`
- `PUT /api/projects/{projectId}/delivery-channel`
- `POST /api/projects/{projectId}/delivery-channel/validate`
- `POST /api/projects/{projectId}/sessions`
- `PUT /api/sessions/{sessionId}/template`
- `POST /api/sessions/{sessionId}/messages`
- `POST /api/pipeline-templates`
- `PATCH /api/pipeline-templates/{templateId}`
- `POST /api/pipeline-templates/{templateId}/save-as`
- `DELETE /api/pipeline-templates/{templateId}`
- `POST /api/providers`
- `PATCH /api/providers/{providerId}`

`POST /api/sessions/{sessionId}/messages` 只允许两类语义：
- 新需求输入
- 澄清回复

当消息语义为 `new_requirement` 时，只允许在 `Session.status = draft` 且 `current_run_id = null` 时调用；后端必须在同一服务事务中基于当前 `selected_template_id` 创建 `PipelineRun`、模板快照、`GraphDefinition`、首条消息事件与初始 `requirement_analysis` StageRun。

当消息语义为 `clarification_reply` 时，只允许在当前会话处于 `waiting_clarification` 且当前阶段为 `requirement_analysis` 时调用；后端必须把补充信息回写到当前澄清中断并恢复同一个 `GraphThread`。

项目级 `DeliveryChannel` 接口必须满足以下规则：
- `GET /api/projects/{projectId}/delivery-channel` 返回 `ProjectDeliveryChannelDetailProjection`
- `PUT /api/projects/{projectId}/delivery-channel` 返回保存后的最新 `ProjectDeliveryChannelDetailProjection`
- `POST /api/projects/{projectId}/delivery-channel/validate` 不修改已固化到历史 run 的交付快照，只对当前项目最新配置执行校验并返回校验结果
- 当 `delivery_mode = git_auto_delivery` 且 `credential_ref` 无法解析为可用凭据时，`credential_status` 必须返回 `invalid` 或 `unbound`，且 `readiness_status` 不得返回 `ready`

### 9.2 Run、Approval 与 Control Command API

至少提供以下命令接口：
- `POST /api/sessions/{sessionId}/runs`
- `POST /api/runs/{runId}/pause`
- `POST /api/runs/{runId}/resume`
- `POST /api/runs/{runId}/terminate`
- `POST /api/approvals/{approvalId}/approve`
- `POST /api/approvals/{approvalId}/reject`

其中：
- `POST /api/sessions/{sessionId}/runs` 对应显式重新尝试，不对应暂停后的继续执行；后端必须确认旧 run 的 `GraphThread` 已处于终态，创建新的 `PipelineRun` 与新的 `GraphThread`，不得恢复或复用旧 `GraphThread`
- `POST /api/runs/{runId}/pause` 必须暂停当前 `GraphThread` 并保存可恢复 checkpoint
- `POST /api/runs/{runId}/resume` 必须从最近 checkpoint 恢复同一个 `GraphThread`；若该 run 在暂停前停留于审批等待，则恢复后必须重新进入同一个 `waiting_approval` 检查点
- `POST /api/approvals/{approvalId}/approve` 与 `POST /api/approvals/{approvalId}/reject` 在 run 未暂停时，必须通过恢复对应 `GraphInterrupt` 来继续执行图
- `POST /api/approvals/{approvalId}/approve` 与 `POST /api/approvals/{approvalId}/reject` 在 run 已暂停时，必须被拒绝，并返回明确的“当前运行已暂停，恢复后继续等待审批”错误信息

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
- `GET /api/control-records/{controlRecordId}`
- `GET /api/delivery-records/{deliveryRecordId}`
- `GET /api/preview-targets/{previewTargetId}`

其中：
- `GET /api/sessions/{sessionId}/workspace` 返回完整会话工作台视图，而不是 raw graph state
- `GET /api/sessions/{sessionId}/workspace` 必须返回 `SessionWorkspaceProjection`，其中包含会话级状态、项目级交付配置摘要、多 run 摘要列表、按 run 归属可分段的 Narrative Feed，以及当前 Composer 所需状态
- `GET /api/runs/{runId}` 返回领域层的 run 状态摘要，而不是 raw graph thread 详情
- `GET /api/runs/{runId}` 至少返回 `RunSummaryProjection` 的全部字段，以及该 run 的 `current_stage_run_id`
- `GET /api/runs/{runId}/timeline` 必须返回 `RunTimelineProjection`
- `GET /api/stages/{stageRunId}/inspector` 必须返回按 `input`、`process`、`output`、`artifacts`、`metrics` 分组的完整阶段 Inspector 投影
- `GET /api/control-records/{controlRecordId}` 用于控制型条目的详情查看
- `GET /api/control-records/{controlRecordId}` 返回的详情不得退化为仅摘要文本；必须包含与该控制条目直接相关的原始上下文、过程记录、结果与引用
- `GET /api/delivery-records/{deliveryRecordId}` 必须返回完整交付结果详情，不得只返回最终摘要

### 9.4 API 文档契约

后端必须把 API 文档作为正式交付物提供。

至少提供以下文档接口：
- `GET /api/openapi.json`
- `GET /api/docs`

并满足以下规则：
- `GET /api/openapi.json` 必须返回与当前服务实现一致的 machine-readable OpenAPI 文档
- `GET /api/docs` 必须提供 human-readable API 文档页面
- OpenAPI 文档必须覆盖功能一全部核心 REST 接口，包括 `Project`、`Session`、`PipelineTemplate`、`Provider`、项目级 `DeliveryChannel`、`PipelineRun` 生命周期、审批、控制条目、Inspector、交付结果与预览目标查询
- OpenAPI 文档必须覆盖 `GET /api/sessions/{sessionId}/events/stream` 的事件流端点及其事件载荷结构
- API 文档必须定义请求参数、请求体 Schema、响应体 Schema、枚举值、通用错误响应与关键接口示例
- 运行接口与 OpenAPI 文档必须同版本交付，不允许文档落后于已发布接口

## 10. 实时更新契约

V1 的实时更新机制定义为：

`快照查询 + 会话级领域事件流`

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

`event_type` 在 V1 至少支持：
- `session_created`
- `session_message_appended`
- `pipeline_run_created`
- `stage_started`
- `stage_updated`
- `clarification_requested`
- `clarification_answered`
- `approval_requested`
- `approval_result`
- `control_item_created`
- `delivery_result`
- `system_status`
- `session_status_changed`

`payload` 必须按 `event_type` 输出对应结构，至少满足以下规则：
- `session_created`
  - 至少包含：`session`
- `session_message_appended`
  - 至少包含：`message_item`
- `pipeline_run_created`
  - 至少包含：`run`
- `stage_started`
  - 至少包含：`stage_node`
- `stage_updated`
  - 至少包含：`stage_node`
- `clarification_requested`
  - 至少包含：`run_id`、`stage_run_id`、`control_item`
- `clarification_answered`
  - 至少包含：`run_id`、`stage_run_id`、`message_item`
- `approval_requested`
  - 至少包含：`approval_request`
- `approval_result`
  - 至少包含：`approval_result`
- `control_item_created`
  - 至少包含：`control_item`
- `delivery_result`
  - 至少包含：`delivery_result`
- `system_status`
  - 至少包含：`system_status`
- `session_status_changed`
  - 至少包含：`session_id`、`status`、`current_run_id`、`current_stage_type`

上述 `payload` 中出现的 `message_item`、`stage_node`、`approval_request`、`approval_result`、`control_item`、`delivery_result`、`system_status`，其字段语义必须与查询接口返回的同名投影条目保持一致；SSE 只允许传递增量，不允许定义第二套独立产品语义。

前端收到增量事件后，必须能够：
- 追加 Narrative Feed 条目
- 更新会话状态
- 更新当前审批块状态
- 更新阶段结点内容与量化指标
- 在需要时重新拉取 Inspector 详情

原始 `LangGraph` 事件流不得直接暴露给前端。

## 11. 领域事件模型

功能一 V1 的事件模型分为两层：

### 11.1 执行图内部事件

执行图内部事件至少包括：
- `GraphCompiled`
- `GraphThreadStarted`
- `GraphNodeStarted`
- `GraphNodeCompleted`
- `GraphCheckpointSaved`
- `GraphInterrupted`
- `GraphResumed`
- `GraphFailed`

执行图内部事件用于驱动内部执行与审计，不直接作为前端产品事件暴露。

### 11.2 对外领域事件

功能一 V1 至少定义以下关键领域事件：
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
- `ApprovalRequested`
- `ApprovalApproved`
- `ApprovalRejected`
- `RollbackTriggered`
- `RetryTriggered`
- `CodePatchGenerated`
- `TestsGenerated`
- `TestsExecuted`
- `TestGapAnalyzed`
- `ReviewCompleted`
- `DeliveryPrepared`
- `CommitCreated`
- `MergeRequestCreated`
- `RunPaused`
- `RunResumed`
- `RunCompleted`
- `RunFailed`
- `RunTerminated`

对外领域事件必须满足以下规则：
- 事件既服务于查询投影，也服务于前端增量更新
- 事件必须能映射到 Narrative Feed 条目或状态变化
- 审批结果与澄清结果必须进入同一条会话事件流

## 12. 工作区、工具与交付适配

后端必须通过统一工具接口暴露能力，分为两类。

工具协议必须先于具体工具实例稳定。`ToolProtocol` 至少定义工具名称、类别、输入 Schema、结果载荷、错误结构、审计引用和可绑定的工具描述。LangGraph runtime、LangChain Provider adapter 与后续交付适配器只能依赖该抽象协议和工具注册契约；不得直接绑定尚未实现的具体 delivery tool 实例。

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

1. 能创建项目、会话、模板快照、执行图定义与完整 `PipelineRun`。
2. 能在 `Requirement Analysis` 阶段内部处理多轮需求澄清。
3. 不把需求澄清建模为人工审批。
4. 只在 `Solution Design` 与 `Code Review` 创建正式 `ApprovalRequest`。
5. 审批 `Reject` 理由能够进入后续上下文并驱动回退重新执行。
6. 能为前端输出项目列表、会话列表、Narrative Feed、Inspector、审批块、控制型条目和交付结果投影，且 Inspector 投影包含完整输入、过程、输出、引用与量化信息。
7. 能通过 SSE 提供会话级领域事件流。
8. 能在历史会话中回放结构化产物、审批记录、回退记录与交付结果。
9. 能在代码评审失败时执行受控自动回归。
10. 能列出系统模板与用户模板，并在不破坏固定主干阶段的前提下编辑允许字段。
11. 能把模板修改保存为覆盖现有用户模板、另存为新用户模板或删除用户模板，并在运行开始时固化模板快照和执行图定义。
12. 能在项目级配置默认 `DeliveryChannel`，并在最终人工审批通过后、进入 `Delivery Integration` 前固化 `delivery_channel_snapshot_ref`。
13. 能提供与运行接口一致的 `OpenAPI` 文档 JSON 与可读 API 文档页。
14. 当 `delivery_mode = demo_delivery` 时，能生成仅用于展示的分支信息与提交说明预览，而不执行真实 Git 写操作。
15. 当 `delivery_mode = git_auto_delivery` 时，能自动创建分支、创建提交并发起 MR/PR。
16. 能为功能二保留 `ChangeSet`、`ContextReference`、`PreviewTarget`、`DeliveryRecord` 的复用边界。
