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
- `LangGraph + LangChain` 必须作为功能一 V1 的正式执行内核，其中 `LangGraph` 负责六阶段主链、条件路由、人工中断、检查点与恢复，`LangChain` 负责模型接入、消息对象、工具绑定与结构化输出
- 阶段内部动态执行必须通过 stage-scoped runner 承载；V1 的复杂研发阶段采用单 Agent ReAct 循环，不通过嵌套业务子图表达每个内部动作
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
  承载领域事件记录与 Narrative Feed 投影来源数据
- `log.db`
  承载平台级运行日志轻量索引、安全审计记录、日志文件位置引用、载荷摘要、裁剪状态与跨层关联标识

功能一 V1 必须同时使用本地日志文件作为运行时观察载体：
- `.runtime/logs/app.jsonl`
  承载服务级运行日志
- `.runtime/logs/runs/{run_id}.jsonl`
  承载单次 run 的运行日志
- `.runtime/logs/audit.jsonl`
  承载安全审计日志的本地文件副本

上述 `.runtime/logs` 表示平台后端服务的运行数据目录，不表示被操作项目的业务工作区目录。V1 本地部署时如果该目录落在平台仓库路径下，后端必须把该目录视为运行期私有数据，默认排除出项目文件索引、工作区工具扫描、代码变更 diff、Git 自动交付与交付结果统计。

平台运行数据根目录必须可配置；未配置时默认使用平台服务当前运行目录下的 `.runtime`。后端启动时必须确保运行数据目录和日志子目录存在且可写；若目录无法创建或不可写，后端不得进入可接受用户命令的正常运行状态。

该存储策略必须满足以下规则：
- 不允许把全部领域对象、运行记录、执行图状态与事件流混入同一个 `SQLite` 文件
- `graph.db` 只承载执行内核相关对象，不直接充当对前端暴露的产品级查询真源
- `event.db` 记录可驱动产品投影和状态回放的领域事实
- 本地 JSONL 日志文件记录平台运行观察事实与审计事实的运行时文本流
- `log.db` 记录可查询的轻量索引、审计台账、文件位置、裁剪状态和关联标识
- `event.db` 与 `log.db` 不得互相替代
- `log.db` 中的日志记录不得反向作为 `PipelineRun`、`StageRun`、`ApprovalRequest`、`DeliveryRecord`、Narrative Feed 或 Inspector 的产品状态真源
- 本地日志文件不得作为产品状态真源，也不得由前端直接读取
- 本地日志文件不得作为 Agent、工具或交付适配器的默认可读业务上下文；只有诊断工具或后端日志查询能力可以按日志审计契约读取
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
- `LangGraph` 必须用于表达固定业务主链、条件边、人工中断点、检查点与恢复，不得把前端产品语义绑定到 raw graph state
- `LangChain` 必须用于统一封装模型供应商、消息对象、`ChatOpenAI` 兼容接入、`bind_tools()` 工具绑定与结构化输出
- Agent 内部工具调用必须使用模型原生 tool/function calling；不得通过自由文本、正则或字符串解析方式模拟工具调用
- 与模型供应商、远端托管平台或其他 HTTP 服务的交互必须优先使用 `httpx`
- 与工作区、构建、测试和 Git 交付相关的受控执行必须优先使用标准库 `subprocess` 和本地 `git CLI`
- `SSE` 实现必须优先采用 `FastAPI` / `Starlette` 原生流式响应能力；只有在原生能力无法满足协议与维护要求时，才允许引入小型专用补充库

### 2.1.2 技术选型原则与禁止项

功能一 V1 的后端技术选型必须遵循以下原则：
- 以成熟、主流、文档完善、社区使用广泛的通用库为优先，而不是以抽象完整性或框架新颖性为优先
- 以降低项目开发期的理解成本、调试成本、联调成本与维护成本为优先，而不是为潜在远期扩展预先引入额外基础设施
- `LangGraph state` 是执行内核恢复真源，`Project`、`Session`、`PipelineRun`、`StageRun`、`ApprovalRequest`、`StageArtifact`、`DeliveryRecord` 是产品级领域真源，两者必须同时存在且职责分离
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
- 记录平台级运行日志、安全审计记录、工具执行诊断、模型调用诊断与系统错误诊断
- 提供前端控制台所需的查询投影与实时更新能力
- 管理工作区读取、代码修改、命令执行、测试运行与交付通道适配
- 为功能二保留 `ChangeSet`、`ContextReference`、`PreviewTarget`、`DeliveryRecord` 的复用边界

## 4. 总体架构

功能一后端采用以下基础结构：

`FastAPI Gateway / Control Plane + LangGraph Runtime Plane + Stage Agent Runtime Plane + Context Management Plane + Projection / Event Plane + Observability / Audit Plane + Workspace / Delivery Adapter`

架构边界如下：
- `Gateway / Control Plane` 负责 REST API、会话管理、模板管理、Provider 管理、审批命令与查询聚合
- `LangGraph Runtime Plane` 负责六阶段业务主链、条件路由、人工中断、检查点、暂停恢复与重新尝试边界
- `Stage Agent Runtime Plane` 负责在单个正式业务阶段内驱动 stage-scoped Agent 执行，包括 ReAct 循环、模型调用、工具调用、结构化输出校验与阶段结果生成
- `Context Management Plane` 负责在每次阶段执行或模型调用前解析、组装、排序、裁剪、折叠、压缩并留痕上下文
- `Projection / Event Plane` 负责把执行图事件翻译为领域事件、Narrative Feed 条目与查询投影
- `Observability / Audit Plane` 负责记录运行日志、审计日志、诊断上下文、关联标识与日志查询投影
- `Workspace & Delivery Adapter` 负责与代码仓库、测试环境和托管平台交互

### 4.1 系统模块划分

功能一后端至少包含以下核心模块：

1. `Pipeline Template Registry`
负责管理流程模板、固定业务阶段骨架、阶段角色绑定、审批检查点配置与自动回归配置。

2. `Graph Compiler`
负责把模板快照编译成 `GraphDefinition`，并生成六阶段主链、阶段执行模式、条件边、审批中断点与交付分流定义。

3. `Run Lifecycle Service`
负责创建 `PipelineRun`、启动 `GraphThread`、维护 run 状态、处理暂停恢复终止与重新尝试。

4. `LangGraph Runtime Engine`
负责执行六阶段主链、保存检查点、处理中断恢复、驱动阶段节点并维护 `GraphThread`。

5. `Stage Agent Runtime`
负责阶段内 Agent 执行，V1 中包括结构化 LLM 调用、stage-scoped ReAct 循环、validation pass、结构化输出修复和阶段产物提交。

6. `Context Management Service`
负责构建 `ContextEnvelope`、生成 `ContextManifest`、执行上下文尺寸守卫、触发上下文压缩并把上下文使用记录写入阶段过程记录。

7. `Approval & Interrupt Service`
负责创建审批对象、处理中断载荷、记录审批决策、回写拒绝理由并恢复执行图。

8. `Run Context / Artifact Store`
负责持久化运行上下文、阶段输入输出、结构化产物与共享引用。

9. `Projection & Event Translator`
负责把执行图内部事件翻译成领域事件、Narrative Feed 条目、Inspector 投影与会话级状态摘要。

10. `Log & Audit Service`
负责统一采集、裁剪、关联、持久化和查询平台运行日志、安全审计记录、工具执行日志、模型调用日志、外部命令日志与错误诊断记录。

