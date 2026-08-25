# P5-N10 事件驱动回测内核

`backtest-core` 提供 Phase 5 的研究回测运行时边界。它只消费 `quant_core.strategy` 的公开 API，负责把不可变运行清单中的决策事件按确定性顺序交给策略生命周期，并把策略 `Signal` 交给显式的组合意图策略。

## 运行边界

一次运行由 `BacktestRunManifest` 完整定义：策略 descriptor、参数快照、策略与 policy 的 identity/version/fingerprint、数据集身份和 digest、代码与配置版本、事件排序版本、RNG 算法与 seed、时间范围以及冻结事件。构造阶段可以把 exact `tuple` 输入规范化为 canonical order；Engine 在调用任何 Program factory 或 strategy hook 前必须调用非变异的 `validate_integrity()`，重新校验当前 descriptor、parameters、事件、Context、PIT、唯一性、时间范围、canonical order 和 `manifest_digest`，不会静默排序或修复已经篡改的对象。Manifest 会使用 descriptor 的 parameter specs 校验 required、unknown、type、minimum 和 maximum，并要求公共 `validate_parameters` 返回的 canonical `StrategyParameters` 与清单中的参数快照完全相等；默认值补全或其他隐式修复都会被拒绝。`Manifest.events`、`DeterministicEventQueue` 的输入和 `PortfolioIntentPolicy` 的返回值都必须是运行时 exact `tuple`；引擎拒绝 `list`、`dict` 和其他 `Sequence`。

```text
(logical_time in UTC, phase, source_id, source_sequence, event_id)
```

Manifest 不读取当前时间，不生成 UUID，不使用进程内 `hash`，并通过规范化 JSON 的 SHA-256 生成 `manifest_digest`。`BACKTEST_ENGINE_VERSION`、`MANIFEST_SCHEMA_VERSION`、`EVENT_ORDERING_VERSION` 和 `RNG_ALGORITHM` 是固定、导出的支持版本常量；清单构造和 integrity validation 都必须精确匹配，不支持的 engine/schema/event-order/RNG 版本 fail-closed。事件、Context、Feature、Universe、Signal、State、Intent、Trace 和 Result 在公共聚合边界重新调用其 dataclass invariants，并捕获 `AttributeError`/`TypeError`；事件 ID、同一 source 的 sequence、排序键冲突、未来 available time、上下文时间不一致和范围外事件都会在任何策略 hook 之前拒绝。

## 生命周期

`BacktestEngine` 没有运行态字段。对 conforming trusted Program，每次 `run` 都调用 factory 创建 run-local 的事件队列、`SimulationClock`、`DeterministicRandom`、`StrategyRunner` 和 `PortfolioIntentPolicy`，并在任何 strategy hook 前验证 descriptor、parameters、strategy implementation fingerprint，以及 Manifest 中的 policy id、policy version 和 policy implementation fingerprint：

```text
manifest.start_time
  -> runner.initialize(first context)
  -> clock.advance(event.logical_time)
  -> runner.on_decision(context, state)
  -> policy.to_intents(sorted signals, context, event_id, random_source, domain="decision")
  -> ...
  -> runner.finalize(last context, state)
  -> policy.to_intents(sorted finalize signals, context, event_id, random_source, domain="finalize")
```

策略返回的 Signal 按 `signal_id` 排序，意图按 `(source_signal_id, intent_id)` 排序，并要求 intent_id 在一次运行内全局唯一。Engine 不从 `LONG`/`SHORT` 推导 `BUY`/`SELL`；方向必须由 policy 明确产出，并且每个 intent 都验证来源 Signal、实体、逻辑时间、manifest digest、policy id/version 和 policy fingerprint。Trace 与 Result 还会绑定 Signal 的 Context、snapshot、descriptor/version，验证 State lifecycle、相邻状态链、finalize context 和 `finalize_result.next_state`；即使没有 finalize intent，finalize Signal 也必须绑定最后一个事件 Context。`PortfolioIntentPolicy` 只负责从 Signal 产生纯 `BacktestOrderIntent`，不持有或计算组合状态。

## 随机源

