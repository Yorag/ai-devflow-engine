# 功能一平台级 V1 项目总计划

> 状态：Draft for review
> 计划口径：10 周功能完成 + 2 周联调、回归与硬化
> 执行模型：前后端并行，后端契约先行，deterministic runtime 先打通稳定链路，LangGraph runtime 作为正式编排路径
> 适用范围：功能一平台级 V1，不以临时演示版本为目标

## 1. 计划目标

本文档用于把功能一当前前后端规约拆解为可排期、可追踪、可测试、可继续细化为 Superpowers 实施计划的项目总计划。

本文档的直接输入依据为：
- `docs/specs/function-one-product-overview-v1.md`
- `docs/specs/frontend-workspace-global-design-v1.md`
- `docs/specs/function-one-backend-engine-design-v1.md`

本文档不以 `docs/specs/function-one/` 下的细分文档作为输入依据。后续若这些细分文档通过评审并成为正式规格，需要单独更新本计划。

## 2. 总体交付口径

功能一平台级 V1 的目标不是一次性演示链路，而是一个具备正式平台边界的软件版本。V1 必须同时满足以下交付口径：
- 前端具备单一 SPA 控制台、项目与会话工作台、模板空态、统一设置弹窗、Narrative Feed、Run Switcher、Composer、Approval Request、Inspector 与历史回放能力。
- 后端具备 FastAPI 服务、REST API、SSE、OpenAPI、领域模型、查询投影、多 SQLite 职责拆分、运行状态机、人工介入、工作区工具、交付适配与 LangGraph 执行内核接入。
- 测试具备分层覆盖：领域单元测试、API 契约测试、投影测试、SSE 流测试、前端组件测试、前端状态测试、端到端测试、工作区与交付适配测试。
- 执行内核采用双路径：deterministic runtime 负责稳定测试、前端联调和端到端验收；LangGraph runtime 负责正式 Agent 编排路径。
- 交付模式同时覆盖 `demo_delivery` 与 `git_auto_delivery`。`demo_delivery` 不能替代真实交付适配边界，`git_auto_delivery` 必须通过受控适配层实现。

## 3. 拆解原则

本计划采用“平台能力层 + 可验收执行切片”的混合拆分方式。

拆分原则如下：
- 后端契约先行：前端依赖 OpenAPI、投影 Schema、事件载荷、状态枚举与 mock fixtures 并行开发。
- 平台骨架先行：Project、Session、Template、Provider、DeliveryChannel、PipelineRun、StageRun、Event、Projection 是后续能力的基础，不延后到业务阶段实现之后。
- Walking skeleton 先行：先打通默认 Project、draft Session、首条需求创建 fake run、workspace projection、前端读取与 SSE 增量，再逐步替换为完整 runtime。
- Deterministic runtime 先行：deterministic runtime 先完成六阶段、澄清、审批、失败和终止，并通过正式 `demo_delivery` 形成 DeliveryRecord；再接入 LangGraph runtime 与 `git_auto_delivery`。
- 领域对象优先于框架细节：LangGraph 原始状态不暴露给前端；产品级 API、投影和事件以领域对象为准。
- 子任务可单独验收：每个执行切片必须有明确文件范围、实现对象、验收标准和测试方法。
- 每个执行切片只交付一个明确行为，避免同一切片同时覆盖持久化、服务、API、投影和 UI。
- 每个实现切片必须继续拆成 TDD 实施计划：总计划只定义交付切片，进入开发前必须用 `superpowers:writing-plans` 写出该切片的红绿步骤。

## 4. Superpowers 执行方式

### 4.1 总体流程

每个非文档实现切片按以下流程执行：

1. 使用 `git-delivery-workflow` 做分支门禁判断。该步骤只做只读检查，任何 Git 写动作必须等待用户批准。
2. 使用 `superpowers:writing-plans` 为单个切片写实施计划。计划存放在 `docs/plans/implementation/`，文件名采用 `<task-id>-<task-name>.md`。
3. 单个实施计划必须包含 TDD 红绿步骤、具体测试代码、具体实现代码、运行命令和预期输出。
4. 执行时优先使用 `superpowers:subagent-driven-development`。若当前环境或用户选择不使用子代理，则使用 `superpowers:executing-plans`。
5. 每个子任务完成后使用 `superpowers:verification-before-completion` 做完成前验证。
6. 若需要提交，只能提出提交申请，不能主动执行提交。规格文档与计划文档在用户评审前不得提交。

