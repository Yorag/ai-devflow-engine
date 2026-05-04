# Function One Acceleration Execution Plan

本文件取代已归档的 `docs/archive/function-one-delivery-branch-plan-legacy.md`，作为功能一剩余实现的唯一主动调度入口。

本计划采用“子任务依赖队列 + lane 冲突域分支 + integration checkpoint”的执行模型：

- `docs/plans/function-one-platform-plan.md` 与对应 split plan 仍是子任务范围、验收标准和最终完成状态的事实来源。
- 本文件控制剩余任务如何分配到 lane、隔离共享写集、收敛到 integration 分支并更新主线事实。实时 claim 状态由 git common dir 下的共享 coordination store 承载。
- Worker 分支不得直接把全局任务状态标记为最终完成；最终 `[x]` 状态只在 integration checkpoint 通过后由主协调会话统一更新。
- 旧 DB12-DB34 不再作为可启动分支或前置门槛；其覆盖范围已被本文件的 lane queue 接管。

## 1. Mode

| Key | Value |
| --- | --- |
| Execution mode | active |
| Coordination skill | `.codex/skills/acceleration-workflow/SKILL.md` |
| Slice execution skill | `.codex/skills/slice-workflow/SKILL.md` |
| Integration branch | `integration/function-one-acceleration` |
| Stable branch | `main` |
| Current baseline | claim 时的当前 `main` 或最新 integration checkpoint |
| Legacy branch plan | `docs/archive/function-one-delivery-branch-plan-legacy.md` |
| Live coordination store | `<git-common-dir>/codex-coordination/function-one.sqlite` |
| Coordination CLI | `.codex/skills/acceleration-workflow/scripts/coordination_store.py` |

## 2. Status Model

### 2.1 Lane Status

| Status | Meaning |
| --- | --- |
| `planned` | Lane 已规划，尚未创建或认领工作区。 |
| `claimed` | Lane 已由主协调会话分配，worktree 可创建或正在实施。 |
| `integrating` | Lane 的一个或多个 claim 正在合入 integration 分支。 |
| `blocked` | Lane 被依赖、共享写集、验证或来源追溯问题阻塞。 |
| `complete` | Lane 覆盖的任务均已在 integration checkpoint 后完成。 |

### 2.2 Claim Status

| Status | Meaning |
| --- | --- |
| `queued` | 子任务在 lane queue 中，但依赖或 start gate 尚未满足。 |
| `ready` | 子任务依赖满足，可由主协调会话 claim。 |
| `claimed` | 子任务已分配给一个 lane worker。 |
| `reported` | Worker 本地 worktree 已写入 evidence report、implementation plan、代码或测试变更；主协调会话可读取本地状态，但该 claim 尚无可合入 checkpoint。 |
| `implemented` | Worker 分支已有用户批准的 checkpoint commit，包含代码、测试、implementation plan 和 evidence report，等待 integration。 |
| `mock_ready` | Worker 分支已有用户批准的 checkpoint commit，只完成 mock-first 或 fixture-based 可验证部分；不得标 `[x]`。 |
| `integrated` | 子任务实现已进入 integration 分支并通过对应 checkpoint 验证。 |
| `done` | 主协调会话已把 platform plan 与 split plan 状态更新为 `[x]`。 |
| `blocked` | 子任务存在阻塞项，不能继续执行或集成。 |

### 2.3 Base Fields

| Field | Meaning |
| --- | --- |
| `Coordination Base` | 主协调会话分配 claim 时记录的当前基线提交，用于判断任务资格和 owner 冲突。初始 claim 使用当时的 `main` HEAD；存在 integration checkpoint 后使用最新 integration 基线，除非主协调会话另行记录。 |
| `Worker HEAD` | 主协调会话在 ingest 时读取并写入共享 coordination store 的分支提交。Worker 不在 evidence report 中声明权威 Worker HEAD。`reported` 状态下它只标识当前 worktree 的已提交基线，必须结合 dirty status 和本地 diff 读取；`implemented` 或 `mock_ready` 状态下它必须是包含 evidence report 的 checkpoint commit。 |
| `Integration Base` | integration checkpoint 使用的目标分支提交，通常是 `integration/function-one-acceleration` 的当前 HEAD。 |

## 3. Lane Registry

六条 AL lane 是功能一剩余实现的长期并行分支。`QA` 是 integration-owned 验证队列，不作为产品实现 lane。所有 lane 从当前基线开始 claim，不从旧分支表或旧收尾分支继承 active 状态。

