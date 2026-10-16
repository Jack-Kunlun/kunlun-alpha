# 真实行情数据源运行手册

## 当前能力

日线行情观测与入库概览的字段语义、故障边界和只读核验见[日线入库概览运行手册](market-data-coverage.md)。

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

运维管理员还可以在实例级 `/settings/market-data` 页面配置 AKShare/Tushare 来源。该配置保存
在显式的 PostgreSQL settings DSN 中，Tushare token 只以 AES-256-GCM envelope 形式持久化；
浏览器响应不会包含 token、密文、nonce、tag、key 或 digest。保存成功表示“已保存，下一采集
周期生效”，不表示当前运行中的 worker 已经应用；页面不会把一次配置读取当作运行态确认。
AKShare 不需要 token，也不会把已保存的 token 解密下发给 worker；免费源仍不保证全市场覆盖、
实时性或商业 SLA。

## 离线回放验收包

仓库提供 `data/fixtures/offline-market-replay-v1.json`，用于在断网且没有数据库的环境中验证
raw manifest、内容校验和、重启后恢复以及真实 AKShare parser 路径。该文件固定声明
`SANITIZED_OFFLINE_FIXTURE_NO_MARKET_CLAIM`；其中价格和成交量是脱敏合成值，不是历史行情，
不得写入 ClickHouse、API 响应、排名快照或产品页面。

在仓库根目录执行：

```bash
uv run --package data-worker offline-market-replay-check
```

命令只在系统临时目录中创建 content-addressed raw 对象，结束时自动清理；它不会创建网络
客户端请求，也不会连接 PostgreSQL 或 ClickHouse。当前验收包包含 6 个 capture、11 根 Bar
与 5 个代表性标的，覆盖沪深主板、创业板、科创板、北交所，以及 DAILY/MINUTE_1 两种
回放 profile。输出只给出版本、数量和覆盖面，不回显价格数据。

AKShare 的公开函数返回 pandas DataFrame。适配器会在任何字段解析前把 SDK 返回的表序列化
到 raw capture；这是“适配器 payload capture”，不是上游 HTTP wire bytes。成交量按下述
固定 SDK 版本规则统一为股；日线时间按上海时区 15:00，分钟时间按上海时区
解释后保存为 UTC。Sina 分钟公开函数固定请求最多（通常为最近）1970 条（`datalen=1970`），
不接受日期窗口；adapter 保留完整 raw payload，再依据 manifest 的 `requested_start` 与
`requested_end` 在确定性解析阶段过滤；过滤后的结果不能反向修改 raw。Sina payload 不回显
证券代码，因此响应身份只能追溯到 adapter 请求与 capture manifest，不能声称由响应字段独立
验证，这是免费源的物理限制。每个被过滤行会在
writer 运行前写入同一 capture 关联的 `FILTERED` 质量证据，包含 raw 行号、UTC 时间、请求
窗口和固定原因码；证据写入失败时不会写入 Bar。窗口内乱序、重复或其他质量异常仍生成
`REJECTED` 证据并拒绝整次写入。空结果是有效的空 capture。

## 数据源限制与权限

### 固定 SDK 的成交量修正

