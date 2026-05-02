---
name: delivery-branch-coordinator
description: "Legacy only. Use when explicitly auditing the archived Function One Delivery Branch Plan history or explaining the retired DB batch workflow."
---

# Delivery Branch Coordinator (Legacy)

## Overview

本技能已退役为历史参考。功能一后续主动调度使用 `.codex/skills/acceleration-workflow/SKILL.md` 和 `docs/plans/function-one-acceleration-execution-plan.md`。

旧 DB batch 表已归档为 `docs/archive/function-one-delivery-branch-plan-legacy.md`。不要使用本技能选择新工作区、claim 新任务、生成 worker prompt 或更新执行状态。

## Allowed Uses

- 解释旧 DB00-DB34 批次边界为何存在。
- 审计已合入历史分支的旧 review boundary。
- 对比旧串行 batch 模型和新 acceleration lane 模型。

## Required Sources

- `docs/archive/function-one-delivery-branch-plan-legacy.md`
- `docs/plans/function-one-acceleration-execution-plan.md`
- `docs/plans/function-one-platform-plan.md`

## Stop Conditions

- 用户要求用本技能 claim、启动或更新新的功能一任务。
- 用户要求修改 `docs/plans/function-one-acceleration-execution-plan.md`。
- 用户要求创建 worktree、分支、commit、PR/MR 或 merge。

## Common Mistakes

- 继续把旧 DB12-DB34 当作可启动分支。
- 用旧 `planned / claimed / ready_for_review / merged` batch 状态替代新 Claim Ledger。
- 让 worker 更新全局最终任务状态。
- 忽略 `acceleration-workflow` 的 lane ownership gate。
