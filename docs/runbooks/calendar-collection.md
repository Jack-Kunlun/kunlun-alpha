# 节假日采集边界

## 当前语义

`CalendarCollector` 消费的是单次请求的节假日与临时闭市记录，不是完整逐日交易日历。
节假日之间很长的间隔可能正常；成功返回零条记录只能解释为“本次未返回闭市记录”。
两者都不能证明缺失、全年没有闭市或所有非周末日期均开市。

采集结果中的 `coverage_status` 固定为 `UNKNOWN`。`holiday_count` 是实际返回的记录数，
不是覆盖率；空 `alerts` 也不构成完整性合格结论。旧的 `MISSING_DATE` literal 为内部
兼容而保留，当前稀疏 `Holiday[]` 输入不会产生这种告警。

临时闭市仍产生 `TEMPORARY_CLOSURE`。显式调用 `detect_alerts(..., other_sources=...)`
仍可比较相同日期的闭市原因；`collect()` 本身没有接入多来源读取与冲突解决流程。

## 分页与失败

构造采集器时可通过 keyword-only `max_pages` 限制一次调用的页数，默认 100。
它必须为正整数，布尔值不合法。游标重复、成环或未在页数预算内结束时，以受控
`ProviderDataError` 退出。分页保护产生的错误消息不包含游标或原始 provider 响应；
provider 自身错误继续按既有错误分类向调用方传播，本次不新增日志或错误展示出口。

所有页读取成功后才保存一次版本。分页拒绝或 provider 异常不会保存半份版本；已有
历史版本不受影响。失败后应先修复 provider 的分页行为，再由调用方重新发起完整请求。
本次未实现跨进程恢复、稳定来源快照锚点或自动重试，不承诺分页期间上游数据不变化。
单个 provider 调用的网络超时仍由 adapter 自身负责，页数上限不是总墙钟超时。

## 使用与运行边界

此前的 V3/稀疏修复代码已随 `2cf1f91` 发布到本地 worker 镜像；CLI 自身不自动执行
migration，当前目标环境已完成 V3 migration，SH/2026 版本 `f46a78c8-626e-4627-a0e3-c4ab258246ec`
已持久化 19 条记录，coverage 仍为 `UNKNOWN`。实际部署范围见[本地部署记录](../reviews/2026-09-05-calendar-and-data-quality-deployment.md)。
SZSE direct-daily V4 的冻结运行证据另见下文，不应与本节 V3 稀疏路径混读。现有
`InMemoryCalendarRepository` 仍仅用于测试与单次进程；不能将其用于需要持久化、历史知识
重建或正式缺失判定的验收。

## SH 官方 2026 公告窄入口

`official-sse-calendar-sync` 是当前本地候选中的一次性 worker 入口，尚未接入持续
scheduler/API，
只接受 `SH/2026` 与固定的 [SSE 公告](https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml)。
它不接受 caller URL、跨 host redirect 或其他交易所/年份，不执行 migration，不创建
authoritative snapshot `COMPLETE`，输出的稀疏 `PUBLIC_HOLIDAY` coverage 始终为 `UNKNOWN`。

运行示例（仅说明边界，本次未执行，不应输出现有 DSN）：

```text
KUNLUN_POSTGRES_DSN="$EXISTING_DSN" official-sse-calendar-sync --raw-root "$RAW_ROOT" --exchange SH --year 2026
KUNLUN_POSTGRES_DSN="$EXISTING_DSN" official-sse-calendar-sync --raw-root "$RAW_ROOT" --replay --capture-id "$CAPTURE_ID" --date "$RAW_DATE"
```

`--raw-root` 也可由 `KUNLUN_RAW_ROOT` 提供；数据库连接只读取已有的
`KUNLUN_POSTGRES_DSN`，可选 `KUNLUN_POSTGRES_SCHEMA` 必须是受限 portable SQL identifier，
连接超时有界且不回显 DSN。`--replay` 必须同时提供 capture id 和 observation date，
只读取已保存 raw/state，不重新联网；两种模式都要求已有数据库连接，但入口不会调用
`initialize()` 或自动执行 V3 migration。当前目标环境 ledger 已为 V1-V4，V3 的 SH/2026
版本已持久化 19 条记录，coverage 仍为 `UNKNOWN`。

