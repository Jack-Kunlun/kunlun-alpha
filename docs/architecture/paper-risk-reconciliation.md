# 模拟交易风控与账簿对账

## 交易前风控

交易前决策在后端 `paper-core` 执行，并绑定 `accountStateDigest`、`executionStateDigest`、`policyDigest`、`intentId` 与 `riskDecisionId`。风控引擎不可用、模拟执行断连、最近一次对账不一致或不可用时一律拒绝。

检查还覆盖单笔名义金额、目标集中度、当日换手、活动订单数、现金缓冲和永久模拟隔离。订单检查事件必须携带 `riskDecisionId` 与 `riskPolicyDigest`；部署适配器只允许通过 `create_risk_check_event` 创建检查事件，不接受客户端提交的 `accepted` 字段。

## 交易后账簿

`project_execution_book` 从期初现金和持仓开始，按 `available_time` 与 `fillId` 顺序独立重放成交。买入减少现金并把成交金额与费用计入持仓成本；卖出增加扣费后现金，并按当前平均成本减少持仓成本。

完全重复的 `fillId` 只计一次，不同内容复用同一 `fillId` 直接拒绝。`reconcile_paper_books` 分别报告现金、持仓数量和持仓成本差异。任一差异都会把状态置为 `DRIFTED`，后续交易前风控保持关闭，直到产生新的 `MATCHED` 结果。

## 安全边界

全部逻辑只处理 `PAPER_ONLY` 数据，不接入 broker、真实账户或真实订单。金额计算使用 `Decimal`，对账时间必须为带时区的点时截止时间。
