# 05 deterministic runtime 与 demo_delivery

## 范围

本分卷覆盖 Week 7 的 `deterministic test runtime`、六阶段确定性推进、demo_delivery 和交付结果详情投影。完成后，系统可以不依赖真实模型跑通 `demo_delivery` 全链路，并为正式 LangGraph runtime 提供可回归的基线路径。

本分卷承接 04 分卷的运行控制边界和 03 分卷的 Run / Stage / Artifact 基础，只实现 deterministic runtime 与无 Git 写动作交付适配，不接入正式模型调用或真实 Git 交付。
凡本分卷修改 `backend/app/api/routes/*` 的 API 切片，对应 API 测试必须在本切片内断言新增或修改的 path、method、请求 Schema、响应 Schema 和主要错误响应已进入 `/api/openapi.json`；V6.4 只做全局覆盖回归。

`deterministic test runtime` 阶段推进、失败、终止和 `demo_delivery` 必须写入运行日志摘要并继承 `TraceContext`；`demo_delivery` 不执行真实 Git 写动作，真实 Git 交付由后续 08 分卷落地。

<a id="a41"></a>

## A4.1 RuntimeEngine 接口

**计划周期**：Week 7
**状态**：`[x]`
**目标**：定义 `deterministic test runtime` 与 LangGraph runtime 的共同接口，使运行生命周期服务不依赖具体执行内核，并保证两条执行路径只消费 run 已固化的运行快照。
**实施计划**：`docs/plans/implementation/a4.1-runtime-engine-interface.md`
**验证摘要**：实施计划 `docs/plans/implementation/a4.1-runtime-engine-interface.md` 已完成并在 integration checkpoint 合入 `3cba4f8`。`uv run python -m pytest backend/tests/events/test_event_store.py backend/tests/runtime/test_runtime_engine_contract.py -v` 通过 26 个 E3.1 / A4.1 focused tests；`uv run python -m pytest -q` 通过 356 个 backend tests。

**修改文件列表**：
- Create: `backend/app/runtime/base.py`
- Create: `backend/tests/runtime/test_runtime_engine_contract.py`

**实现类/函数**：
- `RuntimeEngine`
- `RuntimeExecutionContext`
- `RuntimeStepResult`
- `RuntimeInterrupt`
- `RuntimeTerminalResult`

**验收标准**：
- runtime 接口支持启动、推进、从中断恢复和终止。
- runtime 结果只返回领域对象、事件和产物引用，不返回 raw graph state。
- `deterministic test runtime` 与 LangGraph runtime 必须实现 A4.0 定义的 `RuntimeCommandPort` / `CheckpointPort` 调用边界。
- `deterministic test runtime` 只作为稳定测试、前端联调和可重复端到端验收路径；正式 Agent 编排路径由 LangGraph runtime 承担。
- `RuntimeEngine` 接口不得要求调用方识别 deterministic 或 LangGraph 的内部状态结构。
- runtime 接口必须接收并传递 `TraceContext`，运行步骤结果必须允许返回日志摘要引用和审计引用，但不得要求调用方读取日志来推进状态。
- `RuntimeExecutionContext` 必须携带 `template_snapshot_ref`、Provider/模型绑定快照引用、`runtime_limit_snapshot_ref`、`provider_call_policy_snapshot_ref`、`graph_definition_ref` 和必要的交付快照引用；runtime 不得读取最新 Provider、模板或平台运行设置来改变当前 run。

**测试方法**：
- `pytest backend/tests/runtime/test_runtime_engine_contract.py -v`

<a id="a42"></a>

## A4.2 deterministic test runtime 六阶段推进