11. `LLM Provider Adapter`
负责通过 LangChain `ChatOpenAI` 兼容接口统一封装模型供应商接入、模型对象创建、tool/function calling 绑定与结构化输出声明；不负责业务阶段流转和上下文拼装。

12. `Workspace & Tool Service`
负责工作区隔离、文件读取、代码修改、命令执行、diff 生成与工具接口管理。

13. `SCM & Delivery Adapter`
负责封装本地 Git、远端托管平台、交付通道与 MR/PR 创建能力。

14. `REST API + Query Layer`
负责暴露命令接口、查询接口、事件流接口与 OpenAPI 文档。

### 4.2 实施原则

后端实现必须遵循以下原则：
- `图驱动执行`
  正式业务主链、阶段切换、审批中断、回退路由、自动回归路由、暂停恢复与重新尝试边界必须由显式执行图表达；阶段内部动态工作由 stage runner 和阶段过程记录表达。
- `领域契约先于框架细节`
  `LangGraph` 是执行内核，不是产品 API；产品级外部契约仍由领域对象和投影定义。
- `产物驱动`
  后续阶段只能依赖持久化产物和契约化上下文，不允许依赖运行期隐式记忆。
- `上下文显式管理`
  Agent 每次模型调用前必须通过 Context Management 组装上下文；上下文来源、排序、裁剪、折叠、压缩和传输结果必须形成可回看的过程记录。
- `API First`
  前端控制台只能通过命令接口、查询接口和事件流消费后端能力。
- `工具统一抽象`
  文件系统、命令执行、分支准备和代码评审请求都必须通过统一工具协议暴露，并通过模型原生 tool/function calling 触发。
- `日志审计独立建模`
  运行日志、安全审计与诊断记录必须通过专门的日志审计契约采集和查询，不得散落为各模块私有文本输出。
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
- `runtime_capabilities`
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
- 后端运行时模型对象必须由 `LLMProviderAdapter` 通过 LangChain `ChatOpenAI` 兼容接口创建
- 内置 Provider 与自定义 Provider 的协议差异只能存在于 `LLMProviderAdapter` 内部，不得泄漏到阶段编排、上下文管理、工具调用或查询投影
- `LLMProvider` 运行时能力快照必须至少表达 `context_window_tokens`、`max_output_tokens`、`supports_tool_calling`、`supports_structured_output`、`supports_native_reasoning`
- 需要 ReAct 或工具调用的阶段不得绑定不支持 tool/function calling 的 Provider；模板保存或 run 启动时必须拒绝不兼容绑定
- 上下文压缩、结构化输出修复与 validation pass 使用同一 Provider 接入抽象，并通过 `model_call_type` 区分调用目的

6. `GraphDefinition`
表示由某次模板快照编译得到的正式执行图定义，至少包含：
- `graph_definition_id`
- `template_snapshot_ref`
- `graph_version`
- `stage_nodes`
- `stage_execution_modes`
- `interrupt_policy`
- `retry_policy`
- `delivery_routing_policy`
- `created_at`

`GraphDefinition` 必须满足以下规则：
- 每次 `PipelineRun` 启动前都必须生成一份绑定该次模板快照的 `GraphDefinition`
- `GraphDefinition` 必须显式表达六个正式业务阶段对应的主链节点、条件边、审批中断点、自动回归路由与交付模式分流
- `GraphDefinition` 不表达每个阶段内部的全部 ReAct 步骤、工具调用、文件编辑或模型调用；这些动态过程由 `StageRun`、`StageArtifact.process` 与执行日志承载
- `stage_execution_modes` 必须记录每个正式业务阶段采用的执行模式，V1 至少支持：`structured_llm`、`read_only_react`、`write_enabled_react`、`write_execute_react`、`review_react`、`deterministic_adapter`
- `Solution Validation` 不作为独立 `GraphDefinition` 阶段节点；它是 `solution_design` 阶段执行模式中的 validation pass
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
- `graph_node_key`
- `stage_execution_mode`

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
- `stage_execution_mode` 必须来自本次 `GraphDefinition.stage_execution_modes`
- 阶段内部 ReAct iteration、tool/function call、模型调用、上下文压缩、文件编辑与结构化输出修复不创建新的 `StageRun`

### 5.3 产物、控制与审批对象

12. `StageArtifact`
表示阶段级结构化产物，是阶段流转、审批展示与历史回看的基础容器。

`StageArtifact` 必须满足以下规则：
- 作为运行期结构化产物、阶段输入输出快照与稳定引用目标的统一索引对象
- 默认持久化在 `runtime.db`
- 如无特别说明，`StageRun.input_ref`、`StageRun.output_ref`、`GraphInterrupt.payload_ref` 与 `ApprovalRequest.payload_ref` 默认指向 `StageArtifact` 或其派生快照记录
- `StageArtifact` 可通过 `artifact_ref`、`attachments_ref`、`delivery_record_ref` 等查询层稳定引用被前端或其他领域对象间接访问
- `StageArtifact` 必须能够承载供 Inspector 打开的原始阶段信息，包括输入快照、过程记录、输出快照、附件引用与量化信息
- `StageArtifact.process` 必须承载标准化阶段过程记录，而不是只保存最终摘要
- `StageArtifact.process` 在 V1 中至少支持以下过程记录类型：`context_manifest`、`reasoning_trace`、`decision_trace`、`tool_trace`、`model_call_trace`、`file_edit_trace`、`validation_trace`、`compressed_context_block`、`structured_output_repair_trace`
- `StageArtifact.process` 中的过程记录可以引用完整大载荷、工具结果、日志定位或附件，但不得只把关键过程信息留在运行日志中
- `StageArtifact.process` 中的上下文压缩块、工具观察预览和截断片段不得替代其对应原始记录或稳定引用

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
表示跨阶段、跨运行、跨工具观察的上下文引用对象，是 Context Management、阶段产物、代码变更和未来功能二页面驱动改动之间共享的稳定引用边界。

`ContextReference` 在功能一 V1 中至少必须能够表达：
- 用户原始需求引用
- 结构化需求与验收标准引用
- 澄清结论引用
- 方案产物引用
- 审批反馈引用
- 工具观察引用
- 文件路径、目录路径、文件片段与文件版本引用
- diff、测试结果、评审意见与变更集引用
- 上下文压缩块的完整原始过程引用

未来必须能够扩展：
- `page_selection`
- `dom_anchor`
- `preview_snapshot`

`ContextReference` 必须满足以下规则：
- 不得用自由文本替代可解析引用；每个引用必须包含可定位的来源类型、来源对象标识或路径信息
- 引用本身不复制完整大载荷；完整内容应由 `StageArtifact`、工具结果、附件、工作区文件或日志定位等稳定来源提供
- `ContextReference` 可以跨阶段传递，但新的 `PipelineRun` 不得继承旧 run 未交付工作区改动引用
- `ContextReference` 不替代 `StageArtifact`、`ChangeSet`、`DeliveryRecord` 或日志审计对象，只表达上下文来源关系

20. `PreviewTarget`
表示可供前端查询的预览对象。V1 只定义对象和查询接口，不实现预览启动与热更新。

### 5.5 平台日志审计对象

