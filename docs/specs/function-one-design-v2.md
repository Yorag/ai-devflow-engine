# 功能一需求分析 V2

## 1. 文档目标

本文档用于定义 `AI 驱动的需求交付流程引擎` 的 `功能一` 正式需求边界，作为后续规格设计、接口设计、实现规划和项目交付的统一依据。

本文档聚焦：
- 功能一完整闭环的产品与系统需求
- 对赛题 `Must-have` 的逐项覆盖
- 在 `Must-have` 基础上补充流程质量目标与增强方向
- 为功能二预留后端领域与 API 扩展点

本文档不展开：
- 功能二的浏览器注入、圈选交互、悬浮对话框实现
- 长期产品化运营能力，如权限系统、多租户、计费、组织管理

## 2. 赛题理解与问题定义

赛题的最低要求是完成从需求输入到代码交付的端到端链路，但 `Must-have` 只是最低完成线，不代表一个有说服力的产品方案已经成立。

本项目真正的难点不在于把若干步骤串起来，而在于解决研发流程中的信息失真问题：
- 需求理解是否正确
- 方案设计是否合理
- 代码变更是否安全
- 测试覆盖是否充分

传统研发流程中，每个环节依赖不同角色、不同工具，信息在阶段之间反复丢失和变形。一个合格的 `AI DevFlow Engine` 不能只证明“链路能跑通”，还必须降低这种失真，让前一阶段的意图、约束、结论和风险可以被后续阶段可靠继承、检查和纠偏。

因此，本项目第一阶段的核心不只是 `自动生成代码`，而是构建一个 `以流程驱动为核心、以阶段产物为载体、以 Agent 编排为主角、以人工检查点为纠偏机制` 的交付引擎。

## 3. 产品定位

本项目第一阶段定位为：

`一个用于需求到代码交付闭环的 AI 驱动流程引擎原型平台`

其核心价值不是“辅助写代码”，而是让 AI 主导从需求输入到代码交付的完整研发流程，并在关键节点保留人类审批。

平台需要体现三件事：
- `流程可编排`：研发过程不是一次对话，而是一条可定义、可运行、可回退的 Pipeline
- `Agent 可协作`：不同阶段由不同角色的 Agent 执行，输入输出明确
- `交付可验证`：最终结果是可运行代码变更、测试结果、评审结论和交付记录，而不是抽象描述

## 4. 版本目标

本阶段目标不是做一个大而全的 AI 开发平台，而是完成一个可运行、可验证、可扩展的 `功能一 MVP`。

版本目标如下：
- 支持用户输入自然语言需求，并触发一次完整 Pipeline 运行
- 覆盖从需求分析到交付集成的核心阶段
- 具备三个 Human-in-the-Loop 检查点：需求澄清确认、方案设计审批、代码评审确认
- 支持对代码仓库进行真实上下文感知、代码修改、测试执行与交付输出
- 支持平台自身仓库作为默认演示对象，同时架构允许切换为外部本地仓库
- 通过基础控制台与 REST API 展示运行状态、阶段产物与审批操作
- 为功能二预留 `变更、上下文、预览、交付` 等后端能力接口

## 5. 非目标

以下内容不属于功能一第一阶段必须交付范围：
- 浏览器扩展或注入脚本
- 页面元素圈选与 DOM 到源码映射
- 悬浮对话框式页面改动交互
- 完整的多 Agent 协商系统
- 重型消息中间件和复杂分布式调度
- 企业级权限、多租户、审计与配额系统
- 以语义索引为前置依赖的复杂代码智能检索体系

## 6. 目标用户与使用场景

本阶段主要面向 `需求驱动交付场景`，兼顾技术型使用者。

核心用户包括：
- `观察者/管理者`：关注流程是否完整、Agent 编排是否合理、结果是否可验证
- `操作者`：负责输入需求、查看运行状态、执行审批、确认交付
- `平台开发者`：使用平台对自身仓库或外部仓库发起需求交付任务

核心场景包括：
- `预设演示场景`：提前准备一个需求，稳定完成端到端 Pipeline 演示
- `临时需求场景`：给定一个小功能或小改动需求，平台完成分析、生成、测试、评审和交付
- `平台自举场景`：目标仓库为平台自身，展示“用自己的平台给自己加功能”

## 7. 核心设计原则

