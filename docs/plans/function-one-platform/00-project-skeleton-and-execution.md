# 00 项目骨架与执行规则

## 1. 目标目录骨架

功能一平台级 V1 采用单仓库内前后端并行结构。空目录不单独作为 Git 产物提交，目录会随各任务的实际文件落地。

```text
backend/
  app/
    api/
      routes/
    core/
    db/
      models/
    domain/
    schemas/
    services/
      projections/
    runtime/
    providers/
    workspace/
    delivery/
  alembic/
  tests/
    api/
    db/
    delivery/
    domain/
    e2e/
    events/
    projections/
    providers/
    runtime/
    schemas/
    services/
    workspace/
frontend/
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
      workspace/
    mocks/
    pages/
    styles/
e2e/
  tests/
docs/
  api/
  plans/
    implementation/
    function-one-platform/
```

## 2. 目录职责边界

| 路径 | 职责 |
| --- | --- |
| `backend/app/api/routes/` | FastAPI 路由层，只做请求解析、响应返回和服务调用 |
| `backend/app/core/` | 配置、日志、错误模型、应用级依赖 |
| `backend/app/db/` | SQLAlchemy session、数据库角色、多 SQLite 绑定 |
| `backend/app/db/models/` | control、runtime、graph、event 四类模型 |
| `backend/app/domain/` | 领域枚举、状态机、GraphDefinition、ChangeSet 等纯领域对象 |
| `backend/app/schemas/` | Pydantic v2 请求、响应、投影与事件 Schema |
| `backend/app/services/` | Project、Session、Run、Approval、Artifact、Delivery 等业务服务 |
| `backend/app/services/projections/` | Workspace、Timeline、Inspector 投影组装 |
| `backend/app/runtime/` | deterministic runtime、LangGraph runtime、自动回归 |
| `backend/app/providers/` | Provider registry 与 LangChain 适配 |
| `backend/app/workspace/` | 隔离工作区、文件工具、shell 工具 |
| `backend/app/delivery/` | demo_delivery、git_auto_delivery、SCM 适配 |
| `frontend/src/api/` | API client、TanStack Query hooks、接口类型 |
| `frontend/src/app/` | Router、QueryClient、全局 Provider、测试工具 |
| `frontend/src/features/` | 以产品能力拆分的前端功能模块 |
| `frontend/src/mocks/` | mock fixtures 与 mock handlers |
| `e2e/tests/` | Playwright 跨端测试 |
| `docs/plans/implementation/` | 单个子任务的 Superpowers 实施计划 |

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
- 文档需定义 `backend/`、`frontend/`、`e2e/`、`docs/api/`、`docs/plans/implementation/` 的职责。

**验收标准**：
- 项目骨架在文档中可追踪。
- B0.1、B0.2、F0.1 的文件落点与骨架一致。
- 空目录不作为单独交付物，实际目录随首个源文件或测试文件创建。

**测试方法**：
- `rg -n "backend/|frontend/|docs/plans/implementation" docs/architecture/project-structure.md README.md`
- 人工核对 B0.1、B0.2、F0.1 的文件列表与骨架一致。

## 4. Superpowers 执行规则

每个实现子任务必须先写实施计划：
- 计划路径：`docs/plans/implementation/<task-id>-<task-name>.md`
- 必用技能：`superpowers:writing-plans`
- 执行技能：`superpowers:subagent-driven-development` 或 `superpowers:executing-plans`
- 完成验证：`superpowers:verification-before-completion`

实施计划必须包含：
- 文件列表
- TDD 红绿步骤
- 具体测试代码
- 具体实现代码
- 命令与预期输出
- 完成前验证清单

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
