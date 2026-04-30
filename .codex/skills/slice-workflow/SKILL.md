---
name: slice-workflow
description: Use when asked to execute, continue, plan, or choose one task from this repository's one-slice-at-a-time platform implementation plan under docs/plans/function-one-platform-plan.md.
---

# Slice Workflow

## 概述

将 platform plan 中的一个实现切片依次通过本仓库要求的 gate。本技能把通用 Superpowers 执行方式适配到本仓库的平台计划执行规则、Git 规则、split specs 和前端质量门。

## 核心规则

每次调用只执行一个切片。除非当前切片已验证并汇报后，用户明确开始另一个切片，否则不要继续到下一个切片。

## 不适用场景

- 不要用于 `docs/plans/function-one-platform-plan.md` 之外的普通临时功能、缺陷修复或评审。
- 不要在一次调用中执行多个切片。
- 不要因为用户指定了任务 id 就绕过依赖、状态、分支或来源追溯 gate。
- 不要为本计划使用通用 Superpowers 默认流程中会创建 worktree、commit、PR、merge、tag、分支清理或子代理交接的步骤。
- 不要用 `impeccable` 改变产品语义、阶段语义、后端 API、投影字段、事件载荷或测试要求。

## 必读来源

读取最小必要集合，但必须把这些文件视为事实来源：

- `AGENTS.md`
- `docs/plans/function-one-platform-plan.md`
- `docs/plans/function-one-platform/*.md`
- `docs/specs/function-one-product-overview-v1.md`
- `docs/specs/frontend-workspace-global-design-v1.md`
- `docs/specs/function-one-backend-engine-design-v1.md`

仅在分支感知的切片选择、注册分支校验、当前分支 batch 状态更新，或报告可用 batch 选项时读取 `docs/plans/function-one-delivery-branch-plan.md`。当没有激活 batch gate 时，普通 `main` 分支任务查找不要加载它。

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
- **REQUIRED SUB-SKILL:** 使用 `superpowers:executing-plans` 执行已写好的 implementation plan。
- **REQUIRED SUB-SKILL:** 对每个生产代码、行为、测试目标或重构变更使用 `superpowers:test-driven-development`。
- **REQUIRED SUB-SKILL:** 在切片或实施 batch 后使用 `superpowers:requesting-code-review`。
- **REQUIRED SUB-SKILL:** 在任何完成、已修复、通过、commit-ready 或 PR-ready 声明前使用 `superpowers:verification-before-completion`。
- **CONDITIONAL SUB-SKILL:** 对 platform plan 中列出的前端质量门切片使用 `impeccable`。

## 流程

1. 声明正在使用本技能，并说明当前进入的 gate。
2. 将 `git-delivery-workflow` branch gate 作为只读检查运行。
3. 选择且只选择一个符合条件的切片：其依赖已完成，且自身状态尚未完成。如果存在 `Delivery Branch Plan`，在选择前应用当前分支 batch gate。
4. 根据 platform plan 和 split-plan 任务细则解析范围，然后运行预计划 Source Trace Conflict Gate。
5. 使用 `superpowers:writing-plans`，在 `docs/plans/implementation/` 下创建或更新一个 implementation plan。
6. 执行前评审 implementation plan。
7. 在主 agent 会话中使用 `superpowers:executing-plans` 作为外层执行流程。
8. 在该执行流程内，对每个改变生产代码、行为、测试目标或重构结构的子任务使用 `superpowers:test-driven-development`。
9. 使用 `superpowers:requesting-code-review` 运行代码评审检查点。
10. 使用 `superpowers:verification-before-completion` 运行最新验证。
11. 更新 platform plan 和 split plan 中的任务追踪。
12. 如果适合 commit，只准备 commit 批准请求。

## Git Gate（Git 门禁）

在规划工作前，将 `git-delivery-workflow` branch gate 作为只读检查使用。它必须回答：worktree 是 clean 还是 mixed、当前分支目标是什么、本切片是否延续该目标、是否存在无关用户工作，以及下一步 Git 动作是什么。

不要主动运行 Git 写操作。这包括创建分支、切换分支、commit、merge、tag、rebase、worktree、push、创建 PR 或分支清理。如果需要 Git 写操作，准备请求并等待用户明确批准。

不要 revert 用户更改。如果存在无关编辑，保持不动。如果它们阻塞已选切片，停止并询问如何分离这些工作。

如果通用 Superpowers 指令提到 `using-git-worktrees`、`commit`、`finishing-a-development-branch`、`merge`、`PR` 或分支清理，用本仓库流程替换这些步骤：

- 生成已验证检查点。
- 报告变更文件和验证证据。
- 对相关 gate 使用 `git-delivery-workflow`。
- 在任何 Git 写操作前请求用户明确批准。

## 切片选择

### Current-Branch Batch Gate（当前分支 batch gate）

