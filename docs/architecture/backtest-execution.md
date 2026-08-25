# P5-N11 A 股订单与成交模拟

## 边界

`backtest_core.execution` 是回测执行的公共入口。它只消费显式的
`MarketExecutionSnapshot`、`InstrumentExecutionRules`、`SellabilitySnapshot`、
`FeeSchedule` 和 `SlippageModel`，不从策略信号推导数量或价格，也不把 Bar、OHLC、
NAV、iNAV 或复权价格当作可成交盘口。

本节点只产生 `SimulationOrder`、`Fill`、费用明细和匹配结果。现金冻结、持仓成本、
结算、公司行动、净值和组合会计属于 P5-N12；卖出可用量在本节点只在一次
`match_orders` 调用内临时扣减，不持久化。

## 输入契约与 PIT

所有时间戳必须 timezone-aware。每个 `ExecutionProvenance` 都必须提供
`available_time`，未知可用时间不能进入执行边界。`MarketExecutionSnapshot.match_time`
转换到 `Asia/Shanghai` 后派生 `trading_date`，输入日期必须完全一致。当前只接受
`EXECUTION_SCHEMA_VERSION`，不兼容的 snapshot schema 必须先显式迁移，不能由 matcher
猜测或静默接受。

快照、规则、可卖批次、费用、滑点和可执行层级的 `available_time`，以及它们嵌套的
source provenance，必须不晚于 `match_time`；规则、费用和滑点还必须处于自己的
effective interval 内。`SellabilitySnapshot.as_of_time` 必须不晚于 snapshot 的
`match_time`；批次和批次 source 的 available time 必须不晚于 sellability as-of，形成
`lot/source -> sellability.as_of_time -> snapshot.match_time` 的 fail-closed PIT 链。

快照包含交易日历的 id、version、digest，连续竞价 session、交易状态、显式价格带、
显式 `UPPER_LOCKED`/`LOWER_LOCKED` 状态以及 bid/ask 层级。首版只接受
`SessionKind.CONTINUOUS`。非交易日、非连续竞价、停牌、临时停牌和闭市均 fail-closed。

`ExecutableLiquidityLevel.price_source` 必须是 `EXECUTABLE_QUOTE`。`NAV`、`iNAV`、
原始 Bar、复权 Bar 和其他参考源不能生成 Fill。没有真实对手方层级时，结果是
`UNFILLED/MISSING_EXECUTABLE_LIQUIDITY`，不会合成价格。

## 匹配顺序

1. 重验证所有 frozen nominal-type 对象、digest、单证券、单快照和单 backtest manifest
   约束；重复 `order_id` 是批次结构错误。
2. 校验 PIT、日历、session、交易状态、规则 effective interval、订单类型、数量、tick、
   daily band、dynamic valid range、保护价和显式锁状态。
3. 按 side 选择真实层级：BUY 只能消费 ask，SELL 只能消费 bid。`LIMIT_IOC` 使用 limit
   作为 cap/floor；`MARKET_PROTECTED_IOC` 必须提供 protection price，并以它作为 cap/floor。
4. 对同侧订单按 BUY cap 降序或 SELL floor 升序，再按 `submitted_at`、
   `submission_sequence`、`order_id` 排序。快照输入必须已经是 canonical 层级顺序：
   bid 按价格降序、ask 按价格升序，同价按 `level_id` 字典序；构造器拒绝非 canonical
   tuple，不会静默重排以掩盖来源错误。
5. 共享层级容量逐层扣减。成交数量不超过层级可用量，订单可产生
   `FILLED`、`PARTIALLY_FILLED`、`UNFILLED` 或 `REJECTED`。
6. 滑点模型只能跳过或限制已有层级。`adverse_level_offset` 和显式 skip 在本批次将层级
   标为不可用，避免低优先级订单重新拿到被跳过的更优价；不会生成、clamp 或 round 出新价格。
7. 成交后计算费用。先在配置的 `FeeScope` 聚合 raw amount，再应用已对齐的
   minimum/maximum clamp，最后执行配置的 rounding。minimum 和 maximum（如有）必须是
   `rounding_quantum` 的精确倍数，因此任何 rounding mode 都不会把最终金额推到边界外。
   `PER_FILL` 每个 Fill 独立完成这三个步骤；`PER_ORDER` 只对订单总额完成一次，再按
   canonical execution-level order（`execution_sequence` 升序）分摊；分摊产生的 rounding
   residual 始终归入该顺序的最后一个 Fill，分项 allocated 总和必须等于订单级 rounded 总额。
   `unrounded_amount` 始终是 Fill 归属的 raw component amount；`rounded_amount` 表示
   其 scope 层级的 rounded 金额。在本实现中 `PER_ORDER` 的 rounded 采用分摊后的订单级
   金额，因此每个费用项的 `rounded_amount == allocated_amount`，不会错误暗示 minimum
   对每个 Fill 重复应用。
