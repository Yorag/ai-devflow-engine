---
name: acceleration-workflow
description: "Use when coordinating function-one acceleration lanes, claiming ready task slices, launching lane workers, ingesting worker evidence, or running integration checkpoints."
---

# Acceleration Workflow

## Overview

在主协调会话中管理功能一加速执行：读取 `function-one-acceleration-execution-plan.md` 的静态 lane、queue 和 owner 规则，使用 git common dir 下的共享 coordination store 分配 claim，生成 worker prompt，收集 worker evidence，并在 integration checkpoint 后统一更新主线状态快照。

本技能取代主动调度用途的 `delivery-branch-coordinator`。旧 DB 分支表只用于历史追溯。

## Scope

只在主协调会话使用本技能。不要在 worker worktree 中使用它执行代码或更新最终任务状态。

职责边界：

- `acceleration-workflow`：协调 lane、claim、worker prompt、integration checkpoint 和主线状态收敛。
- `slice-workflow`：在 lane worker 分支内执行一个已分配 claim。
- `git-delivery-workflow`：处理 branch、commit、integration、PR/MR 和 merge gate。

不要主动运行 Git 写操作。创建 worktree、创建分支、commit、merge、rebase、push、删除分支或清理 worktree 前，必须有用户明确批准。

## Shared Coordination Store

实时 claim 状态不通过提交 `docs/plans/function-one-acceleration-execution-plan.md` 广播。主协调会话和本地 worker worktree 共享同一个 git common dir，因此 live coordination state 存放在：

```text
<git-common-dir>/codex-coordination/function-one.sqlite
```

通过仓库脚本访问：

```powershell
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py store-path
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py init
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py list --json
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py show --claim <claim-id> --json
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py claim --claim <claim-id> --lane <lane-id> --task <task-id> --branch <branch-name> --base <coordination-base> --evidence docs/plans/acceleration/reports/<claim-id>.md
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py ingest --claim <claim-id> --status implemented --worker-head <head>
```

`Claim Ledger` 在计划文档中只作为 checkpoint snapshot 或审计摘录，不是 live source of truth。不要为了 claim、reported、implemented 或 mock_ready 的高频状态变化提交计划文档。只有 integration checkpoint、主线状态收敛或规则变更需要提交文档。

## Required Sources

最小读取：

- `AGENTS.md`
- `.codex/skills/git-delivery-workflow/SKILL.md`
- `.codex/skills/slice-workflow/SKILL.md`
- `docs/plans/function-one-acceleration-execution-plan.md`
- `docs/plans/function-one-platform-plan.md`
- 相关 `docs/plans/function-one-platform/*.md` split plan 小节
- `.codex/skills/acceleration-workflow/scripts/coordination_store.py`

只读检查：

```powershell
git status --short --untracked-files=all
git branch --show-current
git worktree list
git branch --list
git log --oneline --decorate -5
git check-ignore -q .worktrees
```

如果 `.worktrees/` 未被忽略，先报告需要处理 `.gitignore`；不要建议直接创建 project-local worktree。

## Modes

- **Queue Discovery**：从 lane queue 中找出 ready claim 候选，说明依赖、owner 和风险。
- **Claim Slice**：主协调会话把一个 ready task 写入共享 coordination store，状态为 `claimed`。
- **Worker Launch**：为已 claim 的 slice 输出 worktree 命令和 worker prompt。
- **Progress Ingest**：读取 worker evidence report。Local ingest 最多在共享 coordination store 中把 claim 收敛为 `reported` 或 `blocked`；Committed ingest 才能把 claim 收敛为 `implemented` 或 `mock_ready`。
- **Integration Checkpoint**：协调 AL 分支进入 `integration/function-one-acceleration`，跑验证并更新最终状态。
- **Main Promotion**：integration checkpoint 通过后，按 `git-delivery-workflow` 准备进入 `main` 的 PR/MR-ready 或 merge-ready 报告。

## Candidate Selection

一个 task slice 只有同时满足以下条件才可 claim：

- task 存在于 platform plan 和对应 split plan。
- platform plan 与 split plan 状态不是 `[x]`。
- task 在 acceleration execution plan 的 Lane Registry 和 Lane Queue 中有且只有一个归属 lane。
- lane status 是 `planned` 或 `claimed`。
- 共享 coordination store 中没有同一 task 的 active claim：`claimed`、`reported`、`implemented`、`mock_ready` 或 `integrating`。
- 任务依赖满足，或 Start Gate 明确允许 mock-first。
- 当前 active claims 不会与候选 task 共享同一个非 owner 写入口。
- 候选 task 不要求 worker 修改其它 lane owner 的共享入口。