| Lane | Branch | Coverage | Status | Owner Scope | Review Boundary |
| --- | --- | --- | --- | --- | --- |
| AL01 | `feat/al-run-core-events` | R3.1, E3.1, R3.2a, R3.2, R3.3, R3.4, R3.4a, R3.4b, R3.5, R3.6, R3.7, C2.9a, C2.9b | claimed | Run 状态机、PipelineRun、EventStore、snapshot、GraphDefinition、StageRun、StageArtifact、历史可见性命令 | Run 和事件真源 |
| AL02 | `feat/al-projections-streams` | Q3.1, Q3.2, Q3.3, Q3.4, Q3.4a, E3.2, L3.1, L4.2, Q3.4b | claimed | Projection services、SSE、run/stage log query、audit query route | 查询投影、实时流和轻查询 API |
| AL03 | `feat/al-runtime-human-loop` | A4.0, L4.1, H4.1, H4.3, D4.0, H4.4, H4.4a, H4.4b, H4.5, H4.6, H4.7 | claimed | RuntimeOrchestrationService、clarification、approval、delivery snapshot gate、runtime control commands | 运行编排和人工介入后端 |
| AL04 | `feat/al-tools-deterministic-delivery` | A4.1, W5.0, W5.0a, W5.0b, W5.0c, W5.0d, W5.1, W5.2, W5.3, W5.4, W5.5, W5.6, A4.2, A4.3, A4.4, D4.1, D4.2, D4.3, D5.1, D5.2, D5.3, D5.4 | claimed | RuntimeEngine、ToolProtocol、ToolRegistry、Workspace tools、ChangeSet、PreviewTarget、deterministic runtime、DeliveryRecord、delivery adapters | 工具、deterministic runtime 和交付适配 |
| AL05 | `feat/al-provider-langgraph-context` | A4.5, A4.6, A4.7, A4.8, A4.8a, A4.8b, A4.8c, A4.8d, A4.9, A4.9a, A4.9e, A4.9b, A4.9c, A4.9d, A4.10, A4.11 | claimed | LangGraph runtime、Provider registry、PromptValidation、PromptRegistry、PromptRenderer、ContextEnvelope、Provider adapter、AgentDecision、StageAgentRuntime | Provider、LangGraph、上下文和 Stage Agent |
| AL06 | `feat/al-frontend-runtime-ui` | F3.1, F3.2, F3.3, F3.4, F3.5, F3.6, F3.7, H4.2, F4.1, F4.2, F4.3, F4.3a, F4.4, F5.1, F5.2a, F5.2b | claimed | frontend workspace store、SSE reducer、Feed、StageNode、Inspector、Composer、Approval、Tool Confirmation、Delivery UI | 前端运行工作台和交付展示 |
| QA | `test/al-regression-hardening` | V6.1, V6.2, V6.3, V6.4, V6.5, V6.6, V6.8, L6.1, L6.2, V6.7 | planned | backend API flow、OpenAPI、Playwright、frontend error states、config regression、log hardening、release checklist | integration 回归和发布候选验证 |

## 4. Shared Ownership

共享入口只能由 owner lane 修改。标记为 `current baseline` 的入口来自当前基线，不预设 active owner；后续如果 claim 需要修改这些入口，必须先由主协调会话明确分配 owner lane，否则停止当前 slice 并报告 owner conflict。

| Shared Entry | Owner | Consumers |
| --- | --- | --- |
| Provider、DeliveryChannel、ConfigurationPackage、PlatformRuntimeSettings API 与 service | current baseline | AL01, AL03, AL04, AL05, AL06 |
| Run 状态枚举转换、PipelineRun、StageRun、StageArtifact、GraphDefinition、EventStore | AL01 | AL02, AL03, AL04, AL05, AL06, QA |
| 高影响多库公开语义 / publication boundary，以及为 enforce 该边界而做的 startup workspace/timeline/SSE visibility filter | AL01 | AL02, AL03, QA |
| Projection payload、SSE payload、run/stage log query route、audit query route | AL02 | AL06, QA |
| RuntimeOrchestrationService、clarification、approval、tool confirmation、runtime control command semantics | AL03 | AL04, AL05, AL06, QA |
| ToolProtocol、ToolRegistry、WorkspaceManager、Workspace tools、ChangeSet、PreviewTarget、DeliveryRecord、delivery adapter | AL04 | AL03, AL05, AL06, QA |
| Prompt、Context、Provider adapter、LangGraph node/checkpoint、AgentDecision、StageAgentRuntime | AL05 | AL01, AL03, AL04, AL06, QA |
| frontend API client runtime-facing additions、workspace store、Feed/Inspector/Composer/Approval/Delivery components | AL06 | QA |
| OpenAPI/e2e/regression harness and release checklist | QA | all lanes |

`R3.2a` owner decision：AL01 被授权直接修改 `backend/app/services/projections/workspace.py`、`backend/app/services/projections/timeline.py`、`backend/app/api/routes/events.py`，但仅限于 enforce publication boundary 的 reader visibility filter。该例外不转移 AL02 对通用 projection payload、SSE payload、query route 和 projection contract 演进的 owner scope。

## 5. Dependency And Start Gates

Start gate 只允许开始实现或 mock-first；它不等于完成 gate。