21. `RunLogEntry`
表示一次平台运行观察记录的结构化轻索引，用于后端排障、诊断分析、性能分析与执行复盘，至少包含：
- `log_id`
- `session_id`
- `run_id`
- `stage_run_id`
- `approval_id`
- `delivery_record_id`
- `graph_thread_id`
- `source`
- `category`
- `level`
- `message`
- `log_file_ref`
- `line_offset`
- `line_number`
- `log_file_generation`
- `payload_ref`
- `payload_excerpt`
- `payload_size_bytes`
- `redaction_status`
- `correlation_id`
- `trace_id`
- `span_id`
- `parent_span_id`
- `created_at`

`RunLogEntry.category` 在功能一 V1 中至少支持：
- `runtime`
- `agent`
- `tool`
- `model`
- `workspace`
- `delivery`
- `api`
- `security`
- `error`

`RunLogEntry.level` 在功能一 V1 中至少支持：
- `debug`
- `info`
- `warning`
- `error`
- `critical`

`RunLogEntry` 必须满足以下规则：
- `session_id`、`run_id`、`stage_run_id`、`approval_id`、`delivery_record_id`、`graph_thread_id` 允许按上下文为空，但凡运行上下文已经存在，必须写入对应关联标识
- `message` 必须是便于排障阅读的短文本，不得承载完整大载荷
- 完整日志原文必须优先写入本地 JSONL 日志文件，并通过 `log_file_ref` 与 `line_offset` 建立定位关系
- `log_file_ref` 必须是相对平台运行数据目录的稳定文件路径，不得保存本机绝对路径作为主引用
- `line_offset` 表示该 JSONL 记录在目标日志文件中的起始字节偏移；`line_number` 表示该记录在目标日志文件中的行号
- `log_file_generation` 表示日志文件轮转后的代际或文件名标识；未发生轮转时允许为空
- 命令输出、模型请求响应、工具输入输出与异常堆栈必须先裁剪或摘要化；V1 允许只在本地日志文件中保留裁剪后的文本，不要求把完整载荷写入 `log.db`
- `payload_ref` 用于指向额外结构化载荷或后续日志存储位置；V1 不要求为每条运行日志创建独立 `LogPayload`
- 日志记录必须追加写入，不得通过更新原记录改写历史事实；如需修正分类或说明，必须追加新的修正日志
- 日志记录不得作为产品状态推进的输入，不得驱动 `PipelineRun.status`、`StageRun.status`、审批状态或交付状态流转

22. `AuditLogEntry`
表示一次平台审计记录，用于追踪用户动作、系统控制动作、安全敏感动作、配置变更与交付动作，至少包含：
- `audit_id`
- `actor_type`
- `actor_id`
- `action`
- `target_type`
- `target_id`
- `session_id`
- `run_id`
- `stage_run_id`
- `approval_id`
- `delivery_record_id`
- `request_id`
- `correlation_id`
- `result`
- `reason`
- `metadata_ref`
- `created_at`

`AuditLogEntry.actor_type` 在功能一 V1 中至少支持：
- `user`
- `system`
- `agent`
- `tool`

`AuditLogEntry.result` 在功能一 V1 中至少支持：
- `accepted`
- `rejected`
- `succeeded`
- `failed`
- `blocked`

`AuditLogEntry` 必须覆盖以下动作：
- 会话创建、首条需求提交、澄清回复提交
- run 创建、暂停、恢复、终止、重新尝试与运维重启
- 审批提交、审批拒绝、审批因暂停或状态不匹配被拒绝
- 模板创建、覆盖、另存、删除与运行快照固化
- Provider 创建、修改与凭据引用变更
- 项目级 `DeliveryChannel` 修改、校验与运行交付快照固化
- 工作区写入、文件编辑、命令执行、测试执行、Git 分支创建、提交创建与 MR/PR 创建
- 权限、凭据、路径、外部服务与交付相关的安全敏感失败

`AuditLogEntry` 必须满足以下规则：
- 审计记录必须追加写入，不得物理覆盖或静默删除
- 审计记录必须保存动作主体、动作目标、动作结果与原因摘要
- 对用户可触发的命令接口，后端必须为成功、失败与被拒绝三类结果写入审计记录
- 对系统自动执行的高影响动作，后端必须以 `actor_type = system`、`agent` 或 `tool` 写入审计记录
- 审计记录不得替代领域对象；例如审批提交仍必须创建 `ApprovalDecision`，审计记录只证明该命令何时由谁触发以及结果如何

23. `LogPayload`
表示日志或审计记录可选引用的结构化载荷摘要或后续存储位置，至少包含：
- `payload_id`
- `payload_type`
- `storage_ref`
- `summary`
- `content_hash`
- `redaction_status`
- `size_bytes`
- `created_at`

`LogPayload.payload_type` 在功能一 V1 中至少支持：
- `tool_input`
- `tool_output`
- `model_request`
- `model_response`
- `command_output`
- `exception`
- `http_request`
- `http_response`
- `audit_metadata`

`LogPayload.redaction_status` 在功能一 V1 中至少支持：
- `not_required`
- `redacted`
- `blocked`

`LogPayload` 必须满足以下规则：
- 载荷写入前必须完成敏感信息裁剪或阻断
- 明文凭据、访问令牌、API Key、私钥、Cookie、授权头与本机敏感路径不得进入可查询日志载荷
- 当载荷因安全策略不能保存时，必须写入 `redaction_status = blocked` 的占位记录，并保留阻断原因摘要
- 大文本、命令输出和模型响应必须支持长度上限与截断标记，不得无界写入 SQLite
- `content_hash` 用于辅助完整性校验和重复排查，不作为安全签名替代
- V1 的 `LogPayload` 是可选扩展对象；基础运行日志不得依赖 `LogPayload` 才能被本地检查

24. `TraceContext`
表示跨 API、run、stage、graph node、tool、model call 与 delivery action 的关联上下文，至少包含：
- `trace_id`
- `correlation_id`
- `request_id`
- `session_id`
- `run_id`
- `stage_run_id`
- `approval_id`
- `delivery_record_id`
- `graph_thread_id`
- `created_at`

`TraceContext` 必须满足以下规则：
- 每个外部 API 请求必须具备 `request_id`
- 每个 `PipelineRun` 必须具备贯穿该 run 的 `trace_id`
- 同一用户动作触发的领域事件、运行日志、审计日志与查询投影更新必须共享可追踪的 `correlation_id`
- 工具调用、模型调用、命令执行和交付动作必须继承当前 `trace_id` 与 `correlation_id`
- 当后台恢复、运维重启或重新尝试创建新的执行上下文时，必须记录新旧 `trace_id` 与 `run_id` 的关联关系

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
- `Solution Validation` 是 `solution_design` 阶段内部的 validation pass，不形成独立 `StageRun`
- `solution_design_approval` 与 `code_review_approval` 是固定审批中断点，位于对应源阶段完成之后，不属于正式业务阶段
- 回退、重试、暂停、恢复与终止属于运行控制语义，不属于正式业务阶段

### 6.2 模板到执行图的编译规则

