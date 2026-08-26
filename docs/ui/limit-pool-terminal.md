# P6-N03 涨跌停与连板终端

## 数据边界

- 页面只读取 `limit_pool_terminal_snapshots_v2` 中已物化的 Phase 2 算法结果。
- 不从日线价格反推封板、开板、连板或晋级事实；没有快照时显示明确空态。
- 查询同时约束 `event_time <= asOf` 与 `available_time <= asOf`，历史点时不读取未来修订。
- 同一事件时点、池算法版本、梯队算法版本、规则版本、物化器版本和修订出现不同载荷、可得时间或 provenance 时查询失败关闭。
- 未指定版本但同一时点存在多个版本向量时，接口要求用户完整指定池算法、梯队算法、规则和物化器四元版本；不接受部分版本条件。
- `emotion_core.limit_pool.materialize_terminal_snapshot` 是唯一 canonical 投影边界，池算法和规则版本绑定上游不可变快照，摘要覆盖完整版本向量与载荷，`processing_time` 由调用方显式提供。
- `data_worker.jobs.limit_pool_terminal.materialize_and_persist_terminal_snapshot` 是生产物化入口，通过受控 ClickHouse writer 写入 V2 表。
- `limit-pool-terminal-materialize` 是仓库可运行的 composition root：严格读取有界 JSON 请求，构造 canonical 上游快照并写入 ClickHouse。Local Compose 仅使用 `data/fixtures/limit-pool-terminal-local.json` 脱敏样例，生产环境必须由上游任务提供请求文件。

## 晋级率语义

`promotionRateBps = promotedCount / previousDayEligibleCount * 10000`，四舍五入到基点。分母为零时返回 `null`，页面显示 `-`，不以零冒充无晋级。

## 终端状态

- 当前模式每 30 秒刷新；历史模式不轮询。
- 当前快照 90 秒内为实时，91–300 秒为延迟，超过 300 秒为陈旧且明确标注“非实时”。
- 页面提供加载、空、错误、无权、部分数据和成功状态。
- 大池使用固定行高与 overscan 的语义表格窗口化；表头暴露 `aria-sort`，证据按钮和抽屉支持键盘操作。

## 导出与安全

- CSV 只导出当前筛选及排序后的记录，并携带算法版本、规则版本、修订、来源版本和证据 ID。
- 可重复的隔离烟测：`node scripts/ci/limit-pool-terminal-smoke.mjs` 验证 PIT 与冲突；`node scripts/ci/limit-pool-terminal-runtime-smoke.mjs` 验证真实 Data Worker CLI 写入。两者都创建随机临时数据库并在结束时整库删除，不接触业务库。
- Phase 0–6 只提供研究终端；本节点不引入 Broker SDK、真实账户凭据或真实下单路径。
