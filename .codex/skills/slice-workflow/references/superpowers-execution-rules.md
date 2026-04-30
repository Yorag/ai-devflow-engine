# Superpowers 执行规则参考

当已选切片需要 platform plan 中的 Superpowers 执行规则细节、前端呈现质量检查、API/OpenAPI 路由检查，或日志 / 审计要求时，加载本文件。停止规则、Git 规则、TDD 规则和验证规则仍以 `SKILL.md` 为准。

## 独立计划或独立 batch

以下边界需要单独的 implementation plan 或独立执行 batch：

- 数据模型和枚举的第一轮实现。
- OpenAPI 和前端客户端生成策略的第一轮实现。
- Run 生命周期状态机的第一轮实现。
- Narrative Feed 顶层条目语义的第一轮实现。
- DeliveryChannel 和最终审批阻塞语义的第一轮实现。
- `PlatformRuntimeSettings` 和 run snapshot 语义的第一轮实现。
- `PromptAsset` Schema、内置提示词资产目录和 PromptRenderer 消费边界的第一轮实现。
- LangGraph runtime 和 `deterministic test runtime` 接口边界的第一轮实现。
- 工具确认和人工审批边界的第一轮实现。
- 工具风险分类和执行 gate 的第一轮实现。

如果已选切片看起来跨越上述边界，而当前任务没有隔离该边界，使用 `SKILL.md` 中的 Source Trace Conflict Gate。

## Writing-Plans 覆盖规则

使用 `superpowers:writing-plans` 时，在通用技能模板之上应用本仓库执行规则：

- 将计划保存到 `docs/plans/implementation/<task-id>-<task-name>.md`，不要保存到 `docs/superpowers/plans/`。
- 计划头部必须把 `superpowers:executing-plans` 标为执行 skill。不要推荐 `superpowers:subagent-driven-development`。
- 不要提供通用的“子代理驱动或内联执行”执行选择；本仓库使用主 agent 内联执行，并配合 `superpowers:executing-plans`。
- 不要包含 commit 步骤、commit 命令、Git worktree 设置、分支收尾、PR 创建、merge、tag 或分支清理步骤。
- 将任何通用的“频繁 commit”指令替换为已验证检查点和 commit 批准请求。
- 如果 implementation plan 需要最终 Git 步骤，写成“在最新验证后，使用 `git-delivery-workflow` 准备 commit 批准请求”；不要写 `git add` 或 `git commit` 命令。
- 保留 writing-plans 对精确文件路径、具体测试代码、具体实现代码、精确命令、预期失败输出、预期通过输出和自评审的要求。

## Implementation Plan 清单

每个 implementation plan 必须包含：

- 文件列表，列出精确的创建、修改和测试路径。
- TDD red-green 步骤。
- 具体失败测试代码。
- 具体实现代码。
- 精确运行命令。
- 预期失败输出和预期通过输出。
- 完成验证清单。

## API 和 OpenAPI 检查

对于 `backend/app/api/routes/*` 变更，implementation plan 必须包含本地 API 测试和 `/api/openapi.json` 断言，覆盖：

- Path。
- Method。
- Request schema。
- Response schema。
- 主要错误响应。

## Log & Audit Integration

对于用户命令接口、run 生命周期变更、runtime 节点、模型调用、工具调用、workspace 写入、`bash`、Git 交付、远程交付、配置变更，或安全敏感失败，implementation plan 必须包含 `Log & Audit Integration`：

- Runtime log category、audit action、关联对象和失败结果。
- `request_id`、`trace_id`、`correlation_id`、`span_id` 和 `parent_span_id` 的生成或继承。
- 敏感字段脱敏、阻断、摘要和载荷大小限制。
- 日志写入、审计写入或 `log.db` 索引失败时的行为。
- 测试证明日志不会替代领域对象、领域事件、Narrative Feed、Inspector 或产品状态事实。

## Frontend Design Gate

以下前端质量门切片使用 `impeccable`：

- `F2.3-F2.6`
- `F3.3-F3.7`
- `F4.1-F4.4`
- `F4.3a`
- `F5.1-F5.2b`
- `H4.2`
- `F0.1`
- `V6.2`, `V6.3`, `V6.6`, `V6.7`, `V6.8`

纯 API 客户端、mock fixture 或状态合并切片，只有在引入可见 UI 时才使用 `impeccable` skill。

适用前端展示切片的 implementation plan 必须包含 `Frontend Design Gate`：

- 基调来源和继承的项目基调。
- 没有参考时的默认基调：安静、专业、高信息密度的 workspace UI。
- 参考边界：采用什么、不复制什么。
- 需要重新确认的条件。
- 实现前的信息层级、布局、状态、交互路径和响应式策略。
- 实现后的可访问性、响应式、溢出、对比度、焦点和视觉反模式评审。
- 交付前对空态、加载态、错误态、禁用态、长文本、历史记录和边界状态的加固。
- 已报告发现、已处理项、剩余风险和验证证据。

主 agent 必须在 `F0.1` 或第一个可见前端切片前建立或继承项目基调。如果用户没有提供参考，记录默认 workspace 基调并继续；不要因为缺少样式输入阻塞实现。
