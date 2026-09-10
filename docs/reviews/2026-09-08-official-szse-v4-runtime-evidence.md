# SZSE 官方逐日 V4 运行验收证据

## 结论与范围

截至 2026-09-08，SZSE direct-daily V4 的 raw-first capture/replay、V4 PostgreSQL
持久化、hydration、as-of 查询和本地 worker 镜像 E2E 已完成冻结验收。本记录只证明
SZSE 当前 accepted horizon 的这一次运行，不宣称 P1-N07 的所有交易所、年份、行情
完整性或证券生命周期缺口已经补齐，也不表示 24 小时正式门禁已经启动。

这条路径使用 parser/source `szse-direct-daily-v4` 和 scan-run contract
`calendar-scan-run-v4`。原始证据先持久化并校验，再 replay 入 V4 ledger；调用方不能
用未经过 raw replay 的结果或 proof 直接伪造可见 snapshot。

## 冻结实现与检查

冻结对象的完整 SHA-256 如下：

- `official_calendar_repository.py`：`1240122e73833564d8d000979d80a84acb7ab4d4bbf4993e55b54dce2963f2eb`
- `official_calendar_migration.sql`：`03742808116b4b3adece9e6d6f8455ec93d9a20e9f797a7c0857ef9844874972`
- `migrations.py`：`901803113b6953dbb85602a0c034f2d0a7b37962933e5cb995dc2f178a29f8af`
- `test_official_calendar_v4_postgres.py`：`d92f451019934c24a3bd7873b913efaad93035efd0991446cd2d86ecf5552e0e`

父级定向检查结果为：V4 offline `19 passed / 20 skipped`，V4 real PostgreSQL `39 passed`，
受影响日历 real PostgreSQL `303 passed`，C2A/core `198 passed`，静态检查全部通过。
这些数字分别属于代码/测试验证，不等同于目标库或镜像运行证据。

新增的一次性入口为 `official-szse-daily-sync`，固定处理 `SZ/2026`。collect 先完成
raw-first capture，再仅使用 raw coordinates 写入 V4；replay 必须指定既有 `run_id`、
`manifest_date` 和 `manifest_capture_id`，不访问网络。CLI 不执行 migration，也不接入
scheduler。入口在本地 worker 镜像中已安装，镜像内 `--help` 执行成功。

本地定向检查合计为 `164 passed / 20 skipped`，skipped 仅表示未启用 real-PostgreSQL
fixture；Ruff 通过，BasedPyright 为 `0 errors`。该汇总与上面的 V4/real-PG/受影响日历
分项结果属于不同检查口径，不能相加推导更大范围的覆盖结论。

本次 runtime hardening 的 working-tree 定向回归为 `test_official_szse_runtime.py`：
`38 passed`。raw-root 现在要求预先存在的绝对非根非 symlink 目录，并校验根目录及
immediate parent 的 owner、group/world-writable 状态和 dev/inode identity；CLI 生命周期
保持目录 capability/guard，在 raw storage 操作及 collect 到 persist 边界前后复核。未知
领域错误只映射到固定 allowlist，close 失败返回固定错误且不输出成功 JSON；migration 测试
通过真实 `data_worker.storage.migrations` import boundary 验证 runtime 不暴露或调用迁移。
结果组合遵循 V4 状态机：`COMPLETE` 仍要求 snapshot + `FINAL_YEAR`，无 snapshot 仍必须
为 `INDETERMINATE`；非 confirmed 的 `OUT_OF_ORDER_BLOCKED`、`CONFLICT_HEAD` 及其
`DUPLICATE` 可在 full-year proof 下保持无 snapshot + `INDETERMINATE`。
该 working-tree 修复本身尚未重建镜像或重新执行 Docker/网络/目标库验收；上节镜像 digest
仍仅代表已记录的上一轮镜像运行证据。

## 目标 PostgreSQL 验收

目标 ledger 的 V4 checksum 为 `03742808116b4b3adece9e6d6f8455ec93d9a20e9f797a7c0857ef9844874972`。
目录核验包含 9 张 V4 表和 5 个 V4 函数：

- owner mismatch：`0`
- persistence mismatch：`0`
- RLS-or-forced mismatch：`0`
- explicit ACL mismatch：`0`
- security-definer mismatch：`0`
- function owner mismatch：`0`
- function config mismatch：`0`

这部分只记录已验收的 schema/catalog/权限结果；本文件不包含 DSN、密码、token 或原始
响应正文。

## 持久 raw 与运行结果

冻结的 live raw run 为
`3d5e39e8-551d-4868-9ca8-c2ba382a8dd2`，accepted snapshot 为
`099b0d2e-5c17-5d88-946f-e64ae62650c3`，proof digest 为
`c3bf387ed1341993a2d375e7d41b076d85a5e70c8280ee4952b508a3162cdf15`。
计数按 `typed refs / attempts / catalogs / passes / pages / manifest / snapshot evidence / days`
排列，为 `69 / 28 / 12 / 2 / 24 / 1 / 69 / 365`。

该 snapshot 覆盖 365 天，其中 242 个交易日、123 个非交易日，包含 19 个工作日闭市日，
确认到 `2026-09-07`。实际 as-of 查询结果为：`2026-01-02` 返回
`NON_TRADING / OFFICIAL_NON_TRADING`；`2026-09-07` 返回 `TRADING / OFFICIAL_TRADING`；
`2026-10-01` 返回 `INDETERMINATE / OFFICIAL_HORIZON_UNCONFIRMED`。同一 run 的重复
replay 返回 `DUPLICATE`，保持幂等且不增加可见 snapshot。

## 镜像与耐久 raw 验收

本地 worker 镜像 digest 为
`sha256:01e11e97712270f9e73870e38eebc0c9e2d533f0dc3f57e8786e47fdfa4b27c7`，镜像内记录的
repository/SQL hash 与冻结对象一致。容器 E2E 的 duplicate replay 和 `TRADING` 查询均通过。

一次性容器使用现有 `docker_default` 网络、只读 `kunlun-market-raw` volume 和目标
PostgreSQL 执行离线 replay；返回同一 `run_id=3d5e39e8-551d-4868-9ca8-c2ba382a8dd2`、
`snapshot_id=099b0d2e-5c17-5d88-946f-e64ae62650c3`、`disposition=DUPLICATE`、
`coverage_level=CONFIRMED_HORIZON`、`terminal=INDETERMINATE`。这里的
`terminal=INDETERMINATE` 是确认窗口只到 `2026-09-07` 时的预期失败关闭语义；不表示
未来日期已经确认，也不表示 scheduler/API 已持续接通。

持久 raw 复制结果为 `402/402`，缺失数和 mismatch 数均为 `0`，对象 owner 为
`10001:10001`。本记录不写入个人路径、临时主机路径或 raw body。

## 独立审计与未覆盖边界

Terra 对冻结 C2B 范围的最终审计结果为 P0/P1 `0`；P2 verifier/runtime hardening
仍是单独边界，不在本次运行证据中升级为已完成能力。

V3 SSE 稀疏路径的 19 条记录仍为 `UNKNOWN`；SH 与 SZ 的工作日闭市集合比较为
`0/0` 差异，但这不能升级 SH 的来源完整性。SH/BJ 官方来源穷尽性和 BSE 授权仍是
阻塞项；证券生命周期、行情应有条数缺失判定、来源价格差异检测以及 AKShare/Tushare
真实采集验收也不由本记录覆盖。

因此，P1-N07 仍不能宣布全部完成，24 小时正式门禁仍未启动。本轮没有 commit 或 push。
