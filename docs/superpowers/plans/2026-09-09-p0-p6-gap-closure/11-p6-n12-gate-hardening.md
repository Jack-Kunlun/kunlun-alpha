# 计划 11：P6-N12 门禁实现加固

## 目标

在冻结候选版之前，收敛当前未提交的 paper endurance/reliability 修改，保证宿主睡眠、UTC 与
单调时钟不一致、数据库中断、证据漂移和连接泄漏都能在短时测试中失败关闭。该计划不运行
正式 24 小时门禁。

## 已有基础与缺口

- R4 四类故障矩阵通过，但宿主睡眠导致 UTC 跨度约 38 小时、有效运行约 24 小时，独立检查器
  返回 `CLOCK_ELAPSED_MISMATCH`。
- 工作区已有 `paper-core`、runner 和恢复 runbook 修改；这些修改尚未形成冻结候选证据。
- 不能只在最终报告阶段发现睡眠/时钟问题；启动前和运行中都要有可验证的失败关闭信号。

## TDD 与实施顺序

1. 固化 R4 不一致为回归 fixture，先证明旧 preflight/runner 无法提前阻断。
2. 增加启动前检查：禁止自动睡眠能力、UTC/monotonic 基线、数据库 marker/权限、依赖服务
   restart count、遗留进程和证据路径隔离。
3. 增加运行中检查：wall/monotonic 漂移、时钟回拨/跳变、进度文件身份、sourceVersion 和依赖
   重启变化；异常立即写固定 failure code 后停止。
4. 加固 PostgreSQL 断连、连接释放、重试幂等、runner 关闭和检查器固定字段/摘要绑定。
5. 统一 `reliability.py`、`endurance_evidence.py`、`run-paper-soak.py`、测试和 runbook 的 P6
   最低 24 小时资格；补 23 小时拒绝与 24 小时 durable PostgreSQL 资格通过回归。
6. 将 `endurance_evidence.py`、`scripts/check-paper-soak-evidence.py`、报告 schema、
   `MAX_CLOCK_DRIFT_SECONDS=300.0` 和最低时长纳入候选证据绑定。
7. 执行分钟级短时 dry-run 和四类故障各一次，不将短时结果标记为资格证据。
8. 独立 Terra Max 审核 runner、只读检查器和证据篡改边界；通过后才进入候选冻结。

## 验收标准

- R4 fixture 稳定返回 `CLOCK_ELAPSED_MISMATCH`，历史文件不被修改或重新签名。
- 模拟睡眠/时钟漂移在固定容差内被运行中守卫阻断；无守卫能力时启动前失败。
- 任一 source/config/evidence 摘要漂移、路径复用或数据库 UUID 不匹配均失败关闭。
- 23 小时请求固定拒绝；24 小时 durable PostgreSQL 请求满足资格时长契约。短测只验证逻辑，
  不产生正式资格。
- 检查器必须从不可变候选镜像/已哈希 wheel 运行，或在候选 manifest 中记录其独立 SHA-256；
  `--expected-source-version` 必须精确匹配候选 manifest。
- 四类故障短测能恢复并完成对账；末端 adapter connections/leases/pending messages 符合契约。
- 所有测试使用 `PAPER_ONLY` fake/simulation，不包含 broker SDK、真实账户或真实订单路径。

## 验证范围

- `paper-core` endurance/reliability 定向测试、runner CLI/fixture、BasedPyright/Ruff。
- 专用 UUID 测试数据库的 PostgreSQL 故障与清理测试。
- 23/24 小时时长边界、分钟级短测、检查器正反例、证据 hash/路径身份和进程清理。
- 不扩大为正式 24 小时运行；完成后仍须执行计划 12 和 13。
