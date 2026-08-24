# hotspot-core

`P3-N08` 的纯领域包：把版本化主题归属与已验证 `MarketEvent` 聚合为 point-in-time `HotTopicSnapshot`。

- HotScore 版本：`hot-score-v1`
- 时间窗：左开右闭 `(decision_time - lookback, decision_time]`
- 算法：纯整数 BPS，禁止浮点漂移
- 去重：同一 `event_id` 的完全相同投递幂等；冲突投递 fail-closed
- 未来数据：事件或主题归属在决策时点尚不可用时直接拒绝
- 历史：每个快照有内容寻址 `snapshot_id`，新算法或新策略不覆盖旧快照

事件数量只是样本量和有限饱和强度的输入，不直接等同于热点强度。评分同时考虑证据质量、时效、独立来源、
标的/板块广度和近期动量。完整公式见 `docs/algorithms/hot-score-v1.md`。
