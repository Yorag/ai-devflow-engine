# 功能一平台级 V1 项目总计划

> 状态：Draft for review
> 计划口径：10 周功能完成 + 2 周联调、回归与硬化
> 执行模型：前后端并行，后端契约、runtime boundary 与 ToolProtocol 先行，Claude Code 风格 Workspace tools 基座先于正式 runtime 消费，`deterministic test runtime` 先打通稳定测试链路，LangGraph runtime 作为正式编排路径
> 适用范围：功能一平台级 V1，不以临时演示版本为目标

## 1. 计划目标

本文档用于把功能一当前前后端规约拆解为可排期、可追踪、可测试、可继续细化为 Superpowers 实施计划的项目总计划。

本文档的直接输入依据为：
- `docs/specs/function-one-product-overview-v1.md`
- `docs/specs/frontend-workspace-global-design-v1.md`
- `docs/specs/function-one-backend-engine-design-v1.md`

## 2. 总体交付口径

功能一平台级 V1 的目标不是一次性演示链路，而是一个具备正式平台边界的软件版本。V1 必须同时满足以下交付口径：
- 前端具备单一 SPA 控制台、项目与会话工作台、模板空态、统一设置弹窗、Narrative Feed、Run Switcher、Composer、Approval Request、Tool Confirmation、Provider 调用状态、Inspector 与历史回放能力。
- 后端具备 FastAPI 服务、REST API、SSE、OpenAPI、领域模型、查询投影、多 SQLite 职责拆分、环境变量与可热重载配置设置分层、系统内置提示词资产管理、平台日志审计、运行状态机、人工介入、高风险工具确认、Provider 指数退避与熔断、工作区工具、交付适配与 LangGraph 执行内核接入。
- 测试具备分层覆盖：领域单元测试、API 契约测试、投影测试、SSE 流测试、日志审计测试、前端组件测试、前端状态测试、端到端测试、工作区与交付适配测试。
- 执行内核采用双路径：`deterministic test runtime` 负责稳定测试、前端联调和端到端验收；LangGraph runtime 负责正式 Agent 编排路径。
- 交付模式同时覆盖 `demo_delivery` 与 `git_auto_delivery`。`demo_delivery` 不能替代真实交付适配边界，`git_auto_delivery` 必须通过受控适配层实现。
- `SolutionDesignArtifact.implementation_plan` 是方案设计阶段的正式产物，后续代码生成、测试生成执行和代码评审阶段必须按稳定任务标识引用。
- 功能一 V1 不提供跨会话长期记忆。历史会话、历史 run、历史产物、历史审批、历史工具确认和历史工具过程只用于回看、追溯、诊断和审计，不自动进入新 Session 的 Agent 上下文。

## 3. 拆解原则

本计划采用“平台能力层 + 可验收执行切片”的混合拆分方式。

拆分原则如下：
- 后端契约先行：前端先依赖状态枚举、Pydantic Schema、投影 Schema、事件载荷与 mock fixtures 并行开发；每个 API 切片在本地 API 测试中断言 OpenAPI path、method、请求 Schema、响应 Schema 与主要错误响应，V6.4 只做全局覆盖回归。
- 平台骨架先行：Project、Session、Template、Provider、DeliveryChannel、PipelineRun、StageRun、Event、Projection 是后续能力的基础，不延后到业务阶段实现之后。
- Walking skeleton 先行：先打通默认 Project、draft Session、首条需求创建正式 `PipelineRun`、模板快照、Provider 与模型绑定快照、运行上限快照、`GraphDefinition`、首条消息事件、初始 `StageRun`、workspace projection、前端读取与 SSE 增量，再逐步接入完整 runtime。
- Runtime boundary 先行：人工介入命令必须先依赖统一 runtime orchestration boundary，不允许先用 run 状态字段临时模拟中断、恢复或终止。
- 工具确认独立于人工审批：高风险工具确认是运行时权限控制点，不属于两个正式人工审批检查点；`tool_confirmation` 是独立顶层 Narrative Feed 条目，`ApprovalRequest` 和 `ApprovalDecision` 不承载工具确认语义。
- 配置边界先行：`EnvironmentSettings`、正式配置存储、`PlatformRuntimeSettings`、`ConfigurationPackage`、业务配置对象、系统内置提示词资产与运行快照必须在控制面、Run 启动和 runtime 消费前先固定；环境变量只服务启动路径、前后端连接、工作区与日志落点、凭据引用解析，不承载 Provider、DeliveryChannel、模板运行配置、Agent 运行上限、Provider 模型能力、上下文压缩阈值、日志策略、系统内置提示词正文或提示词资产版本切换。
- ToolProtocol 与风险门禁先行：正式 runtime、Provider adapter、Workspace tools 与 Delivery tools 只能消费抽象 `ToolProtocol`、`ToolRegistry` 和统一风险分级门禁，不允许先接入临时工具函数或尚未实现的具体 delivery tool 实例；Workspace tools 参考 Claude Code 的工具工作方式，正式契约名固定为 `bash`、`read_file`、`edit_file`、`write_file`、`glob`、`grep`。
- Provider 失败策略先行：Provider 请求超时、网络错误和限流必须按本次 run 固化策略执行指数退避重试，连续失败熔断必须进入过程记录和前端可见投影，不得通过运行外 Provider 变更改变已启动 run。
- `deterministic test runtime` 先行：`deterministic test runtime` 先完成六阶段、澄清、审批、失败和终止，并通过正式 `demo_delivery` 形成 DeliveryRecord；再接入 LangGraph runtime 与 `git_auto_delivery`。
- Delivery snapshot gate 先行：`code_review_approval` 的 Approve 必须一次性完成交付就绪 gate、顶层 `approval_result`、交付快照固化和进入 `delivery_integration`，不允许先 approve 后补交付快照。
- 日志审计嵌入式推进：日志管理不单列独立周期，按运行数据目录、`log.db`、TraceContext、API 关联上下文、RedactionPolicy、JSONL 写入与索引、控制面审计、Run 日志、命令审计失败语义、审计查询、工具审计、交付审计、轮转保留清理与日志审计回归拆入对应阶段；不得以工期紧为由把日志审计集中延期到 Week 12。
- 领域对象优先于框架细节：LangGraph 原始状态不暴露给前端；产品级 API、投影和事件以领域对象为准。
- 子任务可单独验收：每个执行切片必须有明确文件范围、实现对象、验收标准和测试方法。
- 每个执行切片只交付一个明确行为，避免同一切片同时覆盖持久化、服务、API、投影和 UI。
- 每个实现切片必须继续拆成 TDD 实施计划：总计划只定义交付切片，进入开发前必须用 `superpowers:writing-plans` 写出该切片的红绿步骤。`docs/plans/implementation/*.md` 可以在执行对应子任务时按需创建，但创建前必须先核对当前分卷的文件列表、边界、测试方法和 API/OpenAPI 验收，不得在实施计划中放宽或改写分卷语义。

## 4. Superpowers 执行方式

本计划文档只维护任务表、依赖关系、里程碑、验收口径和风险记录。单切片执行流程由 repo-local skill `.codex/skills/slice-workflow` 维护；该 skill 会读取本总表和对应分卷计划，选择一个依赖已完成且当前未完成的任务，并负责分支门禁、实施计划、TDD、执行、审查、验证、状态更新和提交申请口径。

后续如果切片执行规范需要调整，优先更新该 skill；本计划只保留与排期、依赖和验收相关的信息。

## 5. 分层测试策略

### 5.1 后端测试层

后端测试分为以下层级：
- 领域单元测试：验证状态机、模板快照、审批规则、交付配置规则、投影组装规则。
- 持久化测试：使用临时 SQLite 文件验证 `control.db`、`runtime.db`、`graph.db`、`event.db`、`log.db` 的模型、约束与迁移。
- API 契约测试：使用 FastAPI TestClient 验证 REST 接口、错误响应、OpenAPI Schema；修改 `backend/app/api/routes/*` 的切片必须在对应 API 测试内验证本切片 OpenAPI 变更。
- 事件流测试：验证 SSE 事件顺序、载荷结构、断线重建所需快照一致性。
- 日志审计测试：验证运行数据目录预检、JSONL 写入、日志索引、审计记录、TraceContext 传递、日志查询、审计查询、轮转、保留、脱敏和 `.runtime/logs` 排除。
- 配置测试：验证 `EnvironmentSettings` 启动加载、SQLite 默认路径派生、`PlatformRuntimeSettings` 校验、硬上限拒绝、热重载不改变已启动 run 快照。
- Runtime 测试：`deterministic test runtime` 测试固定阶段推进；LangGraph runtime 测试图编译、中断、恢复、失败。
- 工具确认测试：验证 `ToolConfirmationRequest` 创建、allow / deny、paused 禁用、终态只读、OpenAPI 契约和审计失败回滚。
- Provider 失败测试：验证 Provider 指数退避重试、连续失败熔断、不可重试错误、过程记录和投影更新。
- 工作区测试：使用临时 Git fixture 仓库验证读写、diff、命令执行、测试执行和隔离边界。
- 交付测试：`demo_delivery` 验证无 Git 写动作；`git_auto_delivery` 使用本地 fixture 和 mock 托管平台客户端验证分支、提交、推送与代码评审请求流程。

