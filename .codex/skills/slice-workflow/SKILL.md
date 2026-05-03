---
name: slice-workflow
description: Use when executing an assigned acceleration claim or one task slice from this repository's function-one platform implementation plan.
---

# Slice Workflow

## 概述

将 acceleration claim 指向的一个实现切片依次通过本仓库要求的 gate。本技能把通用 Superpowers 执行方式适配到本仓库的平台计划执行规则、lane owner 规则、Git 规则、split specs 和前端质量门。

## 核心规则

每次调用只执行一个切片。除非当前切片已验证并汇报后，用户明确开始另一个切片，否则不要继续到下一个切片。

## 不适用场景

- 不要用于 `docs/plans/function-one-platform-plan.md` 之外的普通临时功能、缺陷修复或评审。
- 不要在一次调用中执行多个切片。
- 不要因为用户指定了任务 id 就绕过依赖、claim、lane、owner、状态、分支或来源追溯 gate。
- 不要接受通用 Superpowers 默认流程中会创建 worktree、commit、PR、merge、tag 或分支清理的步骤；子代理执行仅限本技能定义的 implementer / reviewer 工作流。
- 不要用 `impeccable` 改变产品语义、阶段语义、后端 API、投影字段、事件载荷或测试要求。
- 不要在 worker 分支更新共享 coordination store、中央 checkpoint snapshot、platform plan 或 split plan 的最终完成状态；这些只由主协调会话在 ingest 或 integration checkpoint 后统一更新。

## 必读来源

读取当前 gate 所需的最小必要集合，并把这些文件视为事实来源：

- `AGENTS.md`
- `docs/plans/function-one-acceleration-execution-plan.md`
- `docs/plans/function-one-platform-plan.md`
- `docs/plans/function-one-platform/*.md`
- `docs/specs/function-one-product-overview-v1.md`
- `docs/specs/frontend-workspace-global-design-v1.md`
- `docs/specs/function-one-backend-engine-design-v1.md`
- `.codex/skills/acceleration-workflow/scripts/coordination_store.py`

切片选择阶段默认只读取 acceleration execution plan 的静态 lane/queue/owner 规则、共享 coordination store 中的当前 claim、platform plan、相关 split-plan 细则和当前分支名。三个当前 specs 在语义不清、发现冲突，或已选切片触及对应契约时读取相关章节。

旧 DB batch 表已归档为 `docs/archive/function-one-delivery-branch-plan-legacy.md`，不得作为主动切片选择或状态更新来源。只有用户明确要求历史追溯时才读取归档表。

不要重新引入已归档的功能一语义。只有用户明确要求做历史对比时，才使用归档文档。

当 split specs 发生重叠时，按本仓库约定处理：

| 主题 | 来源 |
| --- | --- |
| 产品和阶段边界 | `function-one-product-overview-v1.md` |
| 前端交互和呈现语义 | `frontend-workspace-global-design-v1.md` |
| 后端领域模型、API、投影和事件 | `function-one-backend-engine-design-v1.md` |

## 必需子技能

- **REQUIRED SUB-SKILL:** 使用 `git-delivery-workflow` 处理分支和 commit gate。
- **REQUIRED SUB-SKILL:** 在触碰实现代码前使用 `superpowers:writing-plans`。
- **REQUIRED SUB-SKILL:** 优先使用 `superpowers:subagent-driven-development` 执行已写好的 implementation plan。
- **CONDITIONAL FALLBACK SUB-SKILL:** 当环境无法调度子代理、任务无法安全拆分、或子代理上下文无法被精确限定时，使用 `superpowers:executing-plans`。
- **REQUIRED SUB-SKILL:** 无论由主 agent 还是 implementer subagent 执行，对每个生产代码、行为、测试目标或重构变更使用 `superpowers:test-driven-development`。
- **REQUIRED SUB-SKILL:** 在切片或 claim 实施后使用 `superpowers:requesting-code-review`。
- **REQUIRED SUB-SKILL:** 在任何完成、已修复、通过、commit-ready 或 PR-ready 声明前使用 `superpowers:verification-before-completion`。
- **CONDITIONAL SUB-SKILL:** 对 platform plan 中列出的前端质量门切片使用 `impeccable`。

## 流程

