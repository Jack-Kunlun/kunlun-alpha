# P5-N12 组合会计与绩效

## 边界与非目标

P5-N12 提供不可变、追加式、FIFO 的回测组合账本，以及独立的
`quant_core.metrics` Decimal 绩效计算。组合对象固定为
`ExecutionCapability.BACKTEST_ONLY`；本节点不产生真实券商、QMT、网络或实盘下单
路径，也不改变 P5-N10/P5-N11 的撮合实现。

## 信任边界与不可变历史

结构校验和事实校验是两层不同的职责：

- 结构校验只验证候选 dataclass 的字段、Decimal 类型、账务平衡、事件链摘要、资产
  恒等式和状态内部一致性。`revalidate_portfolio_state` 明确只做这一层，不能证明
  候选状态来自真实历史。
- `PortfolioHistoryRef` 将状态绑定到 `tape_id`、事件数量和事件 tape digest。
  `TrustedPortfolioEventSource` 是只读注入端口，由账本外的编排器/存储实现；它按
  引用返回精确的不可变事件 tuple。`verify_portfolio_state_from_source` 从 genesis
  重放该 tape，并比较完整规范状态。

所有公开的状态消费路径都必须先使用注入的 trusted source 验证前置状态，包括事件
应用、成交结算、公司行为、应收结算、权威卖出可用性导出和估值。`create_portfolio`
会写入真实的 initial-capital journal/applied record，而不是用空事件的正资本状态
冒充 genesis。应用新事件返回带新引用的状态；编排器必须先把新的追加 tape 持久化到
trusted source，再把该状态交给下一次公开调用。

这里的 source 是信任锚，不是候选对象自己携带的包装器。哈希能发现候选状态或事件
被改写，但进程内无法检测调用方同时替换 trusted adapter 和它返回的全部数据；这是
必须由进程外存储、权限和审计解决的边界。
带下划线的内部事件应用函数仅供 genesis 和 trusted-source replay 使用，导入这些
内部函数属于不受支持的用法；其输出在重新通过 trusted source 验证前永远不是权威状态。

## P5-N11 执行输入边界

`ExecutionReplayBundle` 只携带 engine-owned `ExecutionArtifactRef`、候选
`BatchMatchResult` 以及非信任标识符，不再携带并自称原始订单或规则。公开结算必须
注入 `TrustedExecutionArtifactSource`，按 artifact id 和 expected input digest
解析精确的原始订单、行情快照、撮合规则、卖出可用性、费率、滑点以及外部来源/配置
摘要。解析后的 `TrustedExecutionInputs` 会重新计算 canonical input digest，并由
`verify_batch_match_result_against_inputs` 校验候选成交。

`BuyCashReservation` 绑定 order id/digest、费率摘要、artifact id 和 trusted
execution-input digest。BUY 与 SELL 都必须使用该 source；SELL 还必须证明候选卖出
可用性与 trusted snapshot 的可用性完全一致。重建 bundle、替换 quote snapshot 或
价格后重新计算所有候选摘要，不能通过原 artifact source 的校验。调用方协同替换
artifact adapter 与所有输入的限制与组合历史 source 相同，不能在进程内消除。

## 账务、FIFO 与终态订单

每个 `LedgerEvent` 必须满足：

```text
sum(debits) = sum(credits)
```

现金买入先冻结现金，成交后转为持仓成本和费用；卖出把持仓成本转为 sale
receivable，并以 FIFO lot cost 计算 realized PnL；应收必须由显式 settlement event
释放。`_consume_fifo` 用一次遍历构造剩余 lots，不在收缩列表上继续使用旧 index。每
次部分分配使用配置的量化单位，最后一个精确闭合的 lot 接收 residual，保证总成本不
丢失。FIFO 顺序为 `(acquisition_trade_date, lot_id)`。

在任何 settlement mutation 之前，如果 `order_id` 已在 `settled_order_ids`，BUY、
SELL、rejected 和 unfilled terminal result 都会被拒绝；因此重复终态结果不能再次
改变现金、lot 或费用。

## T+1 日历 lineage

`NextTradingDateResolution` 必须与 execution snapshot 的 `calendar_id`、
`calendar_version`、`calendar_digest` 和 source trading date 逐项相等。resolution
的 availability/provenance 时间不得晚于 `match_time`，且 next trading date 必须
严格晚于 source date。上述字段是 trusted execution input 的 digest 内容，不能用
重建或 rehash 后的替代日历绕过。

## 公司行为与 record-time entitlement

`PortfolioLot.acquisition_time` 来自 `Fill.match_time`，或来自显式公司行为 lineage；
只有 `acquisition_time <= record_time` 的 lot 才有现金/股票行动资格，同一交易日但在
record time 之后成交的 lot 不享有权益。

公司行为持久化 `source_id`、`raw_capture_id`、`action_id`、`lineage_id` 和版本。相同
action identity 的精确重复由 event tape 的 event idempotency 处理；不同 event id
再次使用相同 identity、重复 lineage、revision 或 correction 都拒绝。新 identity
才可以表示新的事实版本。

现金代替零碎股票时，即使 PnL 为零也必须产生平衡 posting：

```text
Dr CORPORATE_RECEIVABLE = explicit cash amount
Cr POSITION_COST        = allocated fractional cost
positive difference     -> Cr OTHER_CORPORATE_ACTION_PNL
negative difference     -> Dr OTHER_CORPORATE_ACTION_PNL
```

状态只减少一次 lot 数量/成本并增加一次 corporate receivable；posting 与状态聚合
必须同时满足账本恒等式。

## 估值恒等式

`PortfolioValuation` 的结构校验要求所有资产分量为精确 `Decimal` 且非负，并要求：

```text
nav             = available_cash + frozen_cash + sale_receivable
                  + corporate/dividend_receivable + marked_position_value
book_assets     = available_cash + frozen_cash + sale_receivable
                  + corporate/dividend_receivable + open_position_cost
unrealized_pnl  = marked_position_value - open_position_cost
total_pnl       = nav - initial_capital
total_pnl       = realized_pnl + unrealized_pnl + dividend_pnl
                  + other_corporate_action_pnl + fee_pnl
```

结构上自洽的伪造 NAV 仍可能不是历史事实。`verify_portfolio_valuation_against_state`
通过 trusted history source、原始 marks、cutoff 和 policy 重新计算并比较完整估值；
`value_portfolio` 在估值前验证 trusted predecessor state。

## Decimal metrics

`quant_core.metrics` 在本地 `decimal.Context` 中计算累计收益、年化收益、样本波动率、
wealth-index 最大回撤、Sharpe、Sortino 和 Calmar，不修改也不依赖调用方的全局
Decimal context。每个 `MetricStatus`/value 对都必须一致：`AVAILABLE` 必须有有限
Decimal，其他状态必须是 `None`。

空 NAV 仍会先完整校验 risk-free path，只跳过没有 NAV cutoff 时的相对 future-availability
比较；结构有效时所有 NAV 派生指标返回明确的 `INSUFFICIENT_SAMPLES`。非空样本继续
区分 missing、misaligned、future risk-free 失败及短样本状态。零波动、无 downside、
零回撤和缺失 risk-free 不通过异常伪装成可用结果。`PerformanceMetrics` 的结构摘要
只用于字段完整性和 traceability；公式真实性必须通过
`verify_performance_metrics_against_inputs` 使用原始 NAV、risk-free 和 policy 重算确认。

## Phase 0–6 安全边界

本模块仅允许模拟/回测能力。真实 broker credential、生产 QMT connection、可调用
real-order path 均不属于 P5-N12；任何此类需求必须停止并重新授权。
