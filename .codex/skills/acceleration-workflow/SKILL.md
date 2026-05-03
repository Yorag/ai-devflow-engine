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
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py current-worker --json
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py scan-worker-commits --json
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py ingest-worker-commits
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py sync-idle-branches
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py auto-advance-claims
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py status-summary
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py worker-start
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py post-checkpoint
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
- **Sync Idle Branches**：integration checkpoint push 后，同步没有 active / blocked claim 的空闲 lane branch 到最新 integration base。
- **Auto Advance**：integration checkpoint 完成后，为已同步到最新 integration base 且没有 active claim 的 lane 自动 claim 下一条 queue task。
- **Checkpoint Closeout**：integration checkpoint push 后，在同一次主协调收尾中执行 `post-checkpoint --apply`，收敛 ingest、空闲 branch 同步和自动解封。
- **Status Summary**：输出 AL01-AL06 lane、branch delta、dirty、latest claim 和下一动作。
- **Post Checkpoint**：在 integration checkpoint 后串联 scan/ingest、空闲同步和自动解封；默认 dry-run，`--apply` 才写 store 或执行 ff-only sync。
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
- claim id、lane id、task id、Coordination Base；如果 worker prompt 未显式列出这些字段，worker 必须用 `current-worker --json` 只读发现当前 branch 的唯一 `claimed` / `reported` claim。
- coordination store 读取方式：`uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py current-worker --json` 或 `uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py show --claim <claim-id> --json`。
- evidence report 路径。
- lane owner scope。
- forbidden shared entries。
- 允许命令和验证命令。
- 禁止更新最终进度表、禁止自行 claim 下一个任务、禁止写入 coordination store、禁止未经用户批准的 Git 写操作。未提交 evidence 只能报告 `reported`；claim commit 必须走 `git-delivery-workflow` commit gate。

## Progress Ingest

主协调会话默认使用自动扫描交接，不要求用户手工复制 worker checkpoint report。worker 分支完成并获得用户批准提交后，主协调会话或 integration 会话运行：

```powershell
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py scan-worker-commits
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py ingest-worker-commits
```

`scan-worker-commits` 只读检查当前 shared store 中 `claimed` / `reported` claim 的分支 HEAD、对应 worktree dirty 状态、evidence report 是否已提交、evidence metadata 是否匹配 claim/lane/task/base、implementation plan 是否在分支 diff 中，以及 evidence report 是否声明 expected ingest result。`ingest-worker-commits` 只在扫描结果 ready 时把对应 claim 更新为 `implemented` 或 `mock_ready` 并写入 Worker HEAD。

worker 提交后的人工回复只作为可读摘要，不是协调必要输入。不要要求用户把 worktree、branch、changed files 或验证命令逐项复制给主会话；这些信息应优先从 Git branch、evidence report 和 coordination store 自动读取。

读取 worker evidence report 后：

- `reported`：本地 worktree 中已有 evidence report、implementation plan、代码 / 测试 diff 和验证记录；只能用于本地协调，不得进入 integration。
- `implemented`：worker 分支已有用户批准的 checkpoint commit，包含代码、测试、implementation plan 和 evidence report，等待 integration。
- `mock_ready`：worker 分支已有用户批准的 checkpoint commit，只完成 mock-first 或 fixture-based 部分，不得标 `[x]`。
- `blocked`：记录 blocker，并把共享 coordination store 中的对应 claim 设为 `blocked`。

只有主协调会话可以把 claim 推进到 `integrated` 或 `done`。

## Sync Idle Branches And Auto Advance

主协调会话在 integration checkpoint 完成、claim 已收敛为 `done`、integration 分支已 push 后，必须在同一次 checkpoint closeout 中先检查空闲分支同步，再运行自动解封：

```powershell
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py status-summary
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py post-checkpoint
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py post-checkpoint --apply
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py sync-idle-branches
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py sync-idle-branches --apply
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py auto-advance-claims
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py auto-advance-claims --apply
```

`status-summary` 输出六路协调状态。主协调会话每次汇报都应包含该六路摘要，避免只讨论当前 lane。

`post-checkpoint` 是 checkpoint closeout 的常用入口：默认 dry-run，串联 worker commit scan、可 ingest 判断、空闲 branch 同步候选和 auto-advance 候选。`post-checkpoint --apply` 才执行 committed ingest、`sync-idle-branches --apply` 和 `auto-advance-claims --apply`。它不执行 lane merge、verification、checkpoint commit 或 push；这些仍由 integration checkpoint 明确控制。

closeout 的完成定义：

- integration checkpoint 的 merge、verification、状态更新和 push 已完成。
- `post-checkpoint --apply` 已执行完成，或主协调会话明确报告为何本次 closeout 只执行了其中的受限子步骤。
- 主协调会话已输出最新 `status-summary`，包含本次新解封 claim 或跳过原因。

不要把“integration checkpoint 已通过”和“checkpoint closeout 已完成”混为一谈。若未完成 closeout，主协调会话不得把该 checkpoint 报告为 fully complete，也不得把后续 worker 无 claim 视为 worker 侧异常。

`sync-idle-branches` 默认 dry-run，只报告哪些 lane branch 可 ff-only 同步；`--apply` 才执行 Git `merge --ff-only`。因为它会移动 branch HEAD，必须遵守 `git-delivery-workflow` 的批准规则。