1. 声明正在使用本技能，并说明当前进入的 gate。
2. 将 `git-delivery-workflow` branch gate 作为只读检查运行。
3. 选择且只选择当前 acceleration claim 指定的切片：其 claim 已由主协调会话写入共享 coordination store、当前分支匹配 lane、依赖或 start gate 满足，且自身状态尚未完成。
4. 根据 platform plan 和 split-plan 任务细则解析范围，然后运行预计划 Source Trace Conflict Gate。
5. 使用 `superpowers:writing-plans`，在 `docs/plans/implementation/` 下创建或更新一个 implementation plan。
6. 执行前评审 implementation plan。
7. 判断 implementation plan 是否能拆成边界清晰、上下文可精确限定的实现子任务。
8. 默认使用 `superpowers:subagent-driven-development`：主 agent 负责调度、上下文裁剪、review 循环和 gate，implementer subagent 负责限定范围内的 TDD 实现。
9. 只有当子代理不可用、任务无法安全拆分，或上下文不能精确限定时，fallback 到 `superpowers:executing-plans`，并在最终报告中说明原因。
10. 无论使用哪种执行路径，对每个改变生产代码、行为、测试目标或重构结构的子任务使用 `superpowers:test-driven-development`。
11. 使用 `superpowers:requesting-code-review` 运行代码评审检查点。
12. 使用 `superpowers:verification-before-completion` 运行最新验证。
13. 更新 implementation plan 和 worker evidence report；不得在 worker 分支更新 platform plan、split plan 或 acceleration execution plan 的最终状态。
14. 如果适合 commit，使用 `git-delivery-workflow` commit gate 自主完成提交；无需额外请求批准。

## Git Gate（Git 门禁）

在规划工作前，将 `git-delivery-workflow` branch gate 作为只读检查使用。它必须回答：worktree 是 clean 还是 mixed、当前分支目标是什么、本切片是否延续该目标、是否存在无关用户工作，以及下一步 Git 动作是什么。

不要主动运行超出当前切片 gate 的 Git 写操作。这包括创建分支、切换分支、merge、tag、rebase、worktree、push、创建 PR 或分支清理。如果需要这些 Git 写操作，准备请求并等待用户明确批准。`commit` 仅在满足 `git-delivery-workflow` commit gate 时允许自主执行。

不要 revert 用户更改。如果存在无关编辑，保持不动。如果它们阻塞已选切片，停止并询问如何分离这些工作。

如果通用 Superpowers 指令提到 `using-git-worktrees`、`commit`、`finishing-a-development-branch`、`merge`、`PR` 或分支清理，用本仓库流程替换这些步骤：

- 生成已验证检查点。
- 报告变更文件和验证证据。
- 对相关 gate 使用 `git-delivery-workflow`。
- 对 `commit` 应用 commit gate；其它 Git 写操作前请求用户明确批准。

## 切片选择

### Acceleration Lane Gate（加速 lane gate）

在切片选择前，通过 `git branch --show-current` 读取当前分支，检查 `docs/plans/function-one-acceleration-execution-plan.md` 的静态 lane/queue/owner 规则，并用共享 coordination store 校验 claim。

共享 coordination store 位于 git common dir：

```text
<git-common-dir>/codex-coordination/function-one.sqlite
```

Worker 自动发现命令：

```powershell
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py worker-start --json
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py current-worker --json
```

这些命令只读读取当前 Git branch，并查找该 branch 下唯一 `claimed` / `reported` claim。`worker-start --json` 还会报告 branch HEAD、dirty 状态和 integration delta。它们不能从 queue 抢任务，也不能写 coordination store。如果返回 0 个或多个 active claim，停止并报告主协调会话。

Worker 已知 claim id 时的只读校验命令：

```powershell
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py validate-worker --claim <claim-id> --branch <current-branch> --status claimed --status reported --json
```

如果该命令失败，停止执行，不得通过修改计划文档、修改共享 store 或跳过 gate 继续。

当前请求可以提供 claim id，也可以只要求继续当前 worktree 已分配的 claim。没有显式 claim id 时，必须先运行 `worker-start --json` 或 `current-worker --json` 自动发现当前 branch 的唯一 `claimed` / `reported` claim；发现 0 个或多个时停止。worker 不得自行从 queue 抢任务。若当前 branch 没有 active claim，报告主协调会话运行 `post-checkpoint --apply`；worker 不自行写 coordination store。

对 claim 执行以下 gate：