本版本遵循以下原则：
- `流程优先`：先把流程引擎做对，再谈更复杂的交互层
- `事件驱动`：系统核心以状态机和领域事件驱动阶段流转
- `产物显式化`：每个阶段必须产生结构化产物，不能只保留隐式文本
- `人机协同`：AI 负责执行，人类在关键节点审批与兜底
- `API First`：所有核心能力通过 REST API 暴露，控制台只是 API 消费者
- `扩展前置`：功能二暂不实现，但要保证后端能力模型可复用
- `质量优先于跑通`：不仅要求流程能走完，还要求关键阶段能保留上下文、暴露风险并支持纠偏
- `工具统一抽象`：工作区能力通过统一 Tool 接口暴露，而不是零散函数拼装
- `能力按价值引入`：多 Agent、自动回归、索引等增强能力必须服务于核心瓶颈，不能为了展示而引入

## 8. 功能范围

功能一第一阶段必须覆盖以下主流程：

`需求输入 -> 需求分析 -> 方案设计 -> 代码生成 -> 测试生成/执行 -> 代码评审 -> 交付集成`

每个阶段需具备：
- 明确输入
- 明确 Agent 角色
- 明确输出产物
- 明确状态
- 明确失败与回退路径

标准阶段如下：

1. `Requirement Analysis`
输入自然语言需求，输出结构化需求、验收标准、歧义点列表和待确认事项。

2. `Solution Design`
输入结构化需求和代码库上下文，输出技术方案、影响范围、文件变更清单和关键设计决策。

3. `Code Generation`
输入技术方案和仓库上下文，输出代码变更集与变更摘要。

4. `Test Generation & Execution`
输入代码变更和需求，输出测试代码、测试执行结果与测试缺口分析。

5. `Code Review`
输入代码变更、方案与测试结果，输出评审报告、问题列表和回退判定。

6. `Delivery Integration`
输入通过评审的变更，输出最终可交付结果、交付摘要和 MR/PR 信息。

## 9. 核心领域对象

为保证赛题要求可落地，以下对象必须是一等建模对象：

1. `PipelineTemplate`
定义一条流程的结构，包括阶段、依赖、Agent 绑定、检查点配置。

2. `PipelineRun`
一次具体的需求交付运行实例。

3. `StageDefinition`
模板中的单个阶段定义，包含阶段类型、顺序、依赖、输入输出契约。

4. `StageRun`
某次运行中的具体阶段实例，具有运行状态、输入、输出、错误信息。

5. `StageArtifact`
每个阶段的标准化产物对象，是阶段流转和审批展示的基础。
包含：
- `structured_requirement`
- `clarification_items`
- `solution_design`
- `design_decisions`
- `code_changeset`
- `test_bundle`
- `test_gap_report`
- `review_report`
- `delivery_record`

6. `Checkpoint`
人工审批节点，记录审批对象、审批状态、审批意见、回退目标阶段。

7. `AgentRole`
某阶段使用的 Agent 角色定义，包含 System Prompt、能力边界、输入输出契约。

8. `Workspace`
目标仓库的隔离工作区，用于上下文读取、代码修改、测试执行与 diff 生成。

9. `ToolDefinition`
统一工具定义对象，描述工具名称、用途、参数 Schema、返回载荷和错误信息。

10. `ToolCallRecord`
单次工具调用记录对象，用于记录调用参数、执行结果、错误信息和关联阶段。

11. `ChangeSet`
一次代码变更集合，记录影响文件、补丁、摘要、来源阶段与当前状态。

12. `ChangeRisk`
对单次变更的风险分级与风险说明对象，用于决定测试强度、审批要求和是否允许自动推进。

13. `AcceptanceCriteria`
结构化验收标准对象，用于贯穿需求、方案、代码、测试与交付。

14. `ClarificationItem`
需求阶段识别出的歧义点、缺失信息或待确认事项对象，记录问题内容、影响范围、确认状态和最终结论。

15. `CoverageTrace`
需求验收项到设计、代码、测试、交付的覆盖映射对象。

16. `DeliveryRecord`
最终交付对象，记录测试结果、评审结论、交付摘要、MR/PR 链接等。

17. `SkillAsset`
沉淀的需求模式、修复路径、评审规则或执行说明对象，用于阶段执行复用。

18. `DomainEvent`
系统运行过程中产生的关键事件，用于驱动状态流转与投影视图更新。

19. `ContextReference`
Agent 执行时引用的上下文来源对象，用于表达需求文本、仓库路径、文件路径、前序产物等不同上下文来源。

20. `PreviewTarget`
可预览工作区对象，用于定义工作区与预览命令、预览状态之间的关系，为功能二预留能力边界。

