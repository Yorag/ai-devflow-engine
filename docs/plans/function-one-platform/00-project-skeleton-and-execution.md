# 00 项目骨架与执行规则

## 1. 目标目录骨架

功能一平台级 V1 采用单仓库内前后端并行结构。空目录不单独作为 Git 产物提交，目录会随各任务的实际文件落地。

```text
backend/
  alembic/
  app/
    api/
      routes/
    core/
    db/
      models/
    domain/
    repositories/
    schemas/
    services/
      projections/
    observability/
    runtime/
    context/
    prompts/
      assets/
        compression/
        repairs/
        roles/
        runtime/
        tools/
    providers/
    tools/
    workspace/
    delivery/
  tests/
    api/
    core/
    db/
    delivery/
    domain/
    e2e/
    errors/
    events/
    fixtures/
    observability/
    projections/
    context/
    prompts/
    providers/
    regression/
    runtime/
    schemas/
    services/
    support/
    tools/
    workspace/
frontend/
  package.json
  tsconfig.json
  vite.config.ts
  src/
    api/
    app/
    features/
      approvals/
      composer/
      delivery/
      errors/
      feed/
      inspector/
      runs/
      settings/
      templates/
      tool-confirmations/
      workspace/
    mocks/
    pages/
    styles/
e2e/
  package.json
  playwright.config.ts
  tests/
docs/
  api/
  architecture/
  archive/
  plans/
    implementation/
    function-one-platform/
  specs/
pyproject.toml
README.md
```

## 2. 目录职责边界

| 路径 | 职责 |
| --- | --- |
| `backend/alembic/` | Alembic env 与迁移脚本，负责数据库结构演进 |
| `backend/app/api/` | API router 聚合、API 层错误契约与 OpenAPI 暴露入口 |
| `backend/app/api/routes/` | FastAPI 路由层，只做请求解析、响应返回和服务调用 |
| `backend/app/core/` | EnvironmentSettings、启动配置、错误模型、应用级依赖与通用中间件挂载 |
| `backend/app/db/` | SQLAlchemy session、数据库角色、多 SQLite 绑定 |
| `backend/app/db/models/` | control、runtime、graph、event、log 五类模型 |
| `backend/app/domain/` | 领域枚举、状态机、GraphDefinition、运行快照、ChangeSet 等纯领域对象 |
| `backend/app/repositories/` | SQLAlchemy 持久化访问适配层，只封装查询和写入，不承载业务状态机、审批语义或投影组装 |
| `backend/app/schemas/` | Pydantic v2 请求、响应、投影与事件 Schema |
| `backend/app/services/` | Project、Session、Run、Approval、Artifact、Delivery、PlatformRuntimeSettings 等业务与平台运行设置服务 |
| `backend/app/services/projections/` | Workspace、Timeline、Inspector 投影组装 |
| `backend/app/observability/` | 平台运行数据目录、JSONL 日志、日志索引、审计记录、TraceContext、裁剪、轮转、保留与日志诊断查询服务 |
| `backend/app/runtime/` | deterministic test runtime、LangGraph runtime、RuntimeLimitSnapshot 消费、自动回归 |
| `backend/app/context/` | ContextEnvelope、ContextManifest、上下文来源解析、上下文尺寸守卫、压缩过程记录 |
| `backend/app/prompts/` | 系统内置提示词资产、PromptRegistry、PromptRenderer、提示词版本留痕与渲染辅助 |
| `backend/app/prompts/assets/` | 系统内置提示词资产正文，按角色、runtime 指令、修复提示、压缩提示和工具提示分组 |
| `backend/app/providers/` | Provider registry 与 LangChain 适配 |
| `backend/app/tools/` | ToolProtocol、ToolRegistry、工具输入输出、错误结构、审计记录和审计引用等跨工具契约 |
| `backend/app/workspace/` | 隔离工作区、`read_file` / `write_file` / `edit_file` / `glob` 文件工具、`grep` 内容搜索工具、`bash` 命令工具 |
| `backend/app/delivery/` | demo_delivery、git_auto_delivery、SCM 适配 |
| `backend/tests/` | pytest 测试根目录，按 API、领域、服务、runtime、delivery、workspace 等行为边界分组 |
| `backend/tests/api/` | FastAPI 路由、错误响应与 OpenAPI 契约测试 |
| `backend/tests/core/` | EnvironmentSettings、启动配置和应用级依赖边界测试 |
| `backend/tests/db/` | 多 SQLite 绑定、SQLAlchemy 模型和迁移边界测试 |
| `backend/tests/e2e/` | 后端 API/runtime 端到端测试，不启动浏览器 |
| `backend/tests/errors/` | 错误码目录、错误响应结构和跨工具错误契约测试 |
| `backend/tests/fixtures/` | 后端测试 fake、settings override、fixture 仓库和 mock remote 契约测试资产 |
| `backend/tests/observability/` | 运行数据目录、日志写入、日志索引、审计记录、TraceContext、裁剪、轮转、保留与诊断查询测试 |
| `backend/tests/context/` | ContextEnvelope、ContextManifest、上下文来源解析、尺寸守卫与压缩测试 |
| `backend/tests/prompts/` | PromptAsset Schema、PromptRegistry、PromptRenderer 与内置提示词资产测试 |
| `backend/tests/regression/` | 发布候选前跨切片回归测试，不替代单切片测试 |
| `backend/tests/support/` | 跨测试层共享的轻量辅助函数和配置构造，不承载业务 fake 语义 |
| `backend/tests/tools/` | 抽象工具协议、注册表和跨工具契约测试 |
| `frontend/src/api/` | API client、TanStack Query hooks、接口类型 |
| `frontend/src/app/` | Router、QueryClient、全局 Provider、测试工具 |
| `frontend/src/features/` | 以产品能力拆分的前端功能模块 |
| `frontend/src/features/tool-confirmations/` | Tool Confirmation 允许 / 拒绝动作、状态辅助和对应测试 |
| `frontend/src/mocks/` | mock fixtures 与 mock handlers |
| `frontend/src/pages/` | 路由级页面组合层，不承载可复用业务组件实现 |
| `frontend/src/styles/` | 全局样式、基础 CSS 和主题变量，不承载组件私有状态 |
| `frontend/src/**/__tests__/` | 前端就近单元测试和组件测试 |
| `e2e/` | Playwright 工程配置、脚本与跨端浏览器测试项目 |
| `e2e/tests/` | Playwright 跨端测试 |
| `docs/api/` | API 文档补充说明和 OpenAPI 相关说明 |
| `docs/architecture/` | 结构性架构说明，如目录结构、存储分层和运行拓扑 |
| `docs/archive/` | 历史规格和历史设计参考，不作为当前实现依据 |
| `docs/plans/implementation/` | 单个子任务的 Superpowers 实施计划 |
| `docs/plans/function-one-platform/` | 功能一平台级分卷计划与子任务列表 |
| `docs/specs/` | 当前有效规格文档，实施计划必须以这里和当前计划为依据 |
| `pyproject.toml` | 后端依赖、pytest 配置与 Python 工程入口配置 |
| `frontend/package.json` | 前端依赖和 `dev`、`build`、`test` 脚本 |
| `e2e/package.json` | Playwright 跨端测试依赖和测试脚本 |

