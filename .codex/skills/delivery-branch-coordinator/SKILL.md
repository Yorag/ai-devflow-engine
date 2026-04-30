---
name: delivery-branch-coordinator
description: "Use when the user asks from main to coordinate Delivery Branch Plan batches, identify startable branches, prepare worktree launch instructions, or manage branch-status updates around PR/MR review."
---

# Delivery Branch Coordinator

## Overview

在主会话协调 `Delivery Branch Plan`：选择可启动 batch、按需预标 `claimed`、生成 worktree 命令和 worker 启动提示词，并在 PR/MR 合入后更新 `merged`。本技能不执行 slice；分支内实施仍由 `slice-workflow` 控制。

## Scope

只在主分支协调工作区使用本技能。不要在 worker worktree 中使用它选择 slice、实施任务、更新任务完成状态或创建 PR/MR 内容。

保持职责边界：

- `delivery-branch-coordinator`：协调 batch、worktree、worker prompt、主线合入状态。
- `slice-workflow`：在具体分支内一次选择并执行一个 slice。
- `git-delivery-workflow`：处理 branch、commit、PR、merge gate。

不要主动运行 Git 写操作。创建 worktree、创建分支、commit、merge、rebase、push、删除分支或清理 worktree 前，必须有用户明确批准。用户只要求“给出命令”时，只输出命令。

## Required Sources

最小读取：

- `AGENTS.md`
- `.codex/skills/git-delivery-workflow/SKILL.md`
- `.codex/skills/slice-workflow/SKILL.md`
- `docs/plans/function-one-delivery-branch-plan.md`
- `docs/plans/function-one-platform-plan.md`

只读检查：

```powershell
git status --short --untracked-files=all
git branch --show-current
git worktree list
git branch --list
git log --oneline --decorate -5
```

如果要给出 project-local worktree 命令，检查 `.worktrees/` 是否被忽略：

```powershell
git check-ignore -q .worktrees
```

如果 `.worktrees/` 未被忽略，先报告需要处理 `.gitignore`；不要建议直接创建 project-local worktree。可改用仓库外全局路径，或先让用户批准 `.gitignore` 变更。

## Modes

根据用户请求选择模式：

- **Discovery mode**：只找出下一批可启动 batch，并输出原因、风险和命令草案。
- **Claim mode**：用户选定 batch 后，可只把这些 batch 的 `Status` 从 `planned` 改为 `claimed`，但该预标不是 worker 执行前置。
- **Worker launch mode**：为已注册且可启动的 batch 输出 worktree 命令和 worker 启动提示词；batch 仍为 `planned` 时也可启动，worker 首次状态更新会收敛为 `claimed`。
- **Merge coordination mode**：PR/MR 已通过后，在主分支 review、合入，并只在合入完成后把 batch 标记为 `merged`。

## Candidate Selection

解析 `docs/plans/function-one-delivery-branch-plan.md` 表格。一个 batch 只有同时满足以下条件才可启动或预标认领：

- `Status` 是 `planned`。
- `前置门槛` 为 `无`，或列出的每个 batch id 都存在且 `Status` 是 `merged`。
- `交付分支` 没有被无关 worktree 使用；如果本地同名 branch 或对应 worktree 已存在，报告已物化的分支位置，不要创建重复分支，并可输出进入该分支继续执行 `slice-workflow` 的提示。
- 与当前 `claimed`、`ready_for_review` batch 不共享同一个明确的 `主要共享入口 / 冲突点`。
- 与同一推荐 wave 内的其它候选 batch 不共享同一个明确的 `主要共享入口 / 冲突点`。

并行等级解释：

- `S` 是串行门槛：它合入前，不得启动依赖它的下游 batch。`S` 不等于全局独占；没有依赖关系且写入范围不冲突的 peer batch 仍可并行。
- `Y` 是有序并行：可以并行实施，但合入前必须同步最新 `main`，并按前置关系完成合入。
- `G` 是绿色并行：前置已合入且写入范围不重叠时，可以和其它绿色或无冲突 batch 并行。

如果没有可启动 batch，报告阻塞原因：前置未 `merged`、状态不是 `planned`、branch/worktree 被无关工作区占用、冲突点重叠或表格结构异常。

## Output Format

Discovery mode 输出：

```text
当前主线状态：
- Branch: main
- Dirty worktree: <clean / mixed with files>
- Active batches: <claimed / ready_for_review / materialized planned>

可启动 batch：
| Batch | Branch | Tasks | Parallel | Preconditions | Review boundary | 风险 |
| --- | --- | --- | --- | --- | --- | --- |

推荐 wave：
1. <Batch> <Branch> - <reason>
```

