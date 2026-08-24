# Phase 0–3 本地 Docker 部署

本部署只用于本地开发与验收，包含现有基础设施、NestJS API、React Web 和
`sample-engine`。Phase 0–6 仍不包含真实券商凭证、实盘网络或可调用下单路径。

## 部署边界

- `postgres`、`clickhouse`、`redis`、`minio` 与可观测性服务沿用
  `infra/docker/docker-compose.yml`。
- `server-migrate`、`data-worker-migrate` 与 `clickhouse-migrate` 是幂等 one-shot
  服务，成功后以退出码 0 停止；`data-worker-migrate` 复用 Phase 1 的 checksum、
  advisory lock 和 schema 漂移校验。
- `server` 暴露宿主端口 `3002`，健康检查为 `/api/v1/health`。
- `web` 暴露宿主端口 `5173`，并在容器内把 `/api` 代理到 `server:3002`。
- `sample-engine` 暴露宿主端口 `8080`，健康检查为 `/health`。
- `data-worker` 与 `intelligence-engine` 当前没有长期运行入口，只作为已测试的库和
  流水线模块存在，不创建虚假的常驻容器。

## 启动

首次运行时创建本地环境文件：

```bash
cp infra/docker/.env.example infra/docker/.env
pnpm docker:up
pnpm docker:ps
```

Compose 使用现有 bind mount 和 named volume。启动、重建或普通 `docker:down`
不会删除 PostgreSQL、ClickHouse、Redis、MinIO 或可观测性数据。

## 验证入口

- Web：<http://localhost:5173/event-workbench>
- API 健康：<http://localhost:3002/api/v1/health>
- Swagger：<http://localhost:3002/api/docs>
- 数据质量：<http://localhost:5173/data-quality>
- 市场情绪：<http://localhost:5173/market-regime>
- Python 健康：<http://localhost:8080/health>
- Grafana：<http://localhost:3001>
- MinIO Console：<http://localhost:9001>

事件反馈写入保持 fail-closed；未接入授权实现时返回 forbidden 是预期行为。

## 停止与恢复

```bash
pnpm docker:down
pnpm docker:up
```

禁止为常规重启使用 `docker compose down -v`，也不要删除
`infra/docker/data`。如需重置数据，必须先单独备份并明确确认目标卷。