<a id="b00"></a>

## 3. B0.0 项目目录骨架与边界声明

**计划周期**：Week 1
**并行性**：串行起点
**状态**：`[ ]`
**目标**：在实施前固定仓库目录骨架、文件责任边界和后续实施计划落点。

**修改文件列表**：
- Create: `docs/architecture/project-structure.md`
- Modify: `README.md`
- Modify: `docs/plans/function-one-platform-plan.md`

**实现类/函数**：
- 无生产代码。
- 文档需定义 `backend/`、`frontend/`、`e2e/`、`docs/api/`、`docs/plans/implementation/` 的职责，并覆盖 `backend/app/context/`、`backend/app/prompts/`、`backend/tests/context/` 与 `backend/tests/prompts/` 的落点边界。

**验收标准**：
- 项目骨架在文档中可追踪。
- B0.1、B0.2、F0.1 的文件落点与骨架一致。
- C1.10a、A4.8b-A4.8d 与 A4.9a-A4.9b 的 context/prompts 文件落点与骨架一致。
- 空目录不作为单独交付物，实际目录随首个源文件或测试文件创建。

**测试方法**：
- `rg -n "backend/|frontend/|docs/plans/implementation" docs/architecture/project-structure.md README.md`
- 人工核对 B0.1、B0.2、F0.1、C1.10a、A4.8b-A4.8d 与 A4.9a-A4.9b 的文件列表与骨架一致。

## 4. Superpowers 执行规则

每个实现子任务必须先写实施计划：
- 计划路径：`docs/plans/implementation/<task-id>-<task-name>.md`
- 必用技能：`superpowers:writing-plans`
- 执行技能：`superpowers:subagent-driven-development` 或 `superpowers:executing-plans`
- 完成验证：`superpowers:verification-before-completion`

`docs/plans/implementation/*.md` 是执行期下钻计划，可以在对应子任务开始时创建，不要求在当前总计划评审阶段预先存在。创建实施计划前，必须先核对总计划、对应分卷、三份当前 split specs 和本文件的执行规则；实施计划只能细化执行步骤、测试代码和命令，不能改变任务边界、规格语义、文件责任、事件口径或 API 契约。

实施计划必须包含：
- 文件列表
- TDD 红绿步骤
- 具体测试代码
- 具体实现代码
- 命令与预期输出
- 完成前验证清单

涉及用户命令接口、运行生命周期推进、runtime 节点执行、模型调用、工具调用、工作区写入、`bash` 命令、Git 交付、远端交付、配置变更或安全敏感失败的实施计划还必须包含 `Log & Audit Integration` 小节：
- 明确本切片产生的运行日志类别、审计动作、关联对象和失败结果。
- 明确 `request_id`、`trace_id`、`correlation_id`、`span_id` 与 `parent_span_id` 的生成或继承方式。
- 明确敏感字段裁剪、阻断、摘要化与载荷大小限制。
- 明确本切片的日志写入失败、审计写入失败和 `log.db` 索引失败处理方式。
- 明确本切片测试如何断言日志记录不替代领域对象、领域事件、Narrative Feed、Inspector 或产品状态真源。

涉及 `backend/app/api/routes/*` 的实施计划还必须包含本切片 API 测试与 `/api/openapi.json` 断言，覆盖新增或修改的 path、method、请求 Schema、响应 Schema 和主要错误响应；V6.4 只做全局汇总回归，不替代本地 API 契约断言。

## 5. Git 边界

本仓库规则覆盖 Superpowers 模板中的 commit 步骤：
- 不主动创建分支。
- 不主动提交。
- 不主动合并。
- 不主动 tag。
- 提交前必须等待用户明确批准。
- 规格文档与计划文档在用户评审前不得提交。

## 6. 子任务状态更新规则

任务执行时只更新两类位置：
- 总表：`docs/plans/function-one-platform-plan.md` 中对应任务状态。
- 分卷：对应任务细则中的状态、实施计划链接、验证结果摘要。