8. 成功的 `FILLED`/`PARTIALLY_FILLED` 只能携带成功成交元数据；未成交结果必须有拒绝原因。
   Fill 按 `execution_sequence` 保持 canonical 执行顺序，并绑定 result 的订单、意图、
   instrument、side、manifest、snapshot、rules、fee 和 slippage digest。Fill 和
   BatchMatchResult 保存 snapshot/rules/fee/slippage/source intent/order/manifest digest，
   以及日历、订单集合和配置摘要 digest，支持确定性重放；batch 会逐项绑定 result 上下文。

## 交易规则

`InstrumentExecutionRules` 通过 instrument、kind、effective interval、source 和 version
配置 lot、tick、买入最小量/增量、单笔上限、零股策略、同日卖出策略和支持的订单类型。
测试中的股票 100 股单位、0.01 tick 和基金 0.001 tick 只是 fixture；生产代码不把这些
数值视为全市场永久常量。

T+1 只允许 `sellable_from_trade_date <= trading_date` 且 acquisition date 早于交易日的
显式 lot；T+0 是否允许同日卖出完全由规则和 SellabilitySnapshot 决定，不按名称、代码
前缀或证券类别猜测。请求量超过当批可卖量时整单拒绝，并区分
`T_PLUS_ONE_NOT_SELLABLE` 与 `INSUFFICIENT_SELLABLE_QUANTITY`。非整手卖出只在显式
`FULL_SELLABLE_REMAINDER` 策略下、且一次卖出全部 eligible remainder 时允许。

涨跌停价格本身不表示封板。只有快照的显式 lock state 才能阻止对应方向；因此达到上限
但存在 ask 且未 `UPPER_LOCKED` 时仍可买入。订单和层级必须已经 tick 对齐且处于显式
daily/dynamic price range，系统不会把它们 round 或 clamp 到边界。北交所等特殊规则不在
本节点硬编码，必须新增带 effective/version/source 的配置。

## 规则来源与版本

规则配置应保存交易所及基金相关官方交易规则、实施细则或业务公告的 source 标识、版本、
生效区间和可用时间。上交所、深交所的交易规则入口及其基金交易细则是股票与场内基金
配置的官方依据；具体条款在接入时按证券类别、市场和生效版本登记。交易所规则会随证券
类别和版本变化，文档中的 fixture 数值不是当前市场政策的永久复制。

场内黄金、债券、跨境、货币等 ETF 可能与股票 ETF 采用不同的 T+0/T+1 规则，因此
`same_day_sell_policy` 必须逐规则配置。NAV/iNAV 仍然只是点时研究/参考字段，不是
可执行价格。基金管理费、托管费和 NAV 内费用不进入本二级市场 matcher；stamp duty 等
也只能作为配置的 SELL-only fee component，不在代码中永久硬编码。

## 结构完整性与可信重放

`BatchMatchResult.validate_integrity()` 和 `revalidate_batch_match_result` 只验证候选
对象自身的类型、字段关系和 canonical digest。候选对象自己计算出的 digest 是可追溯
元数据，不是真实性签名，不能在没有原始输入的情况下证明成交价、成交层级或容量真实。

需要验证可执行价格语义时，调用公开的
`verify_batch_match_result_against_inputs`，提供原始 orders、snapshot、rules、可选
sellability、fee schedule 和 slippage model。该函数先做结构重验证，再使用这些外部信任
的输入确定性调用 `match_orders`，比较完整 batch digest。若输入和输出都被同时篡改并
重新计算 digest，单靠本节点无法识别；外部签名或不可变 registry 才能提供该锚定能力，
不属于 P5-N11。

## 安全边界

Phase 0-6 只允许回测和模拟。执行模型固定 `simulation_only=True`、
`execution_capability=BACKTEST_ONLY`，不保存账户、券商或凭据字段，也不提供外部订单
调用路径。真实执行能力必须属于后续阶段的独立审批、隔离和审计范围，本节点不会提前引入。
