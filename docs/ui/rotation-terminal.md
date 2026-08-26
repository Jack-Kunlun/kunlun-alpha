# P6-N04 轮动与热点终端

## 范围

`/rotation` 复用已验收的 Phase 2 情绪/轮动回放 API 与 Phase 3 事件情报 API，提供热点生命周期、板块交叉事件、同源对比、结构化事件证据和历史回放。终端不重新计算轮动、热点或板块生命周期，也不产生 `Signal`、`OrderIntent` 或真实订单。Emotion 旧调用未传 `asOf` 时兼容为所选上海交易日结束；仓储内部始终收到明确截止点，不存在关闭可得时间过滤的模式。

## 数据来源

- `GET /api/v1/emotion/snapshots`：交易日情绪快照，服务端按 `available_time <= asOf` 截断。
- `GET /api/v1/emotion/rotation-events`：板块交叉与衰减事件，服务端按 `available_time <= asOf` 截断。
- `GET /api/v1/event-intelligence/hot-topics`：指定 `asOf` 的最新热点生命周期快照。
- `GET /api/v1/event-intelligence/events`：按热点引用的 `eventIds` 分批精确查询，并按 `available_time <= asOf` 截断。

页面中的热点图形和明细表共同使用 `buildTopicComparison` 的确定性排序结果。所有可见时间统一转换为 `Asia/Shanghai`。情绪和轮动查询先在服务端按持久化 `available_time` 截断，再由页面按 `timestamp`、`evidenceEnd` 做防御性校验；结构化事件按热点引用 ID 跨日分批读取并按 `availableTime` 截断，热点按 `decisionTime` 截断。事件接口的日期筛选边界固定为 `Asia/Shanghai`，不依赖 PostgreSQL 会话时区。

所有显式 `asOf` 只接受带 `Z` 或明确 offset、且日历日期真实存在的 RFC3339 instant；`-00:00` 这类未知 offset 不作为确定时点接收。PostgreSQL 读取 JSONB 后按照生成的 MarketEvent 与 HotTopicSnapshot Schema 执行闭合对象校验，包括事件证据、模型溯源、热点组件、计数和 `eventIds`；畸形持久化载荷会以受控数据源错误失败关闭，不进入页面可信状态。

## 数据断点

接口部分失败、晚于回放点的记录、无效时间，以及热点引用但点时查询未返回的事件证据都会进入连续性提示。即使全部记录被截断为空或所有来源都失败，连续性提示仍保持可见。热点接口按服务端上限请求 100 条；达到上限时页面降级为 `partial` 并明确提示生命周期统计可能不完整。页面不插值、不补线，不以动画隐藏数据缺口；热点证据缺失时也不会使用替代事件补齐。

## 状态与安全

页面覆盖 loading、empty、error、forbidden、partial 和 success。证据详情保留事件 ID、证据 ID、来源版本、算法/模型版本和证据窗口。所有信息标记为研究用途；Phase 6 路径不包含 broker SDK、QMT 或真实订单调用。