如果主工作区有无关未提交修改，仍可报告候选项，但不要修改 `Delivery Branch Plan`，直到用户确认如何隔离这些修改。

## Claim Rules

用户确认认领后，只修改 `docs/plans/function-one-delivery-branch-plan.md` 中选定行的 `Status`：

- `planned` -> `claimed`

不要在 claim 阶段修改：

- platform plan task 状态。
- split-plan task 状态。
- implementation plan。
- 其它 batch 行。
- `ready_for_review` 或 `merged` 状态。

如果用户要求一次认领多个 batch，先重新应用 Candidate Selection。只认领同一安全 wave 内的 batch；对冲突或前置不满足的 batch，报告原因并跳过。

## Worktree Commands

对每个已注册且可启动 batch，输出 PowerShell 命令。路径使用分支名的安全目录名：把 `/` 替换为 `-`。

模板：

```powershell
git worktree add ".worktrees\<safe-branch-name>" -b "<branch-name>" main
cd ".worktrees\<safe-branch-name>"
```

示例：

```powershell
git worktree add ".worktrees\chore-engineering-baseline" -b "chore/engineering-baseline" main
cd ".worktrees\chore-engineering-baseline"
```

如果 branch 或 worktree 已存在，不要自动创建重复 worktree；报告现有位置，并让用户决定是进入现有 worktree、为已有 branch 创建一个明确指定的新 worktree，还是先清理旧工作区。

## Worker Prompt

为每个 batch 生成一个可直接粘贴到新 Codex 会话的启动提示词：

```text
你现在位于 <worktree-path>，当前分支必须是 <branch-name>。

使用 $slice-workflow 执行当前分支在 Delivery Branch Plan 中的下一个符合条件 slice。

Batch: <batch-id>
覆盖任务: <tasks>
Review boundary: <review-boundary>

只在该 batch 覆盖任务内工作。不要创建或切换 worktree，不要切换分支，不要合并 main，不要修改其它 batch 行。

每次只推进一个 slice。完成当前 slice 后，更新对应 platform plan、split plan、implementation plan 和当前 batch 状态，并给出验证证据。如果 batch 仍有未完成 slice 且没有阻塞项，将 planned 收敛为 claimed 或保持 claimed，停止并报告下一个继续提示词。

当该 batch 的覆盖任务全部完成、验证通过且 review 问题已处理后，将当前 batch 状态更新为 ready_for_review，准备 PR/MR-ready 报告。不要把状态改为 merged；merged 只由主会话在合入 main 后更新。
```

## Merge Coordination

当用户说某个 branch 已 PR/MR-ready 或请求合入时：

1. 使用 `git-delivery-workflow` 的 PR gate 和 merge gate。
2. 确认 branch 只覆盖一个 Review boundary。
3. 确认 branch 已同步最新 `main`，或用户明确接受当前集成策略。
4. 确认分支范围验证是最新的。
5. 合入前不要把 batch 标记为 `merged`。
6. 合入完成并通过主线验证后，只把对应 batch `Status` 改为 `merged`。

不要在主会话重新执行 worker 的 slice 实施。主会话只 review、集成、解决冲突，并更新主线协调状态。

## Stop Conditions

遇到以下情况停止并报告：

- 当前分支不是 `main`，但用户要求认领、更新主表或合入状态。
- 主工作区有无关未提交修改，且用户要求修改 `Delivery Branch Plan`。
- `Delivery Branch Plan` 表格缺列、重复 batch id、重复交付分支，或前置门槛引用不存在的 batch。
- 用户选定的 batch 不是 `planned`。
- 用户选定 batch 的前置门槛未全部 `merged`。
- 本地已有同名 branch 或 worktree，且用户要求主会话创建重复 branch/worktree。
- 多个待认领 batch 共享明确冲突点。
- 用户要求 worker 在主分支直接执行 slice。
- 用户要求 worker 把 batch 状态改为 `in_progress`。
- 用户要求合入前把 batch 标记为 `merged`。

## Common Mistakes

- 在主会话运行 `slice-workflow` 实施任务。
- 要求 worker 把 `claimed` 改为 `in_progress`；`claimed` 已覆盖预标认领、worktree 已创建和正在实施。
- 合入前把 batch 标记为 `merged`。
- 两个 worker 同时修改同一个共享 Schema、全局入口、migration 链或 App shell。
- 根据部分分支名猜 batch；必须使用 `交付分支` 精确匹配。
- 把 `S` 当作全局独占，或把 `Y` / `G` 当作不需要同步和 review。
