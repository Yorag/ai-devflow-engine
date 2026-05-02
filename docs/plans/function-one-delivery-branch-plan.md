# Function One Delivery Branch Plan

本文件对应 [function-one-platform-plan.md](function-one-platform-plan.md) 的 `9.1 Delivery Branch Plan` 索引入口。

本表定义交付分支边界，用于控制跨分支协作、PR/MR review boundary 与合入顺序。本表不替代 Git 状态、PR/MR 状态或子任务完成事实；`main` 上的进度追踪表仍是全局事实来源。每个分支内仍按单个 slice 顺序执行：实施计划、TDD、验证、状态更新、提交申请。

并行等级固定为：
- `S` 串行门槛：该分支合入前，不得启动依赖它的下游交付分支。
- `Y` 有序并行：允许并行开发，但合入前必须同步最新 `main`，并按前置关系完成合入。
- `G` 绿色并行：前置已合入且写入范围不重叠时，允许与其它绿色分支并行开发和独立 review。

调度状态固定为：
- `planned`：已规划且未进入实施追踪；当当前 Git 分支与本表 `交付分支` 精确匹配、前置门槛满足且任务属于 `覆盖任务` 时，`planned` 不阻塞分支内执行。
- `claimed`：已由主会话预标，或已由分支内首次状态更新收敛为实施中；worktree 可创建或正在实施。
- `ready_for_review`：分支验证完成，等待 PR/MR review 或合入。
- `merged`：分支已合入 `main`，进度追踪表状态成为主线事实。
- `blocked`：依赖、写集、验证或语义冲突阻塞执行。

分会话未完成覆盖任务且没有阻塞项时，将 `planned` 收敛为 `claimed` 或保持 `claimed`，不得新增或使用 `in_progress` 类状态。

开工前必须执行 Parallel Safety Gate：
- 前置分支已合入 `main`，或本分支仅使用已合入契约的 mock 数据且不得调用未合入真实实现。
- 本分支不会与其它活动分支同时修改同一共享 Schema、全局枚举、错误码、API router 汇总入口、Alembic migration 链、前端 API client 类型入口、前端全局 store 或 App shell 入口。
- 本分支的验证命令能独立证明覆盖任务完成；跨端和全链路验证只放入明确的 regression / hardening 分支。
- 一个分支只修改自己的 batch row、覆盖任务状态和对应 split-plan 小节；合入 `main` 后主线进度表成为事实。
- 前置门槛必须列出具体 batch id，不使用 `DBxx-DByy` 范围缩写，以便会话和工具按显式依赖执行。

拆分触发条件固定为：
- 分支同时需要修改后端契约、API、持久化和前端 UI 时，必须在实施前拆分。
- 分支内出现第二条 Alembic migration 链、第二处全局错误码扩展或第二个前端全局入口改动时，必须先重新评审分支边界。
- 分支验证无法用本分支范围内命令独立证明时，必须拆出后续 regression 分支。

