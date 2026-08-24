# P4-N04 席位事件研究绩效特征

## 语义边界

本节点计算的是龙虎榜事件研究特征，不是可成交收益、组合收益、组合回撤或交易建议。结果不能解释为买入后一定可以成交的收益。涨跌停收盘价可以作为事件路径观测，但不代表成交。

公共入口是 `seat_core.features.compute_seat_performance`。它只接受不可变的 `Trade`、`DailyPriceObservation` 和窄 `TradingCalendarProtocol` 快照，不抓取价格、不访问 broker/QMT、不依赖 data-worker 或服务层。调用方可以在边界把 market-core 的公开 `StoredBar` 和 `TradingCalendar` 适配为这些类型，并负责先执行同一决策时点的 PIT 查询。

## v1 口径

- `PERFORMANCE_FEATURE_SCHEMA_VERSION` 为 `seat-performance-feature-v1`。
- `PERFORMANCE_ALGORITHM_VERSION` 为 `seat-performance-algorithm-v1`。
- 默认 policy 为 `seat-performance-policy-v1`，其 fingerprint 覆盖算法版本、日线 interval、adjustment、session、bar schema、calendar version、最小样本数、taxonomy、允许标签、风格样本阈值和份额阈值。
- 样本限定为指定 `seat_id`、闭区间 `[window_start, window_end]`、`net_amount > 0`、且 latest revision 在 `decision_time` 已可得的 Trade。
- `available_time == decision_time` 纳入；晚于 decision time 的 Trade 或 bar 不可见。
- `d0 = trade_date`，`dN` 是交易所日历向后的第 N 个交易日，不用自然日、不顺延缺失价格、不前填。
- `rN = P(dN) / P(d0) - 1`。T+1、T+3、T+5 是共同完整路径样本的 Decimal 等权算术均值。
- 胜率为 `count(r5 > 0) / n`，零收益不计胜。
- 单样本路径 MDD 为 d0..d5 收盘路径的峰值回撤，汇总 `max_drawdown` 取所有纳入样本中最差值。
- `n < policy.min_samples` 时保留 `sample_count`、样本路径和排除诊断，但 `performance` 与 `preference` 为 `None`。

## PIT、修订和价格序列

Trade revision 不以 `trade_id` 作为 lineage key。每个 `source` 命名空间内，先按 `available_time <= decision_time` 过滤，再在调用方提供的 visible 完整链上以 `(source, revision_id)` 和 `previous_revision_id` 构建连通图；`previous_revision_id is None` 的根 revision 定义稳定 lineage identity，唯一 terminal 的最新 Trade 可以拥有不同于 predecessor 的 `trade_id`。visible successor 缺失 predecessor、重复 revision、revision fork、循环、坏顺序或多个 terminal 都 fail-closed，不能把旧 revision 和新 revision 双计。decision time 之后的 revision 完全不参与图校验、诊断或结果，因此未来 fork/cycle/bad order 不影响过去结果。

每条样本必须有 d0..d5 六个合格价格。价格必须来自单一 `DAILY`、明确 adjustment、session、schema、source、source_version 和非空 `data_version` 的序列；`DailyPriceObservation` 的 semantic bar identity 至少包含 instrument、时区感知 `event_time`、interval、adjustment/price type、session、source、source_version、data_version 和 schema。`replacement_version` 只在完全相同 semantic identity 内比较；同一 trade date 出现不同 event time 或其他 semantic identity 时为歧义，不能直接取最大 replacement。跨日期 sequence identity 不含 event_time、raw_capture_id、replacement_version 或可选来源 revision，避免把不同日期的 replacement 误判为混序列。对同一 semantic identity 只选择决策时点可见的最高 `replacement_version`；同最高版本冲突或跨序列混用会排除整条样本。停牌、缺失、非正价格、PIT 不可见价格和序列歧义都有稳定 `ExclusionReason`，不会记零收益。

每个 `PerformanceSample` 保存纳入/排除状态、稳定原因、Trade lineage/root、Trade 的 revision、previous revision、source/source_version、raw_record_id、evidence_id、available time、完整 d0..d5 日期，以及选中的日线及其 `event_time`、`raw_capture_id`、`replacement_version`、source/source_version、data/schema version、suspended 和 available time，可据此重放输入选择；不编造不存在的 StoredBar revision 字段。输出同时保存 `decision_time` 和逻辑 `logical_available_time`；后者是实际纳入 Trade、bar 和有效 style 输入的最大 available time。没有任何有效输入贡献结果时为 `None`，不伪造为 decision time。

日线还保留受控 `limit_state`：`UNKNOWN`、`NONE`、`LIMIT_UP`、`LIMIT_DOWN`。涨跌停收盘价仍可纳入事件研究，但该字段只是事件观测 provenance，结果不表达可成交或成交成功。

## 受控风格偏好

风格只读取独立的、版本化的 `StyleObservation`。同一 `(source, observation_id)` 先按 decision time 过滤，再在 visible 完整 `previous_revision_id` 链上选择唯一 latest；revision ID 也只在 source 命名空间内解释。visible 断链、fork、cycle、重复 latest 或坏顺序 fail-closed。未来 style revision 完全不参与历史结果。系统不从 `listing_reason`、营业部名称或其他自由文本推断。只有 seat、闭区间 observation time、`available_time <= decision_time`、taxonomy 版本一致且 `style_tag` 在 policy `allowed_style_tags` 中的观察才进入计数。未知标签、窗口外观察和 taxonomy 不一致均保留带 source/source_version、evidence_id、available_time、observation/revision identity 的稳定诊断。

当有效风格样本达到 `min_style_samples` 且标签 share 达到 `min_style_share` 时输出受控标签、每个允许标签的 Decimal share、taxonomy 和 policy fingerprint；否则不输出 preference。

## 适配责任和重放

market-core 适配器应使用公开 `BarStorage.query_bars(..., as_of=decision_time)`，将 `StoredBar.bar.unified_code/date/close/interval/price_type/session/suspended` 和 `StoredBar.event_time` 映射到 `DailyPriceObservation` 的 instrument/date/close/interval/adjustment/session/suspended/event_time；将 `StoredBar.data_version` 映射到 `data_version`，并保留 `raw_capture_id`、`replacement_version`、source/source_version 和 `available_time`。`StoredBar` 当前没有 `revision_id` 或 limit-state 字段：适配器不得编造；revision provenance 可保持 `None`，limit state 没有可信来源时使用 `UNKNOWN`。适配器不得把不同 source、source_version、data_version、adjustment 或 schema 拼成一个序列，也不得把 decision time 之后的 row 传入特征计算器。

日历适配器的每次 `next_trading_day` 返回都必须严格晚于输入日期；非递增或非法日期会 fail-closed。调用方应同时记录日历快照版本，并将其纳入 request/policy provenance；v1 的窄协议不要求具体实现依赖 market-core。

所有 Decimal 计算不经过 float。结果是研究事实快照，必须和输入修订、bar provenance、algorithm version、policy version/fingerprint 一起保存；历史结果不可覆盖。