模板编译必须满足以下规则：
- 每次 `PipelineRun` 启动前，必须基于该次模板快照编译出一份 `GraphDefinition`
- `GraphDefinition` 必须显式表达六个正式业务阶段对应的主链节点、条件边、固定审批中断点、自动回归路由与交付分流
- `GraphDefinition` 必须为每个正式业务阶段记录 `stage_execution_mode`
- `Requirement Analysis` 阶段必须支持“分析 -> 需要澄清时中断 -> 恢复后继续分析”的同阶段继续执行语义
- `Solution Design` 阶段必须支持“方案生成 -> validation pass -> 校验失败后在同一阶段重新生成 -> 校验通过进入审批中断”的同阶段订正语义
- `Code Generation`、`Test Generation & Execution`、`Code Review` 必须保持业务阶段串行推进
- `Code Review` 完成后必须由主链条件边决定是否触发自动回归并回到 `Code Generation`
- `Delivery Integration` 必须由主链条件边按交付模式分流到对应交付适配器
- 阶段内部 ReAct iteration、tool/function call、模型调用、文件编辑、上下文压缩与结构化输出修复不进入 `GraphDefinition`；这些过程必须通过 `StageArtifact.process`、运行日志和审计记录留痕
- 图编译结果必须记录稳定的 `graph_node_key` 到 `stage_type` 映射关系

### 6.3 Requirement Analysis 生命周期

`Requirement Analysis` 必须按以下规则运行：
- 接收用户原始需求输入
- 产出结构化需求、验收标准、约束与待确认事项
- 当信息不足时，创建 `ClarificationRecord` 与 `GraphInterrupt(type=clarification_request)`，并把 `PipelineRun.status` 与 `StageRun.status` 投影为 `waiting_clarification`
- 前端通过会话消息接口提交补充信息
- 补充信息回写到同一个业务阶段上下文并恢复同一个 `GraphThread`
- 本阶段恢复执行后继续分析，直到产出完整结果
- 本阶段默认采用 `structured_llm` 执行模式；当需要读取代码库上下文时，允许受控使用只读工具辅助分析
- 本阶段产生的推理片段、澄清判断、上下文引用和最终结构化输出必须进入 `StageArtifact`

本阶段禁止创建 `ApprovalRequest`。

### 6.4 Solution Design 生命周期

`Solution Design` 必须按以下规则运行：
- 本阶段默认采用 `read_only_react` 执行模式，通过只读工具读取仓库结构、关键文件、相关 API 与前序产物
- 本阶段必须先产出技术方案、影响范围、关键设计决策、文件变更清单、接口设计与风险分析
- 本阶段必须执行 validation pass，对方案合理性、需求覆盖、影响范围、接口设计、代码安全与测试充分性进行独立校验
- 方案校验结果必须作为 `Solution Design` 阶段产物的一部分持久化
- 校验失败时，不得创建新的独立 `Solution Validation` 阶段；系统必须依据校验结论在同一个 `solution_design` 阶段内订正方案
- 校验通过后，创建 `ApprovalRequest(type=solution_design_approval)` 与对应 `GraphInterrupt`
- 创建审批请求后，当前 `solution_design` 的 `StageRun.status` 必须置为 `waiting_approval`
- 审批通过后，进入 `Code Generation`
- 审批拒绝后，记录拒绝理由并回到 `Solution Design`
- 本阶段的架构分析、设计取舍、validation pass、工具观察、上下文清单和压缩块必须进入 `StageArtifact.process`

### 6.5 Code Generation 到 Code Review 生命周期

`Code Generation`、`Test Generation & Execution`、`Code Review` 必须保持正式业务阶段串行执行：
- 先执行代码生成
- 再执行测试生成与执行
- 最后执行代码评审

`Code Generation` 必须满足以下规则：
- 本阶段默认采用 `write_enabled_react` 执行模式，V1 只使用单 Agent ReAct，不引入 subagent
- 本阶段必须基于已批准或当前有效的技术方案、需求产物、上下文引用和目标仓库工作区执行
- 文件改写前必须读取当前文件内容或具备等价的文件版本引用
- 文件写入、编辑、diff 生成与变更记录必须通过受控 workspace tool 完成
- `ChangeSet` 必须由实际工作区 diff、文件编辑记录和上下文引用计算或构建，不得只由模型自由文本声明
- 每个文件编辑必须形成可追踪的 `file_edit_trace` 或等价过程记录

`Test Generation & Execution` 必须满足以下规则：
- 本阶段默认采用 `write_execute_react` 执行模式
- 本阶段必须基于代码变更集、需求验收标准和相关上下文引用生成或修改测试
- 测试命令执行必须通过受控 shell tool 完成
- 测试 stdout / stderr、退出码、失败项、修复尝试和测试缺口必须形成结构化过程记录或稳定引用

`Code Review` 必须满足以下规则：
- 本阶段默认采用 `review_react` 执行模式，只允许读取方案、变更集、测试结果、相关文件和必要上下文
- 本阶段必须从正确性、安全性、规范性、需求覆盖、测试充分性和交付风险等维度形成评审报告
- 评审报告必须包含问题列表、严重程度、证据引用和修复要求
- 自动回归判定必须基于评审证据，而不是模型任意继续优化的偏好

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
- 本阶段采用 `deterministic_adapter` 执行模式；模型可辅助生成说明文本、提交信息预览或交付摘要，但不得主导真实 Git 写动作

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

Agent 编排采用 `LangGraph 主链 + stage-scoped runner` 的结构。

`LangGraph` 只负责以下运行边界：
- 六个正式业务阶段的主链推进
- 条件路由、自动回归路由和交付分流
- 澄清、审批等人工中断
- pause / resume / terminate / rerun 的检查点与恢复

`Stage Agent Runtime` 负责单个正式业务阶段内部的动态执行。阶段内部执行不得直接修改 `PipelineRun` 主链状态；阶段 runner 只能通过结构化阶段结果、领域事件、控制记录、审批对象或交付记录影响后续流程。

功能一 V1 的阶段执行模式固定如下：

| 阶段 | 执行模式 | 规则 |
| --- | --- | --- |
| `requirement_analysis` | `structured_llm` | 以结构化需求产出为主，必要时可使用只读工具辅助分析，并支持澄清中断 |
| `solution_design` | `read_only_react` | 使用只读 ReAct 读取仓库上下文、分析架构、形成方案，并执行 validation pass |
| `code_generation` | `write_enabled_react` | 使用单 Agent ReAct 读取方案、逐文件修改、应用 patch、检查 diff 并形成 `ChangeSet` |
| `test_generation_execution` | `write_execute_react` | 使用单 Agent ReAct 生成或修改测试、执行测试命令、分析失败并修正 |
| `code_review` | `review_react` | 使用只读 ReAct 审查方案、变更集和测试结果，并基于证据判定是否自动回归 |
| `delivery_integration` | `deterministic_adapter` | 由交付适配器执行 demo 或真实 Git 交付，模型只辅助说明文本 |

V1 明确不引入代码生成 subagent。后续如支持 subagent，必须先扩展上下文隔离、文件所有权、冲突处理、过程投影和审计边界。

Agent 编排必须满足以下规则：

1. `阶段角色明确`
每个正式业务阶段都必须配置明确的 `AgentRole`，运行时实际使用的角色绑定、`system_prompt` 和 Provider 必须来自 `template_snapshot_ref`。

2. `Context Management 先于模型调用`
每次阶段执行、ReAct iteration、结构化输出修复、validation pass 或上下文压缩调用前，必须先通过 Context Management 生成 `ContextEnvelope`。

3. `工具调用模型`
Agent 内部工具调用必须使用模型原生 tool/function calling。LangChain 侧必须通过 `ChatOpenAI` 兼容接口和 `bind_tools()` 绑定由 `ToolProtocol` 派生的工具 schema。