采集先写不可变 raw capture，再校验固定 HTML 和七个子段，最后写 sparse repository version
与 provenance receipt。503、redirect、非 HTML、超限或解析失败的响应/attempt 可保留审计，
但不可用 capture-state 不允许 replay 入库；已有 receipt 时会先做只读 operation/version
核验，缺失或冲突不写 save/latest/audit。原始 HTML 不进入日历 note 或 CLI 输出。该切片
的测试与证据见[官方 SSE 证据记录](../reviews/2026-09-05-official-sse-calendar-evidence.md)。

当前本地运行环境/候选已完成一次受控运行，但未将该入口接入持续 scheduler/API；跨平台
host 尚未实测。项目仍为 `PAPER_ONLY`，该入口没有任何实盘下单能力。

## SZSE 官方 direct-daily V4 运行边界

当前已冻结并验收 `szse-direct-daily-v4`（parser/source）与 `calendar-scan-run-v4`
（scan-run contract）这条 SZSE 逐日路径。它先保存并校验持久 raw evidence，再 replay
到 V4 PostgreSQL ledger，最后通过 hydration 与 as-of 查询验证；这不等同于 scheduler/API
持续接入，也不表示其他交易所或所有年份已经完整。完整证据见[SZSE V4 运行验收记录](../reviews/2026-09-08-official-szse-v4-runtime-evidence.md)。

当前一次性入口为 `official-szse-daily-sync`，固定处理 `SZ/2026`。collect 模式先写入
并校验 raw capture，之后只使用 raw coordinates 写入 V4；replay 模式必须指定既有
`run_id`、`manifest_date` 和 `manifest_capture_id`，只读已保存 raw/state，不访问网络。
该 CLI 不执行 migration，也不接入 scheduler；目标库和运行任务的生命周期仍由外部运维
流程管理。旧 worker 镜像中的 `--help` 和 Plan 00 冻结验收属于历史证据，不能证明该镜像
包含本轮新增的 `--capture-only`；既有镜像未替换，也未验证其含有新 flag。新 flag 当前仅在
工作区源码与本轮单独构建的 wheel 产物边界内做隔离验收。

`--capture-only --raw-root "$RAW_ROOT"` 是确认窗口续接入口：它不是“完全不持久化”，而是
在调用方明确提供且已获授权的隔离 raw root 中，通过同一 raw-first collector 写入并校验
不可变 raw evidence，随后输出固定状态
`RAW_CAPTURED_UNPERSISTED` 及 run/manifest 坐标、proof/版本、`available_at` 和派生的
`source_nowdate`/`confirmed_through`。它不读取 `KUNLUN_POSTGRES_DSN`、不打开 repository、
不执行 migration、不产生 accepted snapshot，也不声明 `COMPLETE` 或 caller 提供的
`FINAL_YEAR`。非隔离目录或现有持久 raw root 需要另行授权；该模式不能与 `--replay` 或任一
replay 坐标同时使用。缺页、重定向、漂移或结果校验失败时不输出成功 JSON。

`--raw-root` 必须指向预先存在的绝对非根目录，根目录及 immediate parent 不能是 symlink、
非目录或包含控制字符/首尾空白；POSIX 下还要求 owner 为当前用户或 root，且根目录及
immediate parent 不得 group/world-writable。CLI 生命周期内保持目录 capability/identity guard，
在 raw storage 操作及 collect 到 persist 边界前后复核；检测到替换、丢失或权限变化即固定
错误失败，不调用 repository。该 guard 依赖 single trusted writer，不能声称防御拥有受信任
parent 写权限的主体。未知 `OfficialSzseCalendarError` 只映射到固定 CLI 错误，连接关闭失败
返回固定 DB 错误且不输出成功 JSON。结果输出遵循 V4 状态机：`COMPLETE` 必须有 snapshot
且为 `FINAL_YEAR`；无 snapshot 必须为 `INDETERMINATE`；非 confirmed 的 blocked/conflict
及其 `DUPLICATE` 可以保留 full-year proof 并返回 `INDETERMINATE`。