空闲分支同步只允许处理同时满足以下条件的 lane：

- lane 没有 `claimed`、`reported`、`implemented`、`mock_ready`、`integrating` 或 `blocked` claim。
- worker branch 存在且有 worktree。
- worktree clean。
- branch 相对 integration target 没有独有未集成 commit。
- branch 落后 integration target，且可 `merge --ff-only`。

`auto-advance-claims` 默认 dry-run，只报告每条 lane 会 claim 哪个下一任务或为什么跳过；`--apply` 才写入共享 coordination store。

自动解封只允许 claim 同 lane 的下一条 queue task，并且必须满足：

- lane 没有 `claimed`、`reported`、`implemented`、`mock_ready` 或 `integrating` claim。
- worker branch 存在、worktree clean，且 branch HEAD 等于当前 integration coordination base。
- 下一任务在 platform plan 和 split plan 中均不是 `[x]`。
- 下一任务没有 active claim，且不是 `blocked`。
- 任务位于 Lane Registry 和 Lane Queue 中。

如果 lane branch 落后 integration，自动解封必须跳过该 lane；先由用户批准运行 `sync-idle-branches --apply` 或手动同步该 worker branch 到 integration checkpoint，再运行 auto-advance。自动解封不得创建分支、worktree、commit、merge 或 push。

因此完整节奏是：worker checkpoint commit -> scan / ingest -> integration merge / verify / mark done / push -> `post-checkpoint --apply` 完成 checkpoint closeout；其中包含 `sync-idle-branches --apply` 同步空闲 worker branch 和 `auto-advance-claims --apply` 解封下一条 claim。

Worker 会话启动时可用以下命令代替手工读 claim 字段：

```powershell
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py worker-start --json
```

`worker-start` 只读检查当前 branch 的唯一 `claimed` / `reported` claim、branch HEAD、dirty 状态和 integration delta。返回 `startable: true` 时，worker 可继续执行 `$slice-workflow`；返回 no active claim 时，worker 停止并让主协调会话运行 `post-checkpoint --apply` 或 `auto-advance-claims --apply`。

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
- 运行 `post-checkpoint` dry-run，并在同一次 checkpoint closeout 批准中执行 `post-checkpoint --apply`，让后续 worker 会话可直接用 `worker-start --json` 或 `current-worker --json` 发现下一条 claim。

checkpoint closeout 批准请求默认应覆盖：

- 本次 integration checkpoint 所需的 merge / verification / push。
- `post-checkpoint --apply`。
- closeout 后的 `status-summary` 汇报。

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

Claim: <claim-id 或运行 current-worker --json 自动发现>
Lane: <lane-id 或 current-worker 输出>
Task: <task-id 或 current-worker 输出>
Coordination Base: <current-baseline-commit 或 current-worker 输出>
Worker HEAD: <由主协调会话在 ingest 时填写；worker 不在 evidence report 中声明权威 Worker HEAD>
Coordination store: 使用 `git rev-parse --git-common-dir` 定位 `<git-common-dir>/codex-coordination/function-one.sqlite`，并用 `uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py current-worker --json` 自动发现当前 branch 的唯一 active claim；如果已显式获得 claim id，也可用 `show --claim <claim-id> --json` 复核。
Evidence report: docs/plans/acceleration/reports/<claim-id>.md 或 current-worker 输出的 evidence_path

只在该 lane owner scope 和该 task slice 范围内工作。不要修改其它 lane owner 的共享入口。不要写入 coordination store。不要更新 function-one-acceleration-execution-plan.md、function-one-platform-plan.md 或 split plan 的最终完成状态；这些由主协调会话在 integration checkpoint 后统一更新。

必须写或更新 implementation plan，按 TDD 执行，运行 claim 范围验证，并在 evidence report 中记录 red/green、验证命令、关键输出、mock-first 状态、commit readiness 和阻塞项。

完成后停止并报告简短 checkpoint 摘要和本地结果 `reported` 或 `blocked`。如果验证通过且适合提交，准备 commit 批准请求，并说明提交后主协调会话会通过 `scan-worker-commits` / `ingest-worker-commits` 自动读取 branch HEAD、evidence report 和 expected ingest result。获得明确批准后才能提交该 lane 分支。不要自行 claim 下一个任务，不要合并 integration，不要直接向 main 提交。
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
- 忘记同步空闲 lane branch 就运行 auto-advance，导致自动解封被 branch head guard 跳过。
- integration checkpoint 后忘记运行 auto-advance，导致 worker 会话反复回主协调申请下一条 claim。
- 将 integration checkpoint 的 merge / verify / push 与 `post-checkpoint --apply` 拆成两个松散流程，导致 checkpoint 看似通过但 lane 未解封。
- 让多个 worker 同时更新共享 coordination store 或中央 checkpoint snapshot。
- 把本地 `reported` evidence 当作可 merge 的 integration 输入。
- 把 mock-first 的 `mock_ready` 当作完成。
- 让前端 lane 自行发明 projection 或 event payload。
- 让非 owner lane 修改 schema、router、migration、frontend store 或 event payload。
- 在 integration checkpoint 前更新 platform plan 和 split plan 的最终完成状态。