工具调用必须满足以下规则：
- 模型只产生 tool call request，不直接执行工具
- 实际工具执行必须经过 `ToolRegistry`、阶段工具权限、工作区边界、输入 Schema 校验和审计策略
- 模型不得动态声明新工具或绕过工具注册表调用本地函数
- 禁止使用自由文本、正则匹配、字符串命令解析或 JSON 猜测来模拟工具调用
- 工具结果必须返回结构化 `ToolResult`，并形成 `tool_trace`

4. `模型供应商可切换`
- V1 默认内置两个 `builtin` Provider：`火山引擎`、`DeepSeek`
- V1 允许用户新增 `custom` Provider
- `custom` Provider 的接入协议统一采用 `OpenAI Completions compatible`
- 后端运行时通过 LangChain `ChatOpenAI` 兼容接口创建模型对象
- Provider 绑定单位是 `AgentRole`
- Provider 差异不得泄漏到上层业务流程逻辑

5. `输出结构化`
- Agent 输出必须转换为结构化领域对象
- 必须执行 Schema 校验、格式修复与错误处理
- 非法输出不得直接推进下一阶段
- 结构化输出修复必须作为独立 `model_call_type = structured_output_repair` 的模型调用或等价可追踪过程记录

6. `推理与过程可见`
- Provider 返回的原生推理、模型输出中的可展示推理、决策片段、工具调用过程和平台过程记录必须按规则进入 `StageArtifact.process`
- 如果 Provider 不返回原生推理内容，系统不得伪造 raw chain-of-thought
- 前端中栏可以展示截断推理片段，Inspector 必须能查看当前对象相关的完整或更完整过程记录及其稳定引用

7. `循环边界`
阶段内 ReAct 和修复循环必须受控。V1 默认值与平台硬上限如下：

| 配置 | 默认值 | 平台硬上限 |
| --- | ---: | ---: |
| `max_react_iterations_per_stage` | 30 | 50 |
| `max_tool_calls_per_stage` | 80 | 150 |
| `max_file_edit_count` | 20 | 40 |
| `max_patch_attempts_per_file` | 3 | 5 |
| `max_structured_output_repair_attempts` | 3 | 5 |
| `max_auto_regression_retries` | 2 | 3 |
| `max_clarification_rounds` | 5 | 8 |

超过循环边界时，阶段必须输出明确失败、风险状态或等待人工处理的结构化结果，不得静默继续执行。

8. `执行与查询解耦`
`LangGraph Runtime`、`Stage Agent Runtime`、`LLMProviderAdapter` 和工具调用产生的内部事件必须转换为领域对象、领域事件、`StageArtifact` 过程记录或稳定引用后才能进入查询投影。前端不得直接消费 raw graph state、raw node event、raw tool event 或 raw model adapter 对象。

### 7.6 Context Management

Context Management 是 Agent Runtime 在每次模型调用或阶段执行前对提示词、阶段目标、阶段产物、工具描述、推理轨迹、工具观察结果和上下文引用进行解析、组装、排序、尺寸守卫与留痕的运行时能力。

Context Management 不作为新的产品状态真源。可回看的产品事实仍以 `StageArtifact`、`ContextReference`、`TraceContext`、`ToolProtocol`、领域事件、审批对象、变更集与交付记录为准。

Context Management 至少包含以下对象和能力：
- `ContextEnvelope`
- `ContextManifest`
- `ContextSourceResolver`
- `ContextEnvelopeBuilder`
- `ContextSizeGuard`
- `ContextCompressionRunner`
- `CompressedContextBlock`
- `ContextTokenEstimator`

#### 7.6.1 ContextEnvelope

`ContextEnvelope` 表示一次模型调用前实际传递给模型的上下文封装。它是短生命周期运行时结构，不直接作为产品查询真源。

`ContextEnvelope` 必须按以下顺序组装：
1. `runtime_instructions`
2. `agent_role_prompt`
3. `stage_contract`
4. `task_objective`
5. `specified_action`
6. `input_artifact_refs`
7. `context_references`
8. `working_observations`
9. `reasoning_trace`
10. `available_tools`
11. `recent_observations`
12. `response_schema`
13. `trace_context`

其中：
- `agent_role_prompt` 必须来自当前 run 的 `template_snapshot_ref`，不得读取最新 `AgentRole` 运行外状态
- `stage_contract` 必须包含阶段职责、输入契约、输出契约、工具权限和结构化产物要求
- `available_tools` 必须来自 `ToolRegistry`，并按阶段权限过滤
- `reasoning_trace` 只包含当前阶段已产生且允许继续传输的推理或过程记录
- `response_schema` 必须明确当前模型调用预期返回工具调用、结构化阶段结果、澄清请求、失败原因或其他受控结果

#### 7.6.2 ContextManifest

每次构建 `ContextEnvelope` 都必须生成 `ContextManifest`，并以 `context_manifest` 过程记录形式写入 `StageArtifact.process` 或其稳定引用。

`ContextManifest` 至少记录：
- 所属 `session_id`、`run_id`、`stage_run_id`、`trace_id`、`correlation_id`、`span_id`
- envelope 构建时间
- 使用的 `template_snapshot_ref`
- 使用的 `system_prompt` 快照引用
- 使用的阶段契约和输出 Schema
- 可用工具集及其 schema 版本
- 每块上下文的来源类型、来源对象标识、文件路径、hash 或版本信息
- 是否发生截断、折叠或压缩
- 完整内容的稳定引用
- 估算 token 或字符规模

`ContextManifest` 不重复保存所有大文本；大文本必须通过稳定引用、附件、工具结果或阶段产物访问。

#### 7.6.3 Context Source Resolution

Context Management 至少支持以下上下文来源：
- 用户原始需求
- 结构化需求、验收标准、约束与假设
- 澄清问题、用户回复与澄清结论
- 技术方案、影响范围、设计决策、API 设计和文件变更清单
- 审批理由与拒绝反馈
- ChangeSet、diff、文件编辑记录与代码引用
- 测试代码、测试命令、测试输出、失败项和测试缺口
- 代码评审意见、问题证据和自动回归记录
- 工具观察结果、模型过程记录、推理轨迹和上下文压缩块
- 当前 run 的隔离工作区路径和工作区快照引用

日志文件和 `log.db` 查询结果不得作为默认业务上下文来源。只有诊断工具或明确的后端日志查询能力可以按日志审计契约读取日志。

raw `LangGraph` state、raw checkpoint payload、raw node event 和 raw thread 对象不得进入 `ContextEnvelope`。

#### 7.6.4 Context Size Guard

`ContextSizeGuard` 负责在不限制 Agent 可读取文件数量的前提下，控制单次模型调用的上下文窗口、payload 大小、超长文本截断和长链路延续。

功能一 V1 采用三级尺寸守卫：

1. `Observation Budgeting`
大文件读取、搜索结果、测试输出、diff、shell stdout / stderr 和工具错误不得无界进入 `ContextEnvelope`。Envelope 中保留预览、摘要字段、路径、hash、行号、退出码、错误摘要和稳定引用；完整内容由 `StageArtifact.process`、工具结果、附件或文件引用提供。