- 共享 coordination store 中存在该 claim。
- claim `Status` 是 `claimed` 或 `reported`，不是 `queued`、`implemented`、`mock_ready`、`integrated`、`done` 或 `blocked`。
- 当前分支与 claim 的 `Branch` 完全匹配。
- claim 的 `Task` 属于 claim 的 `Lane` 在 Lane Registry 和 Lane Queue 中的覆盖范围。
- claim 所属 lane 在静态 Lane Registry 中存在；claim 状态由共享 coordination store 判断，文档中的 lane status 只作为 checkpoint snapshot 或审计摘录。
- 当前 task 在 platform plan 和对应 split plan 中存在，且状态不是 `[x]`。
- 任务依赖已满足，或 acceleration execution plan 的 Start Gate 明确允许 mock-first。
- 本 claim 不需要修改其它 lane owner 的共享入口。

如果用户指定 task id，必须与 claim 的 `Task` 完全一致；否则停止。

不要从部分分支名、任务前缀、文件路径或当前 diff 推断 lane。Lane Registry 中的 branch 必须与当前 Git 分支完全匹配。

每次只执行 claim 指定的一个 task slice。不要把边界设定任务与无关实现合并。不要执行同一 lane queue 中的下一个 task，除非主协调会话已手动 claim 或通过 `auto-advance-claims --apply` 自动解封了新的 claim。

### 任务资格

只有同时满足以下条件时，一个切片才符合条件：

- 该任务存在于 platform-plan 任务表，并且有匹配的 split-plan 细则小节。
- platform-plan 任务状态是 `[ ]` 或 `[/]`，不是 `[x]`。
- split-plan 任务状态是 `[ ]` 或 `[/]`，不是 `[x]`。
- 依赖概览、split-plan 细则或任务验收标准要求的每个前置任务都已完成，或 acceleration execution plan 的 Start Gate 明确允许该 claim 以 `mock_ready` 方式先行。
- 该任务不需要按照 `references/superpowers-execution-rules.md` 拆成独立计划或独立 batch。

在切片选择期间，读取 `references/superpowers-execution-rules.md`，并在声明任务符合条件前检查独立计划 / batch 列表。

不得在 worker 分支自动扫描全局任务表选择下一个切片。只有主协调会话通过 `acceleration-workflow` 手动 claim 或 auto-advance claim 的 task 才能执行。

遇到以下情况时停止，而不是继续选择：

- platform-plan 状态与 split-plan 状态不一致。
- 依赖未记录为完成，且 Start Gate 未允许 mock-first。
- 前置任务不清楚，或只由文字隐含。
- 因重复任务 id 或失效锚点，多个候选任务看起来满足同一排序位置。
- 用户指定的任务 id 已完成、缺失、阻塞，或与当前分支 / worktree 状态冲突。
- claim id 缺失且 `current-worker` 无法发现唯一 active claim、共享 coordination store 不可读、claim 未知、状态不可执行，或与当前分支不匹配。
- 当前分支未注册在 Lane Registry 中。
- 请求的任务不在当前 claim 或 lane coverage 中。
- 当前分支是 `main`，但用户要求执行 worker claim。
- 当前分支是 integration 分支，但用户要求执行 lane worker claim。

### Superpowers 执行规则引用

在切片选择期间读取 `references/superpowers-execution-rules.md`，用于检查独立计划和独立 batch 边界。当已选切片涉及前端呈现质量、`Log & Audit Integration`、API/OpenAPI 路由检查，或必须覆盖的通用 `superpowers:writing-plans` 默认规则时，在写 implementation plan 前再次读取它。

## 范围解析

写 implementation plan 前，读取已选 split-plan 任务细则：文件、目标类 / 函数、验收标准、测试、依赖和状态。

已选 split-plan 任务细则是规划基线，因为它们是已评审的任务级指令。当前 specs 只作为辅助追溯来源，用于澄清不明确或缺失的细节；不要把 specs 当成覆盖已评审任务细则的许可。

如果任务边界、实现细节、产品边界、阶段语义、API 契约、投影契约、事件语义或前端交互语义不清楚，追溯到三个当前 specs。如果 specs 能在不冲突已选任务细则的情况下补充缺失细节，将该追溯写入 implementation plan。如果 specs 沉默、含糊，或与已选任务细则冲突，停止并用定向选项向用户报告问题。

当未实现区域存在不清楚的规划语言时，实现前优先修正规划，而不是叠加补丁式说明。只有在用户要求，或当前任务明确是规划 / 文档任务时，才修改规划 / specs 措辞；草稿 specs 文档在 commit 前仍需要用户评审。

## Source Trace Conflict Gate（来源追溯冲突 gate）

在写 implementation plan 前使用此 gate；当执行过程暴露已选切片、implementation plan、现有代码、已完成任务与当前 specs 之间可能存在冲突、缺失规则或漂移风险时，也再次使用。