**计划周期**：Week 7
**状态**：`[x]`
**目标**：实现稳定可控的 `deterministic test runtime` 六阶段推进，使端到端测试和前端联调不依赖真实模型输出。
**实施计划**：`docs/plans/implementation/a4.2-deterministic-six-stage-runtime.md`
**验证摘要**：实施计划 `docs/plans/implementation/a4.2-deterministic-six-stage-runtime.md` 已在 integration checkpoint 合入 `7f61772`。Worker verification 中 `uv run pytest backend/tests/runtime/test_deterministic_runtime.py -v` 通过 11 个 focused tests，`uv run pytest backend/tests/runtime/test_deterministic_runtime.py backend/tests/runtime/test_runtime_engine_contract.py backend/tests/services/test_stage_run_store.py backend/tests/services/test_artifact_store.py backend/tests/events/test_event_store.py -v` 通过 74 个 impacted backend tests，`uv run pytest -q` 通过 1014 个 backend tests。本次 integration verification 在 `integration/function-one-acceleration` 上重复运行 focused 与 impacted backend 命令并通过，`uv run pytest -q` 通过 1028 个 backend tests，保留既有 LangChain adapter `temperature` warning。

**修改文件列表**：
- Create: `backend/app/runtime/deterministic.py`
- Create: `backend/tests/runtime/test_deterministic_runtime.py`

**实现类/函数**：
- `DeterministicRuntimeEngine`
- `DeterministicRuntimeEngine.run_next()`
- `DeterministicRuntimeEngine.emit_stage_artifacts()`

**验收标准**：
- `deterministic test runtime` 可稳定推进六个业务阶段。
- 每个阶段写入 StageRun、StageArtifact 和领域事件。
- Solution Validation 作为 `solution_design` 内部过程记录出现，不形成独立阶段。
- `deterministic test runtime` 在调用 `read_file`、`write_file`、`edit_file`、`glob`、`grep` 或 `bash` 能力时必须通过 W5.0 `ToolProtocol` 与 `ToolRegistry`；若本切片尚未调用工具，则只能写入固定结构化产物和领域事件，不得引入临时工具函数。
- `deterministic test runtime` 每个阶段推进必须写入运行日志摘要，包含阶段、耗时、结果状态、产物引用和 `span_id`；阶段事实仍由 StageRun、StageArtifact 和领域事件承载。
- `deterministic test runtime` 必须使用 R3.4、R3.4a、R3.4b 固化的模板、Provider/模型绑定和运行上限快照，不得读取最新配置或暴露为用户可选运行模式。
- 前端端到端测试可使用固定输出。

**测试方法**：
- `pytest backend/tests/runtime/test_deterministic_runtime.py -v`

<a id="a43"></a>

## A4.3 deterministic test runtime 澄清、审批与工具确认中断

**计划周期**：Week 7
**状态**：`[x]`
**目标**：为 `deterministic test runtime` 增加可配置澄清、方案审批、代码评审审批和工具确认中断路径。
**实施计划**：`docs/plans/implementation/a4.3-deterministic-interrupts.md`
**验证摘要**：实施计划 `docs/plans/implementation/a4.3-deterministic-interrupts.md` 已在 integration checkpoint 合入 `370123d`。Worker verification 中 focused runtime / contract 命令通过 34 个 tests，AL03 service regression 通过 31 个 tests，`uv run pytest -q` 通过 1042 个 backend tests。本次 integration verification 在 `integration/function-one-acceleration` 上重复运行 focused runtime / contract、AL03 service regression 和完整 backend suite；`uv run pytest -q` 通过 1042 个 backend tests，保留既有 LangChain adapter `temperature` warning。

**修改文件列表**：
- Modify: `backend/app/runtime/deterministic.py`
- Create: `backend/tests/runtime/test_deterministic_interrupts.py`

**实现类/函数**：
- `DeterministicRuntimeEngine.configure_interrupts()`
- `DeterministicRuntimeEngine.resume_from_interrupt()`
- `DeterministicRuntimeEngine.emit_approval_request()`
- `DeterministicRuntimeEngine.emit_tool_confirmation_request()`

**验收标准**：
- 可配置触发澄清。
- 可配置触发 solution design approval。
- 可配置触发 code review approval。
- 可配置触发高风险工具确认，生成 `ToolConfirmationRequest`、`GraphInterruptRef(type=tool_confirmation)` 和顶层 `tool_confirmation` 投影。
- 中断恢复必须通过 A4.0 runtime boundary 继续同一个 run、同一个 GraphThreadRef 和同一个源阶段。
- 审批拒绝按规格回到目标阶段。
- 工具确认拒绝不得触发审批 rollback；存在低风险替代路径时继续当前阶段，不存在替代路径时进入失败或等待用户显式运行控制。
- deterministic 中断、恢复、审批请求生成、工具确认请求生成和恢复失败必须写入运行日志，并继承同一 `trace_id` 与 `correlation_id`。