### 5.2 前端测试层

前端测试分为以下层级：
- 组件单元测试：验证 Shell、Template Editor、Narrative Feed、Composer、Approval Block、Inspector、Settings Modal。
- 状态测试：验证 Zustand store、SSE merge、Run focus、Composer 状态机、审批可提交状态、工具确认可提交状态和 Provider 调用状态。
- API client 测试：验证 TanStack Query hooks、错误态、缓存失效、mock fixtures。
- 路由测试：验证 SPA 路由、控制台进入、会话切换、历史回放。
- E2E 测试：使用 Playwright 验证新建会话、首条需求启动、澄清、审批、高风险工具确认、暂停恢复、终止、重新尝试、交付结果回看。
- 响应式测试：验证桌面三栏、窄屏抽屉、Composer 固定底部、文本不溢出。
- UI 质量检查：验证前端展示切片的信息层级、状态覆盖、可访问性、文本溢出、响应式和视觉反模式；执行者可使用可用的设计审查工具辅助完成该检查。

### 5.3 TDD 要求

所有实现子任务遵循以下 TDD 纪律：
- 先写失败测试，再写实现。
- 必须观察测试按预期失败。
- 实现只覆盖当前测试要求。
- 通过后再做重构。
- 每个新增公开函数、服务方法、组件交互和 API 行为必须有测试。
- 对模型调用、远端托管平台和本地命令执行使用可控 fake 或 mock 边界，测试目标必须是本系统行为，不是 mock 自身。

## 6. 里程碑排期

| 周期 | 里程碑 | 后端主线 | 前端主线 | 联调与验收 |
| --- | --- | --- | --- | --- |
| Week 1 | 工程与骨架基线 | 工具链、FastAPI app、错误模型、EnvironmentSettings、运行数据目录预检 | Vite React 骨架、路由、测试工具 | 后端健康检查、启动配置边界、日志目录预检与前端控制台入口可运行 |
| Week 2 | 契约与持久化 | 枚举、Schema、Project/Session 历史可见性、PlatformRuntimeSettings、运行快照 Schema、PromptAsset Schema、ToolConfirmation Schema、工具风险枚举、Provider 调用策略快照、多 SQLite、Alembic、log.db、TraceContext | API client、mock fixtures | Pydantic Schema、投影契约、配置契约、提示词资产契约、工具确认契约、Provider 调用策略契约与日志审计契约可作为前后端输入 |
| Week 3 | 控制面可用 | Project、Session、Template、Provider、DeliveryChannel API、agent_role_seed 提示词资产种子、PlatformRuntimeSettings 管理服务、request context、RedactionPolicy、JSONL/log index、AuditService | Shell、项目/会话左栏、设置弹窗、模板空态 | 控制面 OpenAPI、字段、配置边界、历史可见性、提示词资产非用户配置边界、日志与审计记录对齐 |
| Week 4 | Run 主链骨架 | Session 删除、Project 移除、Run 状态机、模板快照、Provider/模型绑定快照、运行上限快照、GraphDefinition、StageArtifact、run trace | Workspace 页面、Run 分段基础展示 | draft、running、运行快照、历史管理阻塞态与基础阶段回放可用，run 级 trace 可追踪 |
| Week 5 | 投影与实时更新 | Workspace Projection、Timeline、Inspector、ToolConfirmationInspectorProjection、SSE、run/stage 日志查询 | Narrative Feed、Tool Confirmation 顶层块入口、Provider 调用状态、Inspector、SSE merge | 快照 + 增量一致，工具确认和 Provider 状态进入投影，诊断日志查询不进入前端主路径 |
| Week 6 | 人工介入、工具确认与 runtime 边界 | Runtime orchestration boundary、命令审计失败语义、审计查询、澄清、审批、工具确认命令、暂停、恢复、终止、重新尝试、交付快照 gate | Approval Block、Tool Confirmation Block、Composer lifecycle、重新尝试 UI | 人工介入命令和工具确认命令只通过统一 runtime 边界推进，命令审计可追踪 |
| Week 7 | deterministic test 与工具基座 | RuntimeEngine、`deterministic test runtime`、ToolProtocol、统一错误码、ToolRegistry execution gate、工具风险确认门禁、Workspace tools 基座、工具审计、demo_delivery | 前端完整流程联调 | 不依赖真实模型跑通 demo_delivery，终态回放可用，工具协议、风险分级、配置快照、错误码、Claude Code 风格工具口径和审计不临时分叉 |
| Week 8 | LangGraph 正式路径 | Graph compiler、interrupt、checkpoint、PromptValidation、PromptRegistry、PromptRenderer、ContextEnvelope / ContextManifest、Provider adapter、Provider retry/circuit breaker、AgentDecision、Stage Agent Runtime、自动回归、模型/runtime 日志 | Runtime 错误态、Provider 状态与工具确认状态呈现 | 内部测试/联调路径可在 `deterministic test runtime` 与 LangGraph runtime 间切换，正式用户运行只走 LangGraph；LangGraph 消费 Context Management、PromptRegistry、PromptRenderer、AgentDecision、Provider 失败策略、抽象 ToolProtocol 与已注册 `bash/read_file/edit_file/write_file/glob/grep` 或 fake 工具 |
| Week 9 | 扩展边界与执行展示 | ChangeSet、ContextReference、PreviewTarget、运行数据目录排除 | diff、工具调用、测试结果展示 | 功能二预留边界、前端执行展示和 `.runtime/logs` 排除可验收 |
| Week 10 | 真实 Git 交付适配 | git_auto_delivery、Git/远端交付审计 | 真实交付结果、交付失败态、历史详情 | git_auto_delivery 可测，交付失败可通过日志审计定位 |
| Week 11 | 系统回归 | API、SSE、持久化、runtime、日志审计回归 | 组件、状态、E2E、响应式回归 | 主要成功路径、人工介入路径和日志审计主路径通过 |
| Week 12 | 平台硬化 | OpenAPI、错误处理、审计、迁移稳定、日志轮转保留清理、日志审计回归包 | 可用性、空态、错误态、视觉一致性 | 发布候选验收清单完成 |

## 7. 任务依赖总览

本总览使用中文描述依赖语义，保留已在规格中固化的英文对象、API、服务类与交付模式名称。

```text
项目目录骨架与边界声明
  -> 工程基线
    -> 运行数据目录与日志启动预检
    -> 枚举与 Schema 契约
      -> EnvironmentSettings 启动配置边界
      -> 多 SQLite 默认路径派生与持久化边界（control、runtime、graph、event、log）
        -> PlatformRuntimeSettings、Provider 调用策略快照与运行快照 Schema 契约
        -> PromptAsset Schema 契约
          -> 系统模板 agent_role_seed 提示词资产种子
        -> 日志审计契约、TraceContext、API 关联上下文、RedactionPolicy、JSONL 写入与 AuditService
        -> 控制面对象（Project、Template、Session、DeliveryChannel）
        -> PlatformRuntimeSettings 管理服务
          -> 前端 API 客户端与模拟契约数据
            -> 前端工作台外壳、设置与模板交互
              -> Run 状态机、EventStore、模板快照、Provider/模型绑定快照、运行上限快照与 GraphDefinition
                -> Session 重命名、Session 删除与 Project 移除历史管理
                -> 首个 Run 启动事务
                  -> StageArtifact
                    -> 查询投影（Workspace、Timeline、Inspector、ToolConfirmationInspector）
                    -> SSE、Run/Stage 日志轻查询与前端状态合并
                      -> Narrative Feed、Tool Confirmation、Provider 调用状态与 Inspector 展示
                        -> Runtime 编排边界
                          -> 命令审计失败语义
                          -> 审计日志查询
                          -> 交付快照门禁
                            -> 人工介入命令与工具确认命令
                              -> ToolProtocol 与 ToolRegistry
                                -> 统一错误码字典与 ToolRegistry execution gate
                                  -> 后端测试 fixture 契约
                                    -> Tool risk classifier 与 confirmation gate
                                      -> 工作区工具基座
                                      -> `deterministic test runtime` 与 demo_delivery 交付路径
                                        -> LangGraph 运行时与 Provider 适配器
                                          -> PromptValidation、PromptRegistry、PromptRenderer 与 ContextEnvelope Builder
                                            -> Provider retry/backoff/circuit breaker 与 Context Size Guard
                                              -> AgentDecision
                                                -> Stage Agent Runtime 执行循环
                                              -> 功能二预留对象（ChangeSet、ContextReference、PreviewTarget）
                                                -> git_auto_delivery 交付适配
                                                  -> 端到端回归、日志轮转保留清理、日志审计回归包与平台硬化
```

前端允许在后端实现未完成时基于模拟契约数据（mock fixtures）并行推进，但模拟契约数据必须来源于后端 Schema 与投影契约。