如果没有 ready task，报告阻塞原因：依赖未满足、owner 冲突、已有 active claim、lane blocked、split/platform 状态冲突或 start gate 不允许。

## Claim Rules

主协调会话独占写入共享 coordination store。Worker 只能读取该 store 做 gate，不得写入。

Claim 阶段只允许更新：

- 使用 `.codex/skills/acceleration-workflow/scripts/coordination_store.py claim` 新增或更新该 claim。
- 必要时在 checkpoint snapshot 中记录批次状态；不要为单个 live claim 状态提交文档。

Claim 阶段不得更新：

- platform plan task 状态。
- split plan task 状态。
- implementation plan。
- worker evidence report。
- 其它 lane 的 claim。

## Worker Launch

对每个 lane 输出 PowerShell 命令。路径使用分支名安全目录名：把 `/` 替换为 `-`。

初次创建 lane 分支时从 `main` 创建。存在 `integration/function-one-acceleration` 且该 lane 已完成过 checkpoint 后，新 claim 必须先同步 integration 基线；同步方式由 `git-delivery-workflow` 判断并在 Git 写操作前请求用户批准。

```powershell
git worktree add ".worktrees\<safe-branch-name>" -b "<branch-name>" main
cd ".worktrees\<safe-branch-name>"
```

如果 branch 或 worktree 已存在，不要创建重复工作区；报告现有位置，并让用户决定进入现有 worktree、为已有 branch 创建明确的新 worktree，还是清理旧工作区。

已有 lane worktree 的继续提示必须先报告当前分支 HEAD、dirty status 和目标 Coordination Base；如果当前分支 HEAD 落后 integration checkpoint，停止并准备同步请求。

Worker prompt 必须包含：

- 当前 worktree 和 branch。
- claim id、lane id、task id、Coordination Base。
- coordination store 读取方式：`uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py show --claim <claim-id> --json`。
- evidence report 路径。
- lane owner scope。
- forbidden shared entries。
- 允许命令和验证命令。
- 禁止更新最终进度表、禁止自行 claim 下一个任务、禁止写入 coordination store、禁止未经用户批准的 Git 写操作。未提交 evidence 只能报告 `reported`；claim commit 必须走 `git-delivery-workflow` commit gate。

## Progress Ingest

读取 worker evidence report 后：

- `reported`：本地 worktree 中已有 evidence report、implementation plan、代码 / 测试 diff 和验证记录；只能用于本地协调，不得进入 integration。
- `implemented`：worker 分支已有用户批准的 checkpoint commit，包含代码、测试、implementation plan 和 evidence report，等待 integration。
- `mock_ready`：worker 分支已有用户批准的 checkpoint commit，只完成 mock-first 或 fixture-based 部分，不得标 `[x]`。
- `blocked`：记录 blocker，并把共享 coordination store 中的对应 claim 设为 `blocked`。

只有主协调会话可以把 claim 推进到 `integrated` 或 `done`。

Evidence 读取规则：

- Local Progress Ingest：从本地 worker worktree 读取 `docs/plans/acceleration/reports/<claim-id>.md`，并读取 `git -C <worktree> status --short`、`git -C <worktree> diff --stat` 和 `git -C <worktree> rev-parse --short HEAD`。如果 report 与共享 coordination store 中的 claim 一致，store 最多更新为 `reported` 或 `blocked`；dirty worktree 不得更新为 `implemented` 或 `mock_ready`。
- Committed Progress Ingest：使用 `git show <branch>:docs/plans/acceleration/reports/<claim-id>.md` 读取报告，并用 `git rev-parse --short <branch>` 记录 Worker HEAD。只有确认 evidence report、implementation plan、代码和测试包含在该 branch commit 中，共享 coordination store 才能更新为 `implemented` 或 `mock_ready`。
- Worker 不在 evidence report 中声明权威 Worker HEAD；Worker HEAD 由主协调会话在 ingest 时写入共享 coordination store。
- 如果 evidence report 不存在、分支不可读，或报告中的 claim/lane/task/Coordination Base 与共享 coordination store 不一致，停止 ingest。
- Progress Ingest 只更新共享 coordination store 中的状态、Worker HEAD 和 blocker 信息；不要合并代码，不要更新 platform plan 或 split plan，不要为每次 ingest 提交计划文档。

## Integration Checkpoint