旧 worker 镜像/Plan 00 的冻结历史验证为 `164 passed / 20 skipped`，其中 skipped 是未启用
的 real-PostgreSQL fixture；该数字不覆盖本轮新 flag。审计回归加入前，受影响工作区源码
与定向测试的 fresh 结果为 `234 passed / 20 skipped`；合并本轮四类边界回归后的五文件
定向结果为 `237 passed / 20 skipped`，其中 20 项 skipped 是未提供 real PostgreSQL DSN，
两者都不等同于新 flag 已进入既有镜像。Ruff 通过，BasedPyright 为 `0 errors`。一次性容器连接现有 `docker_default`、
只读 `kunlun-market-raw` 与目标 PostgreSQL 执行离线 replay，返回既有
`run_id=3d5e39e8-551d-4868-9ca8-c2ba382a8dd2`、
`snapshot_id=099b0d2e-5c17-5d88-946f-e64ae62650c3`、`disposition=DUPLICATE`、
`coverage_level=CONFIRMED_HORIZON`、`terminal=INDETERMINATE`。其中
`terminal=INDETERMINATE` 是确认窗口只到 `2026-09-07` 时的预期失败关闭语义，不表示
未来日期已确认。

冻结运行的计数顺序为：`69` typed refs、`28` attempts、`12` catalogs、`2` passes、
`24` pages、`1` manifest、`69` snapshot evidence rows、`365` calendar days；结果包含
`242` 个交易日、`123` 个非交易日和 `19` 个工作日闭市日，确认到 `2026-09-07`。
未来日期仍为 `INDETERMINATE`，不能由已确认 horizon 推断。

同一 raw run 的重复 replay 保持幂等，不产生额外可见 snapshot；已知交易日和节假日的
as-of 查询可从 accepted snapshot 返回对应结果，未来 as-of 保持不确定。V4 目标库、
本地 worker 镜像和持久 raw 的分层验收均已记录，但本节不宣称 P1-N07 全部缺口已补齐，
也不表示 24 小时正式门禁已经启动。

## 请求与响应范围校验

本节范围校验已进入本地 worker 候选镜像，尚未启动日历采集；不能作为真实来源采集证明。
`collect(exchange, year)` 只接受生成契约中的 `SH`、`SZ`、`BJ` 字符串及 `1..9999`
的整数年份，布尔值、浮点数、字符串年份、大小写变体、空白或 vendor 别名均不自动转换。
非法请求在调用 provider 前以固定 `ProviderDataError` 失败，不保存新版本。

每页返回记录的交易所与日期年份必须和请求一致；任一条不匹配即拒绝整个请求，
不继续请求下一页、不静默过滤、不改写记录，也不保存已读取的部分页。失败不改变
已有快照、当前来源记录与手工修正审计。错误消息不包含请求值、游标或来源 note。

合法零条响应仍返回 `coverage_status=UNKNOWN`。范围一致只说明返回记录属于请求，
不能证明来源没有漏报闭市日期，更不能证明全年交易日历完整。

## 内存版本与修正隔离

本节改动已进入本地 worker 镜像，未启用日历任务。内存仓储按 `(source, exchange, year)` 保存各自最新版本；
历史快照依旧独立深复制，版本 ID 是 opaque 标识，不能从字符串解析交易所或年份。
重复采集只更新目标范围的最新指针，不覆盖其他范围或任何历史版本。

读取应优先使用完整范围：

```python
version_id = repository.latest_version_id("exchange-a", "SH", 2026)
holidays = repository.source_holidays("exchange-a", exchange="SH", year=2026)
```

`version_id is None` 表示该范围从未保存；已保存的空快照有自己的版本 ID，不能将它与
从未采集混为一谈。空快照仍不能证明全年没有闭市。

旧 `save_version(source, year, holidays)` 仅在非空且同交易所/年份的记录中推导交易所。
空快照需要显式 `exchange=...`；collector 始终传入该参数。旧 `source_holidays(source)`
在无记录或只有一个范围时兼容；有多个范围时抛 `CalendarScopeAmbiguityError`，不能猜最新。
只传交易所或只传年份同样失败。无效或不一致的保存不分配新版本，不修改指针或审计。

手工修正应显式传 `version_id`，其标准 ISO 日期必须属于目标版本的年份。修正只出现在
该版本的 overlay，不改原始快照，也不自动转移到同范围的新版本。省略 `version_id`
只在仓储恰有一个历史版本时兼容绑定；零或多版本拒绝写入。读取 overlay 省略版本时，
零版本返回空、单版本兼容、多版本拒绝。审计日志可用于查看历史操作，不应以无范围
overlay 充当全局修正规则。未知版本 ID 以 `KeyError` 拒绝，不回显任意输入。

## PostgreSQL 稀疏快照仓储