1. 针对冲突点停止本地实现工作。
2. 将已选 split-plan 任务细则视为基线。
3. 使用上面的事实来源表，将争议行为追溯到相关当前 spec 小节。
4. 如果 spec 在不冲突已选任务细则的情况下澄清了缺失任务细节，将该追溯写入 implementation plan。
5. 如果 spec 沉默、含糊，或与已选任务细则、platform plan、任务依赖顺序、现有实现或已完成任务记录冲突，停止工作流。
6. 向用户报告冲突，包含文件引用、竞争解释、受影响任务 id 和定向建议。
7. 在修改 specs、修改计划、收窄切片或实现代码前等待用户指示。

不要使用 specs 覆盖已评审任务细则。当任务细则和追溯来源不能解决语义解释时，不要自行选择解释。不要通过兼容胶水、临时别名、更宽泛测试或仅实现层面的补丁说明隐藏冲突。

## Implementation Plan 要求（实施计划要求）

### Writing-Plans 覆盖规则

使用 `superpowers:writing-plans` 时，在通用技能模板之上应用本仓库执行规则。加载 `references/superpowers-execution-rules.md` 以获取详细覆盖规则。

使用 `superpowers:writing-plans`，并将 implementation plan 保存为：

```text
docs/plans/implementation/<task-id>-<task-name>.md
```

implementation plan 遵循 `superpowers:writing-plans` 的任务表结构，并包含精确文件路径、TDD red-green 步骤、具体失败测试代码、具体实现代码、精确运行命令、预期失败和通过输出，以及完成验证清单。加载 `references/superpowers-execution-rules.md` 获取本仓库覆盖规则。

implementation plan 不得放宽任务边界、重写已批准语义、遗漏必需验收标准，或使用 TODO/TBD/fill in later 之类占位符。

对于 `backend/app/api/routes/*` 变更，加载 `references/superpowers-execution-rules.md`，并在 implementation plan 中包含 API/OpenAPI 清单。

对于用户命令接口、run 生命周期变更、runtime 节点、模型调用、工具调用、workspace 写入、`bash`、Git 交付、远程交付、配置变更或安全敏感失败，包含 `Log & Audit Integration`；加载 `references/superpowers-execution-rules.md`，并将适用清单写入 implementation plan。

## 计划评审门禁

执行前，对已写好的 implementation plan 按以下内容评审：

- 已选 split-plan 任务。
- platform-plan Superpowers 执行规则。
- 相关当前 spec 小节。
- 已完成前置任务及其记录语义。

如果 implementation plan 存在严重缺口、矛盾语义、依赖不确定、缺少 TDD 步骤、缺少预期输出、缺少 API/OpenAPI 检查、缺少日志 / 审计要求，或适用的前端切片缺少前端设计门，停止。

## 执行规则

默认使用 `superpowers:subagent-driven-development` 作为外层执行流程。主 agent 不把自己的完整会话历史交给子代理；必须为每个 implementer / reviewer subagent 构造精确任务上下文，包含已选切片、implementation plan 中对应任务、允许文件、相关 split-plan 细则、必要 spec 追溯、测试命令和禁止事项。

### 子代理命令权限

子代理任务上下文必须列出允许命令。子代理可运行 implementation plan 中声明的只读检查和现有验证命令，例如 `uv run pytest ...`、`uv run ruff check ...`、`npm --prefix frontend test|lint|build ...`。涉及依赖安装或同步、lock / manifest 变更、数据库迁移、配置或环境文件变更、删除 / 移动文件、外部服务写入、Git 写操作，子代理必须停止并回报 `APPROVAL_REQUIRED`，由主 agent 向用户请求批准。

主 agent 保留以下控制权，不委托给子代理：

- 切片选择、依赖检查、Acceleration Lane Gate 和 Source Trace Conflict Gate。
- Git gate、commit 批准请求、PR-ready / merge-ready 判断和所有 Git 写操作决策。
- implementation plan 和 worker evidence report 更新。
- 最新验证结论、完成声明和用户汇报。

主协调会话独占以下最终状态更新；主 agent 不得执行：

- 共享 coordination store 和 checkpoint snapshot 的状态收敛。
- platform plan 和 split plan 的最终 `[x]` / `[/]` 状态更新。
- integration checkpoint 状态更新。

子代理执行必须遵守以下边界：