2. `Sliding Working Window`
阶段内 ReAct 循环只在 `ContextEnvelope` 中保留最近若干轮完整过程，包括最近工具调用、最近错误、当前 patch、当前文件任务、最近 reasoning / CoT 片段和最近模型响应。更早过程必须转为结构化索引或引用，不删除原始过程记录。

3. `LLM Context Compression`
当前两级处理后仍接近模型窗口上限时，`ContextCompressionRunner` 必须调用 LLM 生成 `CompressedContextBlock`。压缩使用平台默认 `compression_model_binding` 与平台默认 `compression_prompt`，二者属于后端平台配置，不进入普通模板编辑 UI。压缩调用必须经过 `LLMProviderAdapter`，并生成 `model_call_type = context_compression` 的模型调用记录。压缩输出必须满足结构化 Schema，不允许自由文本摘要作为唯一结果。

`pinned_context` 永不压缩，至少包括：
- `runtime_instructions`
- `stage_contract`
- `task_objective`
- `response_schema`
- `system_prompt` 快照引用
- 结构化需求和验收标准
- 已批准或当前有效的技术方案
- 当前审批或拒绝理由
- 当前 active file task
- 可用工具 schema

#### 7.6.5 CompressedContextBlock

`CompressedContextBlock` 表示由上下文压缩模型生成的结构化压缩块，至少包含：
- `compressed_context_id`
- `stage_run_id`
- `covered_step_range`
- `compression_trigger_reason`
- `compression_prompt_id`
- `compression_prompt_version`
- `model_call_ref`
- `summary`
- `decisions_made`
- `files_observed`
- `files_modified`
- `failed_attempts`
- `open_issues`
- `evidence_refs`
- `full_trace_ref`
- `created_at`

`CompressedContextBlock` 必须满足以下规则：
- 不得替代原始过程记录、工具结果、文件内容、测试结果、评审意见、`ChangeSet` 或审批记录
- 必须保留 `full_trace_ref`，使 Inspector 能回到压缩前完整过程
- 压缩调用必须使用 `model_call_type = context_compression`
- 压缩失败不得伪造摘要；若仍能构建 envelope，必须记录 warning 并继续；若无法构建 envelope，阶段必须进入明确的 `context_overflow` 错误或失败状态
- 连续压缩失败必须触发熔断，不得无限重试

#### 7.6.6 模型调用类型

所有模型调用必须标记调用类型。V1 至少支持：
- `stage_agent_call`
- `context_compression`
- `structured_output_repair`
- `validation_pass`

模型调用必须继承当前 `TraceContext`，并形成 `model_call_trace` 或等价过程记录。模型输入输出进入日志前必须按日志审计契约裁剪、摘要或阻断。

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
- `context`
- `reasoning`
- `decision`
- `model_call`
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
- 当中栏 Narrative Feed 对 reasoning、工具结果、diff、测试输出或模型过程记录做截断展示时，Inspector 必须提供完整内容、完整内容稳定引用、截断状态和脱敏状态
- Inspector 可以展示 `ContextManifest`、`CompressedContextBlock`、working window、`pinned_context` 引用、tool trace、model call trace、file edit trace、validation trace 和 reasoning trace，但这些内容必须来自 `StageArtifact.process` 或稳定引用

`StageInspectorProjection` 必须至少按以下分组提供内容：
- `identity`
  至少包含阶段标识、所属 run、状态、开始时间、结束时间
- `input`
  至少包含本阶段接收的原始输入快照、上下文引用与前序产物引用
- `process`
  至少包含本阶段的原始过程记录，如上下文清单、压缩上下文块、模型调用、推理、决策、工具调用、文件编辑、校验、diff、测试执行、评审或交付步骤记录
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
- `GET /api/runs/{runId}/logs`
- `GET /api/stages/{stageRunId}/inspector`
- `GET /api/stages/{stageRunId}/logs`
- `GET /api/control-records/{controlRecordId}`
- `GET /api/delivery-records/{deliveryRecordId}`
- `GET /api/preview-targets/{previewTargetId}`
- `GET /api/audit-logs`

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
- `GET /api/runs/{runId}/logs` 返回该 run 关联的运行日志分页结果，不返回其他 run 的日志
- `GET /api/stages/{stageRunId}/logs` 返回该阶段关联的运行日志分页结果，不返回同一 run 中其他阶段的日志
- `GET /api/audit-logs` 返回平台审计日志分页结果，必须支持按动作、主体、目标、run、时间范围与结果过滤

日志与审计查询接口必须满足以下规则：
- `GET /api/runs/{runId}/logs`、`GET /api/stages/{stageRunId}/logs` 与 `GET /api/audit-logs` 是后端诊断与本地运维只读接口，不属于前端工作台主路径依赖
- 日志分页必须使用稳定游标，不得只依赖 offset 扫描
- 日志分页的稳定顺序必须基于 `created_at + log_id` 或等价全局稳定顺序
- `GET /api/runs/{runId}/logs` 与 `GET /api/stages/{stageRunId}/logs` 至少支持 `level`、`category`、`source`、`since`、`until`、`cursor`、`limit` 查询参数
- `GET /api/audit-logs` 至少支持 `actor_type`、`action`、`target_type`、`target_id`、`run_id`、`result`、`since`、`until`、`cursor`、`limit` 查询参数
- 日志查询响应必须返回 `entries`、`next_cursor`、`has_more` 与查询条件回显
- 日志查询响应不得返回完整大载荷，只能返回 `message`、`payload_excerpt`、`payload_size_bytes`、`redaction_status`、`log_file_ref` 与 `line_offset`
- 日志查询接口不得作为 Narrative Feed、Inspector、审批块或交付结果投影的依赖接口
- V1 不要求提供完整日志载荷详情查询接口；后续平台运维能力可以在权限、脱敏与归档策略成熟后补充 `GET /api/log-payloads/{payloadId}` 或等价接口

### 9.4 API 文档契约

后端必须把 API 文档作为正式交付物提供。

至少提供以下文档接口：
- `GET /api/openapi.json`
- `GET /api/docs`

并满足以下规则：
- `GET /api/openapi.json` 必须返回与当前服务实现一致的 machine-readable OpenAPI 文档
- `GET /api/docs` 必须提供 human-readable API 文档页面
- OpenAPI 文档必须覆盖功能一全部核心 REST 接口，包括 `Project`、`Session`、`PipelineTemplate`、`Provider`、项目级 `DeliveryChannel`、`PipelineRun` 生命周期、审批、控制条目、Inspector、交付结果、预览目标查询、运行日志轻查询与审计日志查询
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

执行图内部事件用于驱动内部执行、内部追踪与日志审计采集，不直接作为前端产品事件暴露。

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
- 对外领域事件不得被运行日志或审计日志替代；同一动作需要同时形成产品事实和审计事实时，必须分别写入领域事件与审计日志

## 12. 平台日志审计契约

功能一 V1 的日志审计能力定位为平台级运行治理能力，服务于后端排障、运行复盘、安全追踪、审计问责、容量与性能分析、后续运维面板和系统稳定性演进。