| Gate | Rule |
| --- | --- |
| Baseline gate | 运行快照、交付快照、Provider adapter 和配置回归从当前基线读取 Provider、DeliveryChannel、ConfigurationPackage、PlatformRuntimeSettings 契约；需要修改这些共享入口时必须停止并报告 owner conflict。 |
| AL01 gate | AL01 可从当前基线开始 R3.1、E3.1、R3.5-R3.7 和 R3.2a 的纯领域、持久化与公开语义边界实现；R3.4a、R3.4b 的最终完成必须接入真实运行状态和配置契约；R3.2 的最终完成必须复用 R3.2a 的多库公开语义边界，不得把 reader visibility 缺口继续留在 R3.2 本身。 |
| AL02 gate | AL02 可基于 AL01 提供的事件 fixture 或冻结 projection contract 先行；最终完成必须读取真实 EventStore、StageArtifact 或 runtime model。Q3.4b 必须消费 H4.4b 提供的稳定 deny follow-up source，再暴露顶层 `tool_confirmation.deny_followup_action` / `deny_followup_summary`；若 H4.4b 未先提供该 source，AL02 必须停止并回报 owner dependency，而不是以 `alternative_path_summary` 或 run 终态猜测映射补齐契约。 |
| AL03 gate | AL03 可基于 AL01/AL02 的 stub 接口先行 A4.0、L4.1、H4.1、H4.3；审批命令、运行控制和 tool confirmation 的最终完成必须接入真实 run state 和 projection events；H4.4 的最终完成必须复用 R3.2a 的 publication boundary。H4.4b 只负责为 deny 路径固化 `continue_current_stage`、`run_failed`、`awaiting_run_control` 三类稳定后续处理语义来源，不直接修改 AL02 owner scope 的顶层 projection payload、SSE payload 或 query schema。 |
| AL04 gate | AL04 可立即开始 ToolProtocol、错误码、WorkspaceManager、纯工具和 fixture；deterministic runtime 与 delivery adapter 的最终完成必须接入 AL01 run truth、AL03 runtime boundary 和当前基线的 delivery settings。 |
| AL05 gate | AL05 可立即开始 PromptValidation、PromptRegistry、PromptRenderer、Context schema 和 provider registry；LangGraph 与 StageAgentRuntime 的最终完成必须接入 AL01、AL03、AL04。 |
| AL06 gate | AL06 可基于冻结 projection/event/mock payload 先行所有 runtime UI；最终完成必须切换到真实 API/SSE、真实 error contract 和真实 delivery/result payload。F4.3a 的最终完成必须读取 Q3.4b 暴露的顶层 `tool_confirmation.deny_followup_action` / `deny_followup_summary`，不得从 Inspector、run terminal status 或 `alternative_path_summary` 私有字段自行推断拒绝后的后续运行语义。 |
| QA gate | QA 可提前创建测试骨架、fixture 和 checklist；任何回归任务的 `done` 必须基于 integration 分支的真实实现验证。 |

## 6. Coordination Store And Checkpoint Snapshot

主协调会话独占写入共享 coordination store。Worker 只能只读校验已经被分配的 claim，不得自行从 queue 抢任务，不得写入 coordination store。

共享 store 通过以下命令定位和读取：

```powershell
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py store-path
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py list --json
uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py show --claim <claim-id> --json
```

下表只作为最近一次 coordination checkpoint snapshot 或审计摘录，不是 live source of truth。不要为了 claim、reported、implemented 或 mock_ready 的高频状态变化提交本文档；这些状态写入共享 coordination store。integration checkpoint、主线状态收敛或调度规则变更时，主协调会话可以更新本 snapshot。

