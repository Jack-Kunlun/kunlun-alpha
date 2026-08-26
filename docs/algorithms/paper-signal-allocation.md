# 模拟账户信号分配

## 输入与输出

输入为同一决策时点可见的 `Signal`、模拟账户状态、证券行情和版本化分配策略。输出为目标持仓、`PaperOrderIntent` 与拒绝原因。输出只是模拟执行意图，不是订单，也不能发送到 broker。

## 决策顺序

1. 验证账户、Signal、行情和估值的 `available_time` 不晚于决策时点。
2. 同一证券存在相反方向时整组拒绝，不猜测净方向。
3. 拒绝低置信度和卖空 Signal。
4. 计算 `min(maximum_position_weight, max(score, 0) × confidence)`。
5. 总目标权重超过 `maximum_total_weight` 时按比例缩放。
6. 使用账户点时 NAV 和行情价格计算目标数量。
7. 买入和非清仓卖出按交易单位向下舍入；不足一个交易单位时不生成意图。
8. 买入资金不得占用策略现金缓冲，也不预支尚未成交的卖出收入。

## 确定性与解释

相同输入、账户状态摘要和策略摘要产生相同 `decisionDigest` 与 `intentId`。每个目标、意图和拒绝都携带来源 Signal、数量变化和原因，便于审计与重放。

## 安全边界

- `brokerExecutable` 固定为 `false`。
- `executionCapability` 固定为 `PAPER_ONLY`。
- 本模块不导入 broker SDK，不创建订单，不执行撮合。
- 现金、价格、权重和计算过程只使用 `Decimal`。