## 10. 系统模块划分

为确保功能一完整覆盖 Must-have 并支撑增强能力，采用以下 12 个核心模块：

1. `Pipeline Template Registry`
负责管理 Pipeline 模板、阶段定义、依赖关系、检查点位置与 Agent 绑定。

2. `Pipeline Orchestrator`
负责运行时调度，驱动阶段开始、完成、失败、回退、重试、暂停、恢复、终止。

3. `Run Context / Artifact Store`
负责保存每次运行中的阶段输入输出、阶段产物和共享上下文，支撑阶段间数据流转。

4. `Agent Role Registry`
负责管理每个阶段的 Agent 角色、Prompt 模板、输入输出契约和执行策略。

5. `Skill Registry`
负责管理可复用 Skill、模板规则、修复路径和阶段执行说明。

6. `Clarification & Decision Service`
负责管理需求歧义点、待确认事项、人工澄清结论和关键设计决策的结构化记录。

7. `Agent Runtime`
负责组装上下文、调用 LLM Provider、驱动 Tool 调用、校验结构化输出，并回写阶段产物。

8. `LLM Provider Adapter`
统一封装不同模型供应商，支持至少两个 Provider，并支持运行时切换。

9. `Workspace & Tool Service`
负责代码仓库挂载、工作区隔离、文件上下文装载、代码变更应用、命令执行、diff 生成以及统一工具接口管理。

10. `Checkpoint & Review Service`
负责审批节点创建、Approve/Reject 操作、Reject 理由回注、评审结果持久化。

11. `Observability & Projection Service`
负责实时阶段状态、事件时间线、阶段通过/失败状态、耗时、重试次数、Token 消耗、聚合成功/失败率、Agent 执行摘要和关键错误信息的投影。

12. `REST API + Query Layer`
负责提供标准 REST API、阶段查询、事件时间线、产物查看、审批入口及 OpenAPI 文档。

## 11. 流程引擎需求

Pipeline 引擎必须满足以下要求：

1. `可配置阶段结构`
- 支持 Stage 定义
- 支持顺序与依赖关系
- 支持阶段类型扩展
- 支持检查点插入
- 支持按模板定义是否允许自动回归、最大重试次数和风险推进策略

2. `阶段绑定 Agent`
- 每个阶段可绑定一个或多个 Agent Role
- `Requirement Analysis` 使用单 Agent
- `Solution Design` 使用双 Agent 串行结构
- `Code Generation` 与 `Test Generation & Execution` 使用双 Agent 并行结构
- `Code Review` 使用单 Agent
- `Delivery Integration` 使用单 Agent

3. `阶段间数据流转`
- 上一阶段输出必须以 `StageArtifact` 形式持久化
- 后续阶段通过契约化方式读取所需产物
- 不允许仅依赖内存态临时传参
- 验收标准、澄清结论、设计决策、评审意见等关键上下文必须可跨阶段传递

4. `生命周期管理`
- 支持启动、暂停、恢复、终止
- 支持阶段失败后终止或重试
- 支持审批拒绝后回退到指定阶段重跑
- 支持自动回归结束后转入人工决策或风险确认
- `PipelineTemplate.max_auto_regression_retries` 定义自动回归最大次数
- V1 中 `PipelineTemplate.max_auto_regression_retries` 固定为 `2`

5. `运行可观测`
- 可查询当前运行状态
- 可查看各阶段状态
- 可查看关键事件时间线
- 可查看每阶段产物与错误信息
- 可查看每阶段是否通过、失败或等待审批
- 可查看待确认事项是否已经完成澄清

## 12. Agent 编排与执行需求

Agent 编排必须满足以下要求：

1. `阶段角色明确`
每个阶段必须配置明确的 Agent Role，包括：
- 角色名称
- System Prompt
- 输入契约
- 输出契约
- 失败处理策略

系统定义以下核心 Agent：
- `Requirement Analysis Agent`
- `Solution Design Agent`
- `Solution Validation Agent`
- `Code Generation Agent`
- `Test Generation & Execution Agent`
- `Code Review Agent`
- `Delivery Integration Agent`

2. `上下文感知能力`
Agent 至少支持以下上下文输入方式：
- 目标仓库路径
- 指定目录路径
- 指定文件路径
- 前序阶段产物引用
- 结构化验收标准引用
- 需求澄清结论引用
- 历史评审意见引用

3. `工具调用模型`
Agent 不直接绑定零散函数签名，而是通过统一的 Tool 泛型接口调用工作区能力。V1 的工具集合限定为：
- `read_file`
- `write_file`
- `edit_file`
- `list_files`
- `search`
- `shell`