| Claim | Task | Lane | Branch | Status | Coordination Base | Worker HEAD | Evidence | Blocker |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AL01-R3.1 | R3.1 | AL01 | `feat/al-run-core-events` | done | 5d44d4a | 222396d | `docs/plans/acceleration/reports/AL01-R3.1.md` | - |
| AL01-E3.1 | E3.1 | AL01 | `feat/al-run-core-events` | done | 4ea6251 | 38defe9 | `docs/plans/acceleration/reports/AL01-E3.1.md` | - |
| AL01-R3.4 | R3.4 | AL01 | `feat/al-run-core-events` | done | 67f5290 | d1fcb14 | `docs/plans/acceleration/reports/AL01-R3.4.md` | - |
| AL01-R3.4a | R3.4a | AL01 | `feat/al-run-core-events` | done | 74578b0 | ec0b023 | `docs/plans/acceleration/reports/AL01-R3.4a.md` | - |
| AL01-R3.2a | R3.2a | AL01 | `feat/al-run-core-events` | done | 60cc934 | 3888945 | `docs/plans/acceleration/reports/AL01-R3.2a.md` | - |
| AL02-Q3.1 | Q3.1 | AL02 | `feat/al-projections-streams` | done | 67f5290 | d07f094 | `docs/plans/acceleration/reports/AL02-Q3.1.md` | - |
| AL02-Q3.2 | Q3.2 | AL02 | `feat/al-projections-streams` | done | 74578b0 | 827d4dd | `docs/plans/acceleration/reports/AL02-Q3.2.md` | - |
| AL02-Q3.4b | Q3.4b | AL02 | `feat/al-projections-streams` | done | 5376b2e | 3c1ec4f | `docs/plans/acceleration/reports/AL02-Q3.4b.md` | - |
| AL03-A4.0 | A4.0 | AL03 | `feat/al-runtime-human-loop` | done | 5d44d4a | ebfcb61 | `docs/plans/acceleration/reports/AL03-A4.0.md` | - |
| AL03-L4.1 | L4.1 | AL03 | `feat/al-runtime-human-loop` | done | 4ea6251 | c6290f5 | `docs/plans/acceleration/reports/AL03-L4.1.md` | - |
| AL03-H4.1 | H4.1 | AL03 | `feat/al-runtime-human-loop` | done | 67f5290 | 8040668 | `docs/plans/acceleration/reports/AL03-H4.1.md` | - |
| AL03-H4.3 | H4.3 | AL03 | `feat/al-runtime-human-loop` | done | 74578b0 | 3cd8bb7 | `docs/plans/acceleration/reports/AL03-H4.3.md` | - |
| AL03-H4.4b | H4.4b | AL03 | `feat/al-runtime-human-loop` | done | 3c5f689 | 76ea445 | `docs/plans/acceleration/reports/AL03-H4.4b.md` | - |
| AL03-H4.5 | H4.5 | AL03 | `feat/al-runtime-human-loop` | done | 5707ce3 | 94b1376 | `docs/plans/acceleration/reports/AL03-H4.5.md` | - |
| AL04-A4.1 | A4.1 | AL04 | `feat/al-tools-deterministic-delivery` | done | cf4828c | 3cba4f8 | `docs/plans/acceleration/reports/AL04-A4.1.md` | - |
| AL04-W5.0 | W5.0 | AL04 | `feat/al-tools-deterministic-delivery` | done | 67f5290 | 2b78be5 | `docs/plans/acceleration/reports/AL04-W5.0.md` | - |
| AL04-W5.0a | W5.0a | AL04 | `feat/al-tools-deterministic-delivery` | done | 74578b0 | e2c777c | `docs/plans/acceleration/reports/AL04-W5.0a.md` | - |
| AL04-W5.0b | W5.0b | AL04 | `feat/al-tools-deterministic-delivery` | done | 7aeff59 | 41f80c8 | `docs/plans/acceleration/reports/AL04-W5.0b.md` | - |
| AL04-W5.1 | W5.1 | AL04 | `feat/al-tools-deterministic-delivery` | done | 5376b2e | fdaf066 | `docs/plans/acceleration/reports/AL04-W5.1.md` | - |
| AL04-W5.2 | W5.2 | AL04 | `feat/al-tools-deterministic-delivery` | done | 161432a | 723c3f0 | `docs/plans/acceleration/reports/AL04-W5.2.md` | - |
| AL04-W5.3 | W5.3 | AL04 | `feat/al-tools-deterministic-delivery` | done | 637f51c | c5f7ff6 | `docs/plans/acceleration/reports/AL04-W5.3.md` | - |
| AL05-A4.8 | A4.8 | AL05 | `feat/al-provider-langgraph-context` | done | 5d44d4a | aee52fb | `docs/plans/acceleration/reports/AL05-A4.8.md` | - |
| AL05-A4.8a | A4.8a | AL05 | `feat/al-provider-langgraph-context` | done | 874161e | 8d7a5e8 | `docs/plans/acceleration/reports/AL05-A4.8a.md` | - |
| AL05-A4.8b | A4.8b | AL05 | `feat/al-provider-langgraph-context` | done | dd28f74 | 1e9ac9c | `docs/plans/acceleration/reports/AL05-A4.8b.md` | - |
| AL05-A4.8c | A4.8c | AL05 | `feat/al-provider-langgraph-context` | done | 59529e1 | c32dfc4 | `docs/plans/acceleration/reports/AL05-A4.8c.md` | - |
| AL06-F3.1 | F3.1 | AL06 | `feat/al-frontend-runtime-ui` | done | 5d44d4a | 564624a | `docs/plans/acceleration/reports/AL06-F3.1.md` | - |
| AL06-F3.2 | F3.2 | AL06 | `feat/al-frontend-runtime-ui` | done | 4ea6251 | c5f11d1 | `docs/plans/acceleration/reports/AL06-F3.2.md` | - |
| AL06-F3.3 | F3.3 | AL06 | `feat/al-frontend-runtime-ui` | done | ab9e0d3 | 47946f8 | `docs/plans/acceleration/reports/AL06-F3.3.md` | - |
| AL06-F3.4 | F3.4 | AL06 | `feat/al-frontend-runtime-ui` | done | 67f5290 | f694762 | `docs/plans/acceleration/reports/AL06-F3.4.md` | - |
| AL06-F3.5 | F3.5 | AL06 | `feat/al-frontend-runtime-ui` | done | 74578b0 | 4042594 | `docs/plans/acceleration/reports/AL06-F3.5.md` | - |
| AL06-F3.6 | F3.6 | AL06 | `feat/al-frontend-runtime-ui` | done | 7aeff59 | 59b8280 | `docs/plans/acceleration/reports/AL06-F3.6.md` | - |
| AL03-D4.0 | D4.0 | AL03 | `feat/al-runtime-human-loop` | done | 7aeff59 | 4c58b8a | `docs/plans/acceleration/reports/AL03-D4.0.md` | - |
| AL02-Q3.3 | Q3.3 | AL02 | `feat/al-projections-streams` | done | 7aeff59 | d9fb331 | `docs/plans/acceleration/reports/AL02-Q3.3.md` | - |
| AL01-R3.4b | R3.4b | AL01 | `feat/al-run-core-events` | done | 7aeff59 | 6734a07 | `docs/plans/acceleration/reports/AL01-R3.4b.md` | - |
| AL01-R3.5 | R3.5 | AL01 | `feat/al-run-core-events` | done | be201ab | 77a037c | `docs/plans/acceleration/reports/AL01-R3.5.md` | - |
| AL03-H4.4 | H4.4 | AL03 | `feat/al-runtime-human-loop` | done | 7819aad | c86b54e | `docs/plans/acceleration/reports/AL03-H4.4.md` | - |
| AL04-W5.0c | W5.0c | AL04 | `feat/al-tools-deterministic-delivery` | done | 7819aad | 72aa856 | `docs/plans/acceleration/reports/AL04-W5.0c.md` | - |
| AL02-Q3.4 | Q3.4 | AL02 | `feat/al-projections-streams` | done | 7819aad | fb45ffb | `docs/plans/acceleration/reports/AL02-Q3.4.md` | - |
| AL06-F3.7 | F3.7 | AL06 | `feat/al-frontend-runtime-ui` | done | 7819aad | 3213b09 | `docs/plans/acceleration/reports/AL06-F3.7.md` | - |
| AL02-Q3.4a | Q3.4a | AL02 | `feat/al-projections-streams` | done | be201ab | 897a7c5 | `docs/plans/acceleration/reports/AL02-Q3.4a.md` | - |
| AL06-H4.2 | H4.2 | AL06 | `feat/al-frontend-runtime-ui` | done | be201ab | bab7b42 | `docs/plans/acceleration/reports/AL06-H4.2.md` | - |
| AL01-R3.6 | R3.6 | AL01 | `feat/al-run-core-events` | done | 969a43c | c5edc12 | `docs/plans/acceleration/reports/AL01-R3.6.md` | - |
| AL03-H4.4a | H4.4a | AL03 | `feat/al-runtime-human-loop` | done | 969a43c | 96ceb48 | `docs/plans/acceleration/reports/AL03-H4.4a.md` | - |
| AL02-E3.2 | E3.2 | AL02 | `feat/al-projections-streams` | done | 017ae5d | 6611958 | `docs/plans/acceleration/reports/AL02-E3.2.md` | - |
| AL02-L3.1 | L3.1 | AL02 | `feat/al-projections-streams` | done | 147563b | 01c39fc | `docs/plans/acceleration/reports/AL02-L3.1.md` | - |
| AL02-L4.2 | L4.2 | AL02 | `feat/al-projections-streams` | done | 2dc4356 | 4c780ed | `docs/plans/acceleration/reports/AL02-L4.2.md` | - |
| AL06-F4.1 | F4.1 | AL06 | `feat/al-frontend-runtime-ui` | done | 017ae5d | e5f3e86 | `docs/plans/acceleration/reports/AL06-F4.1.md` | - |
| AL06-F4.2 | F4.2 | AL06 | `feat/al-frontend-runtime-ui` | done | 147563b | 23636ef | `docs/plans/acceleration/reports/AL06-F4.2.md` | - |
| AL06-F4.3a | F4.3a | AL06 | `feat/al-frontend-runtime-ui` | done | 90a2437 | 5e73325 | `docs/plans/acceleration/reports/AL06-F4.3a.md` | - |
| AL06-F4.4 | F4.4 | AL06 | `feat/al-frontend-runtime-ui` | done | 5cc45f2 | d58895c | `docs/plans/acceleration/reports/AL06-F4.4.md` | - |
| AL06-F5.1 | F5.1 | AL06 | `feat/al-frontend-runtime-ui` | integrated | 47c3899 | 060cda4 | `docs/plans/acceleration/reports/AL06-F5.1.md` | Mock-first frontend slice integrated against frozen projection and mock payload shape; final completion still depends on a later checkpoint proving real backend `code_generation` / `test_generation_execution` payloads and inspector detail semantics. |
| AL06-F5.2a | F5.2a | AL06 | `feat/al-frontend-runtime-ui` | integrated | 2451ebd | 48264fc | `docs/plans/acceleration/reports/AL06-F5.2a.md` | Mock-first demo_delivery result UI integrated against frozen feed and Inspector mock payloads; final completion still depends on real backend `delivery_result` / `DeliveryResultDetailProjection` payload verification. |
| AL01-R3.7 | R3.7 | AL01 | `feat/al-run-core-events` | done | 5707ce3 | 3313a4a | `docs/plans/acceleration/reports/AL01-R3.7.md` | - |
| AL01-C2.9a | C2.9a | AL01 | `feat/al-run-core-events` | done | 874161e | d06be5c | `docs/plans/acceleration/reports/AL01-C2.9a.md` | - |
| AL01-C2.9b | C2.9b | AL01 | `feat/al-run-core-events` | done | f03d52b | eeb54a3 | `docs/plans/acceleration/reports/AL01-C2.9b.md` | - |
| AL04-W5.4 | W5.4 | AL04 | `feat/al-tools-deterministic-delivery` | done | 15a92a3 | 6798ce9 | `docs/plans/acceleration/reports/AL04-W5.4.md` | - |
| AL04-W5.5 | W5.5 | AL04 | `feat/al-tools-deterministic-delivery` | done | 2451ebd | 14f5b52 | `docs/plans/acceleration/reports/AL04-W5.5.md` | Pure domain ChangeSet / ContextReference boundary integrated with future feature-two reference kinds reserved but no feature-two behavior enabled. |
| AL04-W5.6 | W5.6 | AL04 | `feat/al-tools-deterministic-delivery` | done | ea1aa8d | 7a8911a | `docs/plans/acceleration/reports/AL04-W5.6.md` | PreviewTarget object and read-only query API integrated; focused, impacted API, and full backend verification passed. |
| AL05-A4.8d | A4.8d | AL05 | `feat/al-provider-langgraph-context` | done | 62535c5 | a9d28f3 | `docs/plans/acceleration/reports/AL05-A4.8d.md` | Integrated with candidate-a context provenance and trace hardening in `backend/app/context/schemas.py`. |
| AL05-A4.9 | A4.9 | AL05 | `feat/al-provider-langgraph-context` | done | 2451ebd | aca5a8c | `docs/plans/acceleration/reports/AL05-A4.9.md` | LangChain provider adapter integrated with normalized tool-call candidates, `raw_response_ref`, and safe trace metadata boundaries. |
| AL05-A4.9a | A4.9a | AL05 | `feat/al-provider-langgraph-context` | done | ea1aa8d | d349599 | `docs/plans/acceleration/reports/AL05-A4.9a.md` | ContextEnvelope Builder and ContextManifest recording integrated through existing `ArtifactStore.append_process_record(process_key="context_manifest", ...)` shared entry. |
| AL05-A4.9e | A4.9e | AL05 | `feat/al-provider-langgraph-context` | done | 64a96a2 | 0ec0305 | `docs/plans/acceleration/reports/AL05-A4.9e.md` | Provider retry, frozen exponential backoff, circuit breaker state, and retry/circuit trace records integrated through existing `ArtifactStore.append_process_record(...)` persistence boundary; integration verification passed 87 provider, fixture, and ArtifactStore tests. |
| AL05-A4.9b | A4.9b | AL05 | `feat/al-provider-langgraph-context` | done | c8f6776 | c37d0fd | `docs/plans/acceleration/reports/AL05-A4.9b.md` | Context size guard, observation budgeting, sliding-window indexes, compression prompt rendering, and compressed context process records integrated through existing `ArtifactStore.append_process_record(...)`; focused, impacted, and full backend verification passed on integration branch. |
| AL06-F5.2b | F5.2b | AL06 | `feat/al-frontend-runtime-ui` | integrated | d424115 | 4071e82 | `docs/plans/acceleration/reports/AL06-F5.2b.md` | git_auto_delivery result UI integrated against the current frontend feed contract; final completion still depends on real backend `git_auto_delivery` / `delivery_result` payload verification. |
| AL04-A4.2 | A4.2 | AL04 | `feat/al-tools-deterministic-delivery` | done | 32d5a87 | 7f61772 | `docs/plans/acceleration/reports/AL04-A4.2.md` | Deterministic six-stage runtime integrated with StageRun, StageArtifact, domain events, checkpoints, and runtime log refs; focused, impacted, and full backend verification passed on integration branch. |
| AL04-A4.3 | A4.3 | AL04 | `feat/al-tools-deterministic-delivery` | done | 87a0ded | 370123d | `docs/plans/acceleration/reports/AL04-A4.3.md` | Deterministic clarification, approval, code-review approval, and tool-confirmation interrupt paths integrated; focused runtime / contract, AL03 service regression, and full backend verification passed on integration branch. |
| AL04-A4.4 | A4.4 | AL04 | `feat/al-tools-deterministic-delivery` | done | 73a54ad | 74f7d38 | `docs/plans/acceleration/reports/AL04-A4.4.md` | Deterministic completed, failed, terminated, and direct terminate terminal control integrated; focused terminal, impacted runtime / contract, H4.6 service regression, and full backend verification passed on integration branch. |
| AL04-D4.1 | D4.1 | AL04 | `feat/al-tools-deterministic-delivery` | done | d2ac1ca | 9ccf071 | `docs/plans/acceleration/reports/AL04-D4.1.md` | Delivery adapter contract, DeliveryRecord service, adapter registry validation, run-log evidence, and audit rollback boundaries integrated; focused delivery, impacted snapshot/runtime, runtime regression, and full backend verification passed on integration branch. |
| AL04-D5.3 | D5.3 | AL04 | `feat/al-tools-deterministic-delivery` | done | db6f58d | 81e8e95 | `docs/plans/acceleration/reports/AL04-D5.3.md` | push_branch and create_code_review_request tools integrated with controlled Git push, mock PR/MR client support, audit fail-closed checks, redacted remote errors, and focused / impacted integration verification. |
| AL04-D5.4 | D5.4 | AL04 | `feat/al-tools-deterministic-delivery` | done | 7fff2b7 | bbab5d9 | `docs/plans/acceleration/reports/AL04-D5.4.md` | git_auto_delivery adapter orchestration integrated through ToolRegistry execution over frozen snapshot readiness, controlled Git delivery tools, confirmation safety, audit refs, and fixture/mock remote verification; D5 delivery and impacted runtime verification passed on integration branch. |
| AL05-A4.9d | A4.9d | AL05 | `feat/al-provider-langgraph-context` | done | db6f58d | 2707fb2 | `docs/plans/acceleration/reports/AL05-A4.9d.md` | StageAgentRuntime loop integrated with LangGraph stage node handling, ContextEnvelope build, Provider retry traces, ToolRegistry execution gate, structured repair, recovery checkpoints, and focused integration verification. |
| AL05-A4.10 | A4.10 | AL05 | `feat/al-provider-langgraph-context` | done | 7fff2b7 | 9986192 | `docs/plans/acceleration/reports/AL05-A4.10.md` | Automatic regression policy integrated with frozen retry-limit resolution, Code Review retry decisions, sanitized logging, and focused IC3 verification covering auto regression, graph compiler, and LangGraph runtime tests. |