## 8. 分卷索引

| 分卷 | 内容 | 任务范围 |
| --- | --- | --- |
| [00 项目骨架与执行规则](function-one-platform/00-project-skeleton-and-execution.md) | 目标目录骨架与 B0.0 子任务细则 | B0.0 |
| [01 工程基线与契约层](function-one-platform/01-foundation-and-contracts.md) | 工程基线、Schema 契约、数据库职责拆分、Project/Session 历史可见性、EnvironmentSettings、PlatformRuntimeSettings、Provider 调用策略快照、PromptAsset Schema、ToolConfirmation Schema、工具风险枚举、运行数据目录、log.db、TraceContext | B0.1-B0.3, F0.1, C1.1-C1.10, C1.10a, L0.1, L1.1-L1.2 |
| [02 控制面与工作台外壳](function-one-platform/02-control-plane-and-workspace-shell.md) | Project、Session、历史管理、Template、Provider、DeliveryChannel、ConfigurationPackage、PlatformRuntimeSettings 管理服务、控制面日志审计、Shell、设置、模板空态 | C2.1-C2.8, C2.7a, C2.9a-C2.9b, L2.1-L2.4, F2.1-F2.6 |
| [03 Run 主链、投影与叙事流](function-one-platform/03-run-projection-and-feed.md) | PipelineRun、模板快照、Provider/模型绑定快照、运行上限快照、GraphDefinition、StageArtifact、Workspace Projection、ToolConfirmationInspectorProjection、SSE、Run/Stage 日志轻查询、Feed、Provider 调用状态、Inspector | R3.1-R3.4, R3.4a-R3.4b, R3.5-R3.7, Q3.1-Q3.4a, E3.1-E3.2, L3.1, F3.1-F3.7 |
| [04 人工介入、工具确认与运行控制](function-one-platform/04-human-loop-and-runtime.md) | Runtime orchestration boundary、澄清、审批、工具确认、暂停恢复终止、交付快照、命令审计失败语义、审计查询、Composer、Approval Block、Tool Confirmation Block、重新尝试 UI | A4.0, L4.1-L4.2, H4.1-H4.7, H4.4a, D4.0, F4.1-F4.4, F4.3a |
| [05 deterministic runtime 与 demo_delivery](function-one-platform/05-deterministic-runtime-and-demo-delivery.md) | RuntimeEngine、`deterministic test runtime`、六阶段确定性推进、demo_delivery、DeliveryRecord、DeliveryResultDetailProjection | A4.1-A4.4, D4.1-D4.3 |
| [06 LangGraph、Provider、Context 与 Stage Agent Runtime](function-one-platform/06-langgraph-provider-context-stage-agent.md) | LangGraph、Provider、Provider retry/circuit breaker、PromptValidation、PromptRegistry、PromptRenderer、ContextEnvelope / ContextManifest、AgentDecision、Stage Agent Runtime、自动回归 | A4.5-A4.11, A4.8a-A4.8d, A4.9a-A4.9e |
| [07 Workspace Tools、风险门禁与变更边界](function-one-platform/07-workspace-tools-risk-and-change-boundaries.md) | ToolProtocol、ToolRegistry execution gate、工具风险确认门禁、统一错误码、后端测试 fixture、Workspace tools、ChangeSet、ContextReference、PreviewTarget | W5.0-W5.6, W5.0a-W5.0d |
| [08 真实 Git 交付与执行结果展示](function-one-platform/08-git-delivery-and-result-display.md) | read_delivery_snapshot、prepare_branch、create_commit、push_branch、create_code_review_request、git_auto_delivery、工具调用、Diff、测试结果、交付结果展示 | D5.1-D5.4, F5.1-F5.2b |
| [09 回归、硬化与日志收尾](function-one-platform/09-regression-hardening-and-logs.md) | 后端完整 API flow、Playwright、OpenAPI、前端 client、错误态、配置边界、运行快照、日志轮转保留清理、日志审计回归包、发布候选清单 | V6.1-V6.8, V6.7, L6.1-L6.2 |

## 9. 进度追踪表

状态标记固定为：
- `[ ]` 未开始
- `[~]` 进行中
- `[x]` 已完成