工具系统设计参考 Claude Code 的思路，但不追求完整复刻。重点要求如下：
- 每个工具都通过统一接口暴露元数据、输入参数、执行结果和错误信息
- Agent Runtime 只依赖统一 Tool 协议，不依赖具体实现细节
- 工作区工具支持本地执行，并为未来远程或沙箱执行保留一致接口
- 工具调用结果必须被记录到运行上下文和事件流中，便于审查与追踪

4. `代码库检索策略`
V1 不实现语义索引。代码库检索仅使用目录遍历、文件路径上下文、关键字搜索和 `grep` 风格检索。

5. `模型供应商可切换`
- 至少支持两个不同 LLM Provider
- 支持运行时按 Pipeline、按阶段或按执行策略切换
- Provider 差异不应泄漏到上层流程逻辑

6. `输出结构化`
- Agent 输出必须转为结构化领域对象
- 必须做格式校验与错误处理
- 非法输出不能直接推进下一阶段

7. `执行与编排解耦`
- Agent Runtime 只负责执行
- Pipeline Orchestrator 负责决定何时执行、何时暂停、何时回退

8. `多 Agent 使用原则`
多 Agent 协作只在已定义的两个阶段结构中启用：
- `Solution Design`：`Solution Design Agent -> Solution Validation Agent` 串行结构
- `Code Generation` 与 `Test Generation & Execution`：双 Agent 并行结构

其余阶段使用单 Agent。

9. `核心 Agent 设计`
各核心 Agent 的职责如下：

- `Requirement Analysis Agent`
  负责将自然语言需求转换为结构化需求、验收标准、歧义点列表和待确认事项。

- `Solution Design Agent`
  负责结合结构化需求、澄清结论和代码库上下文，输出技术方案、影响范围、文件变更清单和关键设计决策。

- `Solution Validation Agent`
  负责独立校验技术方案是否偏离需求、遗漏影响范围、缺少测试策略、引入过高风险或存在更小改动路径。

- `Code Generation Agent`
  负责根据已通过校验的技术方案生成或修改代码，并输出 `ChangeSet` 与变更摘要。

- `Test Generation & Execution Agent`
  负责生成测试、执行测试，并输出测试结果、失败信息和测试缺口分析。

- `Code Review Agent`
  负责独立审查代码变更、方案一致性、测试充分性和变更风险，并输出评审报告与回退判定。

- `Delivery Integration Agent`
  负责整理交付物、交付摘要、分支信息和 MR/PR 信息。

10. `方案阶段双 Agent 约束`
`Solution Design` 阶段必须采用双 Agent 串行结构：
- 先由 `Solution Design Agent` 产出方案
- 再由 `Solution Validation Agent` 做独立校验
- 校验通过后才能进入方案审批或后续阶段
- 校验不通过时回到方案设计阶段修正

11. `核心 Agent 契约`
各核心 Agent 必须具备明确的目标、输入、输出、可用工具和失败处理规则。

- `Requirement Analysis Agent`
  - 目标：将自然语言需求转换为结构化需求、验收标准、歧义点列表和待确认事项
  - 输入：原始需求文本、历史需求上下文
  - 输出：`structured_requirement`、`acceptance_criteria`、`clarification_items`
  - 可用工具：`list_files`、`search`、`read_file`
  - 失败处理：输出不完整或无法形成结构化结果时停留在当前阶段重试；存在歧义点时创建需求澄清确认节点

- `Solution Design Agent`
  - 目标：输出技术方案、影响范围、文件变更清单和关键设计决策
  - 输入：`structured_requirement`、`acceptance_criteria`、`clarification_items`、仓库上下文
  - 输出：`solution_design`、`design_decisions`
  - 可用工具：`list_files`、`search`、`read_file`
  - 失败处理：无法定位影响范围、无法形成方案或缺少关键决策时回到本阶段重试

- `Solution Validation Agent`
  - 目标：独立校验技术方案是否偏离需求、遗漏影响范围、缺少测试策略、引入过高风险或存在更小改动路径
  - 输入：`solution_design`、`design_decisions`、`acceptance_criteria`
  - 输出：`solution_validation_report`
  - 可用工具：`read_file`、`search`
  - 失败处理：校验不通过时回退到 `Solution Design`