以下描述是 V3 稀疏快照路径：CLI 自身不自动执行 migration；当前目标环境已完成 V3
migration，并已持久化 SH/2026 的 19 条记录，coverage 仍为 `UNKNOWN`。这不等于完整
逐日日历或持续任务接入，也不能把适配器存在解释为全年数据已经完整。SZSE
direct-daily V4 的目标库与 raw 验收不复用这里的 sparse snapshot 语义，见上文证据记录。

`PostgresCalendarRepository(connection)` 仅借用已有 psycopg 连接，不创建或关闭连接；
调用方管理连接生命周期，不能在其他线程或代码中同时使用它。每个公开读写方法
要求连接处于 IDLE，并自行完成事务；调用方已有事务时固定错误拒绝，不接管其提交
或回滚。初始化同样要求 IDLE，在独立迁移流程中显式执行，普通读写不会自动迁移。

迁移作为 V3 `calendar_snapshot_migration` 纳入现有 worker ledger 和共享迁移锁，
沿用 `apply_data_worker_migrations`，没有第二条 DDL 入口。需要先满足已有基础表
前提。SQL 随 wheel 打包；无账本的部分日历表或 checksum/catalog 漂移失败关闭。
历史版本、闭市记录、修正和审计表禁止 UPDATE/DELETE，只有完整范围的 latest 指针
可更新。结构校验同时检查约束、索引、触发器与函数定义，不仅比较名称。

PostgreSQL 版本 ID 为不透明 UUID，不能依赖内存实现的字符串形态；闭市记录按原始序号
保序且保留重复，空快照也有独立版本。`save_version` 可选 `operation_id` 由调用方稳定提供：

- 省略时每次生成新版本，即使内容相同。
- 同标识、同范围及同内容重试返回原版本，不把 latest 退回旧版本。
- 同标识但范围或内容冲突时受控拒绝，事务内不留下部分状态。

仅保存操作标识摘要，不存原标识。collector 尚未管理跨进程操作标识或任务恢复，
不能由仓储幂等能力推断采集任务具备自动重试。手工修正依旧精确绑定版本，不改原始
闭市记录或 latest；无版本的兼容调用仅按当次读取可见的唯一历史版本判定。
overlay 是追加审计记录，不是自动执行的修正规则；其确定性返回顺序不承诺提交先后
或覆盖优先级，不能据此认定“列表最后一条获胜”。将来实际应用冲突修正时，需要
单独定义序列与优先级契约，不能沿用内存列表追加顺序推断数据库语义。

`persisted_at` 使用 PostgreSQL `CURRENT_TIMESTAMP`，是仓储事务时间，不是精确
提交时刻，也不是来源 publish/available 时间；不提供历史 as-of 或 PIT 重建。
持久化错误使用受控异常，不应将 SQL 参数、来源 note、操作标识或底层异常记录到日志。

## 日历质量 V5 projection

`calendar_quality` 是显式的 V5、追加式质量账本，不由通用 V1-V4 migration 自动创建。
纯 projection 可以评估 V3 稀疏输入为 `UNKNOWN`，但 PostgreSQL 持久化边界只接受已验证的
V4 official snapshot；V3 没有可配对的 raw evidence，故明确拒绝。SECONDARY source 在持久化边界拒绝。
每个 source 和 alert 保存成对的 `source_id`、opaque `evidence_ref` 与 SHA-256，不能拆开、
排序或由调用方重新拼接。原始 source、assessment、alert、manual overlay 和 audit 均不可
更新、删除或 truncate；重放使用 operation identity 幂等，同一 operation 的不同内容固定
冲突，不会合并成一条记录。

V3 稀疏公告永远不会生成逐日缺口。V4 只有在 source 自己声明的
`confirmed_through` 内才参与逐日缺行检测；窗口外或没有 accepted source 只产生一个
`MISSING_COVERAGE` scope alert，不合成全年日期，也不推断交易状态。V4 的 `SPECIAL` 行本身
不是临时休市证明；`TEMPORARY_CLOSURE` 需要独立、已验证的 closure evidence。V5 不接通
scheduler、API 或采集入口，部署/重放前仍须由外部流程显式应用迁移并提供已有 V1-V4 前置。
source 的 `available_at` 必须不晚于本次 `detected_at`；assessment 与 alert 的
`available_at` 统一为 `detected_at`，因此延迟评估在检测时刻可见，在此前的 as-of 查询中不可见。