当前基线不预置 live claim。主协调会话在认领 ready task 时写入共享 coordination store，并记录当时的 Coordination Base。

## 7. Lane Queues

Lane queue 记录任务归属和 lane 内执行顺序。任务资格仍必须由 platform plan、split plan 和 start gate 共同确认。

| Lane | Queue |
| --- | --- |
| AL01 | R3.1 -> E3.1 -> R3.4 -> R3.4a -> R3.4b -> R3.5 -> R3.6 -> R3.7 -> R3.2a -> R3.2 -> R3.3 -> C2.9a -> C2.9b |
| AL02 | Q3.1 -> Q3.2 -> Q3.3 -> Q3.4 -> Q3.4a -> E3.2 -> L3.1 -> L4.2 -> Q3.4b |
| AL03 | A4.0 -> L4.1 -> H4.1 -> H4.3 -> D4.0 -> H4.4 -> H4.4a -> H4.4b -> H4.5 -> H4.6 -> H4.7 |
| AL04 | A4.1 -> W5.0 -> W5.0a -> W5.0b -> W5.0c -> W5.0d -> W5.1 -> W5.2 -> W5.3 -> W5.4 -> W5.5 -> W5.6 -> A4.2 -> A4.3 -> A4.4 -> D4.1 -> D4.2 -> D4.3 -> D5.1 -> D5.2 -> D5.3 -> D5.4 |
| AL05 | A4.8 -> A4.8a -> A4.8c -> A4.8b -> A4.8d -> A4.9 -> A4.9a -> A4.9e -> A4.9b -> A4.5 -> A4.6 -> A4.7 -> A4.9c -> A4.9d -> A4.10 -> A4.11 |
| AL06 | F3.1 -> F3.2 -> F3.3 -> F3.4 -> F3.5 -> F3.6 -> F3.7 -> H4.2 -> F4.1 -> F4.2 -> F4.3 -> F4.3a -> F4.4 -> F5.1 -> F5.2a -> F5.2b |
| QA | V6.1 -> V6.4 -> V6.5 -> V6.6 -> V6.8 -> L6.1 -> L6.2 -> V6.2 -> V6.3 -> V6.7 |