| ID | 子任务 | 周期 | 状态 | 负责人模型 | 细则 |
| --- | --- | --- | --- | --- | --- |
| B0.0 | 项目目录骨架与边界声明 | Week 1 | [x] | 串行 | [00](function-one-platform/00-project-skeleton-and-execution.md#b00) |
| B0.1 | 工程与开发命令基线 | Week 1 | [x] | 串行 | [01](function-one-platform/01-foundation-and-contracts.md#b01) |
| B0.2 | 后端 FastAPI 应用与错误契约 | Week 1 | [x] | 后端 | [01](function-one-platform/01-foundation-and-contracts.md#b02) |
| B0.3 | EnvironmentSettings 启动配置边界 | Week 1 | [x] | 后端 | [01](function-one-platform/01-foundation-and-contracts.md#b03) |
| L0.1 | 运行数据目录与日志启动预检 | Week 1 | [x] | 后端 | [01](function-one-platform/01-foundation-and-contracts.md#l01) |
| F0.1 | 前端 SPA 骨架与测试基线 | Week 1 | [x] | 前端 | [01](function-one-platform/01-foundation-and-contracts.md#f01) |
| C1.1 | 全局枚举与状态契约 | Week 2 | [x] | 后端契约 | [01](function-one-platform/01-foundation-and-contracts.md#c11) |
| C1.2 | 控制面 Schema 契约 | Week 2 | [x] | 后端契约 | [01](function-one-platform/01-foundation-and-contracts.md#c12) |
| C1.3 | Run、Feed 与事件 Schema 契约 | Week 2 | [x] | 后端契约 | [01](function-one-platform/01-foundation-and-contracts.md#c13) |
| C1.4 | Inspector 与 Metrics Schema 契约 | Week 2 | [x] | 后端契约 | [01](function-one-platform/01-foundation-and-contracts.md#c14) |
| C1.5 | 多 SQLite 连接与 session 管理 | Week 2 | [x] | 后端 | [01](function-one-platform/01-foundation-and-contracts.md#c15) |
| C1.6 | control 模型与迁移边界 | Week 2 | [x] | 后端 | [01](function-one-platform/01-foundation-and-contracts.md#c16) |
| C1.7 | runtime 模型与迁移边界 | Week 2 | [x] | 后端 | [01](function-one-platform/01-foundation-and-contracts.md#c17) |
| C1.8 | graph 模型与迁移边界 | Week 2 | [x] | 后端 | [01](function-one-platform/01-foundation-and-contracts.md#c18) |
| C1.9 | event 模型边界 | Week 2 | [x] | 后端 | [01](function-one-platform/01-foundation-and-contracts.md#c19) |
| C1.10 | PlatformRuntimeSettings 与运行快照 Schema 契约 | Week 2 | [x] | 后端契约 | [01](function-one-platform/01-foundation-and-contracts.md#c110) |
| C1.10a | PromptAsset Schema 契约 | Week 2 | [x] | 后端契约 | [01](function-one-platform/01-foundation-and-contracts.md#c110a) |
| L1.1 | 日志审计 Schema 与 TraceContext 契约 | Week 2 | [x] | 后端契约 | [01](function-one-platform/01-foundation-and-contracts.md#l11) |
| L1.2 | log 模型与迁移边界 | Week 2 | [x] | 后端 | [01](function-one-platform/01-foundation-and-contracts.md#l12) |
| L2.1 | API 请求与关联上下文 | Week 3 | [ ] | 后端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#l21) |
| L2.2 | 基础 RedactionPolicy 与 payload summarizer | Week 3 | [ ] | 后端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#l22) |
| L2.3 | JSONL writer 与 log index | Week 3 | [ ] | 后端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#l23) |
| L2.4 | AuditService 与控制面命令审计 | Week 3 | [ ] | 后端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#l24) |
| C2.1 | 默认 Project、项目加载与项目列表 | Week 3 | [ ] | 后端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#c21) |
| C2.2 | 系统模板与内置 Provider seed | Week 3 | [ ] | 后端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#c22) |
| C2.3 | draft Session、重命名与模板选择更新 | Week 3 | [ ] | 后端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#c23) |
| C2.4 | 用户模板保存、覆盖与删除 | Week 3 | [ ] | 后端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#c24) |
| C2.5 | Provider 管理 | Week 3 | [ ] | 后端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#c25) |
| C2.6 | DeliveryChannel 查询与保存 | Week 3 | [ ] | 后端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#c26) |
| C2.7 | DeliveryChannel readiness 校验 | Week 3 | [ ] | 后端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#c27) |
| C2.7a | 项目作用域配置包导入导出 | Week 3 | [ ] | 后端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#c27a) |
| C2.8 | PlatformRuntimeSettings 管理服务 | Week 3 | [ ] | 后端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#c28) |
| F2.1 | API Client 路径与类型入口 | Week 2-3 | [x] | 前端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#f21) |
| F2.2 | Mock Fixtures 与 Query Hooks | Week 2-3 | [x] | 前端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#f22) |
| F2.3 | Workspace Shell 与 Project Sidebar | Week 3 | [x] | 前端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#f23) |
| F2.4 | 统一设置弹窗 | Week 3 | [x] | 前端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#f24) |
| F2.5 | 模板空态与模板选择 | Week 3-4 | [ ] | 前端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#f25) |
| F2.6 | 模板编辑与脏状态守卫 | Week 3-4 | [ ] | 前端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#f26) |
| R3.1 | Run 状态机纯领域规则 | Week 4 | [ ] | 后端核心 | [03](function-one-platform/03-run-projection-and-feed.md#r31) |
| C2.9a | Session 删除命令与历史可见性 | Week 4 | [ ] | 后端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#c29a) |
| C2.9b | Project 移除命令与级联历史可见性 | Week 4 | [ ] | 后端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#c29b) |
| E3.1 | 领域事件 Schema 与 EventStore | Week 4 | [ ] | 后端 | [03](function-one-platform/03-run-projection-and-feed.md#e31) |
| R3.2 | 首条需求启动首个 run | Week 4 | [ ] | 后端核心 | [03](function-one-platform/03-run-projection-and-feed.md#r32) |
| R3.3 | 重新尝试领域规则与内部创建基础 | Week 4 | [ ] | 后端核心 | [03](function-one-platform/03-run-projection-and-feed.md#r33) |
| R3.4 | 模板快照固化 | Week 4 | [ ] | 后端 | [03](function-one-platform/03-run-projection-and-feed.md#r34) |
| R3.4a | Provider 与模型绑定快照固化 | Week 4 | [ ] | 后端 | [03](function-one-platform/03-run-projection-and-feed.md#r34a) |
| R3.4b | RuntimeLimitSnapshot 与 ProviderCallPolicySnapshot 固化 | Week 4 | [ ] | 后端 | [03](function-one-platform/03-run-projection-and-feed.md#r34b) |
| R3.5 | GraphDefinition 固定主链编译 | Week 4 | [ ] | 后端 | [03](function-one-platform/03-run-projection-and-feed.md#r35) |
| R3.6 | StageRun 持久化 | Week 4-5 | [ ] | 后端 | [03](function-one-platform/03-run-projection-and-feed.md#r36) |
| R3.7 | StageArtifact 存储 | Week 4-5 | [ ] | 后端 | [03](function-one-platform/03-run-projection-and-feed.md#r37) |
| Q3.1 | SessionWorkspaceProjection | Week 5 | [ ] | 后端 | [03](function-one-platform/03-run-projection-and-feed.md#q31) |
| Q3.2 | RunTimelineProjection | Week 5 | [ ] | 后端 | [03](function-one-platform/03-run-projection-and-feed.md#q32) |
| Q3.3 | StageInspectorProjection | Week 5 | [ ] | 后端 | [03](function-one-platform/03-run-projection-and-feed.md#q33) |
| Q3.4 | ControlItemInspectorProjection | Week 5 | [ ] | 后端 | [03](function-one-platform/03-run-projection-and-feed.md#q34) |
| Q3.4a | ToolConfirmationInspectorProjection | Week 5 | [ ] | 后端 | [03](function-one-platform/03-run-projection-and-feed.md#q34a) |
| E3.2 | SSE 流端点与断线恢复 | Week 5 | [ ] | 后端 | [03](function-one-platform/03-run-projection-and-feed.md#e32) |
| L3.1 | Run 与 Stage 日志轻查询 API | Week 5 | [ ] | 后端 | [03](function-one-platform/03-run-projection-and-feed.md#l31) |
| F3.1 | Workspace Store 快照初始化 | Week 5 | [ ] | 前端 | [03](function-one-platform/03-run-projection-and-feed.md#f31) |
| F3.2 | SSE Client 与 Event Reducer | Week 5 | [ ] | 前端 | [03](function-one-platform/03-run-projection-and-feed.md#f32) |
| F3.3 | Feed Entry Renderer | Week 5-6 | [ ] | 前端 | [03](function-one-platform/03-run-projection-and-feed.md#f33) |
| F3.4 | StageNode 与阶段内部条目 | Week 5-6 | [ ] | 前端 | [03](function-one-platform/03-run-projection-and-feed.md#f34) |
| F3.5 | Run Boundary 与 Run Switcher | Week 5-6 | [ ] | 前端 | [03](function-one-platform/03-run-projection-and-feed.md#f35) |
| F3.6 | Inspector Shell 与打开状态 | Week 5-6 | [ ] | 前端 | [03](function-one-platform/03-run-projection-and-feed.md#f36) |
| F3.7 | Inspector 分组与 Metrics 展示 | Week 5-6 | [ ] | 前端 | [03](function-one-platform/03-run-projection-and-feed.md#f37) |
| A4.0 | Runtime orchestration boundary | Week 6 | [ ] | 后端核心 | [04](function-one-platform/04-human-loop-and-runtime.md#a40) |
| L4.1 | 命令审计失败语义 | Week 6 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#l41) |
| L4.2 | 审计日志查询 API | Week 6 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#l42) |
| H4.1 | 澄清记录与后端消息语义 | Week 6 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#h41) |
| H4.2 | Composer 澄清输入语义 | Week 6 | [ ] | 前端 | [04](function-one-platform/04-human-loop-and-runtime.md#h42) |
| H4.3 | 审批对象与投影语义 | Week 6 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#h43) |
| D4.0 | Delivery snapshot gate | Week 6 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#d40) |
| H4.4 | 审批命令与交付就绪阻塞 | Week 6 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#h44) |
| H4.4a | ToolConfirmationRequest 与工具确认命令 | Week 6-7 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#h44a) |
| H4.5 | Pause/Resume checkpoint 语义 | Week 6 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#h45) |
| H4.6 | Terminate 与 system_status | Week 6 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#h46) |
| H4.7 | 重新尝试命令与多 run 分界 | Week 6 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#h47) |
| F4.1 | Composer 生命周期按钮状态 | Week 6 | [ ] | 前端 | [04](function-one-platform/04-human-loop-and-runtime.md#f41) |
| F4.2 | Run 控制按钮与终止入口 | Week 6 | [ ] | 前端 | [04](function-one-platform/04-human-loop-and-runtime.md#f42) |
| F4.3 | Approval Block 与 Reject 输入 | Week 6 | [ ] | 前端 | [04](function-one-platform/04-human-loop-and-runtime.md#f43) |
| F4.3a | Tool Confirmation Block 与确认交互 | Week 6-7 | [ ] | 前端 | [04](function-one-platform/04-human-loop-and-runtime.md#f43a) |
| F4.4 | 重新尝试 UI 与历史审批禁用态 | Week 6 | [ ] | 前端 | [04](function-one-platform/04-human-loop-and-runtime.md#f44) |
| A4.1 | RuntimeEngine 接口 | Week 7 | [ ] | 后端 | [05](function-one-platform/05-deterministic-runtime-and-demo-delivery.md#a41) |
| W5.0 | ToolProtocol 与工具注册表 | Week 7 | [ ] | 后端 | [07](function-one-platform/07-workspace-tools-risk-and-change-boundaries.md#w50) |
| W5.0a | 统一错误码字典与错误响应契约 | Week 7 | [ ] | 后端契约 | [07](function-one-platform/07-workspace-tools-risk-and-change-boundaries.md#w50a) |
| W5.1 | WorkspaceManager 隔离工作区 | Week 7 | [ ] | 后端 | [07](function-one-platform/07-workspace-tools-risk-and-change-boundaries.md#w51) |
| W5.0b | ToolRegistry execution gate | Week 7-8 | [ ] | 后端 | [07](function-one-platform/07-workspace-tools-risk-and-change-boundaries.md#w50b) |
| W5.0c | 后端测试 fixture、fake provider 与 fake tool 契约 | Week 7-8 | [ ] | 后端测试 | [07](function-one-platform/07-workspace-tools-risk-and-change-boundaries.md#w50c) |
| W5.0d | Tool risk classifier 与 confirmation gate | Week 7-8 | [ ] | 后端 | [07](function-one-platform/07-workspace-tools-risk-and-change-boundaries.md#w50d) |
| W5.2 | 文件工具 read_file/write_file/edit_file/glob | Week 7-8 | [ ] | 后端 | [07](function-one-platform/07-workspace-tools-risk-and-change-boundaries.md#w52) |
| W5.3 | grep 工具 | Week 7-8 | [ ] | 后端 | [07](function-one-platform/07-workspace-tools-risk-and-change-boundaries.md#w53) |
| W5.4 | bash 工具与白名单审计 | Week 7-8 | [ ] | 后端 | [07](function-one-platform/07-workspace-tools-risk-and-change-boundaries.md#w54) |
| A4.2 | deterministic test runtime 六阶段推进 | Week 7 | [ ] | 后端 | [05](function-one-platform/05-deterministic-runtime-and-demo-delivery.md#a42) |
| A4.3 | deterministic test runtime 澄清与审批中断 | Week 7 | [ ] | 后端 | [05](function-one-platform/05-deterministic-runtime-and-demo-delivery.md#a43) |
| A4.4 | deterministic test runtime 终态控制 | Week 7 | [ ] | 后端 | [05](function-one-platform/05-deterministic-runtime-and-demo-delivery.md#a44) |
| D4.1 | Delivery base 与 DeliveryRecord | Week 7 | [ ] | 后端 | [05](function-one-platform/05-deterministic-runtime-and-demo-delivery.md#d41) |
| D4.2 | demo_delivery adapter 与 delivery_result | Week 7 | [ ] | 后端 | [05](function-one-platform/05-deterministic-runtime-and-demo-delivery.md#d42) |
| D4.3 | DeliveryResultDetailProjection 正式实现 | Week 7 | [ ] | 后端 | [05](function-one-platform/05-deterministic-runtime-and-demo-delivery.md#d43) |
| A4.5 | LangGraph 主链与 checkpoint | Week 8 | [ ] | 后端 | [06](function-one-platform/06-langgraph-provider-context-stage-agent.md#a45) |
| A4.6 | LangGraph interrupt resume | Week 8 | [ ] | 后端 | [06](function-one-platform/06-langgraph-provider-context-stage-agent.md#a46) |
| A4.7 | LangGraph 事件到领域产物转换 | Week 8 | [ ] | 后端 | [06](function-one-platform/06-langgraph-provider-context-stage-agent.md#a47) |
| A4.8 | Provider Registry | Week 8 | [ ] | 后端 | [06](function-one-platform/06-langgraph-provider-context-stage-agent.md#a48) |
| A4.8a | PromptValidation 边界校验 | Week 8 | [ ] | 后端 | [06](function-one-platform/06-langgraph-provider-context-stage-agent.md#a48a) |
| A4.8b | ContextEnvelope 与 ContextManifest Schema | Week 8 | [ ] | 后端契约 | [06](function-one-platform/06-langgraph-provider-context-stage-agent.md#a48b) |
| A4.8c | PromptRegistry 与系统提示词资产加载 | Week 8 | [ ] | 后端 | [06](function-one-platform/06-langgraph-provider-context-stage-agent.md#a48c) |
| A4.8d | PromptRenderer 与消息序列渲染 | Week 8 | [ ] | 后端 | [06](function-one-platform/06-langgraph-provider-context-stage-agent.md#a48d) |
| A4.9 | LangChain Provider Adapter | Week 8 | [ ] | 后端 | [06](function-one-platform/06-langgraph-provider-context-stage-agent.md#a49) |
| A4.9a | ContextEnvelope Builder 与 ContextManifest 记录 | Week 8 | [ ] | 后端 | [06](function-one-platform/06-langgraph-provider-context-stage-agent.md#a49a) |
| A4.9e | Provider retry、backoff 与 circuit breaker | Week 8 | [ ] | 后端 | [06](function-one-platform/06-langgraph-provider-context-stage-agent.md#a49e) |
| A4.9b | Context Size Guard 与压缩过程记录 | Week 8 | [ ] | 后端 | [06](function-one-platform/06-langgraph-provider-context-stage-agent.md#a49b) |
| A4.9c | AgentDecision Schema 与解析器 | Week 8 | [ ] | 后端 | [06](function-one-platform/06-langgraph-provider-context-stage-agent.md#a49c) |
| A4.9d | Stage Agent Runtime 执行循环 | Week 8 | [ ] | 后端核心 | [06](function-one-platform/06-langgraph-provider-context-stage-agent.md#a49d) |
| A4.10 | 自动回归策略 | Week 8-9 | [ ] | 后端 | [06](function-one-platform/06-langgraph-provider-context-stage-agent.md#a410) |
| A4.11 | 自动回归控制条目与超限失败 | Week 8-9 | [ ] | 后端 | [06](function-one-platform/06-langgraph-provider-context-stage-agent.md#a411) |
| W5.5 | ChangeSet 与 ContextReference | Week 9 | [ ] | 后端 | [07](function-one-platform/07-workspace-tools-risk-and-change-boundaries.md#w55) |
| W5.6 | PreviewTarget Schema 与查询接口 | Week 9 | [ ] | 后端 | [07](function-one-platform/07-workspace-tools-risk-and-change-boundaries.md#w56) |
| D5.1 | read_delivery_snapshot 与交付快照读取 | Week 10 | [ ] | 后端 | [08](function-one-platform/08-git-delivery-and-result-display.md#d51) |
| D5.2 | prepare_branch 与 create_commit | Week 10 | [ ] | 后端 | [08](function-one-platform/08-git-delivery-and-result-display.md#d52) |
| D5.3 | push_branch 与 create_code_review_request | Week 10 | [ ] | 后端 | [08](function-one-platform/08-git-delivery-and-result-display.md#d53) |
| D5.4 | git_auto_delivery 编排与 snapshot readiness 测试 | Week 10 | [ ] | 后端 | [08](function-one-platform/08-git-delivery-and-result-display.md#d54) |
| F5.1 | 工具调用、Diff 与测试结果展示 | Week 9-10 | [ ] | 前端 | [08](function-one-platform/08-git-delivery-and-result-display.md#f51) |
| F5.2a | demo_delivery 结果展示 | Week 9 | [ ] | 前端 | [08](function-one-platform/08-git-delivery-and-result-display.md#f52a) |
| F5.2b | git_auto_delivery 结果展示 | Week 10 | [ ] | 前端 | [08](function-one-platform/08-git-delivery-and-result-display.md#f52b) |
| V6.1 | 后端完整 API flow 测试 | Week 11 | [ ] | 跨端 | [09](function-one-platform/09-regression-hardening-and-logs.md#v61) |
| V6.2 | Playwright 成功路径 | Week 11 | [ ] | 跨端 | [09](function-one-platform/09-regression-hardening-and-logs.md#v62) |
| V6.3 | Playwright 人工介入路径 | Week 11 | [ ] | 跨端 | [09](function-one-platform/09-regression-hardening-and-logs.md#v63) |
| V6.4 | OpenAPI 核心路由覆盖 | Week 11-12 | [ ] | 跨端 | [09](function-one-platform/09-regression-hardening-and-logs.md#v64) |
| V6.5 | 前端 client 与 OpenAPI 一致性 | Week 11-12 | [ ] | 跨端 | [09](function-one-platform/09-regression-hardening-and-logs.md#v65) |
| V6.6 | 前端错误态与后端错误回归 | Week 12 | [ ] | 跨端 | [09](function-one-platform/09-regression-hardening-and-logs.md#v66) |
| V6.8 | 配置边界与运行快照回归 | Week 12 | [ ] | 跨端 | [09](function-one-platform/09-regression-hardening-and-logs.md#v68) |
| L6.1 | 日志轮转与保留清理 | Week 12 | [ ] | 后端 | [09](function-one-platform/09-regression-hardening-and-logs.md#l61) |
| L6.2 | 日志审计回归包 | Week 12 | [ ] | 后端 | [09](function-one-platform/09-regression-hardening-and-logs.md#l62) |
| V6.7 | 回归场景与发布候选清单 | Week 12 | [ ] | 跨端 | [09](function-one-platform/09-regression-hardening-and-logs.md#v67) |

### 9.1 Delivery Branch Plan

本节索引并行交付分支控制表。完整调度表位于 [function-one-delivery-branch-plan.md](function-one-delivery-branch-plan.md)，用于并行工作区的 branch gate、batch 状态和 PR/MR review boundary 控制。

| 文档 | 内容 | 读取时机 |
| --- | --- | --- |
| [function-one-delivery-branch-plan.md](function-one-delivery-branch-plan.md) | Batch、交付分支、覆盖任务、前置门槛、并行等级、Status、主要共享入口 / 冲突点、Review boundary | 创建或认领工作区、`slice-workflow` 的 Current-Branch Batch Gate、更新当前分支 batch 状态 |
| `function-one-platform-plan.md` 第 9 节 | 全局子任务进度、负责人模型和 split-plan 入口 | 全局进度检查、任务状态更新、选择或验证具体 slice |
| [function-one-platform/](function-one-platform/) | split-plan 任务细则、修改文件列表、验收标准和验证命令 | 选定 slice 后解析范围、编写实施计划和执行验证 |

主线进度事实仍由本文件第 9 节和对应 split-plan 任务状态共同构成；交付分支控制表只维护 batch 边界、依赖、调度状态和 review 边界。

## 10. 每周验收清单

### Week 1

- 后端与前端基础工程可启动。
- 基础测试命令可运行。
- 健康检查和控制台路由可访问。
- `EnvironmentSettings` 能加载启动配置并派生默认运行数据根目录、工作区根目录、默认 Project 根路径和凭据环境变量引用规则。
- 项目目录骨架与文件职责边界完成文档化。
- 平台运行数据目录与 `.runtime/logs` 启动预检可用，目录不可写时服务不进入可接受用户命令状态。
- 前端实施计划模板包含 `Frontend Design Gate`，并确认设计质量门的执行方式。

### Week 2

- 核心枚举、Schema、数据库边界定稿。
- Pydantic Schema、投影契约、配置契约、运行快照契约与事件载荷可作为前端 mock 输入。
- Project 与 Session Schema 明确历史可见性、Session 展示名、重命名、删除和项目移除边界。
- `PlatformRuntimeSettings`、`RuntimeLimitSnapshot`、Provider/模型绑定快照 Schema 定稿，明确 `context_window_tokens`、`max_output_tokens`、`supports_tool_calling`、`supports_structured_output`、`supports_native_reasoning` 是 Provider 模型能力，`compression_threshold_ratio` 是上下文限制策略，且与 C1.10a 对齐明确 `compression_prompt` 是系统内置提示词资产，不是配置项。
- `ToolConfirmationRequest`、`ToolRiskLevel`、`ToolRiskCategory`、`waiting_tool_confirmation`、`tool_confirmation` 顶层条目和 `ProviderCallPolicySnapshot` Schema 定稿。
- `PromptAsset` Schema、提示词资产版本引用、权威级别和缓存属性定稿，且明确系统内置提示词资产不属于环境变量、平台运行设置或前端可写配置。
- 日志审计 Schema、TraceContext、`log.db` 模型边界和迁移测试通过。
- 多 SQLite session 管理、control/runtime/graph/event/log 模型边界和迁移测试通过。
- `event.db` 只承载领域事件和 Narrative Feed 投影来源数据，审计记录归属 `log.db`。

### Week 3

- Project、Session、Template、Provider、DeliveryChannel 与项目作用域配置包导入导出控制面 API 可用，Session 重命名只改变展示名。
- 系统模板初始化从 `agent_role_seed` 提示词资产写入默认 `AgentRole.system_prompt`，写入后运行时真源是模板槽位快照，不回读最新提示词资产。
- `PlatformRuntimeSettings` 管理服务可校验运行上限、Provider 调用策略、上下文裁剪限制、上下文压缩阈值比例、日志策略和诊断查询分页上限，但不进入普通前端设置弹窗。
- 控制面 API 切片已在各自 API 测试中断言本地 OpenAPI path、method、Schema 和主要错误响应。
- API request/correlation context、基础 RedactionPolicy、JSONL writer、log index 与 AuditService 可用。
- 控制面写操作继承关联上下文，先裁剪载荷，再写入运行日志和审计记录；成功、失败和被拒绝结果具备审计记录，且审计记录不替代控制面领域对象。
- 前端 Shell、设置弹窗、模板空态基于 mock 可操作；左栏支持已加载项目和历史会话展示、Session 重命名入口、Session 删除入口和 Project 移除入口的基础状态。
- 设置弹窗展示 DeliveryChannel、Provider 与项目作用域配置导入导出；Provider 页面允许编辑 custom Provider，并允许编辑内置 Provider 的连接字段、默认模型、模型列表、凭据引用和折叠 `高级设置` 中的 Provider 模型能力字段；设置弹窗不展示环境变量、SQLite 路径、平台运行上限、日志策略、`compression_threshold_ratio`、系统内置提示词资产、提示词版本切换或 `deterministic test runtime`。
- Workspace Shell、设置弹窗与模板空态完成设计质量门检查，项目级主基调已记录并被对应实施计划继承。

### Week 4

- Run 生命周期、状态机和 EventStore 测试通过。
- 模板快照与 GraphDefinition 编译测试通过。
- Provider 与模型绑定快照、运行上限快照、Provider 调用策略快照在 run 启动时固化；已启动 run 不读取最新 Provider 或平台运行设置改变语义。
- Session 删除和 Project 移除命令可用，且存在活动 run 时拒绝；Project 移除不删除本地项目文件夹、目标仓库、远端对象、提交或代码评审请求。
- 首条需求启动首个 run 时，PipelineRun、模板快照、Provider 与模型绑定快照、运行上限快照、GraphDefinition、首条消息事件和初始 StageRun 在同一服务事务中创建。
- 首个 run 启动生成贯穿 run 的 `trace_id`，并继承请求 `request_id` 与 `correlation_id`。
- Solution Validation 明确作为 `solution_design` 内部节点组，不形成独立 `StageRun`。
- 前端工作台能展示 draft、running 与基础阶段回放，不要求 failed / terminated 终态回放在 Week 4 完成。

### Week 5

- Session Workspace、Timeline、Inspector 查询投影可用。
- ToolConfirmationInspectorProjection 查询投影可用，且不复用 ApprovalRequest 或 ControlItemInspectorProjection。
- SSE 事件流可用。
- `GET /api/runs/{runId}/logs` 与 `GET /api/stages/{stageRunId}/logs` 可按对象返回裁剪后的日志摘要，且不作为 Narrative Feed 或 Inspector 主路径依赖。
- ControlItemInspectorProjection 只覆盖控制条目详情，不承载交付结果详情。
- 工具确认作为独立顶层 `tool_confirmation` 条目进入 workspace、timeline、SSE 和 Inspector；Provider 重试与熔断状态能进入阶段内部 `provider_call` 或 Inspector。
- 前端可消费快照与增量并展示 Narrative Feed。
- Narrative Feed、Run Boundary 与 Inspector 的实施计划包含设计质量门，顶层条目、阶段内部条目和详情面板的视觉层级不混淆。

### Week 6

- Runtime orchestration boundary 定稿，澄清、审批、工具确认、暂停、恢复和终止不得绕过该边界直接推进 run 状态；重新尝试只验证旧 GraphThread 终态并创建新 PipelineRun。
- 命令审计失败语义固定，高影响动作在审计台账写入失败时拒绝或回滚，不降级为普通运行日志失败。
- 审计日志查询 API 可用，用户可触发命令的接受、拒绝、成功和失败结果可按主体、动作、目标、run 和结果过滤。
- 澄清、审批、工具确认、暂停、恢复、终止、重新尝试路径可用。
- failed / terminated 的顶层 `system_status` 由同一个 TerminalStatusProjector 生成。
- `code_review_approval` 的 Approve 路径同时完成交付就绪 gate、顶层 `approval_result`、交付快照固化和进入 `delivery_integration` 的单一语义。
- 前端 Composer、Approval Block、重新尝试 UI 完成主交互。
- 前端 Tool Confirmation Block 完成允许 / 拒绝交互，不使用 Approve / Reject 文案，不展示审批回退语义。
- Composer 输入语义、Approval Block、Tool Confirmation Block、重新尝试 UI 完成设计硬化检查，禁用态、历史态、拒绝输入、危险操作和窄屏布局通过验收。

### Week 7

- ToolProtocol、ToolRegistry、工具风险确认门禁、统一错误码字典与 Claude Code 风格 Workspace tools 基座完成，`deterministic test runtime` 不使用临时工具接口。
- ToolRegistry execution gate 能按工具名、阶段 `allowed_tools`、输入 Schema、工作区边界、超时策略和审计策略拒绝非法工具调用；拒绝结果使用统一错误码并保留 trace 关联。
- 后端测试 fixture、fake Provider、fake tool、settings override、fixture 仓库和 mock remote 契约完成，所有 fake 能力消费正式 Schema、ProviderSnapshot、ModelBindingSnapshot、ToolProtocol、ToolRegistry execution gate 与交付快照契约。
- Tool risk classifier 能区分 `read_only`、`low_risk_write`、`high_risk`、`blocked`；高风险动作进入工具确认，blocked 动作结构化拒绝且不创建可允许的确认请求。
- Workspace tools 默认排除 `.runtime/logs` 与平台运行数据目录；`write_file`、`edit_file`、`bash` 和测试执行具备运行日志与审计引用，`edit_file` 采用精确字符串替换，`bash` 受命令白名单约束。
- `deterministic test runtime` 可跑通六阶段链路。
- `deterministic test runtime` 阶段推进、失败、终止和 `demo_delivery` 具备运行日志摘要与 trace 关联，并只消费 run 已固化的模板、Provider/模型绑定和运行上限快照。
- `deterministic test runtime` 可触发澄清、审批、高风险工具确认、失败和终止。
- failed / terminated run 的终态回放可用，并满足重新尝试前置条件。
- `demo_delivery` 可生成完整 DeliveryRecord 与顶层 `delivery_result`，且不执行真实 Git 写动作。
- DeliveryResultDetailProjection 基于真实 DeliveryRecord 实现，不使用 Week 5 的临时交付详情语义。
- 前端端到端链路不依赖真实模型完成。

### Week 8

- LangGraph runtime 接入固定主链。
- LangGraph interrupt、checkpoint 与人工介入命令共享 Week 6 的 runtime boundary。
- Provider adapter 接入模板快照。
- Provider retry/backoff/circuit breaker 可用，超时、网络错误和限流按本次 run 固化策略重试，连续失败熔断进入过程记录和前端可见投影。
- PromptValidation 对模板保存和 run 启动前的 `system_prompt` 执行边界校验，拒绝覆盖平台边界、阶段契约、工具边界、审批边界、交付边界、审计边界或输出 Schema 的提示词。
- PromptRegistry、内置提示词资产加载、PromptRenderer 和消息序列渲染可用；系统内置提示词不得散落到 runtime、context builder、Provider adapter 或模板服务的内联字符串中。
- ContextEnvelope、ContextManifest、Context Size Guard、压缩过程记录、AgentDecision Schema 与 Stage Agent Runtime 执行循环可用；模型调用不得绕过 PromptRenderer 和 Context Management，工具调用不得绕过 ToolRegistry，阶段结果不得绕过 StageArtifact。
- Stage Agent Runtime 能处理 `request_tool_confirmation`，高风险工具动作进入 H4.4a 工具确认，blocked 工具动作结构化拒绝；`test_generation_execution` 阶段能基于项目说明、依赖声明和脚本配置识别测试环境与依赖缺失。
- Provider Registry 与 LangChain Provider Adapter 读取 ProviderSnapshot 与 ModelBindingSnapshot，不读取最新 Provider 配置改变已启动 run。
- LangGraph 节点、checkpoint、interrupt/resume、Provider 解析、模型请求响应和结构化输出解析写入裁剪后的运行日志摘要。
- Provider adapter 和 LangGraph runtime 消费抽象 `ToolProtocol` 与已注册 workspace/fake 工具，不绑定 D5.1-D5.4 之前尚未实现的具体 delivery tool 实例；workspace 正式工具契约名只使用 `bash`、`read_file`、`edit_file`、`write_file`、`glob`、`grep`。
- 新建 Session 不自动继承其他会话的历史 run、历史产物、历史审批、历史工具确认或历史工具过程作为 Agent 长期记忆。
- 内部测试、前端联调与端到端验证可在 `deterministic test runtime` 与 LangGraph runtime 间切换；该切换不进入前端设置、项目设置、模板配置或平台环境变量，正式用户运行只走 LangGraph runtime，且 raw graph state 不进入产品 API。

### Week 9

- ChangeSet、ContextReference、PreviewTarget 边界落地。
- ChangeSet、diff、`glob`、`grep` 和工具展示均不把 `.runtime/logs` 或平台运行数据目录当作项目内容。
- 前端可展示工具调用、diff、测试结果。
- 工具调用、diff 与测试结果展示完成设计质量门检查，长日志、失败输出、文件路径和横向内容可用。

### Week 10

- `git_auto_delivery` 有可测路径。
- 交付就绪阻塞只发生在 code review approval。
- `git_auto_delivery` 通过 `read_delivery_snapshot` 读取已固化且字段完整的交付快照，不重新读取项目级最新 DeliveryChannel。
- Git 分支、提交、推送和 MR/PR 创建步骤具备运行日志和审计记录，交付失败可定位到失败步骤与 DeliveryRecord。
- git_auto_delivery 结果展示完成设计质量门检查，并与 `demo_delivery` 共用 `DeliveryResultProjection` 主结构。

### Week 11

- 全链路 E2E 覆盖主要成功路径和人工介入路径。
- 全链路 E2E 覆盖高风险工具确认允许 / 拒绝路径和 Provider 重试或熔断可见状态。
- API、SSE、投影、runtime、前端状态与日志审计主路径开始系统回归。
- 配置边界、系统内置提示词资产边界、运行快照、热重载不回写已启动 run、前端设置边界进入系统回归。
- Playwright 成功路径与人工介入路径覆盖关键 UI 状态，设计质量门发现项已进入回归问题清单。

### Week 12

- OpenAPI 与实现一致。
- OpenAPI 覆盖运行日志轻查询与审计日志查询接口。
- 配置边界与运行快照回归覆盖 EnvironmentSettings、PlatformRuntimeSettings、RuntimeLimitSnapshot、Provider 模型能力、Provider/模型绑定快照、系统内置提示词资产和前端设置边界。
- 错误码回归覆盖配置、Provider、PromptValidation、Context overflow、AgentDecision、ToolRegistry、workspace、bash allowlist、delivery、日志审计和运行数据目录错误；错误响应不得泄露堆栈、凭据、授权头、Cookie、API Key 或私钥。
- fixture 回归覆盖 settings override 不污染正式配置 API、前端设置、环境变量语义或已启动 run 快照，fake Provider / fake tool 只能消费正式抽象。
- 项目与会话历史管理回归覆盖重启后可见性、Session 重命名、Session 删除、Project 移除、活动 run 阻塞和审计事实保留。
- 日志轮转与保留清理通过，不删除领域对象、领域事件、阶段产物、审批记录或交付记录。
- 日志审计回归包覆盖敏感信息裁剪、审计失败回滚、日志查询退化和 `.runtime/logs` 排除。
- 错误态、空态、历史回放、响应式布局完成回归。
- 发布候选验收清单完成。
- 发布候选清单包含设计硬化结果、已修复 UI 问题、保留风险和对应验证证据。

## 11. 风险控制

| 风险 | 控制方式 |
| --- | --- |
| 大规约直接开发导致任务失控 | 每个执行切片先写 `docs/plans/implementation/<task-id>.md` 实施计划 |
| 任务粒度过大导致交付阻塞 | 单个切片只覆盖一个行为，写集控制在少量相邻文件内 |
| 前后端投影口径漂移 | C1.3 先固定 mock 契约，E3.1 先建立事件来源，Q3.1 基于 EventStore 回归校验真实投影，前端 mock 只从契约派生 |
| 日志管理被拖到尾期导致无法追溯早期链路 | 按 L0.1、L1.1、L1.2、L2.1-L2.4、L3.1、L4.1-L4.2、L6.1-L6.2 嵌入各阶段，并要求相关业务切片写 `Log & Audit Integration` |
| 日志审计替代领域事件或产品投影 | EventStore、StageArtifact、DeliveryRecord 和查询投影仍是产品真源；日志审计只记录运行观察事实、安全事实和诊断上下文 |
| 审计失败被降级处理导致高影响动作不可追责 | L4.1 固定审计台账失败时拒绝或回滚高影响动作，普通运行日志失败不得破坏已提交领域状态 |
| `.runtime/logs` 污染工作区、diff 或真实 Git 交付 | L0.1 标记平台运行数据目录，W5.1-W5.5 与 D5.2-D5.4 默认排除 `.runtime/logs` 和平台运行数据目录 |
| 日志载荷泄露凭据或本机敏感信息 | L1.1-L1.2 固定裁剪状态和载荷摘要，L2.2 建立统一裁剪与摘要策略，L2.3-L2.4 只能写入裁剪后载荷且不得接收 raw payload，L6.2 做敏感字段阻断、长度限制和脱敏回归 |
| 环境变量膨胀为业务配置中心 | B0.3 固定 `EnvironmentSettings` 只服务启动、路径、前后端连接和凭据引用解析；C1.10/C2.8 把平台隐性运行设置放入 `PlatformRuntimeSettings`，C1.10a 把系统内置提示词资产固定为版本化后端资产，Provider、DeliveryChannel 和模板运行配置仍走业务 API、模板编辑或配置包导入 |
| 配置包被实现为 runtime 真源 | C1.2 固定 `ConfigurationPackage` Schema，C2.7a 只把导入包通过正式配置服务写入 Provider、DeliveryChannel 或模板配置，R3.4a/R3.4b 固化快照，A4.8-A4.9b 不直接读取配置包 |
| 热重载设置改变已启动 run 语义 | R3.4a/R3.4b 在 run 启动时固化 Provider/模型绑定快照与 `RuntimeLimitSnapshot`，A4.1-A4.11 只消费本次 run 快照，V6.8 做回归 |
| `compression_prompt` 被实现为用户配置或热重载配置 | C1.10a 固定其为系统内置提示词资产类型，A4.8c/A4.8d 负责加载和渲染，A4.9b 只记录系统内置提示词资产版本引用，V6.8 检查其不进入环境变量、设置弹窗、模板编辑或配置 API |
| 系统内置提示词资产散落或版本漂移 | C1.10a 固定 PromptAsset Schema，C2.2 只把 `agent_role_seed` 写入模板默认槽位，A4.8c 统一加载资产，A4.8d 统一渲染消息序列，A4.9a/A4.9b 只消费渲染结果并记录版本、hash 与来源 |
| 前端设置弹窗暴露平台内部配置 | F2.4 只展示 DeliveryChannel、Provider 和项目作用域配置导入导出；Provider 页面只编辑 Provider 自身字段，并把 Provider 模型能力放入折叠 `高级设置`，导入导出只处理用户可见配置包；F2.6 只展示模板允许字段，V6.8 回归环境变量、SQLite 路径、运行上限、日志策略、`compression_threshold_ratio`、系统内置提示词资产、提示词版本切换和 `deterministic test runtime` 不进入普通设置 |
| 会话删除或项目移除被误实现为运行控制或物理删除 | C2.9a/C2.9b 固定其只改变产品历史可见性和常规查询入口；活动 run 阻塞删除/移除，默认 Project 不可移除，V6.8 回归不删除运行记录、产物、交付记录或审计事实 |
| 审计服务分叉导致命令审计语义漂移 | L2.4 是控制面和后续命令审计的唯一基础服务入口；L4.1 只补强审计失败时的拒绝或回滚语义，不创建第二套审计服务、审计表或临时记录 |
| Human-in-the-loop 先于 runtime 语义落地导致后补 | A4.0 在 H4 命令前固定 Runtime orchestration boundary，澄清、审批、暂停、恢复和终止不得绕过该边界；重新尝试只验证旧 GraphThread 终态并创建新 run |
| 高风险工具确认被误建模为第三个人工审批检查点 | C1.1/C1.3/C1.4 固定 `tool_confirmation` 独立顶层条目与 Schema，H4.4a 固定 allow / deny 命令，F4.3a 固定工具确认块文案和交互，审批对象仍只由 H4.3/H4.4 管理 |
| 审批通过与交付快照固化分离导致 approve 语义漂移 | D4.0 前置到 H4.4 之前，`code_review_approval` 的 Approve 在同一服务事务中完成 ready gate、审批决策、`approval_result`、完整 snapshot 和进入 `delivery_integration`，不得暴露已 approve 但 snapshot 未固化的中间态 |
| 交付快照字段含糊导致 Delivery Integration 重新读项目级配置 | D4.0/D5.1 固定完整 snapshot schema：`delivery_mode`、SCM 字段、`credential_ref`、`credential_status`、`readiness_status`、`readiness_message`、`last_validated_at`；项目级校验响应只使用 `validated_at` |
| 模型不确定性阻塞联调 | `deterministic test runtime` 先行，LangGraph runtime 后接 |
| `demo_delivery` 与 runtime 联调边界不清 | Week 7 将 `demo_delivery` 作为正式适配器落地，但限定其不执行真实 Git 写动作 |
| LangGraph 状态泄漏到产品 API | 投影层只读取领域对象、事件和产物引用 |
| ToolProtocol 漂移导致 runtime、Provider adapter 与 delivery tool 绑定口径不一 | W5.0 前置固定 `ToolProtocol` 与 `ToolRegistry`，W5.0b 固定唯一 execution gate，W5.2-W5.4 和 D5.1-D5.4 只实现具体工具，LangGraph、Stage Agent Runtime 和 Provider adapter 只能消费抽象协议；Workspace tools 的正式契约名固定为 `bash`、`read_file`、`edit_file`、`write_file`、`glob`、`grep` |
| 工具风险分级绕过或口径漂移 | W5.0d 固定 `ToolRiskClassifier` 与 confirmation gate，W5.4 只补命令级 allowlist，A4.9d 只能消费 W5.0d 的风险结果；high_risk 创建 `ToolConfirmationRequest`，blocked 结构化拒绝且不创建可允许确认 |
| Provider 失败被静默重试或自动切换配置 | C1.10 固定 Provider 调用策略快照，A4.9e 固定指数退避、熔断与过程记录，Q3.3/F3.4/F3.7 固定前端可见投影；已启动 run 不读取最新 Provider 配置改变执行语义 |
| 错误码散落导致前后端和工具错误不可回归 | B0.2 建立基础错误契约，W5.0a 扩展统一错误码字典，C2.8、R3.4a/R3.4b、A4.8a-A4.9e、W5.0b-W5.4、D5.1-D5.4 和 L6.2/V6.6 只能引用该字典，不得在路由、工具或 runtime 中散落自由文本错误码 |
| 用户 prompt 覆盖平台边界 | A4.8a 在模板保存和 run 启动前执行 PromptValidation；A4.8c 不接受用户 prompt 作为系统资产；A4.9a 只把通过校验且已固化的 `system_prompt` 作为低权威 `agent_role_prompt` 放入 ContextEnvelope |
| 上下文组装绕过可信边界或丢失可追溯性 | A4.8b 固定 ContextEnvelope / ContextManifest Schema，A4.8c/A4.8d 固定系统提示词资产加载与渲染来源，A4.9a/A4.9b 负责构建、尺寸守卫、按 `context_window_tokens * compression_threshold_ratio` 触发压缩并写入 `StageArtifact.process` 记录，Inspector 只能读取 StageArtifact 或稳定引用 |
| 模型自由文本推进状态或执行工具 | A4.9c 固定 AgentDecision 结构化协议，A4.9d Stage Agent Runtime 只按 AgentDecision、stage_contract、ToolRegistry execution gate 和 StageArtifact 契约推进阶段 |
| 历史会话被实现为隐式长期记忆 | 产品总规约固定 V1 无跨会话长期记忆，A4.9a 只把当前 Session 需求链路中显式引用的历史 run 纳入上下文，V6.8 回归新 Session 不自动读取其他会话的历史 run、产物、审批、工具确认或工具过程 |
| 测试 fixture 形成第二套运行语义 | W5.0c 固定 fake Provider、fake tool、settings override、fixture 仓库和 mock remote 只能消费正式 Schema、ProviderSnapshot、ModelBindingSnapshot、ToolProtocol、ToolRegistry execution gate 与交付快照契约 |
| API client 与后端路由路径漂移 | F2.1 统一拥有核心 client 资源路径；每个 API 切片在本地 API 测试中断言 OpenAPI 变更，V6.5 再做前端 client 与 OpenAPI 全局一致性回归 |
| 交付详情投影早于 DeliveryRecord 导致临时详情语义 | Q3.4 只做 ControlItemInspectorProjection；D4.3 在 DeliveryRecord 落地后实现正式 DeliveryResultDetailProjection |
| 工作区改动污染真实仓库 | Workspace tests 使用 fixture 仓库；真实 Git 写动作只在交付适配层受控发生 |
| `git_auto_delivery` 过早复杂化 | Week 7 先完成 `demo_delivery` 与 DeliveryRecord，Week 10 再拆分实现 `read_delivery_snapshot`、branch、commit、push、MR/PR |
| TDD 退化为补测试 | 每个实施计划必须包含失败测试、失败输出、最小实现和通过输出 |
| Superpowers commit 流程与仓库规则冲突 | commit 步骤替换为提交申请，等待用户批准 |
| 前端主基调输入缺失导致实现停滞 | 主 agent 只在 `F0.1` 或首个可见前端切片前提醒用户确立一次主基调；无参考时记录默认产品型工作台风格并继续实施 |
| UI 打磨覆盖业务语义 | 设计质量门只控制呈现质量；所有业务语义、API、投影、事件与运行时控制仍以正式规格和契约测试为准 |
| 设计检查替代真实验证 | 完成前仍必须运行组件、状态、API client、Playwright 或响应式验证，并在汇报中列出命令和结果 |

## 12. 总完成定义

功能一平台级 V1 完成时，必须同时满足：
- 新建项目、会话、模板选择、首条需求、澄清、方案审批、代码评审审批、暂停恢复、终止、重新尝试、交付结果回看可在单一控制台完成。
- 后端 REST API、SSE、OpenAPI、查询投影和领域状态与三份正式规格一致。
- `deterministic test runtime` 能稳定通过端到端测试。
- LangGraph runtime 能运行固定主链并支持中断恢复。
- `demo_delivery` 不执行真实 Git 写动作但生成完整 DeliveryRecord。
- `git_auto_delivery` 通过受控适配层完成分支、提交、推送与代码评审请求流程。
- 平台日志审计能力可用：本地 JSONL、`log.db` 轻量索引、审计记录、TraceContext、run/stage 日志查询、审计日志查询、轮转保留、敏感信息裁剪和 `.runtime/logs` 排除均通过验证。
- 配置管理边界可用：环境变量只服务启动与引用解析，平台运行设置可热重载但不改变已启动 run，业务配置通过对应 API 或模板编辑管理，所有执行语义配置在运行边界固化为快照。
- 项目与会话历史管理可用：已加载项目和历史会话重启后可见，Session 可重命名，非活动 Session 可删除，非默认且无活动 run 的 Project 可移除，且这些动作不删除运行事实或审计事实。
- Inspector 对阶段、控制条目和交付结果提供完整 input/process/output/artifacts/metrics。
- Tool Confirmation 作为独立顶层交互和独立 Inspector 详情可用；高风险工具确认不创建 ApprovalRequest 或 ApprovalDecision。
- Provider 超时、网络错误和限流能按本次 run 固化策略指数退避重试；连续失败能熔断并在阶段状态或 Inspector 中展示。
- 新建 Session 不自动继承其他会话的历史 run、历史产物、历史审批、历史工具确认或历史工具过程作为长期记忆。
- 前端关键展示切片完成设计质量门检查，工作台、Narrative Feed、Inspector、人工介入、工具结果和交付详情的风格一致性、状态覆盖、响应式和可访问性通过验收。
- 分层测试通过，端到端回归通过。
- 所有正式规格变更和计划文档均已通过用户评审后再进入提交流程。