AL 分支默认合入 `integration/function-one-acceleration`，不得直接进入 `main`。

checkpoint 前必须确认：

- integration branch 当前。
- 待集成 lane 的 Coordination Base、Worker HEAD、diff 和 evidence report 一致。
- 待集成 claim 是已提交的 `implemented` 或 `mock_ready`，不是 `reported`，且不是本地 dirty worktree。
- 没有跨 lane owner 未解决冲突。
- focused verification 已在 lane 分支通过。

checkpoint 后必须：

- 运行 checkpoint 声明的 integration verification。
- 将通过的 claim 在共享 coordination store 中更新为 `integrated` 或 `done`。
- 只对通过 merge gate 的 task 更新 platform plan 和 split plan 为 `[x]`。
- 对 mock-first 或部分完成的 task 使用或保持 `[/]`。
- 记录下一批 ready claim。

## Output Formats

Queue Discovery：

```text
当前协调状态：
- Branch: <branch>
- Dirty worktree: <clean / mixed with files>
- Integration branch: integration/function-one-acceleration
- Active claims: <claim ids>
- Coordination store: <git-common-dir>/codex-coordination/function-one.sqlite

Ready queue:
| Claim | Task | Lane | Branch | Start gate | Owner risk | Recommended |
| --- | --- | --- | --- | --- | --- | --- |
```

Worker prompt：

```text
你现在位于 <worktree-path>，当前分支必须是 <branch-name>。

使用 $slice-workflow 执行 acceleration claim：

Claim: <claim-id>
Lane: <lane-id>
Task: <task-id>
Coordination Base: <current-baseline-commit>
Worker HEAD: <由主协调会话在 ingest 时填写；worker 不在 evidence report 中声明权威 Worker HEAD>
Coordination store: 使用 `git rev-parse --git-common-dir` 定位 `<git-common-dir>/codex-coordination/function-one.sqlite`，并用 `uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py show --claim <claim-id> --json` 只读校验。
Evidence report: docs/plans/acceleration/reports/<claim-id>.md

只在该 lane owner scope 和该 task slice 范围内工作。不要修改其它 lane owner 的共享入口。不要写入 coordination store。不要更新 function-one-acceleration-execution-plan.md、function-one-platform-plan.md 或 split plan 的最终完成状态；这些由主协调会话在 integration checkpoint 后统一更新。

必须写或更新 implementation plan，按 TDD 执行，运行 claim 范围验证，并在 evidence report 中记录 red/green、验证命令、关键输出、mock-first 状态、commit readiness 和阻塞项。

完成后停止并报告 worktree path、branch、dirty status、diff stat、evidence report path、验证结果和本地结果 `reported` 或 `blocked`。如果验证通过且适合提交，准备 commit 批准请求，并说明提交后预期由主协调会话 ingest 为 `implemented` 或 `mock_ready`。获得明确批准后才能提交该 lane 分支。不要自行 claim 下一个任务，不要合并 integration，不要直接向 main 提交。
```

## Stop Conditions

遇到以下情况停止并报告：

- 当前分支不是 `main` 或 integration 协调分支，但用户要求 claim、更新中央账本或执行 integration checkpoint。
- 主工作区有无关未提交修改，且用户要求修改中央账本。
- acceleration execution plan 缺少 Mode、Lane Registry、Lane Queue、Shared Ownership 或 Integration Checkpoints，或共享 coordination store 不可读。
- 同一 task 被多个 lane 覆盖。
- 同一 task 在共享 coordination store 中已有 active claim。
- 候选 task 需要修改其它 lane owner 共享入口。
- platform plan 与 split plan 状态冲突。
- 本地已有同名 branch 或 worktree，且用户要求创建重复工作区。
- 用户要求把 `reported` claim、未提交 worktree diff 或缺少 checkpoint commit 的 worker 成果进入 integration checkpoint。
- 用户要求 worker 直接更新最终 `[x]` 状态。
- 用户要求 AL 分支绕过 integration 直接合入 `main`。

## Common Mistakes

- 让 worker 自己从 queue 抢任务。
- 让多个 worker 同时更新共享 coordination store 或中央 checkpoint snapshot。
- 把本地 `reported` evidence 当作可 merge 的 integration 输入。
- 把 mock-first 的 `mock_ready` 当作完成。
- 让前端 lane 自行发明 projection 或 event payload。
- 让非 owner lane 修改 schema、router、migration、frontend store 或 event payload。
- 在 integration checkpoint 前更新 platform plan 和 split plan 的最终完成状态。