## 8. Worker Evidence

Worker 分支完成 claim 后写入本地证据，不直接更新全局完成状态。未提交的本地证据只能支持 `reported` 或 `blocked` 的本地进度收敛；它不能作为 integration checkpoint 的合入输入。

每个 claim 必须提供：

- `docs/plans/implementation/<task-id>-<task-name>.md` 中的实施计划、TDD 步骤和验证记录。
- 代码、测试和必要 fixture。
- `docs/plans/acceleration/reports/<claim-id>.md`，记录 claim、lane、task、Coordination Base、变更文件、TDD red/green、验证命令、mock-first 状态、owner conflict、commit readiness 和剩余 gate。

Worker evidence report 只声明本地结果：`reported` 或 `blocked`，并写明提交后预期由主协调会话收敛为 `implemented` 还是 `mock_ready`。`implemented` 和 `mock_ready` 是主协调会话在确认 worker checkpoint commit 后写入共享 coordination store 的状态。`function-one-acceleration-execution-plan.md`、`function-one-platform-plan.md` 和 split plan 的最终状态只由主协调会话在 integration checkpoint 后更新。

主协调会话通过以下方式读取 worker evidence 并更新共享 coordination store：

- Local Progress Ingest：从已存在的 worker worktree 读取 `docs/plans/acceleration/reports/<claim-id>.md`，同时读取 `git -C <worktree> status --short`、`git -C <worktree> diff --stat` 和 `git -C <worktree> rev-parse --short HEAD`。如果报告、claim、lane、task 和 Coordination Base 一致，共享 coordination store 最多更新为 `reported` 或 `blocked`。本地 dirty worktree 不得更新为 `implemented` 或 `mock_ready`。
- Committed Progress Ingest：使用 `git show <branch>:docs/plans/acceleration/reports/<claim-id>.md` 读取报告，并使用 `git rev-parse --short <branch>` 记录 Worker HEAD。只有当 evidence report、implementation plan、代码和测试都包含在该 branch commit 中，共享 coordination store 才能更新为 `implemented` 或 `mock_ready`。
- 如果报告不存在、分支不可读，或报告中的 `Claim` / `Lane` / `Task` / `Coordination Base` 与共享 coordination store 不一致，Progress Ingest 停止。
- Progress Ingest 只更新共享 coordination store 中的状态、Worker HEAD 和 blocker 信息；不合并代码，不更新 platform plan 或 split plan，不为高频 ingest 提交本文档。