`DeterministicRandom` 不依赖 Python `random` 模块或全局状态。当前固定算法标识为 `RNG_ALGORITHM = "sha256-counter-v2"`。Policy 通过结构化 `RandomSource` 接收当前 `StrategyContext`、当前 `event_id` 和本次 run 独有的确定性随机源；`domain_name` 由 Engine 注入并由 RandomSource 自身固定，Policy 不得靠拼接 purpose 代替作用域。Engine 为 decision 与 finalize 创建不同 domain，防止两个生命周期阶段共享随机序列。每个字节块由明确的 typed、length-prefixed payload 按固定算法的 SHA-256 counter 规则派生：

```text
LP("backtest-rng-v2") ||
LP("algorithm") || LP(algorithm_name) ||
LP("domain") || LP(domain_name) ||
LP("manifest_digest") || LP(manifest_digest) ||
LP("seed") || LP(("I" or "S") || LP(seed text)) ||
LP("event_id") || LP(event_id) ||
LP("purpose") || LP(purpose) ||
LP("index") || LP(decimal index) ||
LP("block") || LP(decimal block)
```

其中 `LP(x)` 是 8-byte big-endian byte length 加原始 UTF-8/ASCII bytes；seed 的 `I`/`S` tag 保留整数与字符串的类型区别。它提供确定性 bytes、非负整数和 Decimal unit value。`integer()` 用足够数量的 256-bit blocks 形成 candidate，令 `space = 2^bits`，`limit = space - (space mod upper_bound)`；只有 `candidate < limit` 才返回 `candidate mod upper_bound`，否则递增 counter 重试，因此不引入单次取模偏差。`domain_name`、purpose 与 index 都是显式域参数，算法名写入 Manifest；相同 domain 重建得到相同输出，不同生命周期 domain 即使其他输入完全相同也得到不同输出。

`manifest_digest`、`BacktestOrderIntent.manifest_digest` 和 `result_digest` 都是规范化 SHA-256 字段，必须是 64 位小写十六进制字符串。`dataset_digest` 表示数据集内容或外部来源的摘要，可以使用带名称或命名空间的外部摘要（例如 `provider:version:digest`），因此不强制是 SHA-256，也不能无依据地称为 SHA-256。

## 意图与后续节点边界

`BacktestOrderIntent` 是 Signal 到显式意图的纯边界，只包含意图 ID、来源 Signal、实体、逻辑时间、BUY/SELL、policy/version/fingerprint 和 manifest digest。它固定 `is_executable=False` 与 `BACKTEST_ONLY`，不包含 quantity、price、account、broker、clientOrderId、Order、Fill、Fee 或 Slippage。

`BacktestProgram` 是同进程 trusted boundary。fingerprint 是受信任构建或编排注入的 provenance 声明，不是字节码、源码或 freshness 的远程证明；Engine 只能在每次 run 调用 factory 并隔离自身状态，不能防止恶意或不 conforming 的 Python Program 撒谎 fingerprint、缓存对象或读取全局状态。确定性保证只针对 conforming trusted Program，不对任意 Python 代码成立。

本节点不定义或实现 `Order`、`Fill`、`Fee`、`Slippage`、撮合、成交优先级、A 股交易约束、Portfolio accounting、现金、持仓、成本、公司行动或净值，也不提供 Broker、QMT 或任何 Execution 路径。撮合与成交相关能力属于后续 P5-N11，组合会计属于 P5-N12；Broker、QMT、Execution 和真实订单/账户路径属于后续阶段或本节点禁区，不能从本节点的 intent 进入。

## 结果

`BacktestRunResult` 保存不可变的 ordered trace、finalize `StrategyResult`、finalize intents、final `StrategyState`、Manifest 和规范化 `result_digest`。结果 digest 不含耗时、日志时间、随机 UUID、对象地址或任何当前时间值，因此相同 Manifest 与程序实现会逐字段复现。

Phase 0 至 Phase 6 不提供真实账户、真实 broker、QMT 或可达的真实订单路径；本节点不实现撮合、成交、费用、滑点或组合会计。`BacktestOrderIntent` 不能越过本边界进入真实执行。