- implementer subagent 只修改分派任务明确允许的文件和测试，不扩大切片范围。
- implementer subagent 必须使用 `superpowers:test-driven-development`，并回报 red/green 命令、退出码和关键输出。
- reviewer subagent 只评审，不承担实现；默认只做静态 review。除非主 agent 明确要求，reviewer 不重复运行测试。
- reviewer subagent 先进行 spec / plan 合规评审，再进行代码质量、测试充分性和回归风险评审。
- 子代理不得运行 Git write 操作，不得更新任务状态，不得提交、创建 PR、merge、tag、rebase、push 或清理分支。

仅当当前环境无法调度子代理、任务无法安全拆分，或子代理上下文无法被精确限定时，使用 `superpowers:executing-plans` fallback。在 fallback 中，主 agent 仍必须执行同等 TDD 步骤、两阶段内联评审和最终验证，并在完成报告中说明 fallback 原因。

对于每个改变生产代码、行为、测试目标或重构结构的步骤：

1. 写一个失败测试。
2. 运行它，并确认失败原因符合预期。
3. 编写最小实现。
4. 运行测试，并确认它通过。
5. 只有在测试转绿后才重构，并保持测试为绿色。

不要用事后补测试替代 TDD。不要在执行期间扩大范围。如果验证反复失败，停止并报告实际阻塞项。

## 代码评审检查点

切片或执行 claim 完成后，使用 `superpowers:requesting-code-review`。当使用 `superpowers:subagent-driven-development` 时，遵循其两阶段 review 顺序：先 spec compliance reviewer，再 code quality reviewer；任一 reviewer 发现 Critical 或 Important 问题时，必须修复并 re-review 后才能继续。

按以下顺序评审：

1. specs 和 plan 合规性。
2. 代码质量。
3. 测试充分性。
4. 回归风险。

在声明完成前修复 Critical 和 Important 发现。如果当前环境无法调度 reviewer，执行同等的两阶段内联评审，并在最终报告中说明该限制和 fallback 原因。

reviewer 默认不重复运行测试，除非主 agent 明确要求。reviewer 测试结果不能替代主 agent 的最终 fresh verification。re-review 应覆盖上轮 findings 和相关变更。

## Frontend Design Gate（前端设计 gate）

在 Codex 中，当切片涉及前端 UI/UX 设计、实现、评审、打磨、加固、可见交互状态、响应式行为、可访问性或视觉一致性时，使用 `impeccable` 作为辅助前端质量工具。

加载 `references/superpowers-execution-rules.md` 获取明确任务 id 和 `Frontend Design Gate` 清单。适用前端展示切片的 implementation plan 必须包含该 gate。

前端设计 gate 只控制呈现质量。它不得覆盖产品语义、阶段语义、运行时控制、后端 API、投影字段、事件载荷或测试要求。

前端设计 gate 不替代测试。完成仍需要相关组件、状态、API client、Playwright 或响应式验证命令。

## 验证和追踪

在说工作完成、已修复、通过、checkpoint-ready、commit-ready 或 PR-ready 前，使用 `superpowers:verification-before-completion`。

最新验证表示：

- 运行变更范围所需的完整命令。
- 读取完整输出和退出码。
- 如实报告失败。
- 不要从过期或局部结果外推。

### 分级验证节奏

- 实现阶段：只运行 focused tests，证明当前 TDD red-green 循环。
- review 修复后：运行 focused tests 和 impacted regression 命令。
- 标记任务完成前：运行一次切片范围需要的 full backend / frontend suite，或 platform plan 明确要求的完整验证命令。
- full suite 之后如果只修改 implementation plan 或 worker evidence report，不重跑 full suite；改为检查 `git diff` / `git status`，确认 full suite 后没有代码、测试、配置或 lock / manifest 变化，并在完成报告中说明。
- 如果 full suite 后又修改代码、测试、配置、依赖清单或会影响运行行为的文档生成物，必须重新运行受影响的 focused / impacted / full 命令。

验证后，worker 分支只更新允许的本地证据：

- 对应 `docs/plans/implementation/<task-id>-<task-name>.md`。
- `docs/plans/acceleration/reports/<claim-id>.md`。

状态更新必须遵守以下规则：