### 4.2 与本仓库 Git 规则的关系

Superpowers 模板中出现的 `commit` 步骤，在本仓库中统一替换为：
- 生成已验证 checkpoint。
- 汇报变更文件、验证命令与结果。
- 按 `git-delivery-workflow` 准备提交申请。
- 等待用户明确批准后再执行 Git 写动作。

任何 agent 或 subagent 都必须遵守：
- 不主动创建分支。
- 不主动提交。
- 不主动合并。
- 不主动打 tag。
- 不回滚用户已有改动。

### 4.3 子代理使用边界

适合使用 `superpowers:subagent-driven-development` 的任务：
- 单个后端服务或单个 API 资源实现。
- 单个前端组件群实现。
- 单个投影或事件处理链路。
- 单个测试层补齐。
- 单个适配器实现。

必须串行执行的任务：
- 数据模型与枚举首次定稿。
- OpenAPI 与前端客户端生成策略定稿。
- Run 生命周期状态机首次定稿。
- Narrative Feed 顶层条目语义首次定稿。
- DeliveryChannel 与最终审批阻塞语义定稿。
- LangGraph runtime 与 deterministic runtime 的接口边界定稿。

### 4.4 前端设计质量门

前端设计质量门用于控制 UI/UX 质量，不作为业务规格来源。所有前端实现切片仍以三份正式规格、OpenAPI、投影契约、事件语义和现有组件边界为准。设计质量门只能用于调整呈现、层级、状态覆盖、可访问性、响应式和视觉一致性，不能改变阶段语义、运行时控制语义、后端 API、投影字段或事件载荷。

执行者可以使用可用的设计审查工具辅助完成设计塑形、审查、打磨和硬化。在 Codex 环境中，已安装的全局 Impeccable skill 可以作为辅助工具使用。

适用范围：
- 必须纳入实施计划的前端展示切片：`F2.3-F2.6`、`F3.3-F3.7`、`F4.1-F4.4`、`F5.1-F5.2`。
- 作为人工介入前端输入切片纳入实施计划：`H4.2`。
- 建立前端基线时纳入检查口径：`F0.1`。
- 系统回归与发布候选阶段纳入验收口径：`V6.2`、`V6.3`、`V6.6`、`V6.7`。
- 纯 API client、mock fixture、状态合并切片只在引入可见 UI 时使用设计质量门；其主验收仍是契约一致性和状态正确性。

前端展示切片的实施计划必须包含 `Frontend Design Gate` 小节：
- 主基调来源：现有 UI、用户参考图、参考产品、已评审的设计上下文文档或默认产品型工作台风格。
- 主基调确立：`F0.1` 或首个可见前端切片必须记录主基调；用户提供参考示例时，将参考示例提炼为项目级主基调。
- 主基调继承：后续前端展示切片默认继承已记录主基调，不逐项重复询问用户。
- 参考边界：明确参考视觉气质、信息密度、组件形态、颜色、字体、布局节奏中的哪些项；明确不复制或不引入的项。
- 默认风格：当用户没有提供参考时，采用安静、专业、高信息密度、便于扫描的产品型工作台界面。
- 重新确认条件：只有用户主动更换参考风格、现有主基调与新界面类型明显冲突，或主基调不足以覆盖新增复杂呈现时，才重新向用户确认。
- 实现前设计门：梳理信息层级、布局、状态、交互路径和响应式策略。
- 实现后审查门：检查可访问性、响应式、文本溢出、对比度、焦点态和视觉反模式。
- 交付前硬化门：处理空态、加载态、错误态、禁用态、长文本、历史态和边界场景。
- 汇报要求：列出设计质量门发现的问题、已处理项、保留风险和对应验证证据。

主基调提醒由主 agent 在 `F0.1` 或首个可见前端切片进入实施计划前执行一次。若用户没有提供参考，实施计划必须记录默认风格选择，并继续执行，不因缺少风格输入阻塞业务开发。

设计质量门不替代测试。完成前仍必须运行对应组件测试、状态测试、API client 测试、Playwright 场景或响应式验证，并使用 `superpowers:verification-before-completion` 汇总证据。

## 5. 分层测试策略

