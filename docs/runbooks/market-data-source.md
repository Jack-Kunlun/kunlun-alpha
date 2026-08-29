# 真实行情数据源运行手册

## 当前能力

data-worker 提供两个可切换的真实行情源。默认源是无需 token 的 AKShare，Tushare Pro
仅在显式选择并提供授权 token 时使用。适配器将未复权行情写入现有 ClickHouse
`bars_daily_v2` 与 `bars_minute_v2` 表。默认 AKShare 路径覆盖以下行情类型：

- A 股、场内 ETF 和交易所指数的日线；
- A 股、场内 ETF 和交易所指数的 1 分钟或 5 分钟 Bar；
- 每次响应先写入不可变 raw landing zone，再解析、校验和版本化落库；
- 价格、成交量和成交额在适配器边界通过 `Decimal` 解析，来源、接口身份、raw capture、
  入库时间、可用时间和替换版本随 Bar 保留。
- raw capture 保留上游 `amount` 的完整精度；写入 `bars_*` 时，人民币金额在 ClickHouse
  transport 边界显式按 `Decimal("0.01")` 使用 `ROUND_HALF_UP` 量化为分，并固定输出两位小数。
  这只改变 JSONEachRow 持久化表示，不改 raw 或领域原值。旧 revision 不删除，新同步以新的
  `replacement_version` 参与 point-in-time 读取并成为可用时刻内的最新版本。

AKShare 日线调用 Tencent-backed `stock_zh_a_hist_tx`，来源元数据为
`akshare-tencent`；分钟调用 Sina-backed `stock_zh_a_minute`，来源元数据为
`akshare-sina`。两条路径都固定传 `adjust=""`，解析出的 `priceType` 固定为 `RAW`。
`source_version` 包含 AKShare 版本、公开函数名和适配器版本。历史 raw replay 仅兼容
已证明语义的 `akshare-eastmoney` 股票日线与股票 `MINUTE_1` profile，其他 legacy profile
保留 raw 但拒绝解析；Eastmoney 不再是默认抓取来源。Tushare 来源元数据为 `tushare-pro`。
默认运行只导入 `600519.SH` 的日线，避免首次启动隐式拉取全市场样本；分钟代码为空，需通过
`MARKET_DATA_MINUTE_SYMBOLS` 显式配置。自定义代码集合仍可通过 `MARKET_DATA_SYMBOLS` 提供，
它们都是本地研究样本，不代表全市场宽度。

AKShare 的公开函数返回 pandas DataFrame。适配器会在任何字段解析前把 SDK 返回的表序列化
到 raw capture；这是“适配器 payload capture”，不是上游 HTTP wire bytes。Tencent 日线和
Sina 分钟路径均按原始返回值保留成交量；日线时间按上海时区 15:00，分钟时间按上海时区
解释后保存为 UTC。Sina 分钟公开函数固定请求最多（通常为最近）1970 条（`datalen=1970`），
不接受日期窗口；adapter 保留完整 raw payload，再依据 manifest 的 `requested_start` 与
`requested_end` 在确定性解析阶段过滤；过滤后的结果不能反向修改 raw。Sina payload 不回显
证券代码，因此响应身份只能追溯到 adapter 请求与 capture manifest，不能声称由响应字段独立
验证，这是免费源的物理限制。每个被过滤行会在
writer 运行前写入同一 capture 关联的 `FILTERED` 质量证据，包含 raw 行号、UTC 时间、请求
窗口和固定原因码；证据写入失败时不会写入 Bar。窗口内乱序、重复或其他质量异常仍生成
`REJECTED` 证据并拒绝整次写入。空结果是有效的空 capture。

## 数据源限制与权限

AKShare 股票、ETF 和指数是默认的免费本地研究源，不需要 token，但免费只表示可以调用
当前公开页面或开源封装；不自动保证上游数据的商业许可、可再分发权、服务等级（SLA）、
稳定 schema、频率额度或生产实时性。Tencent、Sina、AKShare 及下游数据的条款和可用性
需要由使用方自行评估。公开函数也不保证统一的单请求硬超时；同步器只提供有限重试和安全
错误信息，不能把 AKShare 视为生产许可或实时交易 feed。

