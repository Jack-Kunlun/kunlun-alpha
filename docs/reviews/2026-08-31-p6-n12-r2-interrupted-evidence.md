# P6-N12 第二轮中断证据

日期：2026-08-31

## 结论

项目负责人为尽快建立合规门禁，明确授权停止第二轮墙钟运行。该轮仅保留为历史耐久证据，
不得用于关闭 P6-N12 或 Phase 6 门禁，也不得与任何其他运行拼接时长。

## 停止时状态

- launchd 作业：`com.kunlun.p6n12.endurance.r2`，已卸载。
- 进程：PID `44352`，已停止。
- 隔离数据库：`kunlun_paper_endurance_p6n12_r2`，保留且 `ALLOW_CONNECTIONS=true`。
- 已完成迭代：`2788`。
- 已运行墙钟：`168640.733` 秒，约 `46.84` 小时。
- 执行能力：`PAPER_ONLY`。
- 证据范围：`DURABLE_ADAPTER`。
- 存储适配器：`postgresql`。
- 正式报告：未生成；进程未达到请求的 72 小时。
- stdout/stderr：均为空。

原始进度快照保存在
[`2026-08-31-p6-n12-r2-interrupted-progress.json`](./2026-08-31-p6-n12-r2-interrupted-progress.json)，
SHA-256 为 `b6bd7cda23207d3e59a5a9b704cb7910c92f3f30036a974c024da410869c0f66`。

## 只读检查结果

使用原运行的精确 `sourceVersion` 执行 `scripts/check-paper-soak-evidence.py`，退出码为 `2`，
状态为 `INVALID`，错误为：

- `UNSAFE_EVIDENCE_TARGET`
- `PROCESS_NOT_RUNNING`

数据库目标未包含要求的随机 UUID 后缀，即使自然运行满 72 小时也不能取得正式资格。
后续正式门禁必须使用全新 UUID 隔离数据库、全新进度与报告文件，并从零计时。