日志审计能力必须满足以下总边界：
- 日志审计不是 Narrative Feed；Narrative Feed 只呈现面向用户的主链路叙事与高信号执行投影
- 日志审计不是 Inspector；Inspector 展示产品对象的完整输入、过程、输出、引用与指标，日志审计展示平台运行观察记录与审计记录
- 日志审计不是领域事件；领域事件记录产品事实并驱动投影，日志审计记录运行观察事实、安全事实与诊断上下文
- 日志审计不是 `LangGraph` 原始事件直通；底层事件进入日志前必须经过平台统一采集、分类、裁剪与关联
- 日志审计不得成为执行推进条件，不得被 Agent 当作业务上下文直接读取并影响阶段产物
- 功能一 V1 的运行时观察主载体是本地 JSONL 日志文件；`log.db` 只承担轻量索引、审计台账与关联元数据职责
- 功能一 V1 不提供前端全量日志控制台，不实现复杂全文检索，不要求完整日志载荷查询 API

### 12.1 日志分类与采集范围

日志文件写入规则如下：
- 服务级日志必须写入 `.runtime/logs/app.jsonl`
- run 级日志必须写入 `.runtime/logs/runs/{run_id}.jsonl`
- 安全审计日志必须写入 `.runtime/logs/audit.jsonl`，并同步写入 `AuditLogEntry`
- 每行日志必须是一个完整 JSON 对象，不得跨行写入同一条日志
- 每行日志必须至少包含 `schema_version`、`log_id`、`created_at`、`level`、`category`、`source`、`message`、`request_id`、`trace_id`、`correlation_id`、`span_id`、`parent_span_id`、`duration_ms`、`error_code`、`redaction_status` 以及当前可用的产品对象标识
- 每行日志中的产品对象标识至少包括当前可用的 `session_id`、`run_id`、`stage_run_id`、`approval_id`、`delivery_record_id` 与 `graph_thread_id`
- `schema_version` 在 V1 固定为 `1`；后续变更 JSONL 字段含义时必须递增版本，不得静默改变既有字段语义
- `created_at` 必须使用统一时区和可排序时间格式；`log_id` 必须全局唯一，并能与 `created_at` 共同形成稳定排序键
- 文件写入失败不得静默吞掉；后端必须至少向服务级错误通道记录日志写入失败，并避免影响已经持久化的领域状态
- 运行日志文件写入失败不得阻断已经完成的领域事务；安全审计日志写入 `AuditLogEntry` 失败时，后端必须拒绝或回滚对应高影响动作，并返回明确错误
- 安全审计 JSONL 文件副本写入失败但 `AuditLogEntry` 已持久化时，后端必须追加服务级错误日志，并在审计记录中保留文件副本失败标记或等价元数据
- 普通运行日志写入本地文件成功但 `log.db` 轻量索引写入失败时，不得阻断已经完成的领域事务，但必须追加服务级错误日志并保留可诊断线索
- 审计索引或审计台账写入失败时，必须按安全审计失败处理，不得降级为普通运行日志失败

后端必须统一采集以下运行日志：
- API 请求进入、参数校验失败、响应错误与异常返回
- run 创建、图编译、线程启动、节点执行、中断、恢复、暂停、终止、失败与完成
- 阶段开始、阶段更新、阶段完成、阶段失败与阶段重试
- Agent 调用、模型请求、模型响应、结构化输出解析、模型错误与重试
- 工具调用、工具输入摘要、工具输出摘要、工具错误与工具耗时
- 工作区文件读写、搜索、diff 生成、命令执行、测试执行与命令输出摘要
- 交付通道读取、配置校验、分支准备、提交创建、推送、MR/PR 创建与交付失败
- 后台恢复、运维重启、旧 run 终态确认、新 run 创建与新旧运行关联
- 安全策略阻断、敏感信息裁剪、凭据不可用、路径越界、权限拒绝与外部服务鉴权失败

后端必须统一采集以下审计日志：
- 所有用户可触发命令接口的接受、拒绝、成功与失败结果
- 所有会改变模板、Provider、交付配置、会话状态、run 状态、审批状态、工作区内容或交付目标的动作
- 所有系统自动执行的高影响动作，包括文件写入、命令执行、Git 写操作与远端交付动作
- 所有安全敏感失败和凭据相关动作

日志采集必须满足以下规则：
- 运行日志记录“系统发生了什么、在哪里发生、耗时多久、失败原因是什么”
- 审计日志记录“谁或什么主体对哪个目标执行了什么动作、系统是否接受、结果是什么”
- 同一动作可以同时产生领域事件、运行日志和审计日志，但三者职责必须分离
- 低层调试日志可以裁剪或降采样，高影响审计日志不得被采样丢弃
- 工具、模型、命令和交付适配器不得绕过 `Log & Audit Service` 自行写散落日志
- `log.db` 中的 `RunLogEntry` 可以只保存 warning、error、critical、审计关联、阶段边界、工具调用摘要、模型调用摘要与交付关键动作；debug 级细节允许只保存在本地 JSONL 文件中
- 日志采集不得扩大功能一 V1 的产品范围；日志文件、日志索引与审计记录只服务运行治理、诊断和追踪，不作为前端主功能或用户业务产物

### 12.2 关联标识与可追踪性

日志审计必须建立跨层关联能力。

关联规则如下：
- 每个外部 HTTP 请求必须生成或继承 `request_id`
- 每个 `PipelineRun` 必须生成贯穿运行生命周期的 `trace_id`
- 同一用户动作触发的命令处理、领域事件、运行日志、审计日志、SSE 增量与查询投影更新必须共享 `correlation_id`
- 每个工具调用、模型调用、命令执行和交付动作必须具备 `span_id`，并通过 `parent_span_id` 关联到上游 stage、graph node 或 command
- 所有可映射到产品对象的日志必须写入可用的 `session_id`、`run_id`、`stage_run_id`、`approval_id`、`delivery_record_id` 或等价目标标识
- 运行失败、终止、重试与运维重启必须能通过日志审计链路定位到直接失败点、上游触发点与后续处理结果

### 12.3 安全、裁剪与保留策略

日志审计必须默认安全。

敏感信息规则如下：
- 明文凭据、API Key、访问令牌、私钥、Cookie、授权头、系统环境密钥与用户私密配置不得写入可查询日志
- 模型请求与响应进入日志前必须经过敏感信息裁剪；裁剪后仍可能泄露敏感内容的载荷必须阻断保存
- 命令输出、测试输出和异常堆栈必须支持长度上限、截断标记与敏感片段裁剪
- 本地绝对路径可以在开发期用于排障，但必须通过字段标记其敏感级别；后续多项目和多用户场景不得把本机敏感路径直接暴露给无关主体
- 日志载荷必须保存裁剪状态，查询方必须能区分完整载荷、裁剪载荷与被阻断载荷
- 字段名命中 `api_key`、`token`、`secret`、`password`、`authorization`、`cookie`、`private_key`、`credential` 或等价敏感含义时，字段值必须阻断写入日志
- 模型输入、模型输出、工具输入、工具输出和命令输出必须先生成摘要，再按长度上限写入裁剪后片段
- 路径、仓库地址、分支名、提交哈希与 MR/PR 链接可写入日志，但必须标记敏感级别；后续权限模型不得把这些字段直接暴露给无关主体