| Batch | 交付分支 | 覆盖任务 | 前置门槛 | 并行等级 | Status | 主要共享入口 / 冲突点 | Review boundary |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DB00 | `docs/project-structure-boundary` | B0.0 | 无 | S | merged | `README.md`, `docs/plans/*` | 项目目录骨架、路径职责和实施计划落点 |
| DB01 | `chore/engineering-baseline` | B0.1 | DB00 | S | merged | 根目录脚本、后端/前端工程入口 | 前后端依赖、测试命令和开发脚本基线 |
| DB02 | `feat/backend-runtime-bootstrap` | B0.2, B0.3, L0.1 | DB01 | S | merged | `backend/app/api/*`, `error_codes.py`, settings、日志目录预检 | FastAPI、统一错误响应、启动配置和运行数据目录 |
| DB03 | `feat/frontend-spa-baseline` | F0.1 | DB01 | G | merged | `frontend/`, 前端测试入口 | 前端 SPA、测试基线和首个设计质量门 |
| DB04 | `feat/core-schema-contracts` | C1.1-C1.4 | DB02 | S | merged | 全局枚举、核心 Schema、事件 payload、Projection Schema | 全局枚举、控制面、Run/Feed/Event 和 Inspector 契约 |
| DB05 | `feat/runtime-prompt-log-contracts` | C1.10, C1.10a, L1.1 | DB04 | Y | merged | 运行设置 Schema、PromptAsset Schema、TraceContext | 运行设置、提示词资产和日志审计契约 |
| DB06 | `feat/persistence-boundaries` | C1.5-C1.9, L1.2 | DB04, DB05 | S | merged | 数据库 session、control/runtime/graph/event/log models、Alembic migration 链 | 多 SQLite 职责库、模型和迁移边界 |
| DB07 | `feat/observability-control-audit` | L2.1-L2.4 | DB05, DB06 | S | merged | request context、redaction、JSONL writer、AuditService | API 关联上下文、payload 裁剪、日志写入和控制面审计 |
| DB08 | `feat/control-plane-core` | C2.1-C2.4 | DB05, DB06, DB07 | S | ready_for_review | control routes、Project/Session/Template service、audit hooks | Project、Session、系统模板和用户模板核心控制面 |
| DB09 | `feat/provider-delivery-runtime-settings` | C2.5, C2.6, C2.7, C2.7a, C2.8 | DB05, DB06, DB07, DB08 | S | planned | Provider、DeliveryChannel、配置包、PlatformRuntimeSettings service | Provider、DeliveryChannel、配置包和平台运行设置管理 |
| DB10 | `feat/frontend-control-plane-client` | F2.1, F2.2 | DB03, DB04, DB05 | Y | merged | 前端 API client 类型入口、mock fixtures | 前端 API client、mock fixtures 和 query hooks |
| DB11 | `feat/frontend-workspace-template-ui` | F2.3-F2.6 | DB10 | Y | merged | App shell、前端全局 store、设置弹窗、模板 UI | Workspace shell、设置弹窗和模板交互 |
| DB12 | `feat/run-core-events-snapshots` | R3.1, E3.1, R3.4-R3.7 | DB06, DB08, DB09 | S | planned | Run 状态机、EventStore、snapshot services、GraphDefinition、StageRun、StageArtifact | Run 核心领域规则、事件、快照、图定义和阶段产物 |
| DB13 | `feat/run-start-retry-history` | R3.2, R3.3, C2.9a, C2.9b | DB08, DB12 | S | planned | run start transaction、retry service、Project/Session history visibility | 首条需求启动、retry 内部创建和历史可见性命令 |
| DB14 | `feat/backend-projections-streams` | Q3.1-Q3.4a, E3.2, L3.1 | DB07, DB12, DB13 | S | planned | Projection services、SSE endpoint、run/stage log routes | Workspace、Timeline、Inspector、SSE 和日志轻查询 |
| DB15 | `feat/run-feed-inspector-frontend` | F3.1-F3.7 | DB10, DB14 | Y | planned | 前端 workspace store、SSE reducer、Feed、StageNode、Inspector UI | Narrative Feed、Run boundary、StageNode 和 Inspector 展示 |
| DB16 | `feat/runtime-orchestration-audit` | A4.0, L4.1, L4.2 | DB07, DB13, DB14 | S | planned | RuntimeOrchestrationService、AuditService、audit query route | 运行编排边界、命令审计失败语义和审计查询 |
| DB17 | `feat/human-loop-backend` | H4.1, H4.3, D4.0, H4.4, H4.4a | DB09, DB16 | S | planned | clarification、approval、delivery snapshot gate、tool confirmation routes | 澄清、审批、交付快照 gate 和工具确认后端 |
| DB18 | `feat/run-control-backend` | H4.5-H4.7 | DB16, DB17 | S | planned | runtime control commands | Pause/Resume、Terminate 和 retry 命令 |
| DB19 | `feat/human-loop-frontend` | H4.2, F4.1, F4.2, F4.3, F4.3a, F4.4 | DB15, DB17, DB18 | Y | planned | Composer、Approval Block、Tool Confirmation Block、运行控制按钮 | Composer、运行控制、审批和工具确认 UI |
| DB20 | `feat/runtime-tooling-foundation` | A4.1, W5.0, W5.0a, W5.0b | DB09, DB16, DB17 | S | planned | RuntimeEngine port、ToolProtocol、ToolRegistry、error codes | RuntimeEngine、工具协议、执行门和错误码基座 |
| DB21 | `feat/workspace-tools-risk-gate` | W5.0d, W5.1, W5.2, W5.3, W5.4 | DB17, DB20, DB25a | S | planned | risk classifier、WorkspaceManager、file/grep/bash tools | 工具风险门禁、隔离工作区和 Workspace tools |
| DB22 | `feat/deterministic-demo-delivery` | A4.2-A4.4, D4.1-D4.3 | DB17, DB20, DB21 | S | planned | deterministic runtime、DeliveryRecord、demo_delivery | deterministic test runtime、demo_delivery 和交付结果投影 |
| DB23 | `feat/change-preview-boundaries` | W5.5, W5.6 | DB12, DB21 | Y | planned | ChangeSet、ContextReference、PreviewTarget | 功能二预留变更、上下文和预览边界 |
| DB24 | `feat/langgraph-runtime` | A4.5-A4.7 | DB16, DB20, DB22 | S | planned | LangGraph nodes、checkpoint、event conversion | LangGraph 主链、checkpoint、interrupt resume 和事件转换 |
| DB25 | `feat/provider-prompt-foundation` | A4.8, A4.8a, A4.8c, A4.8d, A4.9 | DB09, DB12, DB18, DB20 | Y | planned | Provider registry、PromptValidation、PromptRegistry、PromptRenderer、Provider adapter | Provider、提示词校验、提示词资产加载、消息渲染和模型适配 |
| DB25a | `test/runtime-fixtures-contracts` | W5.0c | DB20, DB25 | S | planned | backend test fixtures、fake provider、fake tool、fixture workspace、delivery fixture | 后端测试 fixture、fake provider、fake tool 和 settings override 契约 |
| DB26 | `feat/context-management` | A4.8b, A4.9a, A4.9e, A4.9b | DB12, DB20, DB23, DB25, DB25a | S | planned | ContextEnvelope、ContextManifest、Context builder、provider retry、size guard | 上下文契约、上下文构建、Provider 重试和上下文尺寸守卫 |
| DB27 | `feat/stage-agent-runtime` | A4.9c, A4.9d, A4.10, A4.11 | DB17, DB18, DB21, DB24, DB26 | S | planned | AgentDecision、StageAgentRuntime、auto regression、control records | AgentDecision、Stage Agent Runtime 和自动回归 |
| DB28 | `feat/git-delivery-runtime` | D5.1-D5.4 | DB17, DB20, DB21, DB22, DB23, DB25a | S | planned | delivery/scm tools、Git CLI adapter、git_auto orchestration | 真实 Git 交付工具和 git_auto_delivery 编排 |
| DB29 | `feat/delivery-result-frontend` | F5.1, F5.2a, F5.2b | DB19, DB22, DB28 | Y | planned | feed delivery components、diff/test display | 工具调用、Diff、测试结果和交付结果展示 |
| DB30 | `test/backend-api-openapi-regression` | V6.1, V6.4 | DB27, DB28 | S | planned | backend e2e tests、OpenAPI notes | 后端完整 API flow 和 OpenAPI 核心覆盖 |
| DB31 | `test/playwright-workflows` | V6.2, V6.3 | DB19, DB22, DB29 | S | planned | Playwright e2e | 跨端成功路径和人工介入路径 |
| DB32 | `test/frontend-error-regression` | V6.5, V6.6 | DB29, DB30 | Y | planned | frontend API compat、error state | 前端 client/OpenAPI 一致性和错误态回归 |
| DB33 | `test/runtime-log-hardening` | V6.8, L6.1, L6.2 | DB27, DB28, DB30 | S | planned | observability retention、config regression、audit regression | 配置边界、运行快照、日志轮转和日志审计回归 |
| DB34 | `docs/release-candidate-checklist` | V6.7 | DB30, DB31, DB32, DB33 | S | planned | regression checklist、acceptance checklist | 发布候选回归场景和验收清单 |
