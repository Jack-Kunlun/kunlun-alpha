# 贵金属基金终端运行说明

## 当前能力

`GET /api/precious-metals/terminal` 聚合交易所上市贵金属 ETF、LOF 和基金的点时数据：

- PostgreSQL 中的基金分类、NAV、iNAV 和关联公开事件；
- ClickHouse 中的交易所日行情与版本化贵金属基金特征；
- 最新交易所成交额排名、估值参考时效、来源版本和证据标识；
- 当前点时与历史 `asOf` 回放。

页面路由为 `/precious-metals`。Web 通过共享 API client 请求，不包含内置行情或验收夹具。

## 数据语义

- 只选择 `available_time` 和 `processing_time` 不晚于 `effectiveAsOf` 的记录。
- iNAV 在事件时间不超过 5 分钟时优先作为研究参考；否则使用不超过 7 天的 NAV。
- 溢折价使用交易所收盘价与选中的参考值进行十进制定点计算，输出 basis points 字符串。
- NAV/iNAV 永远是 `REFERENCE_ONLY`，不能作为可成交价格、模拟成交价或订单限价。
- 排名只按最新可见交易所成交额降序，版本为
  `precious-metals-turnover-ranking-v1`，不表达收益预测。
- 分类只接受 `PRECIOUS_METALS`，底层品类必须明确为 `GOLD`、`SILVER` 或 `OTHER`，不从名称推断。

## 降级与恢复

- PostgreSQL 分类查询失败时终端返回 `UNAVAILABLE` 并失败关闭。
- ClickHouse 行情或特征查询失败时保留基金身份，返回 `PARTIAL` 和显式 gap。
- 缺失或过时的 NAV/iNAV、行情和特征不以零值、当前值或样例值替代。
- 恢复数据源后重新请求相同 `asOf`；历史结果仍按原点时可见性计算。

## 配置

- `PRECIOUS_METALS_POSTGRES_DSN`，可回退到 `KUNLUN_POSTGRES_DSN`。
- `PRECIOUS_METALS_CLICKHOUSE_URL`，可回退到 `EMOTION_CLICKHOUSE_URL`。
- 可选 `PRECIOUS_METALS_CLICKHOUSE_DATABASE`、`PRECIOUS_METALS_CLICKHOUSE_USER`、
  `PRECIOUS_METALS_CLICKHOUSE_PASSWORD` 和 `PRECIOUS_METALS_CLICKHOUSE_TIMEOUT_MS`。

环境变量和日志不得记录真实账户、券商凭据或生产密钥。

## 范围边界

当前能力只覆盖交易所上市基金，不包含贵金属现货、期货、保证金、换月、交割、仓单或实物
业务。服务只读，不创建 `Signal`、`OrderIntent` 或订单；预警入口仅跳转到站内自选规则。