**测试方法**：
- `pytest backend/tests/runtime/test_deterministic_interrupts.py -v`

<a id="a44"></a>

## A4.4 deterministic test runtime 终态控制

**计划周期**：Week 7
**状态**：`[x]`
**目标**：为 `deterministic test runtime` 增加失败和终止路径，使端到端测试能覆盖 run 终态和重新尝试前置条件。
**实施计划**：`docs/plans/implementation/a4.4-deterministic-terminal-control.md`
**验证摘要**：实施计划 `docs/plans/implementation/a4.4-deterministic-terminal-control.md` 已在 integration checkpoint 合入 `74f7d38`。Worker verification 中 focused terminal 命令通过 11 个 tests，impacted runtime / contract 命令通过 45 个 tests，H4.6 terminate 与 rerun service regression 通过 25 个 tests，完整 backend suite 通过 1053 个 tests。本次 integration verification 在 `integration/function-one-acceleration` 上重复运行 focused terminal、impacted runtime / contract、H4.6 terminate / rerun regression 和完整 backend suite；`uv run pytest -q` 通过 1068 个 backend tests，保留既有 LangChain adapter `temperature` warning。

**修改文件列表**：
- Modify: `backend/app/runtime/deterministic.py`
- Create: `backend/tests/runtime/test_deterministic_terminal_states.py`

**实现类/函数**：
- `DeterministicRuntimeEngine.emit_terminal_result()`
- `DeterministicRuntimeEngine.fail_run()`
- `DeterministicRuntimeEngine.terminate_run()`
- `TerminalStatusProjector.append_terminal_system_status()`

**验收标准**：
- `deterministic test runtime` 可配置成功、失败和终止路径。
- failed / terminated run 尾部生成正确终态来源记录，并统一通过 `TerminalStatusProjector` 追加顶层 `system_status`。
- 终态记录可支持后续重新尝试 run 创建。
- 本切片不生成 DeliveryRecord，正式 `demo_delivery` 由 D4.2 负责。
- deterministic 失败和终止必须写入运行日志，并记录直接失败点、源阶段和后续重新尝试所需的关联线索。

**测试方法**：
- `pytest backend/tests/runtime/test_deterministic_terminal_states.py -v`

<a id="d41"></a>

## D4.1 Delivery base 与 DeliveryRecord

**计划周期**：Week 7
**状态**：`[x]`
**目标**：建立交付适配器基类和 DeliveryRecord 服务，使 `deterministic test runtime` 能进入正式 demo_delivery 出口；交付通道快照固化已经由 D4.0 负责。
**实施计划**：`docs/plans/implementation/d4.1-delivery-base-record.md`
**验证摘要**：实施计划 `docs/plans/implementation/d4.1-delivery-base-record.md` 已在 integration checkpoint 合入 `9ccf071`。Worker verification 中 focused DeliveryRecord service 命令通过 20 个 tests，delivery snapshot / runtime model regression 通过 18 个 tests，runtime regression 通过 20 个 tests，完整 backend suite 通过 1088 个 tests。本次 integration verification 在 `integration/function-one-acceleration` 上重复运行 focused D4.1、delivery snapshot / runtime model regression、runtime regression 和完整 backend suite；`uv run python -m pytest backend/tests -q` 通过 1114 个 backend tests，保留既有 LangChain adapter `temperature` warning。

**修改文件列表**：
- Create: `backend/app/delivery/base.py`
- Create: `backend/app/services/delivery.py`
- Create: `backend/tests/delivery/test_delivery_record_service.py`

**实现类/函数**：
- `DeliveryAdapter`
- `DeliveryRecordService.create_record()`
- `DeliveryRecordService.get_record()`
- `DeliveryService.get_adapter()`
- `DeliveryService.create_delivery_record_from_adapter_result()`

