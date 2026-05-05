<div align="center">

# AI DevFlow Engine

### 本地优先的 AI 研发工作流引擎，让需求到交付成为可追踪 Pipeline。

![Status](https://img.shields.io/badge/status-V1%20platform%20buildout-0f766e)
![License](https://img.shields.io/badge/license-MIT-111827)
![Runtime](https://img.shields.io/badge/runtime-Python%203.11%2B-3776ab?logo=python&logoColor=white)
![API](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)
![Frontend](https://img.shields.io/badge/frontend-React%20%2B%20Vite-646cff?logo=vite&logoColor=white)
![Orchestration](https://img.shields.io/badge/orchestration-LangGraph-1c3c3c?logo=langchain&logoColor=white)

[English](README.md) | 简体中文

</div>

---

AI DevFlow Engine 将软件交付组织成一条可追踪的 AI 工作流。它不把 AI 研发理解成“一次提示词 + 一次代码生成”，而是显式建模从需求理解、方案设计、实现、测试、评审到交付的完整路径。

这个项目面向需要超越代码补全的团队与构建者：需求要保持清晰，方案要在编码前可评审，高风险动作要有人类控制，测试要留下证据，每次交付都应该能说明“改了什么”和“为什么这样改”。

<div align="center">
  <img src="assets/agent-delivery-flow.svg" alt="AI DevFlow Engine 从需求到交付的工作流" width="960" />
</div>

## 为什么需要它

AI 编码工具在小任务、短上下文里最有效。真实交付不同：需求意图会在阶段流转中被稀释，方案决策容易消失在聊天记录里，测试很容易被弱化，评审发生时原始上下文往往已经散落。

AI DevFlow Engine 将“过程”本身保留在系统里：

| 需求 | 引擎如何处理 |
| --- | --- |
| 保留需求意图 | 将用户输入转换为结构化需求、验收标准和阶段产物。 |
| 让方案质量前置可见 | 在代码执行前产出设计、实施计划、影响范围和校验记录。 |
| 保持人类控制 | 将澄清、审批、暂停、恢复、重试、回滚和高风险工具确认纳入显式运行控制。 |
| 让交付可审计 | 将需求、方案、代码变更、测试、评审和交付记录连接成一条可追踪链路。 |

## 当前可以运行什么

当前 V1 平台已经具备可运行的后端、前端工作台和验证栈：

| 区域 | 当前能力 |
| --- | --- |
| 后端 API | `FastAPI` 应用，包含 REST 路由、错误契约、OpenAPI、启动种子数据、CORS 和请求关联。 |
| 工作台控制台 | `React` + `Vite` SPA，包含项目/会话导航、需求输入、叙事流、详情栏、设置、审批、交付结果和运行控制。 |
| 运行时路径 | 确定性运行时、LangGraph 引擎边界、阶段运行端口、中断/恢复、事件翻译、Provider 适配、Prompt 资产和自动回归策略支持。 |
| 持久化与可观测性 | 多 SQLite 会话管理、领域模型、JSONL 运行日志、审计记录、脱敏、保留策略、日志索引和诊断查询。 |
| 工作区与交付工具 | 隔离工作区管理、文件和 grep 工具、受控 shell 执行、工具风险关口、演示交付和 Git 交付边界。 |
| 验证 | 后端 pytest、前端 Vitest、OpenAPI 兼容性检查和 Playwright E2E 流程。 |

## 工作流一览

| 阶段 | 目的 | 主要输出 |
| --- | --- | --- |
| Requirement Analysis | 理解意图、约束和验收标准。 | 结构化需求 |
| Solution Design | 产出技术方案、实施计划和方案校验结果。 | 已审批方案 |
| Code Generation | 按已审批计划修改工作区。 | 变更集 |
| Test Generation & Execution | 生成或执行检查，并暴露剩余缺口。 | 测试证据 |
| Code Review | 审查正确性、安全性、测试证据和计划一致性。 | 评审结论 |
| Delivery Integration | 准备最终交付输出并记录结果。 | 交付记录 |

人工审批是工作流的一部分，而不是外部备注。运行控制和工具确认会作为一等事件进入用户可见投影，支持检查和回放。

## 产品体验

AI DevFlow Engine 的形态是一个本地优先的研发工作台：

| 界面 | 作用 |
| --- | --- |
| 工作台控制台 | 提交需求、检查运行、审批阶段、配置 Provider、查看交付结果的主入口。 |
| 叙事流 | 以可阅读时间线展示阶段进展、审批、工具调用、diff、测试和交付事件。 |
| 详情栏 | 展示产物、指标、引用、阶段记录和运行状态投影。 |
| 运行控制 | 暂停、恢复、终止、重试、回滚、审批和工具确认控制。 |
| 交付模式 | 安全演示交付，以及面向真实项目交接的受控 Git 交付概念。 |

## 架构

<div align="center">
  <img src="assets/agent-orchestration-architecture.svg" alt="AI DevFlow Engine 编排架构" width="960" />
</div>

前端不直接读取运行时内部状态。它消费稳定的领域对象、查询投影和 SSE 事件；后端负责命令、编排、持久化、工具和交付记录。

| 层级 | 职责 |
| --- | --- |
| 前端工作台 | React 路由、TanStack Query API 访问、Zustand 工作台状态、SSE 客户端、叙事流、详情栏、审批、模板、设置和交付视图。 |
| API 与投影 | FastAPI 命令、查询端点、OpenAPI 契约、领域错误响应、运行投影、Feed 条目、指标和详情栏 payload。 |
| 运行时编排 | 确定性运行时、LangGraph 集成边界、阶段 Agent、Prompt 渲染、Provider 调用、中断、恢复和终端控制。 |
| 持久化与日志 | 控制、运行时、图、事件和日志数据库，以及带脱敏和保留策略的 JSONL 审计/运行日志。 |
| 工作区与交付 | 受控文件工具、shell 执行关口、风险分类、变更边界、演示交付和 Git 交付扩展点。 |

更详细的说明见 [架构概览](docs/architecture/overview.md)。

## 快速启动

后端：

```powershell
uv sync --extra dev
uv run uvicorn backend.app.main:app --reload
```

API 文档地址为 `http://127.0.0.1:8000/api/docs`。

前端：

```powershell
npm --prefix frontend install
npm --prefix frontend run dev
```

工作台地址为 `http://127.0.0.1:5173`。

完整启动说明见 [Getting Started](docs/getting-started.md)。

## 验证

后端：

```powershell
uv run pytest
```

前端：

```powershell
npm --prefix frontend run build
npm --prefix frontend run test -- --run
```

E2E：

```powershell
npm --prefix e2e run test
$env:E2E_LIVE_BACKEND = "1"; npm --prefix e2e run test
```

聚焦命令和 live-backend E2E 路径见 [Verification](docs/development/verification.md)。

## 文档

| 文档 | 用途 |
| --- | --- |
| [文档索引](docs/README.md) | 产品、架构、开发、API 和计划文档入口。 |
| [Getting Started](docs/getting-started.md) | 本地环境、运行时目录、后端/前端启动和 E2E 说明。 |
| [Architecture Overview](docs/architecture/overview.md) | 系统分层、数据流、运行时边界、可观测性和扩展点。 |
| [Verification](docs/development/verification.md) | 后端、前端和 E2E 验证命令。 |
| [Product Overview](docs/specs/function-one-product-overview-v1.md) | Feature One 的产品边界和阶段边界。 |
| [Frontend Workspace Design](docs/specs/frontend-workspace-global-design-v1.md) | 工作台交互和展示语义。 |
| [Backend Engine Design](docs/specs/function-one-backend-engine-design-v1.md) | 领域模型、API、投影、事件和运行时语义。 |
| [Platform Plan](docs/plans/function-one-platform-plan.md) | V1 实施切片和平台交付计划。 |
| [OpenAPI Notes](docs/api/function-one-openapi-notes.md) | API 伴随说明和 OpenAPI 契约约定。 |

## 项目状态

AI DevFlow Engine 当前处于 V1 平台建设阶段。仓库已经包含第一版可运行的本地平台表面，包括后端 API 模块、前端工作台模块、确定性运行时路径、Provider 与 Prompt 基础设施、工作区工具、交付边界、可观测性和自动化测试。

Feature One 的权威边界仍来自 `docs/specs/` 下的拆分规格。`docs/archive/` 下的历史设计文档只作为历史参考。

## 许可证

本项目使用 [MIT License](LICENSE)。
