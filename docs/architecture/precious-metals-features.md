# 贵金属基金特征 v1

本节点只消费显式标记为 `PRECIOUS_METALS` 的交易所上市 ETF、LOF、FUND，且只发布 `GOLD` 或 `SILVER`。分类必须为 `REVIEWED` 且置信度不低于 `0.80`；`OTHER` 永远拒绝。产品名称与展示型跟踪指数不会参与身份推断。

`PreciousMetalsPolicy` 是不可变的 v1 策略。iNAV 在决策时点不超过 5 分钟时优先使用；否则只允许使用决策时点可见且不超过 7 天的 NAV。滚动窗口为 20 个有效观测，配对、换手和 beta 至少需要 10 个样本。每个 benchmark identity 必须在调用方显式配置允许的 `priceBasis` 和 currency，策略没有全局默认值。

五个特征分别发布溢折价、跟踪差异、跟踪误差、20 日成交额中位数和 benchmark beta。所有计算在显式 Decimal context 中完成，并固定量化到 6 位小数。beta 是 v1 唯一的宏观敏感度表达，其他宏观因子不在本节点的公共点时契约内。

每个结果都保留 source、source revision、raw object、payload digest、event/available/processing time、源记录 ingest time、FeatureSpec、algorithm、policy 和 source-contract 版本。在线事件的 `ingest_time` 是受信任到达时间，不能覆盖 lineage 的源记录 ingest time；在线计算的决策时点来自 engine processing context，payload 的 processing time 只进入 provenance，若晚于 engine 时钟则结果为 future/unavailable。

算法内部先在 Decimal context 中量化到 6 位小数；`FeatureResult.value` 和纯计算结果保留该内部精度，Batch、Online、history 和 Parquet wire 使用 canonical normalized Decimal string，移除无意义尾零，例如 `490000`、`110.5`。Batch engine 的既有序列化契约保持不变。

Batch 与 Online adapter 只负责将引擎事件规范化为 `PreciousMetalsFeatureInput`，随后调用同一个纯 calculator。历史结果不会被新策略覆盖；未来版本必须通过新的 policy 或 algorithm version 产生新的结果。
