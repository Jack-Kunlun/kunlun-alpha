# P4-N05 席位组合及受控题材共现历史表现

## 边界与版本

`seat_core.cooccurrence.compute_seat_cooccurrence` 是纯函数。它只消费已经由 P4-N04 生成的不可变 `SeatPerformanceFeature` 快照和可选的受控 `EventTopicMembership`，不抓取数据、不建立题材图、不推断因果、不产生交易信号，也不表示可成交收益。输出统一标记为 `descriptive_event_study` 和 `as_of_request_decision_time`。

v1 公开版本常量包括：

- `COOCCURRENCE_SCHEMA_VERSION`、`COOCCURRENCE_ALGORITHM_VERSION`、`COOCCURRENCE_POLICY_VERSION`
- `SEAT_EVENT_ID_ALGORITHM_VERSION`
- `TOPIC_MEMBERSHIP_SCHEMA_VERSION`
- `R7_QUANTILE_ALGORITHM_VERSION`
- `BOOTSTRAP_ALGORITHM_VERSION`
- `HASH_TO_INDEX_ALGORITHM_VERSION`
- `SEED_SERIALIZATION_VERSION`

`CooccurrencePolicy` 只接受上述当前 v1 常量，且固定 Decimal precision=`34`、rounding=`ROUND_HALF_EVEN`。policy 不能用伪造版本或不同 precision 声称另一套算法。

## 父快照和 SeatEvent

所有父特征必须严格共享 `schema_version`、`window_start`、`window_end`、`decision_time`、`algorithm_version`、`policy_version` 和 `policy_fingerprint`。不一致、重复 seat feature、非法父 sample 和全局输入预算超限均 fail-closed。

父 feature iterable 按 `max_parent_features + 1` 流式读取即拒绝，不先无界物化。输入 sample 总数包含 included 和 excluded sample，按 sample 逐项累计并在 `max_input_samples + 1` 立即拒绝。只使用 `sample.included is True`，因此 `INSUFFICIENT_SAMPLES` 父特征仍可贡献其完整路径样本。

Seat event 的 join key 是 `SeatEventKey(instrument_id, trade_date)`，与 P3 `MarketEvent.event_id` 完全不同。`seat_event_id` 使用版本化 canonical JSON（UTF-8、排序键、无空白）对 `instrument_id` 和 `trade_date` 做 SHA-256。运行时检查一个 hash ID 不得映射多个 SeatEventKey。P3 upstream event ID 仅作为题材 evidence 保存，不参与等值 join。

同一 SeatEvent 中必须有一致的 instrument/date、T+1/T+3/T+5 returns、path dates 和所有选中 bar 的 provenance/identity。不同 seat 的 Trade provenance 不参与 outcome 冲突比较；但 outcome 冲突会使整个请求 fail-closed。一个 seat 的重复 sample 只产生一次 membership/support，全部 Trade evidence 仍保留。

`k=1` 事件只产生 `isolated_event` diagnostic。`k > max_seats_per_event` 时整个事件排除，不截断、不生成部分 pair。其余事件生成恰好 `C(k, 2)` 个 canonical unordered pair，`left_seat_id < right_seat_id`，无 self edge 或有向重复。

## 题材条件化

`EventTopicMembership` 必须携带 SeatEventKey、topic、taxonomy ID/version、assignment version/fingerprint、source/source_version、evidence、timezone-aware available time 和可选 P3 upstream IDs。只有 `available_time <= decision_time` 且 taxonomy/source 在 policy allowlist 内的记录可进入条件化。

未来记录先过滤，不进入输出、fingerprint 或 diagnostic。完全相同 membership 去重；同一 `(SeatEventKey, topic_id)` 的可见 assignment 冲突产生 provenance diagnostic，并跳过该 conditioned key，裸 pair 保留。未知 taxonomy/source 同样只产生可关联 diagnostic，裸 pair 不受影响。

`max_topic_membership_records` 是全请求扫描预算。单事件 distinct topic 数超过 `max_topics_per_event` 时，本实现选择排除整个事件，记录 `event_topic_limit_exceeded`，不截断 topic，也不保留该事件的裸 pair。每个合法 topic 为 pair 生成一个 `pair + topic` key；无合法 topic 时仍生成裸 pair。

## 统计口径

每个 raw 或 conditioned key 的 events 按 canonical `seat_event_id` 排序，并对 T+1、T+3、T+5 分别输出：`count`、Decimal `mean/min/p25/p50/p75/max`。分位数使用 Decimal R-7 interpolation，不使用 float。

CI 是 alpha=`0.05`、resamples=`1000`、min samples=`5` 的 deterministic non-parametric bootstrap mean。算法在 local Decimal context 中使用 precision 34 和 `ROUND_HALF_EVEN`。seed 覆盖 policy fingerprint、canonical key、metric 和排序后的 event IDs；每个 replicate/draw 使用版本化 SHA-256 hash-to-index，不依赖 runtime random 或输入顺序。CI bounds 也使用 R-7。support 小于 5 时保留完整 distribution，CI 为 `None` 且状态为 `INSUFFICIENT_SAMPLES`。

## Provenance 和 PIT

每个结果 key 保存：排序后的 SeatEvent reference/key/ID algorithm version、参与 seat 的父 feature 版本/fingerprint、每个 seat 的全部 Trade `PerformanceSample` evidence、每个 event 独立关联的完整 selected bar path、条件化 topic membership 和逻辑 available time。`event_outcomes` 保留 event reference 与对应 bars；`shared_bars` 是按 event canonical 顺序展开的完整兼容视图。裸 pair 的 logical available time 是所有参与 event 的 Trade/bar 输入最大值；conditioned key 还纳入实际使用 topic membership 的 available time。

所有输出、diagnostic、统计、CI 和 fingerprint 都按 canonical 顺序生成。增加 decision_time 之后的 topic membership 不会改变过去结果；P4-N04 父 feature 已是 PIT 快照，调用方不得把未来父快照混入同一请求。

## Policy fingerprint 和预算

`CooccurrencePolicy.fingerprint` 覆盖 alpha、resamples、min CI samples、Decimal precision/rounding、canonical seed serialization、fingerprint/hash algorithms、event ID algorithm、topic schema、taxonomy/source allowlist，以及 `max_seats_per_event=32`、`max_parent_features=100000`、`max_events=100000`、`max_edges=100000`、`max_input_samples=100000`、`max_topic_membership_records=100000`、`max_topics_per_event=32`、`max_bootstrap_draws=5000000` 等预算。父 feature、topic 和 raw edge 都在流式增量边界预检；任一全局预算超限都在返回部分结果前抛出 `CooccurrenceInputError`。

`max_edges` 统计最终 distinct raw/conditioned output keys；raw key 在父事件收集时增量预检，conditioned key 按 SeatEventKey 索引生成并预检，超过后整个请求 fail-closed。统计前先计算所有满足 CI 最小样本数 key 的 `support * resamples * 3`，累计超过 `max_bootstrap_draws` 时不会调用任何 bootstrap。输出不会被截断，也不会以部分结果冒充完整研究快照。