- Worker evidence report 可以声明本地结果 `reported` 或 `blocked`，并必须写明提交后预期进入 `implemented` 还是 `mock_ready`；主协调会话会用 `scan-worker-commits` / `ingest-worker-commits` 自动读取该声明，不需要用户复制 checkpoint report。
- `reported` 表示本地 worktree 已写入 evidence report、implementation plan、代码 / 测试 diff 和验证记录；它只支持主协调会话本地读取，不是可合入 checkpoint。
- `implemented` 由主协调会话在确认 worker branch checkpoint commit 后写入共享 coordination store；该 commit 必须包含 claim 范围代码、测试、implementation plan 和 evidence report。
- `mock_ready` 由主协调会话在确认 worker branch checkpoint commit 后写入共享 coordination store；该 commit 只表示基于冻结契约、fixture 或 mock 完成可验证部分，不得视为最终完成。
- `blocked` 必须包含阻塞原因、已验证事实和建议 owner。
- Worker 不在 evidence report 中声明权威 Worker HEAD；Worker HEAD 由主协调会话在 ingest 时读取分支提交并写入共享 coordination store。
- Worker 不得把 platform plan 或 split plan 标记为 `[x]`。
- Worker 不得写入共享 coordination store，不得更新 `docs/plans/function-one-acceleration-execution-plan.md` 的 checkpoint snapshot。
- integration checkpoint 后由主协调会话统一更新 platform plan、split plan、共享 coordination store 和必要的 checkpoint snapshot。

不要更新无关任务状态。

## 停止条件

遇到以下情况时停止并报告用户：

- worktree 有无关变更，使分支 gate 不安全。
- claim id 缺失且 `current-worker` 无法发现唯一 active claim、共享 coordination store 不可读、claim 未知、状态不可执行或与当前分支不匹配。
- claim 所属 task 不在当前 lane coverage 中。
- claim 需要修改其它 lane owner 的共享入口。
- 已选切片依赖未完成或不清楚的前置任务，且 Start Gate 未允许 mock-first。
- platform plan 与 split plan 冲突。
- 当前 spec 与已选任务细则或 implementation plan 冲突。
- 当前实现或已完成任务使用不同语义模型。
- 三个当前 specs 无法解决歧义。
- 已选切片、implementation plan、现有代码路径或已完成任务记录产生需要来源追溯的冲突。
- 来源追溯找不到管辖 spec 小节，或发现 specs / plan / 任务语义冲突。
- 前端质量建议会改变产品语义或 API / 事件契约。
- 通用 Superpowers 流程要求 Git 写操作或分支收尾动作。
- 子代理需要的任务边界、允许文件、上下文或禁止事项无法被精确限定，且 fallback 也无法安全执行。
- 子代理执行或评审试图扩大切片范围、更新中央追踪状态或运行 Git 写操作。
- implementation plan 缺少具体 TDD 步骤、代码、命令或预期输出。
- 验证在聚焦调试后仍反复失败。

停止时，包含具体冲突、文件引用和定向建议。不要靠猜测继续。

## 完成报告

报告：

- 已选切片 id 和 implementation plan 路径。
- claim id、lane id 和 evidence report 路径。
- worktree path、branch、dirty status 和 diff stat。
- 使用的执行路径：`subagent-driven-development` 或 fallback 到 `executing-plans` 的原因。
- 变更文件。
- TDD red/green 证据，或纯文档切片的 N/A 原因。
- 代码评审结果和修复。
- 验证命令、退出码和关键输出。
- 已做 worker evidence 更新；若未更新，说明原因。本地结果只报告 `reported` 或 `blocked`。
- 剩余风险或阻塞项。
- 是否建议 commit 批准请求；如果建议，说明提交后主协调会话会自动扫描 branch HEAD、evidence report 和 expected ingest result 并 ingest 为 `implemented` 或 `mock_ready`。

如果建议 commit，使用 `git-delivery-workflow` commit gate；满足 gate 时可直接 commit，并在完成报告中附上提交信息和验证证据。

## 常见错误

- 选择任务时没有同时检查 platform-plan 和 split-plan 状态。
- 在可安全拆分且可调度子代理时跳过 `superpowers:subagent-driven-development`。
- 把 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 当作 `superpowers:test-driven-development` 的替代品。
- 接受通用 `superpowers:writing-plans` 中的 commit、worktree、PR、merge、tag 或分支清理步骤。
- 让子代理更新 acceleration execution plan、platform plan、split plan 或执行 Git 写操作。
- 用 specs 覆盖已评审任务细则，而不是在冲突时停止。
- 来源追溯发现缺失、含糊或冲突的管辖追溯来源后仍继续。
- 验证后更新无关任务状态。
- 对可见前端工作跳过 `impeccable` quality gate。
- reviewer 无法调度时跳过内联代码评审。
