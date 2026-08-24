# P4-N02 席位别名解析口径

## 范围

P4-N02 只对已经存在的 `SeatProfile` 与 `Alias` 做确定性候选解析。解析不会修改席位档案、别名或历史记录；结果只表达自动建议、人工审核或拒绝。

## 版本与规范化

- `NormalizationPolicy.version`: `seat-normalization-v1`。
- `ResolutionPolicy.version`: `seat-resolution-policy-v1`。
- `algorithm_version`: `seat-resolution-v1`。
- 输入先做 Unicode NFKC，全半角统一；再做 `casefold`，删除 Unicode 空白，并删除末尾常见后缀 `证券营业部`、`营业部`、`营业厅`、`分公司`。
- 规范化键只用于比较，绝不用于生成 `seat_id`。
- 相似度使用标准库实现的 Levenshtein similarity，结果量化到四位小数，输出按 `score`、`seat_id` 稳定排序。

## 自动决策阈值

当前 `ResolutionPolicy` 固定为：

- `auto_score_threshold = 0.9000`。
- `minimum_margin = 0.0500`，最高候选必须领先第二候选至少此间隔。
- 黄金样本准确率门槛 `golden_accuracy_threshold = 0.9500`，由 resolution 测试计算并断言。

版本化黄金样本位于 `python/packages/seat-core/tests/resolution/fixtures/golden-v1.json`，fixture 版本为 `seat-resolution-golden-v1`，共 20 条样本，覆盖正例、改名、全半角、机构、低置信、同名/规范化碰撞、类型冲突、未来和过期点时数据。黄金样本准确率分母固定为全部 20 条；正确项必须同时满足 `expected_status` 和（存在时）预期 seat identity，门槛为 `0.9500`。`REJECT` 仅表示没有任何 PIT 有效候选；存在候选但被低置信、歧义或类型门禁阻断时必须是 `REVIEW`。

只有最高候选达到分数和领先间隔、没有机构/营业部类型冲突、且 profile 不是 `UNKNOWN` 时才产生 `AUTO`。以下情况全部产生 `REVIEW`：低置信、并列或间隔不足、类型冲突、未知席位。只有在 decision time 没有任何可用且业务有效候选时产生 `REJECT`；低分候选不能因为分数低而被静默丢弃。

## 点时与证据

候选必须同时满足：

- `alias.available_time <= decision_time`。
- `Alias.is_valid_at(decision_time)` 为真，采用半开区间 `[valid_from, valid_to)`。
- 关联 `SeatProfile` 也已 available 且在 decision time 有效。

每个候选保留 `seat_id`、分数、规则命中、alias id/原始名称、来源、证据标识及 available/valid 时间。

## 人工审核与审计

`ReviewQueue` 和 `ResolutionAuditLog` 是 frozen value object；入队、决策和记录操作返回新实例，不覆盖旧值。同一个 `request_id` 的相同载荷重复提交幂等；不同载荷或不同决策拒绝并抛出冲突错误。

人工决策必须提供 `reviewer`、时区感知的 `reviewed_at`、`reason`、`algorithm_version`、`policy_version`、原始输入名称和 evidence ids。批准的 seat 必须来自候选集合；拒绝不携带 seat id。
