# 证券主数据同步

当前能力：`data-worker` 提供一次性的 `instrument-master-sync`。采集模式使用固定的 Tushare Pro `stock_basic` 状态分区（`L/P/D`）和交易所基金 `fund_basic(market=E)` 分区（`L/D`），先将每个响应写入不可变 raw landing，再解析并以 raw 坐标重放到私有 provider PostgreSQL 存储。

离线重放只接受 `run_id`、`manifest_date` 和 `manifest_capture_id`，不创建 HTTP transport，也不读取 Tushare token。数据库 schema 不由 CLI 自动迁移；V5 迁移必须由受控运维流程单独执行。CLI 输出只包含运行/快照身份和固定状态字段，不输出 DSN、raw 路径、请求体或 provider 响应。

## 配置

采集模式通过环境变量提供 `KUNLUN_RAW_ROOT`、专用的 `INSTRUMENT_MASTER_RUNTIME_DSN`（或受保护的 `INSTRUMENT_MASTER_RUNTIME_DSN_FILE`）和 `TUSHARE_TOKEN`。运行时固定使用 `kunlun_instrument_provider` schema，不回退到 `KUNLUN_POSTGRES_DSN`，也不接受 `KUNLUN_POSTGRES_SCHEMA`。token 只进入 HTTPS 请求体，不进入 manifest、日志或错误；CLI 不接受操作者自报的 provider revision。

```text
instrument-master-sync
instrument-master-sync --replay --run-id <UUID> --manifest-date <YYYY-MM-DD> --manifest-capture-id <id>
```

数据库角色与 provider migration 是单独的、显式的运维步骤，不由同步命令自动执行。使用 `instrument-master` compose profile 时，先确保 `kunlun` 中的 shared worker V1–V4 ledger 已完成，再按 `role-bootstrap` → `provider-migrate` → `instrument-master-sync` 的顺序运行；该 profile 不会被默认 `docker compose up` 启动。角色 bootstrap 需要管理员连接，并从外部环境读取 `INSTRUMENT_MASTER_MIGRATOR_PASSWORD` 与 `INSTRUMENT_MASTER_RUNTIME_PASSWORD`；两个变量必须非空，否则在任何 DDL/事务开始前 fail closed。bootstrap 只向 `kunlun_im_migrator` 授予 `kunlun` schema 的 `USAGE` 和 `data_worker_schema_migrations` 的 `SELECT`；共享 ledger 缺失时直接失败且不创建它。角色、membership、schema 和 default-privilege DDL 在一个事务中执行，任一步失败都会回滚，不留下部分 bootstrap 状态；密码值不写入仓库、命令行或输出。`kunlun_im_migrator` 到 `kunlun_im_owner` 的 membership 固定为 `INHERIT FALSE, SET TRUE, ADMIN FALSE`，verifier 会检查三项选项、所有 provider 对象的显式 grantee 和 default ACL 漂移。provider migration 只接受 `INSTRUMENT_MASTER_MIGRATOR_DSN`（或受保护的 `_DSN_FILE`），并在 shared worker V1–V4 ledger 通过只读校验后写入独立 provider ledger。共享 PostgreSQL 超级用户仍是 bootstrap/admin trust boundary，不能将该边界描述为对超级用户的全库隔离。

完整性由五个固定分区、每个分区从 offset 0 连续分页、短页终止、成功响应、严格字段/身份校验和 raw manifest 内容寻址证据共同证明；Tushare 未提供可信 revision 时保留 `source_revision=NULL`，本地内容寻址版本由 manifest digest、profile/parser/schema 版本和 raw evidence graph 定义，不构成操作者自证的版本。分区缺页、达到分页上限、结构漂移、身份冲突或 transport 失败时，运行保持 `INDETERMINATE`/`REJECTED`，不会改变已接受 head，也不会把缺席推断为退市。更旧的完整 raw run 只能留下可审计的 `NO_HEAD_CHANGE`，不会制造 removal candidate；相同完成坐标的不同内容会被拒绝。只有 provider 明确的 `D` 状态或退市日期才形成退市证据。该同步不负责行情条数、价格差异、调度或真实交易。