在切片选择前，通过 `git branch --show-current` 读取当前分支。当当前分支不是 `main`、用户要求分支感知选择、需要报告可用 batch 选项，或需要更新当前分支 batch 状态时，检查 `docs/plans/function-one-delivery-branch-plan.md` 中的 `Delivery Branch Plan`。

如果当前分支与 batch 表中一个 `交付分支` 值完全匹配：

- 将该 batch 行视为当前分支目标。
- 不要选择该 batch 行的 `覆盖任务` 之外的任何任务。
- 按行中出现顺序展开 `覆盖任务` 的任务范围，然后从该有序列表中选择第一个符合条件且未完成的任务。
- 如果用户指定了任务 id，仍必须验证该任务 id 属于当前 batch；如果不属于，停止。
- 如果 batch `Status` 是 `planned` 或 `claimed`，继续应用前置门槛、普通任务资格、split-plan 状态、来源追溯和依赖检查；`planned` 不因主会话尚未预先写入 `claimed` 而阻塞已精确匹配的当前分支。
- 如果 batch `Status` 是 `merged` 或 `ready_for_review`，停止并报告该分支没有可执行切片。
- 如果 batch `Status` 是 `blocked`，停止并报告 batch 行和相关 split-plan 细则中的阻塞项。
- 如果 batch `Status` 不是 `claimed`、`planned`、`ready_for_review`、`merged` 或 `blocked`，停止并报告未知状态。
- 验证 `前置门槛` 中列出的每个 batch 都已记录为 `merged`，`无` 除外。如果任何前置 batch 不是 `merged`，停止并列出缺失的前置 batch id。
- 继续应用普通任务资格、split-plan 状态、来源追溯和依赖检查。Batch membership 只缩小候选集合，不覆盖任务依赖。

如果当前分支不匹配任何 `交付分支` 值：

- 在 `main` 上，除非用户明确指定任务 id 或明确要求全局下一个切片选择，否则不要从全局任务表自动执行切片。
- 在任何非 `main` 分支上，停止并报告当前分支未注册在 `Delivery Branch Plan` 中；要求用户切换到已注册分支或在执行切片前添加 batch 行。

不要从部分分支名匹配、任务前缀、文件路径或当前 diff 推断 batch。Batch 行必须与当前分支完全匹配。

如果用户指定了任务 id，使用该任务 id。否则从以下来源识别下一个依赖已满足且未完成的任务：

- `docs/plans/function-one-platform-plan.md`
- 相关的 `docs/plans/function-one-platform/*.md` split plan

不要选择多个切片。不要把边界设定任务与无关实现合并。如果当前分支 batch 处于激活状态，已选切片必须是该 batch 有序 `覆盖任务` 列表中的第一个符合条件且未完成的任务。

### 任务资格

只有同时满足以下条件时，一个切片才符合条件：

- 该任务存在于 platform-plan 任务表，并且有匹配的 split-plan 细则小节。
- platform-plan 任务状态是 `[ ]` 或 `[/]`，不是 `[x]`。
- split-plan 任务状态是 `[ ]` 或 `[/]`，不是 `[x]`。
- 依赖概览、split-plan 细则或任务验收标准要求的每个前置任务都已完成。
- 该任务不需要按照 `references/superpowers-execution-rules.md` 拆成独立计划或独立 batch。

在切片选择期间，读取 `references/superpowers-execution-rules.md`，并在声明任务符合条件前检查独立计划 / batch 列表。

在没有激活当前分支 batch 的情况下自动选择下一个切片时，按顺序扫描 platform-plan 任务表，并选择第一个符合条件的切片。当当前分支 batch 处于激活状态时，只扫描该 batch 的有序 `覆盖任务` 列表。如果找不到符合条件的切片，停止并报告范围内任务是否已全部完成、依赖是否未完成，或状态数据是否不一致。

遇到以下情况时停止，而不是继续选择：

- platform-plan 状态与 split-plan 状态不一致。
- 依赖未记录为完成。
- 前置任务不清楚，或只由文字隐含。
- 因重复任务 id 或失效锚点，多个候选任务看起来满足同一排序位置。
- 用户指定的任务 id 已完成、缺失、阻塞，或与当前分支 / worktree 状态冲突。
- 当前分支已注册在 `Delivery Branch Plan`，但请求的任务在该分支的 `覆盖任务` 之外。
- 当前分支是非 `main` 分支，且未注册在 `Delivery Branch Plan`。
- 当前分支是 `main`，未注册在 `Delivery Branch Plan`，且用户没有明确指定任务 id 或请求全局下一个切片选择。

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

implementation plan 必须包含精确文件路径、TDD red-green 步骤、具体失败测试代码、具体实现代码、精确运行命令、预期失败和通过输出，以及完成验证清单。加载 `references/superpowers-execution-rules.md` 获取完整 implementation-plan checklist。

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

