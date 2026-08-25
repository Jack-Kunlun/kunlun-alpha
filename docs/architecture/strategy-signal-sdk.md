# P5-N09 策略与信号 SDK

## 目标与边界

`quant_core.strategy` 只提供点时研究数据、参数、生命周期和不可执行 Signal。SDK 不包含
Execution、Broker、账户、委托、成交、价格指令、网络客户端、真实时钟或 QMT 依赖。

Phase 0 至 Phase 6 中：

- Strategy 只能读取冻结的 `StrategyContext`。
- Strategy 只能返回 `StrategyResult` 中的 `Signal`。
- Signal 固定 `is_executable=false`，跨语言契约固定
  `executionCapability="NONE"`。
- LONG、SHORT、NEUTRAL 仅表示研究方向，不表示可成交委托；其中 SHORT 也不启用融券、
  做空或任何券商能力。
- 后续组合、回测与模拟成交必须通过各自节点的独立契约，不能把 Signal 直接解释为订单。

Python `Protocol` 不能阻止任意第三方策略代码自行导入系统模块。SDK 保证的是公共能力表面
没有上述入口；加载不受信任策略时，宿主仍必须使用进程、文件、网络和权限隔离。实盘能力
不属于本节点，也不能通过 feature flag 接入。

## Point-in-time Context

`StrategyContext` 由以下冻结内容组成：

- `decision_time`：策略决策时点；
- `data_cutoff_time`：输入快照截止时点，必须不晚于决策时点；
- 版本化 context snapshot；
- `UniverseSnapshot`：带 `as_of_time`、`available_time`、`processing_time` 的历史证券池；
- `FeatureValue`：带事件、可用、处理时间以及来源快照版本的特征值。

Universe 和所有特征的 `processing_time` 必须不晚于 `data_cutoff_time`。实体、特征和参数
采用稳定排序；重复键 fail closed。Context 只暴露固定实体列表和 `get_feature`，不暴露
数据提供者、数据库、当前时间或任意 `as_of` 查询能力。

## 参数与生命周期

`StrategyDescriptor` 固定记录：

- Strategy、算法、SDK 和生命周期版本；
- 所需 Feature 名称；
- BOOLEAN、DECIMAL、INTEGER、STRING 参数定义、默认值及数值边界。

`validate_parameters` 拒绝未知、缺失、类型错误和越界参数，并按参数名生成稳定的
`StrategyParameters`。DECIMAL 必须使用有限 `Decimal`，不能用 float 替代。

Strategy 生命周期仅有：

```text
initialize(context, parameters) -> StrategyState
on_decision(context, parameters, state) -> StrategyResult
finalize(context, parameters, state) -> StrategyResult
```

生命周期不接收执行服务、订单接口、随机源或隐式真实时钟。状态只允许冻结的标量键值。

## Signal 契约

权威 JSON Schema：

- `packages/contracts/schemas/strategy/signal.json`
- `packages/contracts/schemas/strategy/strategy-descriptor.json`

生成物：

- TypeScript：`packages/shared-types/src/index.ts`
- Python DTO：`ashare_contracts.strategy_signal` 和
  `ashare_contracts.strategy_strategy_descriptor`

Signal 包含 Strategy/算法版本、统一实体 ID、决策与数据截止时间、研究方向、Decimal 字符串
分数/置信度、研究期限、解释、输入快照和证据 ID。它明确不包含账户、Broker、数量、价格、
订单或成交字段。

`validate_strategy_result` 要求每个 Signal：

1. Strategy、算法版本与 Descriptor 一致；
2. 决策时点、数据截止、输入快照与 Context 完全一致；
3. 实体属于历史 Universe；
4. ID 不重复；
5. 保持不可执行。

## 版本与兼容性

- SDK 版本：`1.0.0`
- Signal Schema：`signal-v1`
- Descriptor Schema：`strategy-descriptor-v1`

Schema 是跨语言传输权威；Python domain model 额外执行 Decimal、跨字段时间和 Context 绑定
校验。任何不兼容字段或生命周期变更必须发布新 Schema/SDK 版本，不能覆盖历史 Signal。

## Mandatory runtime boundary

`StrategyRunner` is the only public lifecycle entry. `Strategy` exposes only private implementation
hooks (`_initialize`, `_on_decision`, and `_finalize`); consumers must not invoke them. The runner
snapshots the immutable descriptor at construction, validates SDK compatibility and the context
before each hook, canonicalizes state, and validates every returned `Signal` before exposing it.

All public Python collections are runtime-enforced tuples, not only tuple annotations. A context
rejects features whose entity is outside its historical `UniverseSnapshot`; each emitted signal
must also have every descriptor-required feature for that same entity. Signal identity, strategy
and algorithm versions, decision/cutoff times, context snapshot, universe membership, and lifecycle
state version are bound at the runner boundary.

The wire contract has matching fixed safety fields: `executionCapability` is always `NONE` and
`isExecutable` is always `false`. `@kunlun/contracts/strategy` exposes `parseStrategySignal` and
`parseStrategyDescriptor` for TypeScript runtime validation. Generated Pydantic DTOs are frozen,
convert collection fields to tuples, enforce cutoff ordering and exact lifecycle hooks, and validate
parameter defaults and bounds against the declared parameter type.

This SDK intentionally exposes no Broker, account, order, Execution, QMT, wall-clock, network, or
provider capability. Python protocols cannot sandbox arbitrary imports inside untrusted strategy
code; only trusted in-process strategies are supported by this node. Process isolation belongs to a
later explicitly approved node and does not weaken the mandatory runner boundary.