## 9. Integration Checkpoints

integration checkpoint 由主协调会话执行。AL 分支默认合入 `integration/function-one-acceleration`，不得直接进入 `main`。

checkpoint 前必须确认待集成 lane 的 Coordination Base、Worker HEAD、diff 和 evidence report 一致。
`reported` claim、未提交 worktree diff 或缺少 checkpoint commit 的 worker 成果不得进入 integration checkpoint。

| Checkpoint | Scope | Required Verification |
| --- | --- | --- |
| IC1 | AL01 + AL02 最小 run/event/projection/SSE skeleton | focused backend domain/API/projection tests、SSE tests |
| IC2 | AL03 + AL04 deterministic runtime 和 human-loop skeleton | runtime command tests、tool registry tests、demo delivery tests |
| IC3 | AL05 provider/langgraph/context 接入 | provider/context/langgraph focused tests、LangChain/LangGraph API docs check when API usage is unclear |
| IC4 | AL06 前端真实 API/SSE 切换 | `npm --prefix frontend test`, `npm --prefix frontend build` |
| IC5 | QA 回归和发布候选 | backend regression、OpenAPI、Playwright、frontend error regression、log audit regression |

每个 checkpoint 通过后，主协调会话统一执行以下状态收敛：

- 将已验证 claim 从 `implemented` 或 `mock_ready` 更新为 `integrated` 或 `done`。
- 将满足验收标准的 platform plan 与 split plan 任务标记为 `[x]`。
- 将只完成 mock-first 或部分接入的任务保持为 `[/]`，并记录 merge gate。
- 在同一次 checkpoint closeout 中执行 `uv run python .codex/skills/acceleration-workflow/scripts/coordination_store.py post-checkpoint --apply`，完成 ingest、空闲 branch 同步和下一批 claim 自动解封。
- 输出 closeout 后的六路协调摘要，并为下一批 ready claim 生成 worker prompt。