- `Code Generation Agent`
  - 目标：根据已通过校验的技术方案生成或修改代码，并输出变更集合
  - 输入：`solution_design`、`design_decisions`、仓库上下文
  - 输出：`code_changeset`、`change_summary`
  - 可用工具：`read_file`、`write_file`、`edit_file`、`list_files`、`search`、`shell`
  - 失败处理：生成结果不满足结构约束、修改失败或无法形成有效变更时回到本阶段重试

- `Test Generation & Execution Agent`
  - 目标：生成测试、执行测试，并输出测试结果与测试缺口分析
  - 输入：`code_changeset`、`acceptance_criteria`、相关仓库上下文
  - 输出：`test_bundle`、`test_execution_result`、`test_gap_report`
  - 可用工具：`read_file`、`write_file`、`edit_file`、`list_files`、`search`、`shell`
  - 失败处理：测试生成失败或执行失败时回到 `Code Generation`，并携带失败信息

- `Code Review Agent`
  - 目标：独立审查代码变更、方案一致性、测试充分性和变更风险
  - 输入：`code_changeset`、`solution_design`、`design_decisions`、`test_execution_result`、`test_gap_report`
  - 输出：`review_report`、`change_risk`、`rollback_decision`
  - 可用工具：`read_file`、`list_files`、`search`
  - 失败处理：发现可修复问题时触发自动回归；发现根因属于方案错误时回退到 `Solution Design`

- `Delivery Integration Agent`
  - 目标：整理交付物、交付摘要、分支信息和 MR/PR 信息
  - 输入：已通过审查的 `code_changeset`、`review_report`、`test_execution_result`
  - 输出：`delivery_record`、`delivery_summary`、`branch_info`、`merge_request_info`
  - 可用工具：`read_file`、`list_files`、`search`、`shell`
  - 失败处理：交付物不完整或无法生成交付记录时停留在本阶段并返回错误信息

## 13. Human-in-the-Loop 需求

本阶段必须至少提供两个检查点：

1. `需求澄清确认`
位于 `Requirement Analysis` 之后，仅当存在待确认事项时触发，审批对象为歧义点列表、待确认事项和澄清结论。

2. `方案设计审批`
位于 `Solution Design` 之后，审批对象为技术方案、影响范围和关键设计决策。

3. `代码评审确认`
位于 `Code Review` 之后，审批对象为代码变更、测试结果、测试缺口分析与评审报告。

检查点必须满足：
- 支持 `Approve`
- 支持 `Reject`
- Reject 时必须要求填写理由
- Reject 后必须回退到指定前序阶段重新执行
- Reject 理由必须进入后续上下文，供 Agent 重做参考
- 控制台或 API 必须清晰展示审批对象和产物内容

需求澄清确认的触发规则如下：
- 当 `Requirement Analysis` 识别出歧义点、信息缺失或相互冲突的约束时，必须创建需求澄清确认节点
- 当需求已足够清晰且无待确认事项时，可以直接进入 `Solution Design`

## 14. API-First 需求

系统必须通过 RESTful API 暴露所有核心能力。

API 分为两类：

1. `Command API`
用于改变系统状态：
- Pipeline Template CRUD
- Pipeline Run 创建与触发
- Pause / Resume / Terminate
- Clarification Confirm / Resolve
- Checkpoint Approve / Reject
- 风险确认后推进流程

风险确认后推进流程的规则如下：
- 仅当 `ChangeRisk.level = medium` 时允许执行风险确认后推进
- 当 `ChangeRisk.level = high` 时禁止风险确认后推进
- 当存在未解决的结构化需求澄清项时禁止风险确认后推进

2. `Query API`
用于查询系统状态：
- Run 状态查询
- Stage 列表与详情查询
- Artifact 查询
- Clarification Item 查询
- Event Timeline 查询
- Delivery Result 查询
- Observability 面板查询

API 规范要求：
- 统一资源命名
- 清晰错误码与错误信息
- 完整 OpenAPI / Swagger 文档
- 控制台必须只通过这些 API 访问后端能力

## 15. 控制台需求

本阶段前端形态为 `基础控制台`，用于支持演示与审批，不追求复杂产品化。

控制台至少包含：
- 需求输入入口
- 需求澄清项查看与确认入口
- Pipeline Run 列表
- 当前运行详情页
- 阶段状态展示
- 实时事件时间线
- 阶段产物查看
- 检查点审批操作
- 交付结果查看
- 每阶段通过/失败状态展示
- 聚合成功率/失败率展示
- Agent 执行摘要与关键决策说明展示
- 重试次数、关键错误和 Token 消耗展示