V5 首装只允许显式 profile 下的 `calendar-quality-publish` 一次性入口。它使用
`CALENDAR_QUALITY_ADMIN_DSN` 或其 `_FILE` 变体，并在一个 PostgreSQL 外层事务中完成
clean-state preflight、四角色创建、临时 migration window、V5 migration、ACL seal 与
最终 verifier；没有独立可绕过的 bootstrap/migrate/seal 容器或 raw `psql` seal 文件。
已封存且精确通过 verifier 的重复调用只返回 `ALREADY_SEALED`，不会重开权限窗口或轮换
密码。publish 不回退到 `KUNLUN_POSTGRES_DSN`；使用 `_FILE` 时必须由外部 secret 配置
regular file、UID 10001、权限 0400 的只读挂载，路径和内容不会进入输出。
runtime 的每个事务都会重新固定 `kunlun` `search_path` 并同时核对
`SESSION_USER=CURRENT_USER=kunlun_cq_runtime`；管理员 `SET ROLE` 不能冒充 runtime。
Calendar Quality 的破坏性 PostgreSQL 测试只允许连接名称匹配 `kunlun_test_<...>` 且存在
唯一 marker `public.kunlun_test_database_marker`（值为
`kunlun-calendar-quality-pg-test-v1`）的专用数据库，正式 `kunlun` 数据库拒绝执行。

## 独立逐日日历判定规则

`market_core.calendar.authoritative_snapshot` 是独立的纯域组合器，仍不负责接入 provider、
数据库、覆盖 API 或运行采集器。它与原有静态 `TradingCalendar` 分离；内部 authority 枚举及
证据元数据只验证契约，不验证外部来源真实性。未来只能由完成来源身份和捕获校验的
受信任 adapter 构造官方输入，不能凭用户填写的 URL 或 source 名称升级为官方。

COMPLETE 快照必须包含同交易所/年份的每个自然日且恰好一次，并同时绑定已验证、可回放、
连续且无分页/窗口缺口的官方临时公告扫描 bundle。输入转换为不可变逐日副本，舍弃自由
文本 note；全年完整并不等于证券有交易资格，也不证明某个证券的 Bar 完整。仅有规则和
年度公告的基线投影、缺页扫描或官方冲突只能标记 INDETERMINATE；不得仅根据周末或稀疏
节假日反推开市。

单日查询同时传入 as-of，仅考察当时可见的同范围快照。无可见官方、未完成、悬空或
循环替代、跨范围替代、时间倒置或没有唯一版本头时返回 INDETERMINATE；仅合法显式
supersedes 才允许替代，新版本可见前保持旧版本结果。次源可生成固定形状的冲突证据，
不能覆盖官方或为不确定状态补出肯定结果。输出只含固定原因、不透明身份与时间。

构造时的非法字段和非完整却自报 COMPLETE 输入以固定领域错误拒绝；有效输入之间
缺少可选择 lineage 是查询结果“无法判定”，不要将两种情况混为成功空日历。
临时全市场闭市 delta 还必须具备已验证的全天证据，并由包含该 delta 且在其
`available_at` 之后可见的完整 successor scan 复核；缺少 successor scan 时只保留
显式 superseding 的 INDETERMINATE child，child 的 artifact/capture/digest 从 delta
证据派生，不接受调用方另行伪造。该纯域切片仍未接管 provider、持久化或运行采集器；
SZSE V4 的运行边界由上文单独约束。

## 后续缺口

用户已批准后续完整性判定采用交易所官方日历作为权威来源。第三方与官方发生冲突时，
必须保留冲突证据并告警，不能由第三方结果覆盖官方状态；官方资料、完整覆盖或可见
时间不足时返回“无法判定”。这是后续实现的已批准规则，当前稀疏仓储和 collector
并未因此获得完整日历判定能力。

当前纯域组合器已交付三所/年度的基线与扫描门禁；SZSE direct-daily V4 已有一次冻结的
raw-first、目标库和镜像运行证据，但仍不替代来源完整性、可见时间、证券生命周期、
行情完整性、采集任务终态和其他交易所的真实运行接入。V3 SSE 稀疏 19 条记录仍是
`UNKNOWN`；SH/BJ 官方来源穷尽性和 BSE 授权仍未解决。代码与运行证据不代表上述缺口
已全部补齐，也不改变 P6 条件接受或 24 小时墙钟门禁尚未启动的状态。
