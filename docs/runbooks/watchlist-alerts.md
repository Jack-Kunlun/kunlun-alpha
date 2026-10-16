# 自选规则与站内预警运行手册

## 能力边界

该能力只接受固定字段、固定比较运算符和十进制定点阈值，不执行用户代码或任意表达式。通知仅写入站内可靠投递表，不接入短信、邮件或真实交易路径。

## 配置

- `WATCHLIST_ALERTS_POSTGRES_DSN`：规则版本、评估历史和通知投递表使用的 PostgreSQL 连接串。
- `WATCHLIST_ALERTS_OWNER_REF`：本地单用户研究终端的服务端所有者标识。客户端不能提交或覆盖该值。
- `WATCHLIST_ALERTS_EVALUATION_INTERVAL_SECONDS`：最新日线评估间隔。`0` 关闭；启用时必须为
  10–3600 秒。本地 Compose 缺省 60 秒。

任一启用环境都必须同时配置两项。设置所有者但缺少数据库连接时，服务拒绝启动；所有者缺失时，接口拒绝访问。

## 数据与恢复

- 规则变更追加新版本，不覆盖旧版本。
- 页面提供创建和编辑入口的自动评估字段仅为 `LAST_PRICE` 与 `CHANGE_BPS`。编辑只接受规则名称和十进制阈值，其他规则属性沿用当前版本。
- 已保存的 `EMOTION_SCORE_BPS` 与 `FEATURE_VALUE` 规则保留原字段和值；页面标记为“本版本不自动评估”，不展示阈值预览，也不会由日线调度器评估。
- 同一 `ruleId + revisionId + eventId` 只产生一条评估历史和一条通知。
- 评估按 `availableTime` 执行免打扰和节流，展示时区固定为 `Asia/Shanghai`。
- 通知失败保留为 `FAILED`，不会删除已触发历史。恢复投递前应先核对 `notificationId`，避免重复展示。
- 站内通知读取通过 `GET /api/v1/watchlist-alerts/notifications` 完成，最多返回最近 100 条；
  `unreadCount` 对所有持久通知计数，不受返回窗口截断影响。
- 单条和全部已读分别使用 `POST /api/v1/watchlist-alerts/notifications/:notificationId/read`
  与 `POST /api/v1/watchlist-alerts/notifications/read-all`。迁移版本 10 把首次已读时间写入独立的
  `watchlist_notification_receipts`，重复操作幂等，不覆盖 outbox、评估历史或首次已读时间。
- 通知列表、未读计数和已读写入都由服务端 `owner_ref` 限定；客户端不能提交或切换 owner。
- 后台和页面“立即评估最新行情”只自动处理 `LAST_PRICE` 与 `CHANGE_BPS`；每个证券只读取
  最近两根严格点时日线。`eventId` 绑定证券、最新 bar 证据和字段，相同 bar 重跑保持幂等。
- `EMOTION_SCORE_BPS` 与 `FEATURE_VALUE` 保留为受控规则/预览能力，但当前不会由日线调度器
  自动评估；运行摘要会把它们计入 `skippedUnsupported`，不会用零值替代。
- 同一事件身份若带不同证券、时间或观测值重放，服务返回冲突，不会把不同事实静默当成重复。

## 编辑规则与冲突恢复

使用 `POST /api/v1/watchlist-alerts/rules/:ruleId` 追加名称或阈值修订。请求体只允许以下四个字段：

```json
{
  "clientRequestId": "edit-rule-<stable-id>",
  "expectedRevision": 3,
  "name": "贵州茅台价格提醒",
  "threshold": "1532.50"
}
```

`expectedRevision` 必须是安全范围内的正整数，阈值为最多 8 位小数的十进制文本。成功仍返回完整工作区；新修订保留证券、启停状态、比较符、免打扰、节流、通知渠道和创建时间，并通过 `previousRevisionId` 指向旧修订。旧修订与已记录历史不会被覆盖。

同一所有者、规则路径、`clientRequestId` 和请求体的重试只提交一次；网络结果不确定时，客户端应原样重试这组值。相同 ID 被用于不同路径或请求体、或 `expectedRevision` 已过期时返回 `409`。未知规则或其他所有者的规则返回 `404`，格式错误返回 `400`。刷新规则后再开始新的编辑；不要以更换请求 ID 的方式绕过 `409`。

新建和启停接口的请求与响应形状保持不变。

## 故障排查

1. 接口返回 `403`：检查 `WATCHLIST_ALERTS_OWNER_REF` 是否已配置。
2. 服务启动失败：检查数据库连接串是否存在，以及迁移版本 8、10 是否已执行。
3. 事件未触发：核对规则版本、证券代码、指标字段、免打扰时段和节流窗口。
4. 通知为 `FAILED`：保留历史证据，恢复站内投递端后按 `notificationId` 做幂等重试。
5. 自动评估没有记录：检查间隔配置、规则是否启用，以及对应证券是否至少有 1 根
   `LAST_PRICE` 日线或 2 根 `CHANGE_BPS` 日线。
6. 通知中心不可用：检查 read-receipt 迁移是否存在；不要删除 outbox 行来清除未读状态。

## 安全说明

规则输出仅用于研究提醒。该模块没有 broker SDK、账户凭据、订单接口或真实下单能力。