默认路径直接覆盖股票、ETF 和指数的日线/分钟 Bar；任一公开页面或函数不可用时会按
capture fail closed，不会静默改采其他来源。需要有明确权限、SLA 或商业授权的数据服务时，
应显式切换到已获授权的 Tushare Pro 或其他合规 feed。

历史 `akshare-eastmoney` raw replay 仍保留旧股票 `MINUTE_1` 的兼容解析；
`index_zh_a_hist_min_em` 的 `MINUTE_5` capture 因供应商内部复权参数导致价格语义无法证明为
`RAW`，会明确拒绝解析，不猜测或改写原始证据。

Tushare Pro 是需要单独授权的切换项。日线和实时分钟接口的积分、权限和数据许可以官方说明
为准；token 只能通过进程环境或未提交的本地 `.env` 提供，不会写入 raw manifest、ClickHouse、
日志或异常消息。相关协议和接口说明：

- [HTTP 调用协议](https://tushare.pro/document/1?doc_id=130)
- [A 股实时分钟-日累计](https://tushare.pro/document/2?doc_id=457)
- [指数实时分钟](https://tushare.pro/document/2?doc_id=420)
- [ETF 实时分钟-日累计](https://tushare.pro/document/2?doc_id=470)
- [A 股日线行情](https://tushare.pro/document/2?doc_id=27)

这条链路只提供研究行情输入，不提供 Tick 成交明细、全市场证券主数据同步或任何实盘下单
能力。

## 单次同步

在仓库根目录执行。没有设置 `MARKET_DATA_PROVIDER` 时默认使用 AKShare，因此不需要
`TUSHARE_TOKEN`：

```bash
MARKET_DATA_PROVIDER=akshare uv run --package data-worker market-data-sync
```

程序默认先补最近 730 个自然日范围内的 `600519.SH` 日线，不采集分钟数据。成功输出只包含
日期、请求数、收到/写入 Bar 数量和 raw capture ID，不包含凭据。checkpoint 位于
`MARKET_DATA_RAW_ROOT/market-data-checkpoint-v1.json`，进程会用原子替换和独占锁保存 run ID、
capture ordinal、当日日线进度与中断中的请求；损坏或并发占用会 fail closed。
若进程在 raw 落盘后、ClickHouse 确认前中断，下一次启动会先按同一 run ID 与 ordinal 重放已
持久化 capture，只有找不到该证据时才重新请求 provider。ClickHouse 结果不确定时先查询完整
版本字段确认，确认不存在后才按有界指数退避重试。

如需一次采集分钟数据，可显式设置 `MARKET_DATA_MINUTE_SYMBOLS`。如需持续运行，必须显式设置
`MARKET_DATA_RUN_MODE=continuous`，且 `MARKET_DATA_POLL_SECONDS` 不得小于 60：

```bash
MARKET_DATA_MINUTE_SYMBOLS=600519.SH \
MARKET_DATA_RUN_MODE=continuous \
MARKET_DATA_POLL_SECONDS=60 \
uv run --package data-worker market-data-sync
```

如需切换 Tushare，必须在请求前提供已获授权的本地 token：

```bash
export MARKET_DATA_PROVIDER=tushare
export TUSHARE_TOKEN='<authorized-local-token>'
uv run --package data-worker market-data-sync
```

进程会在发送 Tushare 请求前检查 token；AKShare 路径不会读取或要求该变量。Windows
PowerShell 可使用 `$env:MARKET_DATA_PROVIDER="akshare"` 和 `$env:TUSHARE_TOKEN="..."`
设置同名进程环境变量。

## Compose 同步

默认 AKShare 不需要 token。首次使用时可复制 `infra/docker/.env.example` 为未提交的
`infra/docker/.env`；随后从仓库根目录执行：

```bash
docker compose \
  --env-file infra/docker/.env \
  -f infra/docker/docker-compose.yml \
  -f infra/docker/docker-compose.apps.yml \
  --profile real-market-data \
  up -d --build market-data-sync
```

若不创建 `.env`，也可将 `--env-file infra/docker/.env` 替换为
`--env-file infra/docker/.env.example`；Compose 默认值仍会选择 AKShare，并以 once 模式只做
`600519.SH` 的 730 日日线导入，分钟采集关闭。设置
`MARKET_DATA_RUN_MODE=continuous` 后才会持续运行；轮询间隔至少为 60 秒。原始响应保存于
独立 Docker volume `kunlun-market-raw`；停止同步不会删除 raw 或 ClickHouse 数据。

Compose 切换 Tushare 前，在未提交的 `infra/docker/.env` 设置：

```dotenv
MARKET_DATA_PROVIDER=tushare
TUSHARE_TOKEN=<authorized-local-token>
```

然后重新执行上述 `up -d --build market-data-sync` 命令。切回 AKShare 只需设置
`MARKET_DATA_PROVIDER=akshare` 并移除本地 token 值；模板和仓库文件中不得填写真实 token。

## 来源切换与读取策略

切换来源只影响后续 capture，不删除或覆盖已有 `bars_*_v2` 记录。dashboard 读取时先应用
`event_time <= cutoff`、`available_time <= cutoff` 与 `processing_time <= cutoff` 的 point-in-time 条件，再在同一
`unified_code`、事件时间/交易日的合法来源中，优先选择 cutoff 内最近可用的完整
`replacement_version`。仅在完全相同可用时刻，才以 source priority 和稳定来源元组决胜：
已授权的 `tushare-pro` 优先于当前 AKShare 的 `akshare-tencent`/`akshare-sina`，历史
`akshare-eastmoney` 最后。该优先级只是同一可用时刻的 tie-break，不会让旧来源永久覆盖
后来主动切换并采集的新来源。
close、amount、suspended、source_version 和 evidence_id 始终来自同一个获胜记录。未知 source
不参与默认 dashboard 读模型；同一精确来源身份与 replacement version 的 fingerprint 冲突仍会
fail closed。

## 核验

先查看安全摘要日志：

```bash
docker compose \
  --env-file infra/docker/.env \
  -f infra/docker/docker-compose.yml \
  -f infra/docker/docker-compose.apps.yml \
  logs --tail=20 market-data-sync
```

然后在 ClickHouse 中核验来源、样本数和最新事件时间：

```sql
SELECT source, source_version, count(), max(event_time), max(available_time)
FROM bars_minute_v2
WHERE date = today('Asia/Shanghai')
GROUP BY source, source_version
ORDER BY source, source_version;
```

页面 `/market-overview` 每 30 秒刷新读取结果。若只有指数而没有宽度数据，检查配置的 A 股
代码及其日线/分钟权限；若所有区域均为空，依次检查同步日志、ClickHouse 表和 API 的
`freshness`/`completeness`，不要用 fixture 伪装真实行情。

## 故障边界

- `MARKET_DATA_PROVIDER must be akshare or tushare`：provider 配置非法，进程不会发请求。
- `TUSHARE_TOKEN is required when MARKET_DATA_PROVIDER=tushare`：Tushare 未提供 token，
  进程会在发送请求前失败；AKShare 不受此要求影响。
- `AKShare SDK is unavailable` 或 `AKShare provider unavailable`：本地依赖、上游网络或
  有界重试耗尽；错误文本不会透传供应商 payload。
- `provider returned invalid data` / `AKShare capture body ...`：raw capture 已先保留时，
  停止解析并依据 capture ID 排查字段变化；不要静默丢弃坏行。
- `ClickHouse bar write failed` / `ClickHouse bar write outcome is uncertain`：raw 已保留；
  writer 会先按完整版本字段查询确认，再以相同身份做最多三次有界指数退避重试，不能随机生成
  replacement version；
  恢复 ClickHouse 后继续原 checkpoint，不删除旧证据。

不要把 AKShare 当作有硬超时保证的生产 feed，不要降级为 HTTP 抓取网页，不要清理 raw 证据
来掩盖失败，也不要从这条研究同步路径接入真实交易。
