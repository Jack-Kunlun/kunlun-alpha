# 日线入库概览运行手册

## 当前能力

`GET /api/v1/data-quality/market-coverage` 提供 ClickHouse `bars_daily_v2` 的只读观测切片，
前端入口位于数据质量页面的“日线入库概览”区块。它只统计 `interval = DAILY`、
`price_type = RAW` 且来源属于以下集合的记录：

- `tushare-pro`
- `akshare-tencent`
- `akshare-sina`
- `akshare-eastmoney`

默认窗口是上海时区当天向前包含当天的 90 个自然日；调用方可以传单日 `date`，或同时传
`dateFrom` 与 `dateTo`。窗口最大为 366 个自然日，`date` 不能与范围参数混用，范围不能只
传一端。可选的 `source` 与 `unifiedCode` 过滤器会保持参数化查询。

响应固定为 `market-data-coverage-v1`，并声明 `scope = DAILY_RAW_SUPPORTED_SOURCES`、
`meaning = OBSERVED_ONLY`。每行按 `unifiedCode + source` 分组，`observedBarDays` 是去重后的
交易日数，而不是物理行数；同时返回首末交易日以及 `event_time`、`available_time`、
`processing_time` 的各自最大值。三个最新时间可能来自不同记录，不能被解释为同一条记录的
联合版本。服务对三类时钟使用一次固定的 `asOf`，并统一要求不晚于该时刻。

服务最多读取 101 行，响应最多返回 100 行；超出时 `truncated = true`，页面提示缩小日期、
来源或证券筛选。表格时间统一转为上海时区；空值或不可用值显示“未知”。

## 故障边界

- 非法日期、单边范围、超过 366 日、重复数组参数、未知参数和非后缀式证券代码返回 400。
- 全局认证守卫仍保护路由；数据质量模块授权失败返回 403。
- ClickHouse 未配置或查询/响应校验失败返回受控 503，不返回原始异常、路径、DSN 或凭据。
- UI 的基金质量事件和日线入库概览分别维护 loading、empty、error、forbidden 状态；质量事件
  空态只表示当前条件下没有已记录事件，不表示行情完整或系统健康。

## 明确不包含的语义

入库概览与逐日明细不承担行情拒绝证据查询（该能力见独立运行手册）、交易日缺口检测、来源差异对账、全市场证券全集，也不做价格版本
winner/qualified 判定；不会以物理行数冒充 Bar 覆盖率，不使用 `FINAL`，不启动采集、不建表、
不执行迁移，也不产生任何下单能力。因此它是本次 P1-N12 节点的观测切片，不代表整个 P1-N12
数据质量与对账面板或 Phase 1 正式完成。

## 逐日已观测明细

新增接口 `GET /api/v1/data-quality/market-coverage/days`，使用相同的日期规则，
但 `source` 与 `unifiedCode` 都必须指定。页面从概览行进入“查看已入库日期”。
逐日明细已随 `2cf1f91` 更新到现有本地部署，并通过真实入库日期的只读适配器查询验证。
尚未进行登录后的浏览器交互验收；具体范围见[本地部署记录](../reviews/2026-09-05-calendar-and-data-quality-deployment.md)。

响应版本为 `market-data-coverage-days-v1`，含义仍为 `OBSERVED_ONLY`。
`days` 只含实际观测到的日期，按日期升序且唯一，最多 366 项，不补齐日历日期。
重复或修订的物理行合并为一个观测日期；停牌标记不会使已存在的 Bar 被排除。
每天的三个最新时间各自聚合，不能当作某一条原始记录的版本信息。

明细固定本次服务端查询时间，并要求所有输入记录的三类时间均不晚于该时刻。
客户端不能指定 `asOf`。它不是之前汇总的冻结快照；并发入库可能导致与先前汇总的数量
不同，应以各自显示的查询时间解释，不承诺历史存储快照不可变。

以下请求只读，不启动采集：

```text
GET /api/v1/data-quality/market-coverage/days?unifiedCode=600519.SH&source=tushare-pro&dateFrom=2026-09-01&dateTo=2026-09-04
```

成功响应的结构（日期和时间仅为格式示例）：

```json
{
  "schemaVersion": "market-data-coverage-days-v1",
  "scope": "DAILY_RAW_SINGLE_SUPPORTED_SOURCE",
  "meaning": "OBSERVED_ONLY",
  "window": {
    "dateFrom": "2026-09-01",
    "dateTo": "2026-09-04",
    "asOf": "2026-09-05T02:00:00.000Z"
  },
  "unifiedCode": "600519.SH",
  "source": "tushare-pro",
  "days": [
    {
      "date": "2026-09-03",
      "latestEventTime": "2026-09-03T07:00:00.000000Z",
      "latestAvailableTime": "2026-09-03T07:01:00.000000Z",
      "latestProcessingTime": "2026-09-03T07:02:00.000000Z"
    }
  ]
}
```

`days: []` 只表示本查询没有观测日期，**不表示无缺口或数据完整**。
缺少证券/来源、未知或重复参数、非法或过长日期范围返回 400；授权拒绝返回 403；
未配置、读取失败或异常结果返回受控 503，不能以空列表代替不可用。
本次新增端点不改变旧概览端点的响应版本，也不新增存储、权限或依赖。

## 只读核验

自动化测试不连接真实 ClickHouse。实现完成后，另由主代理使用现有 ClickHouse 只读连接执行
临时派生表 fixture，覆盖重复日期、未来的三类时间、未知来源、`MINUTE_1`、QFQ、证券和日期
筛选；该核验不创建表、不写入数据。实现侧定向验证命令及结果见
`docs/reviews/2026-09-05-market-data-coverage-evidence.md`。