控制台目标不是替代引擎，而是把引擎能力清晰呈现给观察者和操作者。

控制台中的 Human-in-the-Loop 交互规则如下：
- 自动回归属于审查阶段内部的系统修复循环，不提供单独的人工触发入口
- 审查阶段内部循环结束后，才进入人工审批阶段
- 人工审批通过后，流程进入下一阶段
- 人工审批拒绝后，流程携带人工意见重新返修

## 16. 仓库与执行环境需求

系统必须支持：
- 以平台自身仓库作为默认演示对象
- 支持切换到外部本地仓库
- 在隔离工作区中进行修改与测试
- 读取目录/文件级上下文
- 应用代码变更并生成 diff
- 执行测试或必要命令
- 形成可交付的最终结果
- 在交付阶段创建分支、生成提交说明并生成 MR/PR 描述
- 建立交付记录与分支、提交、MR/PR 之间的关联关系

工作区能力必须遵循统一工具模型，而不是把“读文件、写文件、搜索文件、执行命令”直接暴露为零散函数。V1 的工作区工具能力限定为：
- `read_file`
- `write_file`
- `edit_file`
- `list_files`
- `search`
- `shell`

这些工具必须通过统一 Tool 接口表达以下内容：
- 工具名称与描述
- 输入参数 Schema
- 执行结果载荷
- 错误信息
- 可审计调用记录

该设计参考 Claude Code 的工作区工具思路，但刻意收缩到最核心的一组工具，以保证实现可控、行为稳定、便于运行说明。

本阶段无需支持：
- 云端托管仓库全量管理
- 大规模分布式构建集群
- 多租户仓库隔离体系

## 17. 事件驱动模型

系统核心采用：

`状态机 + 领域事件日志 + 查询投影`

其目的不是引入复杂中间件，而是让流程驱动、状态可追踪、界面可解释。

关键领域事件包括：
- `PipelineRunCreated`
- `StageStarted`
- `RequirementParsed`
- `AcceptanceCriteriaExtracted`
- `ClarificationRequested`
- `ClarificationResolved`
- `SolutionProposed`
- `SolutionValidated`
- `SolutionValidationFailed`
- `DesignDecisionRecorded`
- `CheckpointRequested`
- `CheckpointApproved`
- `CheckpointRejected`
- `CodePatchGenerated`
- `ChangeRiskEvaluated`
- `TestsGenerated`
- `TestsExecuted`
- `TestGapAnalyzed`
- `ReviewCompleted`
- `AutoRegressionTriggered`
- `AutoRegressionExhausted`
- `DeliveryPrepared`
- `MergeRequestCreated`
- `SkillCaptured`
- `StageFailed`
- `RunPaused`
- `RunResumed`
- `RunTerminated`

这些事件既服务于调度，也服务于控制台展示和运行说明。

## 18. 对 Must-have 的覆盖说明

赛题 Must-have 与本设计对应如下：

1. `Pipeline 引擎`
由 `Pipeline Template Registry`、`Pipeline Orchestrator`、`Run Context / Artifact Store` 覆盖。

2. `Agent 编排与执行`
由 `Agent Role Registry`、`Agent Runtime`、`LLM Provider Adapter`、`Workspace & Tool Service` 覆盖。

3. `Human-in-the-Loop`
由 `Checkpoint & Review Service`、`REST API + Query Layer` 覆盖。

4. `API-First`
由 `REST API + Query Layer` 覆盖，并以 OpenAPI 文档作为正式交付物。

5. `端到端演示`
由标准阶段链路、工作区能力、测试执行、审批机制、交付记录共同覆盖。

## 19. 高于 Must-have 的质量目标

Must-have 只能证明平台最低限度具备完整链路，不足以证明平台真正解决了研发交付中的核心问题。因此，本项目第一阶段还应追求以下质量目标：

1. `需求不失真`
- 需求分析阶段必须输出结构化需求与验收标准
- 需求分析阶段必须输出歧义点列表和待确认事项
- 存在待确认事项时，必须先完成澄清再进入后续高风险阶段
- 后续阶段必须引用这一结构化结果，而不是重复自由发挥

2. `方案可追溯`
- 代码生成必须能够回溯到方案设计中的文件影响范围与技术决策
- 评审阶段必须能够看到代码与方案之间的关系
- 方案阶段必须经过独立校验，避免错误技术路径直接流入代码生成

3. `变更可审查`
- 代码变更不应只是最终文件结果，还应保留 diff、影响文件和变更摘要
- 评审与审批必须围绕真实变更产物进行