## 10. Merge Gates

| Completion Type | Gate |
| --- | --- |
| `reported` | Worker 本地 worktree 有 evidence report、implementation plan、代码 / 测试 diff 和验证记录；只允许本地进度协调，不允许 integration。 |
| `implemented` | Worker checkpoint commit 完整包含代码、测试、implementation plan 和 evidence report，focused tests 通过，未修改其它 lane owner 共享入口。 |
| `mock_ready` | Worker checkpoint commit 完整包含 mock/fixture 来源、验证记录和 evidence report；真实 owner 未完成或未进入 integration，任务不得标 `[x]`。 |
| `integrated` | Claim 已合入 integration 分支，相关 focused tests 和 impacted tests 通过。 |
| `done` | integration checkpoint 通过，platform plan、split plan、实现代码、测试和验收标准一致。 |
| `main-ready` | integration 分支通过本轮主线验证，剩余问题有明确后续 claim，且不会破坏已完成用户流程。 |

## 11. Stop Conditions

遇到以下情况必须停止当前 claim，并向主协调会话报告：

- 当前分支不匹配本文件 Lane Registry 中的 branch。
- 子任务不在当前 lane coverage 或 lane queue 中。
- 子任务依赖未满足，且 start gate 未允许 mock-first。
- 需要修改其它 lane owner 的共享入口。
- platform plan 与 split plan 状态冲突。
- implementation plan 放宽或改写已评审任务语义。
- 当前 specs、split plan 或现有实现之间出现来源追溯冲突。
- claim 只有本地 `reported` evidence、未提交 diff 或缺少包含 evidence report 的 checkpoint commit，却被要求进入 integration checkpoint。
- 验证失败且 focused 调试后仍不能收敛。
- Worker 需要 Git 写操作、依赖安装、lock/manifest 变更、迁移执行或环境文件变更但没有用户批准。

## 12. Worker Prompt Template

```text
你现在位于 <worktree-path>，当前分支必须是 <branch-name>。

使用 $slice-workflow 执行 acceleration claim：

Claim: <claim-id>
Lane: <lane-id>
Task: <task-id>
Coordination Base: <current-baseline-commit>
Worker HEAD: <由主协调会话在 ingest 时填写；worker 不在 evidence report 中声明权威 Worker HEAD>
Evidence report: docs/plans/acceleration/reports/<claim-id>.md

只在该 lane owner scope 和该 task slice 范围内工作。不要修改其它 lane owner 的共享入口。不要更新 function-one-acceleration-execution-plan.md、function-one-platform-plan.md 或 split plan 的最终完成状态；这些由主协调会话在 integration checkpoint 后统一更新。

必须写或更新 implementation plan，按 TDD 执行，运行 claim 范围验证，并在 evidence report 中记录 red/green、验证命令、关键输出、mock-first 状态、commit readiness 和阻塞项。

完成后停止并报告 worktree path、branch、dirty status、diff stat、evidence report path、验证结果和本地结果 `reported` 或 `blocked`。如果验证通过且适合提交，准备 commit 批准请求，并说明提交后预期由主协调会话 ingest 为 `implemented` 或 `mock_ready`。获得明确批准后才能提交该 lane 分支。不要自行 claim 下一个任务，不要合并 integration，不要直接向 main 提交。
```
