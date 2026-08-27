# 模拟组合终端运行手册

## 当前能力

- `quant-engine` 在进程内维护一个模拟账户、账户事件链和模拟执行事件链。
- Web 通过 Nest 控制面创建模拟账户，并运行 Signal 到 OrderIntent、服务端风控、模拟全额成交和双账簿对账闭环。
- 金额使用十进制字符串；订单固定为 `PAPER_ONLY`，不存在真实账户、券商连接或真实下单入口。
- `clientRequestId` 对创建账户与模拟命令提供幂等保护；相同键的不同载荷会 fail closed。

## 已知限制

- 当前状态只保存在 `quant-engine` 进程内。容器或服务重启会清空模拟账户和事件链。
- 当前终端只提供手工多头信号的全额模拟成交，不提供真实行情执行、部分成交输入或跨日可卖数量释放。
- 真实持久化恢复与长时间墙钟运行不属于本地现状，不得从健康检查或单元测试推断其已通过。

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
3. 对账结果为 `DRIFTED` 时停止新增模拟命令，保留响应中的摘要和差异，再重建本地工作区。
4. 不要通过重试更换 `clientRequestId` 绕过冲突；先确认原命令是否已提交。