**验收标准**：
- DeliveryRecord 统一文本需求驱动与未来页面交互驱动的交付出口。
- DeliveryRecord 关联需求、方案、代码、测试、评审和交付产物。
- DeliveryRecord 必须读取 D4.0 已固化的 `delivery_channel_snapshot_ref`，不得重新读取项目级最新 DeliveryChannel。
- 本切片不改变 `ApprovalService.approve()`，不承担交付快照固化。
- 交付 adapter base 只定义输入、输出、错误和审计引用边界，不执行真实 Git 写动作。
- DeliveryRecord 创建成功、创建失败和 adapter 选择失败必须写入运行日志；未来真实交付的高影响动作审计由 D5.1-D5.4 嵌入。

**测试方法**：
- `pytest backend/tests/delivery/test_delivery_record_service.py -v`

<a id="d42"></a>

## D4.2 demo_delivery adapter 与 delivery_result

**计划周期**：Week 7
**状态**：`[ ]`
**目标**：实现 `demo_delivery` 交付路径，使 deterministic 成功链路可生成完整 DeliveryRecord 和展示型交付结果且不执行真实 Git 写动作。
**实施计划**：`docs/plans/implementation/d4.2-demo-delivery-adapter.md`

**修改文件列表**：
- Create: `backend/app/delivery/demo.py`
- Modify: `backend/app/services/delivery.py`
- Create: `backend/tests/delivery/test_demo_delivery.py`
- Create: `backend/tests/e2e/test_deterministic_run_flow.py`

**实现类/函数**：
- `DemoDeliveryAdapter.deliver()`
- `DeliveryRecordService.create_demo_record()`
- `DeliveryService.append_delivery_result()`
- `startDeterministicRunFixture()`

**验收标准**：
- `demo_delivery` 生成展示型交付结果。
- 不执行真实 Git 写动作。
- 成功后追加顶层 `delivery_result`。
- `delivery_result` 详情可通过 DeliveryResultDetailProjection 深看。
- `deterministic test runtime` 可跑通六阶段到 `demo_delivery` 的完整成功链路。
- `demo_delivery` 必须读取已固化交付快照，不重新读取项目级最新 DeliveryChannel。
- `demo_delivery` 必须写入运行日志和审计记录，明确其不执行真实 Git 写动作；审计引用进入 DeliveryRecord 或交付过程引用。

**测试方法**：
- `pytest backend/tests/delivery/test_demo_delivery.py -v`
- `pytest backend/tests/e2e/test_deterministic_run_flow.py -v`

<a id="d43"></a>

## D4.3 DeliveryResultDetailProjection 正式实现

**计划周期**：Week 7
**状态**：`[ ]`
**目标**：在 DeliveryRecord 与 `demo_delivery` 落地后，实现正式交付结果详情投影，替代 Week 5 不允许实现的临时交付详情投影语义。
**实施计划**：`docs/plans/implementation/d4.3-delivery-result-detail-projection.md`

**修改文件列表**：
- Modify: `backend/app/services/projections/inspector.py`
- Modify: `backend/app/api/routes/query.py`
- Create: `backend/tests/projections/test_delivery_result_detail_projection.py`
- Modify: `backend/tests/api/test_query_api.py`

**实现类/函数**：
- `InspectorProjectionService.get_delivery_record_detail()`
- `InspectorProjectionService.build_delivery_result_sections()`

**验收标准**：
- `GET /api/delivery-records/{deliveryRecordId}` 返回完整交付结果详情。
- 详情来源必须是 DeliveryRecord、已固化交付快照、StageArtifact 和稳定引用，不得使用前端摘要或临时 projection payload 反推。
- `delivery_result` 详情包含交付模式、变更结果、测试结论、评审结论、产物、原始交付过程引用与量化信息。
- `approval_result` 仍不作为独立右栏对象；交付详情只服务 `delivery_result`。
- DeliveryResultDetailProjection 可以展示与交付过程直接相关的日志摘要、裁剪片段和审计引用，但不得从日志反推交付结果。
- API 测试必须断言 `GET /api/delivery-records/{deliveryRecordId}` 的响应 Schema、主要错误响应和 OpenAPI path/method 已进入 `/api/openapi.json`。

**测试方法**：
- `pytest backend/tests/projections/test_delivery_result_detail_projection.py -v`
- `pytest backend/tests/api/test_query_api.py -v`