### 5.1 后端测试层

后端测试分为以下层级：
- 领域单元测试：验证状态机、模板快照、审批规则、交付配置规则、投影组装规则。
- 持久化测试：使用临时 SQLite 文件验证 `control.db`、`runtime.db`、`graph.db`、`event.db` 的模型、约束与迁移。
- API 契约测试：使用 FastAPI TestClient 验证 REST 接口、错误响应、OpenAPI Schema。
- 事件流测试：验证 SSE 事件顺序、载荷结构、断线重建所需快照一致性。
- Runtime 测试：deterministic runtime 测试固定阶段推进；LangGraph runtime 测试图编译、中断、恢复、失败。
- 工作区测试：使用临时 Git fixture 仓库验证读写、diff、命令执行、测试执行和隔离边界。
- 交付测试：`demo_delivery` 验证无 Git 写动作；`git_auto_delivery` 使用本地 fixture 和 mock 托管平台客户端验证分支、提交、推送与代码评审请求流程。

### 5.2 前端测试层

前端测试分为以下层级：
- 组件单元测试：验证 Shell、Template Editor、Narrative Feed、Composer、Approval Block、Inspector、Settings Modal。
- 状态测试：验证 Zustand store、SSE merge、Run focus、Composer 状态机、审批可提交状态。
- API client 测试：验证 TanStack Query hooks、错误态、缓存失效、mock fixtures。
- 路由测试：验证 SPA 路由、控制台进入、会话切换、历史回放。
- E2E 测试：使用 Playwright 验证新建会话、首条需求启动、澄清、审批、暂停恢复、终止、重新尝试、交付结果回看。
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
| Week 1 | 工程与骨架基线 | 工具链、FastAPI app、错误模型 | Vite React 骨架、路由、测试工具 | 后端健康检查与前端控制台入口可运行 |
| Week 2 | 契约与持久化 | 枚举、Schema、多 SQLite、Alembic | API client、mock fixtures | OpenAPI 初版可作为前端 mock 输入 |
| Week 3 | 控制面可用 | Project、Session、Template、Provider、DeliveryChannel API | Shell、设置弹窗、模板空态 | 前后端控制面字段对齐 |
| Week 4 | Run 主链骨架 | Run 状态机、模板快照、GraphDefinition、StageArtifact | Workspace 页面、Run 分段基础展示 | draft、running、terminal 状态可回放 |
| Week 5 | 投影与实时更新 | Workspace Projection、Timeline、Inspector、SSE | Narrative Feed、Inspector、SSE merge | 快照 + 增量一致 |
| Week 6 | 人工介入 | 澄清、审批、暂停、恢复、终止、重新尝试 | Approval Block、Composer lifecycle、Retry UI | 人工介入全路径可验收 |
| Week 7 | deterministic 端到端 | deterministic runtime 六阶段链路与 demo_delivery | 前端完整流程联调 | 不依赖真实模型跑通 demo_delivery |
| Week 8 | LangGraph 正式路径 | Graph compiler、interrupt、checkpoint、Provider adapter | Runtime 错误态与状态呈现 | deterministic/runtime 双路径可切换 |
| Week 9 | 工作区能力 | Workspace tools、隔离工作区、测试执行 | diff、工具调用、测试结果展示 | 临时仓库改动与回放可验收 |
| Week 10 | 真实 Git 交付适配 | git_auto_delivery | 真实交付结果、交付阻塞状态、历史详情 | git_auto_delivery 可测 |
| Week 11 | 系统回归 | API、SSE、持久化、runtime 回归 | 组件、状态、E2E、响应式回归 | 主要成功路径与人工介入路径通过 |
| Week 12 | 平台硬化 | OpenAPI、错误处理、审计、迁移稳定 | 可用性、空态、错误态、视觉一致性 | 发布候选验收清单完成 |

## 7. 任务依赖总览

```text
项目目录骨架与边界声明
  -> 工程基线
    -> 枚举 / Schema 契约
      -> 持久化基线
        -> Project / Template / Session / DeliveryChannel 控制面
          -> API client / mock fixtures
            -> 前端 Shell / Settings / Template
              -> Run 状态机 / 模板快照 / GraphDefinition
                -> StageArtifact
                  -> Workspace / Timeline / Inspector 投影
                    -> SSE / 前端状态合并
                      -> Narrative Feed / Inspector UI
                        -> Human-in-the-loop
                          -> deterministic runtime
                            -> LangGraph runtime / Provider adapter
                              -> Workspace tools
                                -> Delivery adapters
                                  -> E2E / Regression / Hardening
```

