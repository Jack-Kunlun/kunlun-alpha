# Phase 0 验收复核与修复记录

日期：2026-08-12
范围：P0-N01 至 P0-N15，仅工程基础设施；不包含 Phase 1 业务能力或任何真实交易路径。

## 结论

WorkBuddy 的初始交付具备 Monorepo、Web、API、Python workspace、基础设施编排和基础质量门禁，但首次复核未达到 Phase 0 出口标准。本轮按节点边界修复阻断项，并以全量门禁、基础设施配置校验和运行态探针作为最终验收依据。

## 首次复核阻断项

| 节点   | 问题                                               | 风险                       | 修复状态                                             |
| ------ | -------------------------------------------------- | -------------------------- | ---------------------------------------------------- |
| P0-N03 | 根运行时采用版本范围而非精确版本                   | 三端环境漂移               | 已精确锁定 Node.js、pnpm、Python、uv                 |
| P0-N10 | Python 生成物与 Schema 漂移，且未纳入类型门禁      | 合同生产者/消费者不一致    | 已统一生成格式并将 `gen:check` 纳入门禁              |
| P0-N11 | ClickHouse/MinIO、API/Grafana 宿主端口冲突         | Compose 与应用无法并行启动 | 已改为唯一宿主端口                                   |
| P0-N12 | OpenTelemetry、指标和 Python 健康检查为占位实现    | 无法证明可观测性链路       | 已接入 OTLP SDK、健康检查、Prometheus 指标和告警规则 |
| P0-N13 | Python 类型检查为 basic，根门禁未覆盖 Ruff/Pyright | 缺陷可绕过 CI              | 已启用 strict 并纳入 `pnpm check`                    |
| P0-N14 | CI 仅监听 `main`，仓库当前采用 `master`            | 推送后不触发 CI            | 已同时覆盖 `main` 与 `master`                        |
| P0-N15 | 端口、健康路径与实际实现不一致，关键状态测试不足   | 运维误导和回归风险         | 已同步文档并补 Web/API/Python 测试                   |

## 验收方法

最终验收必须使用新鲜输出确认：

1. `pnpm format:check`
2. `pnpm lint`
3. `pnpm python:lint`
4. `pnpm typecheck`
5. `pnpm python:typecheck`
6. `pnpm test`
7. `pnpm build`
8. `docker compose -f infra/docker/docker-compose.yml --env-file infra/docker/.env config`
9. 实际启动后检查容器健康、API/Python `/health` 与 `/metrics`
10. LF、契约生成漂移、禁止真实交易路径专项检查

若 Docker 引擎或网络不可用，应明确记录为环境阻断，不得把静态 Compose 校验表述为运行态通过。

## 安全边界

- 本轮没有加入券商 SDK、真实账户凭据、QMT 连接或可调用真实订单路径。
- Phase 0 至 Phase 6 继续保持真实交易能力物理缺失。
- 指标标签仅使用 HTTP 方法、路由和状态码，不使用证券代码、账户 ID 等高基数字段。
- 环境示例仅包含不可用占位值，不记录个人路径或密钥。

## 最终状态

2026-08-12 本机复验结果：

- Prettier、ESLint、Ruff、TypeScript、BasedPyright strict、契约漂移检查全部通过。
- Web 6 项、API 3 项、可观测包 7 项和 Python 12 项测试通过；Python 总覆盖率 93.50%。
- Web、API 与共享包生产构建通过；构建后的 API 实际启动并返回健康与指标响应。
- Python sample-engine 实际启动，`/health` 与 `/metrics` 均返回 HTTP 200。
- Docker Compose 全部镜像拉取成功；PostgreSQL、Redis、ClickHouse、MinIO、Prometheus、Grafana、Loki、Tempo 均为 healthy，MinIO 初始化任务退出码为 0。
- 122 个受检文本文件均为 LF；应用与服务目录未发现券商、QMT、实盘或下单路径。

因此，本轮列出的 Phase 0 阻断项已修复，Phase 0 工程出口门禁通过。运行中的本地基础设施容器被保留，便于后续开发；可使用 `pnpm infra:down` 停止。