当前适配器版本为 `v3`，SDK 仍固定为 AKShare `1.18.94`，没有升级依赖。
[官方接口说明](https://github.com/akfamily/akshare/blob/main/docs/data/stock/stock.md)
要求 Tencent 日线 `volume` 统一为股。该 SDK 的实际实现将 `sz000` 与指数一起排除在
手转股转换之外；因此 `000001.SZ` 等 `000xxx.SZ` 股票的 SDK 表仍是手。

`akshare:1.18.94:stock_zh_a_hist_tx:v3` 只对这一证券范围乘以 100，其他日线和 Sina 分钟
成交量不额外缩放。SDK 返回的 raw 表不修改，转换仅发生在解析边界。旧 `v2` capture 仍按
原语义回放以便审计；其中 `000xxx.SZ` 成交量存在已知单位错误，不能用于成交量分析。
修正通过新 capture 和新行情 revision 发布，不覆盖或删除旧 raw、检查点和记录；历史
point-in-time 查询仍可见其当时发布的版本，不应把新修正提前到旧可用时刻。

1.0 精简入口使用同一 `kunlun-market-raw` volume 下的 `v1-shares-v3` 子目录保存新 raw 和
检查点，使当日已完成的旧采集不会跳过这次规范化修正。停止后重用同一目录继续运行。

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
为准。在 legacy 环境模式中，token 通过进程环境或未提交的本地 `.env` 提供；在实例级 managed
模式中，管理员通过设置页提交后由 server 加密持久化，worker 只通过受限 internal GET 取得有效
token。两种模式都不会把 token 写入 raw manifest、ClickHouse、日志或异常消息。相关协议和接口
说明：

- [HTTP 调用协议](https://tushare.pro/document/1?doc_id=130)
- [A 股实时分钟-日累计](https://tushare.pro/document/2?doc_id=457)
- [指数实时分钟](https://tushare.pro/document/2?doc_id=420)
- [ETF 实时分钟-日累计](https://tushare.pro/document/2?doc_id=470)
- [A 股日线行情](https://tushare.pro/document/2?doc_id=27)

这条链路只提供研究行情输入，不提供 Tick 成交明细、全市场证券主数据同步或任何实盘下单
能力。

## 单次同步

### 实例级设置（可选）

默认不启用远程配置，现有 `MARKET_DATA_PROVIDER`/`TUSHARE_TOKEN` 环境模式保持不变。启用前
必须在部署 secret 管理或 checkout 之外的环境文件中提供以下值；不要把 master key 或 worker
credential 写入仓库、`infra/docker/.env`、日志、raw manifest 或浏览器存储：

```dotenv
MARKET_DATA_SETTINGS_POSTGRES_DSN=postgresql://<settings-db>/kunlun
MARKET_DATA_SETTINGS_MASTER_KEY=<base64-encoded-32-byte-key>
MARKET_DATA_SETTINGS_WORKER_TOKEN=<at-least-32-printable-ascii-bytes>
MARKET_DATA_SETTINGS_URL=https://<internal-server>/api/v1/internal/market-data/settings
MARKET_DATA_SETTINGS_ALLOW_LOCAL_HTTP=false
```

`MARKET_DATA_SETTINGS_MASTER_KEY` 必须是严格 32 字节的标准 base64 密钥；服务不会生成默认
密钥、把密钥写入数据库或在重启时随机生成新密钥。也可使用外部文件提供
`MARKET_DATA_SETTINGS_MASTER_KEY_FILE`，文件不应位于 checkout 内；Compose 需要由部署系统把该
文件以只读方式挂载并显式设置路径，空的 `.env` 占位值不会创建或生成密钥。`MARKET_DATA_SETTINGS_WORKER_TOKEN`
由 server 与 worker 共享，长度为 32–512 个可打印非空格 ASCII 字符；worker 只使用独立
Bearer credential 访问精确的 internal GET，不获得数据库或 master-key 权限。生产环境使用 HTTPS；
本地 Compose 的 `http://server:3002/api/v1/internal/market-data/settings` 只有在显式设置
`MARKET_DATA_SETTINGS_ALLOW_LOCAL_HTTP=true` 时允许，不能推广为 LAN 或任意 HTTP。

设置迁移使用现有 `@kunlun/db` Migration 定义，不在应用启动时执行。迁移命令使用临时的特权
settings DSN，只应用 settings migration；完成后不要把该特权 DSN 继续注入运行中的 server。
运行时 settings DSN 应使用受限数据库角色：仅允许 singleton 配置行的 `SELECT`、`INSERT`、`UPDATE`
以及审计表 `INSERT`，不授予 DDL 或 `DELETE`。settings DSN 与主库相同时可按常规命令迁移；
使用独立 settings DSN 时显式运行：

```bash
MARKET_DATA_SETTINGS_POSTGRES_DSN='postgresql://<settings-db>/kunlun' \
  node apps/server/dist/migrate.js --market-data-settings
```

缺少 DSN 或 master key 时，浏览器配置端点和 internal settings 读取会安全返回不可用；缺少或无效
worker credential 只会禁用 internal worker 读取和 managed mode，不影响已配置密钥的管理员浏览器
读取。系统不会回退到内存存储或把 legacy 环境 token 混入远程配置。POST 使用 `expectedRevision` compare-and-set；
`tokenAction` 为 `KEEP`、`REPLACE` 或 `CLEAR`，Tushare 不允许清除唯一 token。

管理员页面位于 `/settings/market-data`。保存成功仅代表配置已持久化；只有已启用 managed mode
的采集进程会在下一周期边界读取它，不表示进程已经应用配置或供应商已授予数据权限。
managed mode 读取失败、版本回退或同版本内容变化时停止本次采集，不使用旧配置或环境变量兜底。
恢复配置服务后，按既有进程管理方式恢复采集，不能通过删除历史断点绕过校验。

managed mode 的断点按 `managed-checkpoints/<provider>/<revision>` 隔离，原始行情和质量归档根目录
保持不变。共享版本记录采用跨进程锁和原子替换；POSIX 上同步父目录，Windows 沿用已有锁与原子
替换机制，不声称具有 POSIX 目录 fsync 验证。记录仅含版本、来源及以 worker credential 为密钥的
HMAC 指纹，不持久化明文 Token 或普通 Token 哈希。轮换 worker credential 时，应协调停止采集、
更新两端凭据并提高配置 revision 后恢复；不要直接删除版本记录来绕过同版本变更检查。

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

### 1.0 精简入口

已有 `infra/docker/.env` 时，从仓库根目录执行：

```bash
pnpm v1:sync
```

该命令叠加 `docker-compose.v1.yml`，固定使用 AKShare、8 个显式沪深标的、once 日线模式和
`v1-shares-v3` raw/checkpoint 子目录。摘要直接输出到终端，临时同步容器退出后删除；raw 与
ClickHouse 数据保留。启动前置和覆盖清单见[1.0 精简启动](../development/docker-local.md#10-精简启动)。

同一 `V1_MARKET_DATA_SYMBOLS` 清单也配置到 server 的 `DASHBOARD_DAILY_SYMBOLS`。1.0 总览
只批量读取 `bars_daily_v2`，按当前可见的最新共同日期汇总；仅计入该日及至少一根更早可见日线
同时存在的代码，成交额按 Decimal 原值求和。页面显示样本实际截止日期和来源，不把 90/300 秒
分钟级 freshness 阈值用于日线。指数和情绪当前不接入；空样本明确显示无数据，ClickHouse 错误
继续显示错误状态。`DASHBOARD_DAILY_SYMBOLS` 未配置时，server 保留原分钟总览路径；显式配置
时必须为 1–100 个唯一的六位 SH/SZ 代码，否则 server 启动失败。

此次 `v3` 成交量修正必须使用这一入口；不要改用下面的通用命令复用旧根目录，也不要删除
旧检查点来强制刷新。旧根目录同日已完成的 checkpoint 可能跳过新采集，不能证明修正已落库。

### 通用入口（不用于此次 1.0 修正）

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

1.0 入口以 `pnpm v1:sync` 的终端摘要核对日期、写入数和 capture ID；同日已完成后重跑应为
0 请求、0 写入。以下日志命令仅适用于上述通用入口的保留容器，不用于核验已删除的 1.0
临时同步容器：

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