前端允许在后端实现未完成时基于 mock fixtures 并行推进，但 mock fixtures 必须来源于后端 Schema 与投影契约。

## 8. 分卷索引

| 分卷 | 内容 | 任务范围 |
| --- | --- | --- |
| [00 项目骨架与执行规则](function-one-platform/00-project-skeleton-and-execution.md) | 目标目录骨架与 B0.0 子任务细则 | B0.0 |
| [01 工程基线与契约层](function-one-platform/01-foundation-and-contracts.md) | 工程基线、Schema 契约、数据库职责拆分 | B0.1, B0.2, F0.1, C1.1-C1.6 |
| [02 控制面与工作台外壳](function-one-platform/02-control-plane-and-workspace-shell.md) | Project、Session、Template、Provider、DeliveryChannel、Shell、设置、模板空态 | C2.1-C2.7, F2.1-F2.6 |
| [03 Run 主链、投影与叙事流](function-one-platform/03-run-projection-and-feed.md) | PipelineRun、GraphDefinition、StageArtifact、Workspace Projection、SSE、Feed、Inspector | R3.1-R3.7, Q3.1-Q3.4, E3.1-E3.2, F3.1-F3.7 |
| [04 人工介入与执行内核](function-one-platform/04-human-loop-and-runtime.md) | 澄清、审批、暂停恢复终止、deterministic runtime、demo_delivery、LangGraph、Provider、自动回归 | H4.1-H4.7, F4.1-F4.4, A4.1-A4.11, D4.1-D4.2 |
| [05 工作区、真实 Git 交付与硬化](function-one-platform/05-workspace-delivery-and-hardening.md) | Workspace tools、ChangeSet、git_auto_delivery、E2E、OpenAPI、回归硬化 | W5.1-W5.6, D5.1-D5.4, F5.1-F5.2, V6.1-V6.7 |

## 9. 进度追踪表

状态标记固定为：
- `[ ]` 未开始
- `[~]` 进行中
- `[x]` 已完成