4. `测试可解释`
- 测试阶段不仅输出测试代码，还应输出执行结果与失败信息
- 不能把“生成了测试”误当成“完成了验证”

5. `回退可纠偏`
- Reject 不是流程终点，而是可携带理由的纠偏机制
- 被拒绝阶段必须能带着审查意见重新生成更优产物

6. `自动回归可控`
- 自动回归的默认回退目标是 `Code Generation`
- 当评审问题表明技术路径、影响范围或接口设计存在根因性错误时，才回退到 `Solution Design`
- 自动回归必须携带评审意见、问题列表和失败上下文
- 自动回归必须设置最大重试次数，避免死循环
- 自动回归在审查阶段内部循环执行
- 审查阶段内部循环结束后，系统进入人工审批阶段
- 达到最大重试次数后，自动回归结束，系统进入人工决策或风险确认节点

7. `验收标准持续追踪`
- 验收标准必须贯穿需求、方案、代码、测试和交付阶段
- 交付阶段必须能够反查每项验收标准的覆盖情况

8. `需求澄清闭环完整`
- 系统必须显式记录需求中的歧义点、缺失信息和冲突约束
- 系统必须记录每个待确认事项的确认状态和最终结论
- 澄清结论必须进入方案、代码、测试和评审阶段的上下文

9. `设计决策可追踪`
- 方案阶段必须提炼关键设计决策
- 后续代码与评审必须能够引用这些决策，而不是只引用方案全文

10. `变更风险可分级`
- 代码变更后必须生成风险分级
- 风险分级将影响测试强度、审批要求和是否允许带风险推进

11. `测试缺口可见`
- 系统必须能够指出哪些验收项已有测试覆盖
- 必须指出哪些验收项尚未被验证或只能依赖人工验证

12. `运行可解释`
- 使用者在控制台上必须能看清楚每个阶段做了什么、为什么这么做、产出了什么、哪里有风险
- 平台不能表现成单一黑盒聊天助手

## 20. 增强能力融合策略

以下增强能力不是孤立功能，而是为了解决核心瓶颈而内建到流程中的补强能力：

1. `多 Agent 协作`
- 用于在可拆解阶段降低遗漏和补足质量风险
- 典型形式是代码实现 Agent 与测试生成 Agent 并行
- 不作为默认运行模式

2. `自动回归`
- 用于在评审发现问题后自动携带修改意见回退并修复
- 回退到 `Code Generation`
- 仅在问题根因指向方案错误时回退到 `Solution Design`
- 超过最大重试次数后转入人工决策或风险确认

3. `可观测性面板`
- 用于实时暴露阶段状态、通过/失败结果、事件时间线、错误原因、重试情况、聚合成功率/失败率和 Agent 执行摘要
- 同时用于验证、调优和说明

4. `代码库检索`
- V1 使用目录遍历、文件路径上下文和 `grep` 风格检索
- V1 不实现语义索引

5. `Pipeline 模板能力`
- 预定义不同类型模板，如 `新功能开发`、`Bug 修复`、`重构`
- 支持一键选用

6. `Git 集成增强`
- 自动创建分支
- 自动提交代码
- 自动发起 MR/PR
- 自动生成交付摘要和 diff 摘要
- 交付记录与分支、提交、MR/PR 建立关联

7. `Skill 沉淀`
- 将重复出现的需求模式、修复路径、评审意见和成功操作序列沉淀为 Skill
- Skill 既可以表现为模板规则，也可以表现为阶段执行时加载的操作说明
- 设计思路参考 Hermes Agent，但只保留对当前项目有价值的最小能力集合

8. `需求澄清机制`
- 将需求分析阶段识别出的歧义点和待确认事项显式化
- 支持人工确认后将澄清结论注入后续上下文
- 避免需求理解偏差直接传递到方案和代码阶段

9. `方案阶段独立校验`
- 在 `Solution Design` 后增加独立校验角色
- 提前发现方案偏移、影响范围遗漏和测试策略缺失
- 避免问题在代码阶段放大

## 21. V1 轻量落地要求

为保证第一阶段可交付且足够有说服力，以下增强能力在 V1 中采用轻量落地：

1. 提供两个 Pipeline 模板：
- `新功能开发`
- `Bug 修复`

2. 工作区工具集仅实现六个核心工具：
- `read_file`
- `write_file`
- `edit_file`
- `list_files`
- `search`
- `shell`

3. 代码库检索仅依赖：
- 目录遍历
- 文件路径上下文
- `grep` 风格搜索