使用 `superpowers:executing-plans` 作为外层执行流程。在主 agent 会话中执行；不要将 `superpowers:subagent-driven-development` 作为本仓库计划的实现方法。

对于每个改变生产代码、行为、测试目标或重构结构的步骤：

1. 写一个失败测试。
2. 运行它，并确认失败原因符合预期。
3. 编写最小实现。
4. 运行测试，并确认它通过。
5. 只有在测试转绿后才重构，并保持测试为绿色。

不要用事后补测试替代 TDD。不要在执行期间扩大范围。如果验证反复失败，停止并报告实际阻塞项。

## 代码评审检查点

切片或执行 batch 完成后，使用 `superpowers:requesting-code-review`。

按以下顺序评审：

1. specs 和 plan 合规性。
2. 代码质量。
3. 测试充分性。
4. 回归风险。

在声明完成前修复 Critical 和 Important 发现。如果当前环境无法调度 reviewer，执行同等的两阶段内联评审，并在最终报告中说明该限制。

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

验证后，只更新允许的追踪位置：

- `docs/plans/function-one-platform-plan.md` 中对应的任务状态。
- 当分支已注册时，`docs/plans/function-one-delivery-branch-plan.md` 中对应的当前分支 batch 状态。
- 对应 split-plan 任务状态、implementation-plan 链接和验证摘要。

状态更新必须遵守以下规则：

- 只有在所有任务验收标准均满足，且最新验证支撑该声明后，才标记 `[x]`。
- 只有当切片已有已验证的部分进展，但仍有未完成验收标准、验证失败或未解决评审发现时，才使用或保持 `[/]`。
- 当该任务没有已验证交付物完成时，保持 `[ ]`。
- 当验证失败、跳过，或只覆盖部分验收标准时，不要标记完成。
- split-plan 追踪说明必须包含 implementation-plan 链接、验证命令、关键结果，以及任何阻塞项或剩余范围。
- 对已注册的当前分支 batch，按以下方式设置或保持 batch `Status`：
  - 设置或保持 `claimed`：覆盖任务仍未全部完成，且没有阻塞项；如果当前 batch 原为 `planned`，第一次状态更新时写为 `claimed`。
  - `ready_for_review`：仅当 batch 的 `覆盖任务` 在 platform plan 和 split plans 中全部为 `[x]`，分支范围所需全部验证已通过，且评审发现已解决。
  - `blocked`：仅当执行因依赖、来源追溯、写入范围或验证阻塞项停止，且该阻塞项阻止分支继续推进。
  - 执行切片期间绝不要设置 `merged`。`merged` 只用于已经集成到 `main` 的工作。

不要更新无关任务状态。

## 停止条件

遇到以下情况时停止并报告用户：

- worktree 有无关变更，使分支 gate 不安全。
- 已选切片依赖未完成或不清楚的前置任务。
- platform plan 与 split plan 冲突。
- 当前 spec 与已选任务细则或 implementation plan 冲突。
- 当前实现或已完成任务使用不同语义模型。
- 三个当前 specs 无法解决歧义。
- 已选切片、implementation plan、现有代码路径或已完成任务记录产生需要来源追溯的冲突。
- 来源追溯找不到管辖 spec 小节，或发现 specs / plan / 任务语义冲突。
- 前端质量建议会改变产品语义或 API / 事件契约。
- 通用 Superpowers 流程要求 Git 写操作或分支收尾动作。
- implementation plan 缺少具体 TDD 步骤、代码、命令或预期输出。
- 验证在聚焦调试后仍反复失败。

停止时，包含具体冲突、文件引用和定向建议。不要靠猜测继续。

## 完成报告

报告：

- 已选切片 id 和 implementation plan 路径。
- 变更文件。
- TDD red/green 证据，或纯文档切片的 N/A 原因。
- 代码评审结果和修复。
- 验证命令、退出码和关键输出。
- 已做追踪更新。
- 剩余风险或阻塞项。
- 是否建议 commit 批准请求。

如果建议 commit，使用 `git-delivery-workflow` commit gate，并请求批准。没有用户明确批准，不要 commit。

## 常见错误

- 选择任务时没有同时检查 platform-plan 和 split-plan 状态。
- 把 `superpowers:executing-plans` 当作 `superpowers:test-driven-development` 的替代品。
- 接受通用 `superpowers:writing-plans` 中的 commit、worktree、PR 或子代理步骤。
- 用 specs 覆盖已评审任务细则，而不是在冲突时停止。
- 来源追溯发现缺失、含糊或冲突的管辖追溯来源后仍继续。
- 验证后更新无关任务状态。
- 对可见前端工作跳过 `impeccable` quality gate。
- reviewer 无法调度时跳过内联代码评审。