保留策略规则如下：
- V1 必须提供按时间和 run 维度清理本地运行日志文件与 `log.db` 运行日志索引的内部能力，避免运行数据无界增长
- 审计日志的保留周期必须长于普通运行日志；V1 不实现复杂归档系统，但不得把审计日志和普通 debug 日志使用同一清理策略
- 清理运行日志不得删除领域对象、领域事件、阶段产物、审批记录或交付记录
- 当某条日志被清理而 Inspector 或领域对象仍引用其摘要时，引用必须降级为“日志已过保留期”或等价稳定状态，不得导致产品查询失败
- 本地日志文件必须支持按大小或日期轮转；轮转后的文件命名必须保留可排序时间或 run 标识
- 清理优先级必须为：debug 运行日志先于 info 运行日志，普通运行日志先于 error 与 critical 日志，运行日志先于审计日志
- 审计日志、审计索引和高影响动作记录不得和普通运行日志使用同一自动清理阈值

### 12.4 与 Inspector、Narrative Feed 和领域事件的边界

日志审计与产品投影必须遵守以下边界：
- Narrative Feed 的条目只能来自领域对象、领域事件和查询投影，不得直接读取 `RunLogEntry` 拼装
- Inspector 中的完整阶段过程必须来自标准化阶段产物、过程记录、稳定引用或领域对象，不得只存在于日志
- Inspector 可以展示与当前对象直接相关的 `log_id`、日志摘要、裁剪片段或日志查询锚点
- 当日志与 Inspector 对同一事实存在表达差异时，以领域对象、阶段产物和 Inspector 投影为产品语义准绳；日志只用于诊断差异来源
- 领域事件必须可独立支撑产品状态回放；日志审计必须可独立支撑运行诊断和审计复盘

### 12.5 日志审计查询投影

`RunLogEntryProjection` 至少包含：
- `log_id`
- `session_id`
- `run_id`
- `stage_run_id`
- `approval_id`
- `delivery_record_id`
- `graph_thread_id`
- `source`
- `category`
- `level`
- `message`
- `log_file_ref`
- `line_offset`
- `line_number`
- `log_file_generation`
- `payload_ref`
- `payload_excerpt`
- `payload_size_bytes`
- `redaction_status`
- `correlation_id`
- `trace_id`
- `span_id`
- `created_at`

`AuditLogEntryProjection` 至少包含：
- `audit_id`
- `actor_type`
- `actor_id`
- `action`
- `target_type`
- `target_id`
- `session_id`
- `run_id`
- `stage_run_id`
- `approval_id`
- `delivery_record_id`
- `request_id`
- `result`
- `reason`
- `metadata_ref`
- `metadata_excerpt`
- `correlation_id`
- `created_at`

日志审计查询投影必须满足以下规则：
- 默认按 `created_at` 与稳定游标倒序返回，便于排障查看最近记录
- 必须支持按 run 和 stage 聚焦查询，避免前端或诊断工具在全局日志中自行筛选
- 必须返回本地日志文件定位信息、裁剪状态、载荷大小和摘要，不返回完整大载荷
- 必须支持通过 `correlation_id` 查看同一动作相关的领域事件、运行日志和审计日志关联线索
- 查询投影必须是只读视图，不提供修改、重放或删除日志的前端命令
- 全文检索、错误聚合、日志趋势统计、trace 可视化和运维审计控制台属于后续平台运维能力，不属于功能一 V1 必需实现范围

## 13. 工作区、工具与交付适配

后端必须通过统一工具协议暴露受控能力。模型不得直接访问本地函数、文件系统、命令执行器、Git CLI 或远端交付接口。

工具协议必须先于具体工具实例稳定。`ToolProtocol` 至少定义工具名称、类别、描述、输入 Schema、结果 Schema、错误结构、权限边界、副作用等级、超时策略、审计策略、schema 版本和可绑定的工具描述。`LangGraph Runtime`、`Stage Agent Runtime`、`LLMProviderAdapter` 与后续交付适配器只能依赖该抽象协议和工具注册契约；不得直接绑定尚未实现的具体 delivery tool 实例。

`ToolProtocol` 必须能够转换为 LangChain `bind_tools()` 可接受的工具 schema，并最终通过模型原生 tool/function calling 暴露给模型。工具调用不得通过自由文本、正则、字符串命令解析或 JSON 猜测方式触发。

### 13.1 Workspace Tools

V1 仅实现以下六个核心工具：
- `read_file`
- `write_file`
- `edit_file`
- `list_files`
- `search`
- `shell`

### 13.2 SCM / Delivery Tools

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
- 结果 Schema
- 执行结果载荷
- 结构化错误信息
- 权限边界与副作用等级
- 审计记录和稳定引用

工具调用链路必须统一为：
1. `ContextEnvelope` 写入当前阶段允许使用的工具清单及其 schema 版本
2. `LLMProviderAdapter` 通过 LangChain `ChatOpenAI` 兼容接口和 `bind_tools()` 绑定工具
3. 模型返回原生 tool call request
4. `Stage Agent Runtime` 将 tool call request 交给 `ToolRegistry`
5. `ToolRegistry` 校验工具名称、阶段权限、输入 Schema、工作区边界、超时策略与审计策略
6. 具体工具执行并返回结构化 `ToolResult`
7. `ToolResult` 写入运行日志、审计日志、`tool_trace` 和下一轮 `ContextEnvelope` 的工具观察

`ToolResult` 至少包含：
- `tool_name`
- `call_id`
- `status`
- `output_payload`
- `output_preview`
- `error`
- `artifact_refs`
- `audit_ref`
- `trace_context`

所有工具调用必须接入日志审计契约：
- 每次工具调用必须产生运行日志，记录工具名称、输入摘要、输出摘要、耗时、结果状态与错误摘要
- 每次会造成工作区、Git、远端交付或配置状态变化的工具调用必须产生审计日志
- 工具结果中的 `审计记录` 字段必须引用 `AuditLogEntry` 或其稳定引用，不得只是自由文本
- 工具日志必须继承当前 `trace_id`、`correlation_id` 与 `span_id`
- 工具的完整输入、完整输出或超长错误不得无界进入 `ContextEnvelope`；进入模型上下文的只能是预览、摘要、关键结构字段和稳定引用

## 14. 为功能二预留的接口边界

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

## 15. 后端验收标准

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
16. 能把服务级、run 级与审计日志写入本地 JSONL 日志文件，并支持按时间或大小轮转。
17. 能通过 `log.db` 记录运行日志轻量索引、审计记录、日志文件位置、载荷摘要、裁剪状态与跨层关联标识，并提供按 run、stage、动作、主体、结果与时间范围过滤的只读轻查询能力。
18. 能对日志文件内容、日志索引与审计记录执行敏感信息裁剪、阻断与保留策略控制，且日志审计记录不得替代领域事件、Narrative Feed、Inspector 或产品状态真源。
19. 能确保 `.runtime/logs` 属于平台运行数据目录，不被工作区工具、代码 diff、Git 自动交付或交付结果统计当作目标项目内容处理。
20. 能在 `RunLogEntry` 中通过 `log_file_ref`、`line_offset`、`line_number` 与 `log_file_generation` 定位到本地 JSONL 日志原文，并在日志轮转后保持定位语义清晰。
21. 能在安全审计记录写入失败时拒绝或回滚高影响动作；普通运行日志写入失败不得静默吞掉，也不得破坏已持久化的领域状态。
22. 能在启动时校验平台运行数据目录和日志子目录可用；目录不可用时不得进入可接受用户命令的正常运行状态。
23. 能把日志诊断查询接口保持为后端诊断与本地运维只读能力，不作为前端工作台主路径依赖。
24. 能为功能二保留 `ChangeSet`、`ContextReference`、`PreviewTarget`、`DeliveryRecord` 的复用边界。