4. 自动回归最小闭环：
- 评审失败后自动回退到 `Code Generation`
- 最多自动修复 `2` 次
- 自动回归在审查阶段内部循环执行
- 审查阶段结束后进入人工审批
- 超限后进入人工决策或风险确认

5. 多 Agent 最小应用：
- `Code Generation` 与 `Test Generation & Execution` 允许并行
- `Solution Design` 采用双 Agent 串行校验
- 其他阶段使用单 Agent

6. 可观测性最小集：
- 阶段实时状态
- 阶段通过/失败结果
- 聚合成功率/失败率
- 关键事件时间线
- Agent 执行摘要
- 重试次数
- 关键错误信息
- 阶段耗时

7. Skill 最小集：
- 需求模板
- 修复路径模板
- 评审规则模板

8. 需求澄清最小集：
- 歧义点识别
- 待确认事项记录
- 澄清结论回注

## 22. 为功能二预留的接口边界

功能二本期不实现，但功能一必须预留以下后端能力接口：

1. `ChangeSet`
支持把任意来源的代码修改请求统一为变更集合对象。
未来功能二的页面圈选改动，也将落到该对象。

2. `ContextReference`
当前先支持：
- `requirement_text`
- `repo_path`
- `directory_path`
- `file_path`
- `artifact_ref`

功能二扩展时增加：
- `page_selection`
- `dom_anchor`
- `preview_snapshot`

3. `PreviewTarget`
定义某工作区对应的预览对象、启动命令和状态。
V1 仅定义 `PreviewTarget` 对象和查询接口，不实现预览启动与热更新能力。

4. `DeliveryRecord`
统一文本需求驱动和未来页面交互驱动的最终交付出口。

本阶段不预留：
- 浏览器注入消息协议
- 页面悬浮对话框状态
- DOM 元素锚点细节实现

原因是这些属于功能二交互层，不应污染功能一当前的核心领域模型。

## 23. 验收标准

功能一第一阶段验收应满足以下标准：

1. 能创建并运行一条完整 Pipeline
2. 能完成从需求输入到代码交付的全流程
3. 存在三个可操作检查点：需求澄清确认、方案设计审批、代码评审确认
4. Reject 后能带理由回退并重跑
5. Agent 可读取代码库上下文
6. 支持至少两个模型供应商切换
7. 所有核心能力可通过 REST API 操作
8. 提供 OpenAPI/Swagger 文档
9. 控制台可展示运行状态、阶段产物和审批入口
10. 控制台可展示阶段实时信息、通过/失败结果和关键错误
11. 控制台可展示聚合成功率/失败率与 Agent 执行摘要
12. 当存在需求歧义时，系统能生成待确认事项并在确认后继续流转
13. 方案阶段存在独立校验过程
14. 核心 Agent 具备明确的输入、输出、工具和失败处理契约
15. 交付阶段具备分支、提交说明和 MR/PR 描述生成能力
16. 自动回归与人工审批的先后关系明确且可执行
17. 至少完成一次对平台自身仓库的真实端到端演示
18. 具备应对现场小范围功能需求的基本能力

## 24. 风险与设计约束

本阶段需重点控制以下风险：
- 不要把系统做成单轮聊天应用，导致流程能力缺失
- 不要把所有状态只放在前端或内存中，导致不可回退和不可追踪
- 不要把 Agent 输出直接当最终结果，必须经过结构化、验证和持久化
- 不要提前把功能二的前端交互模型塞入功能一内核
- 不要为“长期扩展性”引入过重基础设施，影响第一阶段可交付性
- 不要为了展示多 Agent 而在不必要的阶段引入复杂协作
- 不要把语义检索当作当前版本的必要依赖
- 不要在自动回归失败后无条件带病推进流程

## 25. 结论

功能一第一阶段应被正式定义为：

`一个以事件驱动流程引擎为核心、以 Agent 编排为主角、以统一工具抽象和基础控制台为载体、能够完成需求到代码交付闭环的 AI 研发流程平台原型`

它既要满足 `完整链路、Agent 编排、人机审批、API First、端到端交付` 的要求，也要在 `Must-have` 之上体现对研发流程质量的理解，重点解决需求、方案、代码、测试在阶段间传递时的信息失真问题。

本版本同时将 `多 Agent、自动回归、可观测性、模板、Git 集成、Skill 沉淀` 等增强能力纳入统一流程设计，但通过 V1 轻量落地策略控制复杂度，避免为追求概念完整而损害实现可交付性。
