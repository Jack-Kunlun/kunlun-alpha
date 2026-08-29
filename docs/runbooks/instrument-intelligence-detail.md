# 个股 Intelligence 详情运行手册

## 边界

该接口只聚合研究数据，响应固定声明
RESEARCH_ONLY_NO_REAL_ORDER_PATH。它不包含账户、订单、成交、Broker SDK
或 QMT 调用。

## 接口

除健康检查、Prometheus metrics 与 API 根路径外，控制面接口默认要求有效的本地管理员会话；
首次登录配置见 `docs/runbooks/local-authentication.md`。

- 当前点时：GET /api/v1/instrument-intelligence/600519.SH?mode=CURRENT
- 历史点时：
  GET /api/v1/instrument-intelligence/600519.SH?mode=HISTORICAL&asOf=2026-08-25T08:00:00Z
- 日 K 线：
  GET /api/v1/instrument-intelligence/600519.SH/bars?mode=CURRENT&limit=250

日 K 线响应使用 `instrument-bars-v1`，固定为 `interval=DAILY`、
`priceType=RAW`，`limit` 为 1–500，缺省 250。每根 bar 的 OHLCV、成交额及
时间字段保留为字符串；返回按交易日期升序，且仅来自
`bars_daily_v2`。历史查询会在所有 revision/source winner 选择前同时过滤
`event_time`、`available_time`、`processing_time <= asOf`，不会通过 `FINAL`
掩盖点时语义。同一 identity + replacement version 的指纹冲突会 fail-closed。
响应的 `sourceVersions`、`evidenceIds`、`dataCutoffTime` 与
`freshnessSeconds` 用于解释来源和新鲜度，`dataMeaning` 固定为
`RESEARCH_ONLY_NO_REAL_ORDER_PATH`。

历史模式不会缺省回退到最新数据。所有读模型必须同时满足各自的
available_time 与 processing_time 门槛。

## 一致性

PostgreSQL 的主数据、板块、事件、席位、Claim 与证据在一个
REPEATABLE READ READ ONLY 事务内批量读取。ClickHouse 的行情、情绪和
特征共享同一个 effectiveAsOf，但两个数据库无法形成分布式事务，因此响应
明确标记 BEST_EFFORT_CROSS_STORE。

## 数据状态

- AVAILABLE：存在满足点时门槛的持久化数据。
- EMPTY：存储可用，但该点时没有记录。
- UNAVAILABLE：存储或完整性校验失败。系统不会使用前端夹具或 latest 回退。

## 配置

- INSTRUMENT_INTELLIGENCE_POSTGRES_DSN
- INSTRUMENT_INTELLIGENCE_CLICKHOUSE_URL
- INSTRUMENT_INTELLIGENCE_CLICKHOUSE_DATABASE
- INSTRUMENT_INTELLIGENCE_CLICKHOUSE_USER
- INSTRUMENT_INTELLIGENCE_CLICKHOUSE_PASSWORD
- INSTRUMENT_INTELLIGENCE_CLICKHOUSE_TIMEOUT_MS

未设置专用变量时，读取器可复用 Event Intelligence PostgreSQL 与 Emotion
ClickHouse 的连接配置。

## 故障排查

1. 确认 Server migrations 5、6、7 已执行。
2. 检查响应中具体 section 的 unavailableReason。
3. PostgreSQL 故障会使其负责的 section 一起不可用，以避免混合数据库快照。
4. ClickHouse section 独立失败，不影响其他 section。
5. 证据 URL 只允许 http 或 https；其他 locator 仅以引用标识展示。
