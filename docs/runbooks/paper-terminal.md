# 模拟组合终端运行手册

## 当前能力

- `quant-engine` 维护一个模拟账户、账户事件链和模拟执行事件链；本地 Compose 通过独立持久卷保存命令日志。
- Web 通过 Nest 控制面创建模拟账户，并运行 Signal 到 OrderIntent、服务端风控、模拟全额成交和双账簿对账闭环。
- 金额使用十进制字符串；订单固定为 `PAPER_ONLY`，不存在真实账户、券商连接或真实下单入口。
- `clientRequestId` 对创建账户与模拟命令提供幂等保护；相同键的不同载荷会 fail closed。

## 持久化与恢复

- 设置 `KUNLUN_QUANT_STATE_DIR` 后，创建账户和模拟命令在执行前写入 `paper-workspace.jsonl`。日志按序号和 SHA-256 前序摘要连接，写入后执行 `fsync`；重启会从头验证并重放，再重新生成账户、订单、风控和对账状态。
- 日志缺字段、顺序断裂、摘要不符、载荷不合法或重复命令时，quant-engine 拒绝启动，不会用空工作区掩盖损坏。
- 未设置 `KUNLUN_QUANT_STATE_DIR` 的测试进程仍使用 `VOLATILE_IN_MEMORY`；正式本地 Compose 使用 `DURABLE_COMMAND_JOURNAL`。
- 本地日志只支持单个 quant-engine 实例，不是多副本共用的分布式日志。备份或恢复时必须把服务停在单实例边界，并保留整个 `kunlun-quant-state` 卷。

## 已知限制

- 当前终端只提供手工多头信号的全额模拟成交，不提供真实行情执行、部分成交输入或跨日可卖数量释放。
- 24 小时 P6 墙钟门禁使用独立 PostgreSQL 证据库；本地命令日志恢复不能替代该门禁，也不能据此宣称 Phase 6 已退出。该资格不构成实盘许可；真实交易前仍须取得独立的连续 72 小时合格耐久证据并通过全部 Phase 7 门禁。

## 启动与健康检查

```text
docker compose -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.apps.yml --env-file infra/docker/.env up -d --build
curl http://localhost:8081/health
curl http://localhost:3002/api/v1/paper/workspace
```

Web 页面：`http://localhost:5173/paper`。

Ranking 正式页面只读取 quant-engine 已发布的版本化快照。若尚未发布，页面显示空状态；测试验收 JSON 不会作为运行时回退数据。

## 故障处理

1. `quant-engine` 不健康时检查容器日志和 `KUNLUN_PORT`。
2. Nest 返回 `UNAVAILABLE` 时检查 `PAPER_ENGINE_URL` 与容器网络。
3. quant-engine 因日志损坏拒绝启动时，先复制并保全 `kunlun-quant-state` 卷；不要删除日志或改写摘要来强行启动。
4. 对账结果为 `DRIFTED` 时停止新增模拟命令，保留响应中的摘要和差异，再调查命令日志与账户/执行摘要。
5. 不要通过重试更换 `clientRequestId` 绕过冲突；先确认原命令是否已提交。