| ID | 子任务 | 周期 | 状态 | 负责人模型 | 细则 |
| --- | --- | --- | --- | --- | --- |
| B0.0 | 项目目录骨架与边界声明 | Week 1 | [ ] | 串行 | [00](function-one-platform/00-project-skeleton-and-execution.md#b00) |
| B0.1 | 工程与开发命令基线 | Week 1 | [ ] | 串行 | [01](function-one-platform/01-foundation-and-contracts.md#b01) |
| B0.2 | 后端 FastAPI 应用与错误契约 | Week 1 | [ ] | 后端 | [01](function-one-platform/01-foundation-and-contracts.md#b02) |
| F0.1 | 前端 SPA 骨架与测试基线 | Week 1 | [ ] | 前端 | [01](function-one-platform/01-foundation-and-contracts.md#f01) |
| C1.1 | 状态枚举与阶段类型契约 | Week 2 | [ ] | 后端契约 | [01](function-one-platform/01-foundation-and-contracts.md#c11) |
| C1.2 | 控制面 Schema 契约 | Week 2 | [ ] | 后端契约 | [01](function-one-platform/01-foundation-and-contracts.md#c12) |
| C1.3 | Run、Feed 与事件 Schema 契约 | Week 2 | [ ] | 后端契约 | [01](function-one-platform/01-foundation-and-contracts.md#c13) |
| C1.4 | Inspector 与 Metrics Schema 契约 | Week 2 | [ ] | 后端契约 | [01](function-one-platform/01-foundation-and-contracts.md#c14) |
| C1.5 | 多 SQLite 连接与 session 管理 | Week 2 | [ ] | 后端 | [01](function-one-platform/01-foundation-and-contracts.md#c15) |
| C1.6 | control/runtime/graph/event 模型与迁移边界 | Week 2 | [ ] | 后端 | [01](function-one-platform/01-foundation-and-contracts.md#c16) |
| C2.1 | 默认 Project 与项目列表 | Week 3 | [ ] | 后端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#c21) |
| C2.2 | 系统模板与内置 Provider seed | Week 3 | [ ] | 后端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#c22) |
| C2.3 | draft Session 与模板选择更新 | Week 3 | [ ] | 后端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#c23) |
| C2.4 | 用户模板保存、覆盖与删除 | Week 3 | [ ] | 后端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#c24) |
| C2.5 | custom Provider 管理 | Week 3 | [ ] | 后端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#c25) |
| C2.6 | DeliveryChannel 查询与保存 | Week 3 | [ ] | 后端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#c26) |
| C2.7 | DeliveryChannel readiness 校验 | Week 3 | [ ] | 后端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#c27) |
| F2.1 | API Client 路径与类型入口 | Week 2-3 | [ ] | 前端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#f21) |
| F2.2 | Mock Fixtures 与 Query Hooks | Week 2-3 | [ ] | 前端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#f22) |
| F2.3 | Workspace Shell 与 Project Sidebar | Week 3 | [ ] | 前端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#f23) |
| F2.4 | 统一设置弹窗 | Week 3 | [ ] | 前端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#f24) |
| F2.5 | 模板空态与模板选择 | Week 3-4 | [ ] | 前端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#f25) |
| F2.6 | 模板编辑与脏状态守卫 | Week 3-4 | [ ] | 前端 | [02](function-one-platform/02-control-plane-and-workspace-shell.md#f26) |
| R3.1 | Run 状态机纯领域规则 | Week 4 | [ ] | 后端核心 | [03](function-one-platform/03-run-projection-and-feed.md#r31) |
| R3.2 | 首条需求启动首个 run | Week 4 | [ ] | 后端核心 | [03](function-one-platform/03-run-projection-and-feed.md#r32) |
| R3.3 | retry run 创建规则 | Week 4 | [ ] | 后端核心 | [03](function-one-platform/03-run-projection-and-feed.md#r33) |
| R3.4 | 模板快照固化 | Week 4 | [ ] | 后端 | [03](function-one-platform/03-run-projection-and-feed.md#r34) |
| R3.5 | GraphDefinition 固定主链编译 | Week 4 | [ ] | 后端 | [03](function-one-platform/03-run-projection-and-feed.md#r35) |
| R3.6 | StageRun 持久化 | Week 4-5 | [ ] | 后端 | [03](function-one-platform/03-run-projection-and-feed.md#r36) |
| R3.7 | StageArtifact 存储 | Week 4-5 | [ ] | 后端 | [03](function-one-platform/03-run-projection-and-feed.md#r37) |
| Q3.1 | SessionWorkspaceProjection | Week 5 | [ ] | 后端 | [03](function-one-platform/03-run-projection-and-feed.md#q31) |
| Q3.2 | RunTimelineProjection | Week 5 | [ ] | 后端 | [03](function-one-platform/03-run-projection-and-feed.md#q32) |
| Q3.3 | StageInspectorProjection | Week 5 | [ ] | 后端 | [03](function-one-platform/03-run-projection-and-feed.md#q33) |
| Q3.4 | ControlItem 与 Delivery detail 投影 | Week 5 | [ ] | 后端 | [03](function-one-platform/03-run-projection-and-feed.md#q34) |
| E3.1 | 领域事件 Schema 与 EventStore | Week 5 | [ ] | 后端 | [03](function-one-platform/03-run-projection-and-feed.md#e31) |
| E3.2 | SSE 流端点与断线恢复 | Week 5 | [ ] | 后端 | [03](function-one-platform/03-run-projection-and-feed.md#e32) |
| F3.1 | Workspace Store 快照初始化 | Week 5 | [ ] | 前端 | [03](function-one-platform/03-run-projection-and-feed.md#f31) |
| F3.2 | SSE Client 与 Event Reducer | Week 5 | [ ] | 前端 | [03](function-one-platform/03-run-projection-and-feed.md#f32) |
| F3.3 | Feed Entry Renderer | Week 5-6 | [ ] | 前端 | [03](function-one-platform/03-run-projection-and-feed.md#f33) |
| F3.4 | StageNode 与阶段内部条目 | Week 5-6 | [ ] | 前端 | [03](function-one-platform/03-run-projection-and-feed.md#f34) |
| F3.5 | Run Boundary 与 Run Switcher | Week 5-6 | [ ] | 前端 | [03](function-one-platform/03-run-projection-and-feed.md#f35) |
| F3.6 | Inspector Shell 与打开状态 | Week 5-6 | [ ] | 前端 | [03](function-one-platform/03-run-projection-and-feed.md#f36) |
| F3.7 | Inspector 分组与 Metrics 展示 | Week 5-6 | [ ] | 前端 | [03](function-one-platform/03-run-projection-and-feed.md#f37) |
| H4.1 | 澄清记录与后端消息语义 | Week 6 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#h41) |
| H4.2 | Composer 澄清输入语义 | Week 6 | [ ] | 前端 | [04](function-one-platform/04-human-loop-and-runtime.md#h42) |
| H4.3 | 审批对象与投影语义 | Week 6 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#h43) |
| H4.4 | 审批命令与交付就绪阻塞 | Week 6 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#h44) |
| H4.5 | Pause/Resume checkpoint 语义 | Week 6 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#h45) |
| H4.6 | Terminate 与 system_status | Week 6 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#h46) |
| H4.7 | Retry command 与多 run 分界 | Week 6 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#h47) |
| F4.1 | Composer 生命周期按钮状态 | Week 6 | [ ] | 前端 | [04](function-one-platform/04-human-loop-and-runtime.md#f41) |
| F4.2 | Run 控制按钮与终止入口 | Week 6 | [ ] | 前端 | [04](function-one-platform/04-human-loop-and-runtime.md#f42) |
| F4.3 | Approval Block 与 Reject 输入 | Week 6 | [ ] | 前端 | [04](function-one-platform/04-human-loop-and-runtime.md#f43) |
| F4.4 | Retry UI 与历史审批禁用态 | Week 6 | [ ] | 前端 | [04](function-one-platform/04-human-loop-and-runtime.md#f44) |
| A4.1 | RuntimeEngine 接口 | Week 7 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#a41) |
| A4.2 | deterministic 六阶段推进 | Week 7 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#a42) |
| A4.3 | deterministic 澄清与审批中断 | Week 7 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#a43) |
| A4.4 | deterministic 终态控制 | Week 7 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#a44) |
| D4.1 | Delivery base、snapshot 与 DeliveryRecord | Week 7 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#d41) |
| D4.2 | demo_delivery adapter 与 delivery_result | Week 7 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#d42) |
| A4.5 | LangGraph 主链与 checkpoint | Week 8 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#a45) |
| A4.6 | LangGraph interrupt resume | Week 8 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#a46) |
| A4.7 | LangGraph 事件到领域产物转换 | Week 8 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#a47) |
| A4.8 | Provider Registry | Week 8 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#a48) |
| A4.9 | LangChain Provider Adapter | Week 8 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#a49) |
| A4.10 | 自动回归策略 | Week 8-9 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#a410) |
| A4.11 | 自动回归控制条目与超限失败 | Week 8-9 | [ ] | 后端 | [04](function-one-platform/04-human-loop-and-runtime.md#a411) |
| W5.1 | WorkspaceManager 隔离工作区 | Week 9 | [ ] | 后端 | [05](function-one-platform/05-workspace-delivery-and-hardening.md#w51) |
| W5.2 | 文件工具 read/write/edit/list | Week 9 | [ ] | 后端 | [05](function-one-platform/05-workspace-delivery-and-hardening.md#w52) |
| W5.3 | search 工具 | Week 9 | [ ] | 后端 | [05](function-one-platform/05-workspace-delivery-and-hardening.md#w53) |
| W5.4 | shell 工具与审计记录 | Week 9 | [ ] | 后端 | [05](function-one-platform/05-workspace-delivery-and-hardening.md#w54) |
| W5.5 | ChangeSet 与 ContextReference | Week 9 | [ ] | 后端 | [05](function-one-platform/05-workspace-delivery-and-hardening.md#w55) |
| W5.6 | PreviewTarget Schema 与查询接口 | Week 9 | [ ] | 后端 | [05](function-one-platform/05-workspace-delivery-and-hardening.md#w56) |
| D5.1 | read_delivery_channel 与交付快照读取 | Week 10 | [ ] | 后端 | [05](function-one-platform/05-workspace-delivery-and-hardening.md#d51) |
| D5.2 | prepare_branch 与 create_commit | Week 10 | [ ] | 后端 | [05](function-one-platform/05-workspace-delivery-and-hardening.md#d52) |
| D5.3 | push_branch 与 create_code_review_request | Week 10 | [ ] | 后端 | [05](function-one-platform/05-workspace-delivery-and-hardening.md#d53) |
| D5.4 | git_auto_delivery 编排与 gate 测试 | Week 10 | [ ] | 后端 | [05](function-one-platform/05-workspace-delivery-and-hardening.md#d54) |
| F5.1 | 工具调用、Diff 与测试结果展示 | Week 9-10 | [ ] | 前端 | [05](function-one-platform/05-workspace-delivery-and-hardening.md#f51) |
| F5.2 | DeliveryResultBlock 与交付详情展示 | Week 9-10 | [ ] | 前端 | [05](function-one-platform/05-workspace-delivery-and-hardening.md#f52) |
| V6.1 | 后端完整 API flow 测试 | Week 11 | [ ] | 跨端 | [05](function-one-platform/05-workspace-delivery-and-hardening.md#v61) |
| V6.2 | Playwright 成功路径 | Week 11 | [ ] | 跨端 | [05](function-one-platform/05-workspace-delivery-and-hardening.md#v62) |
| V6.3 | Playwright 人工介入路径 | Week 11 | [ ] | 跨端 | [05](function-one-platform/05-workspace-delivery-and-hardening.md#v63) |
| V6.4 | OpenAPI 核心路由覆盖 | Week 11-12 | [ ] | 跨端 | [05](function-one-platform/05-workspace-delivery-and-hardening.md#v64) |
| V6.5 | 前端 client 与 OpenAPI 一致性 | Week 11-12 | [ ] | 跨端 | [05](function-one-platform/05-workspace-delivery-and-hardening.md#v65) |
| V6.6 | 前端错误态与后端错误回归 | Week 12 | [ ] | 跨端 | [05](function-one-platform/05-workspace-delivery-and-hardening.md#v66) |
| V6.7 | 回归场景与发布候选清单 | Week 12 | [ ] | 跨端 | [05](function-one-platform/05-workspace-delivery-and-hardening.md#v67) |

## 10. 每周验收清单

### Week 1

- 后端与前端基础工程可启动。
- 基础测试命令可运行。
- 健康检查和控制台路由可访问。
- 项目目录骨架与文件职责边界完成文档化。
- 前端实施计划模板包含 `Frontend Design Gate`，并确认设计质量门的执行方式。

### Week 2

- 核心枚举、Schema、数据库边界定稿。
- OpenAPI 初版可作为前端 mock 输入。
- 多 SQLite 职责拆分测试通过。

### Week 3

- Project、Session、Template、Provider、DeliveryChannel 控制面 API 可用。
- 前端 Shell、设置弹窗、模板空态基于 mock 可操作。
- Workspace Shell、设置弹窗与模板空态完成设计质量门检查，项目级主基调已记录并被对应实施计划继承。

### Week 4

- Run 生命周期和状态机测试通过。
- 模板快照与 GraphDefinition 编译测试通过。
- Solution Validation 明确作为 `solution_design` 内部节点组，不形成独立 `StageRun`。
- 前端工作台能展示 draft 与运行中基础状态。

### Week 5

- Session Workspace、Timeline、Inspector 查询投影可用。
- SSE 事件流可用。
- 前端可消费快照与增量并展示 Narrative Feed。
- Narrative Feed、Run Boundary 与 Inspector 的实施计划包含设计质量门，顶层条目、阶段内部条目和详情面板的视觉层级不混淆。

### Week 6

- 澄清、审批、暂停、恢复、终止、重新尝试路径可用。
- 前端 Composer、Approval Block、Retry UI 完成主交互。
- Composer 输入语义、Approval Block、Retry UI 完成设计硬化检查，禁用态、历史态、拒绝输入、危险操作和窄屏布局通过验收。

### Week 7

- deterministic runtime 可跑通六阶段链路。
- deterministic runtime 可触发澄清、审批、失败和终止。
- `demo_delivery` 可生成完整 DeliveryRecord 与顶层 `delivery_result`，且不执行真实 Git 写动作。
- 前端端到端链路不依赖真实模型完成。

### Week 8

- LangGraph runtime 接入固定主链。
- Provider adapter 接入模板快照。
- deterministic/runtime 双路径可切换。

### Week 9

- Workspace tools 支持隔离工作区、文件读写、搜索、命令执行。
- ChangeSet、ContextReference、PreviewTarget 边界落地。
- 前端可展示工具调用、diff、测试结果。
- 工具调用、diff 与测试结果展示完成设计质量门检查，长日志、失败输出、文件路径和横向内容可用。

### Week 10

- `git_auto_delivery` 有可测路径。
- 交付就绪阻塞只发生在 code review approval。
- `git_auto_delivery` 通过 `read_delivery_channel` 读取已固化交付快照。
- DeliveryResultBlock 与交付详情完成设计质量门检查，`demo_delivery` 与 `git_auto_delivery` 的结果呈现可区分。

### Week 11

- 全链路 E2E 覆盖主要成功路径和人工介入路径。
- API、SSE、投影、前端状态开始系统回归。
- Playwright 成功路径与人工介入路径覆盖关键 UI 状态，设计质量门发现项已进入回归问题清单。

### Week 12

- OpenAPI 与实现一致。
- 错误态、空态、历史回放、响应式布局完成回归。
- 发布候选验收清单完成。
- 发布候选清单包含设计硬化结果、已修复 UI 问题、保留风险和对应验证证据。

## 11. 风险控制

| 风险 | 控制方式 |
| --- | --- |
| 大规约直接开发导致任务失控 | 每个执行切片先写 `docs/plans/implementation/<task-id>.md` 实施计划 |
| 任务粒度过大导致交付阻塞 | 单个切片只覆盖一个行为，写集控制在少量相邻文件内 |
| 前后端投影口径漂移 | C1.3、Q3.1、E3.1 先行，前端 mock 只从契约派生 |
| 模型不确定性阻塞联调 | deterministic runtime 先行，LangGraph runtime 后接 |
| `demo_delivery` 与 runtime 联调边界不清 | Week 7 将 `demo_delivery` 作为正式适配器落地，但限定其不执行真实 Git 写动作 |
| LangGraph 状态泄漏到产品 API | 投影层只读取领域对象、事件和产物引用 |
| 工作区改动污染真实仓库 | Workspace tests 使用 fixture 仓库；真实 Git 写动作只在交付适配层受控发生 |
| `git_auto_delivery` 过早复杂化 | Week 7 先完成 `demo_delivery` 与 DeliveryRecord，Week 10 再拆分实现 `read_delivery_channel`、branch、commit、push、MR/PR |
| TDD 退化为补测试 | 每个实施计划必须包含失败测试、失败输出、最小实现和通过输出 |
| Superpowers commit 流程与仓库规则冲突 | commit 步骤替换为提交申请，等待用户批准 |
| 前端主基调输入缺失导致实现停滞 | 主 agent 只在 `F0.1` 或首个可见前端切片前提醒用户确立一次主基调；无参考时记录默认产品型工作台风格并继续实施 |
| UI 打磨覆盖业务语义 | 设计质量门只控制呈现质量；所有业务语义、API、投影、事件与运行时控制仍以正式规格和契约测试为准 |
| 设计检查替代真实验证 | 完成前仍必须运行组件、状态、API client、Playwright 或响应式验证，并在汇报中列出命令和结果 |

## 12. 总完成定义

功能一平台级 V1 完成时，必须同时满足：
- 新建项目、会话、模板选择、首条需求、澄清、方案审批、代码评审审批、暂停恢复、终止、重新尝试、交付结果回看可在单一控制台完成。
- 后端 REST API、SSE、OpenAPI、查询投影和领域状态与三份正式规格一致。
- deterministic runtime 能稳定通过端到端测试。
- LangGraph runtime 能运行固定主链并支持中断恢复。
- `demo_delivery` 不执行真实 Git 写动作但生成完整 DeliveryRecord。
- `git_auto_delivery` 通过受控适配层完成分支、提交、推送与代码评审请求流程。
- Inspector 对阶段、控制条目和交付结果提供完整 input/process/output/artifacts/metrics。
- 前端关键展示切片完成设计质量门检查，工作台、Narrative Feed、Inspector、人工介入、工具结果和交付详情的风格一致性、状态覆盖、响应式和可访问性通过验收。
- 分层测试通过，端到端回归通过。
- 所有正式规格变更和计划文档均已通过用户评审后再进入提交流程。
