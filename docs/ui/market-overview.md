# 市场总览 P6-N02

## 边界

`GET /api/v1/dashboard/market-overview` 只提供研究与模拟决策所需的点时投影。它不连接 Broker，不生成 `OrderIntent`，风险温度也不是订单风控结论。

## 点时与数据来源

- 省略 `asOf` 为当前模式；服务端固定请求时点，页面每 30 秒刷新。
- 传入带时区 RFC3339 `asOf` 为历史模式；页面不轮询。
- bars 与 emotion 查询都先限制 `event_time <= asOf`、`available_time <= asOf`，再选择当时可见的最新修订。
- bars 按完整语义身份检查同版本 fingerprint 冲突，再选择最大 `replacement_version`；同一事件出现跨 source、source version、data version 或 session 歧义时失败关闭，不隐式选赢家。
- 情绪算法版本由 `DASHBOARD_EMOTION_ALGORITHM_VERSION` 明确选择，不按版本字符串猜测最新版本。
- 指数为 `000001.SH`、`399001.SZ`、`399006.SZ`；宽度宇宙版本为 `ashare-code-pattern-v1`，按交易所规范代码段识别 A 股样本。
- 成交额以 ClickHouse `Decimal` 汇总并以十进制字符串传输，前端不转为浮点金额。

## 时效与失败语义

当前模式以最保守的数据截止时间判断：市场宽度与成交额先取所有成分最后更新时间的最小值，全局再取所有区域截止时间的最小值。90 秒内 `FRESH`，90–300 秒 `DELAYED`，超过 300 秒 `STALE`。历史模式固定显示 `HISTORICAL`。没有任何区域数据时为 `NO_DATA`；部分区域缺失为 `PARTIAL`，页面明确显示“无可用数据”，不补零。

ClickHouse 请求默认 5 秒超时；断流或超时直接返回错误，前端显示“市场数据流中断”，不会回退到演示数据。每个快照带 `schemaVersion`、源版本、证据标识、请求点时和数据截止时间。

Server 的 `terminal:read` 默认拒绝。仅隔离的本地 Compose 显式设置 `DASHBOARD_TERMINAL_READ_POLICY=public`，对应 P6-N01 的匿名 viewer；其它部署必须保持 `deny`，直到接入受信身份适配器，不能依赖前端角色。

## 风险温度

`market-risk-temperature-v1` 只基于版本化情绪得分分为 `CALM`、`WATCH`、`STRESSED`。当前情绪数据超过 300 秒或缺失时状态必须为 `UNKNOWN`。
