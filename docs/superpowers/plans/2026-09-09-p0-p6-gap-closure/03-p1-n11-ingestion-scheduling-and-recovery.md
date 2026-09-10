# 计划 03：P1-N11 持续调度与恢复

## 目标

把已经验收的一次性 calendar、instrument-master 和 market-data 入口接入受控调度，使任务可
检查点恢复、可重放、可观测，且不会因重试重复提交数据。

## 前置依赖

- 计划 01 的三所日历来源、终态和 V5 quality 投影已经通过。
- 计划 02 的证券主数据运行和 reader 权限已经通过。
- 现有 market-data scheduler 的 lease/checkpoint/error 分类基线保持有效。

## 范围

- 独立 job type、稳定 operation/run identity、lease、checkpoint、bounded backoff 和 dead letter。
- 明确区分 transport、rate-limit、validation、authorization、conflict、permanent 和 internal error。
- 任务终态及 metrics/alerts；禁止证券代码、run ID 等高基数 Prometheus label。
- 默认 Compose 不自动启动真实采集；启用仍是显式 profile/配置动作。

## TDD 与实施顺序

1. 先增加崩溃点、重复消息、过期 lease、乱序 replay、限流、永久错误和权限失败用例。
2. 为三个任务族分别接入 scheduler adapter，不把 provider 实现写入 scheduler。
3. 持久化 checkpoint 与 terminal state；重启后从最后确认坐标继续。
4. 增加 operator API/只读状态和 runbook，明确 start/stop/replay/rollback。
5. 用隔离数据库和 fake provider 做故障注入，再对现有 Docker 栈执行一次默认禁网的短时
   canary；若 canary 需要真实请求，必须复用计划 06 已批准的 provider、范围、镜像摘要和
   写入边界。

## 验收标准

- 已确认 raw、snapshot 和 bar 不会因重启/重复消息重写或重复提交。
- 授权/结构/完整性错误不重试；暂时错误按有界退避重试并保留最终失败证据。
- 进程终止后 lease 可安全恢复；旧 run 不能覆盖较新的 accepted head。
- 任务状态可按 job/run 查询并链接脱敏证据；停用配置后不发起外网请求。
- 不扩大数据库、raw volume、provider token 或 server 权限。

## 验证范围

- scheduler/task-state 定向测试、三个 adapter 的恢复/幂等测试、真实 PostgreSQL lease/checkpoint 测试。
- Compose 配置、镜像 CLI、短时故障注入 canary 和重启恢复。
- Ruff、BasedPyright、受影响 server 类型/构建检查。
