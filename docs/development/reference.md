# 端口、环境变量与数据重置

## 端口清单

### 应用服务

| 服务                          | 默认端口 | 配置方式                  | 说明                                                                |
| ----------------------------- | -------- | ------------------------- | ------------------------------------------------------------------- |
| Web 终端（Vite）              | 5173     | `apps/web/vite.config.ts` | 开发服务器，`vite` 自动选空闲端口                                   |
| 控制面 API（NestJS）          | 3002     | 环境变量 `PORT`           | 健康检查 `GET /api/v1/health`；指标 `GET /api/v1/metrics`           |
| Python 引擎（FastAPI 类服务） | 8080     | 环境变量 `KUNLUN_PORT`    | `ServiceConfig` 定义于 `ashare-common`，所有服务使用 `KUNLUN_` 前缀 |

> API 使用 3002，Grafana 使用 3001；两者可同时启动且不会占用同一宿主端口。

### 本地基础设施（Docker Compose，`infra/docker/docker-compose.yml`）

| 服务       | 端口                                                | 说明                 |
| ---------- | --------------------------------------------------- | -------------------- |
| PostgreSQL | 5432                                                | 业务数据（TypeORM）  |
| Redis      | 6379                                                | 缓存 / 锁 / 实时状态 |
| ClickHouse | 8123（HTTP）/ 9000（native）                        | 时序行情与特征       |
| MinIO      | 9000（S3 API）/ 9001（Console）                     | 对象存储             |
| Prometheus | 9090                                                | 指标                 |
| Grafana    | 3001                                                | 仪表盘               |
| Loki       | 3100                                                | 日志                 |
| Tempo      | 4317（OTLP gRPC）/ 4318（OTLP HTTP）/ 3200（Query） | 分布式追踪           |

## 环境变量

所有本地默认凭证仅适用于开发，**不得**提交真实凭证。模板见 `infra/docker/.env.example`（基础设施）与根目录 `.env.example`（应用）。

### 基础设施（`infra/docker/.env`）

| 变量                                                                | 默认值                                        |
| ------------------------------------------------------------------- | --------------------------------------------- |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB`               | `kunlun` / `kunlun-local-dev` / `kunlun`      |
| `REDIS_PASSWORD`                                                    | `kunlun-local-dev`                            |
| `CLICKHOUSE_USER` / `CLICKHOUSE_PASSWORD` / `CLICKHOUSE_DB`         | `kunlun` / `kunlun-local-dev` / `kunlun`      |
| `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` / `MINIO_DEFAULT_BUCKETS` | `kunlun` / `kunlun-local-dev` / `kunlun-data` |
| `GRAFANA_USER` / `GRAFANA_PASSWORD`                                 | `admin` / `kunlun-local-dev`                  |

### 应用服务

| 变量                              | 默认值        | 读取方                           |
| --------------------------------- | ------------- | -------------------------------- |
| `PORT`                            | `3002`        | `apps/api/src/env.ts`（NestJS）  |
| `NODE_ENV`                        | `development` | `apps/api/src/env.ts`            |
| `KUNLUN_SERVICE_NAME`             | `kunlun`      | `ServiceConfig`（ashare-common） |
| `KUNLUN_LOG_LEVEL`                | `INFO`        | 同上                             |
| `KUNLUN_HOST`                     | `0.0.0.0`     | 同上                             |
| `KUNLUN_PORT`                     | `8080`        | 同上                             |
| `KUNLUN_SHUTDOWN_TIMEOUT_SECONDS` | `10.0`        | 同上                             |

## 常用命令

| 命令                                                                      | 作用                                                  |
| ------------------------------------------------------------------------- | ----------------------------------------------------- |
| `pnpm install --frozen-lockfile`                                          | 安装 Node 依赖（校验 lockfile）                       |
| `uv sync --locked`                                                        | 安装 Python 依赖（校验 uv.lock）                      |
| `pnpm dev`                                                                | 并行启动 Web + API（turbo）                           |
| `pnpm check`                                                              | 全量门禁：format + lint + typecheck + vitest + pytest |
| `pnpm build`                                                              | 构建全部包                                            |
| `pnpm lint` / `pnpm typecheck` / `pnpm test`                              | 分项门禁                                              |
| `pnpm format`                                                             | 用 Prettier 格式化全仓                                |
| `pnpm python:lint` / `pnpm python:typecheck` / `pnpm python:test`         | Python 分项门禁（ruff / basedpyright / pytest）       |
| `pnpm infra:up` / `pnpm infra:down` / `pnpm infra:ps` / `pnpm infra:logs` | 基础设施启停与查看                                    |

## 数据重置

本地数据落在 `infra/docker/data/`（Compose 卷），全部为可再生的开发数据。

```bash
# 停止但保留数据
pnpm infra:down

# 停止并删除全部数据卷（回到初始状态）
docker compose -f infra/docker/docker-compose.yml --env-file infra/docker/.env down -v
```

`down -v` 会删除数据库内容、对象存储桶、指标与日志。如需保留某个服务的数据，可单独重置其数据目录（如删除 `infra/docker/data/postgres` 后 `pnpm infra:up`）。

> MinIO 首次启动时由 `minio-init` 一次性创建默认桶；删除卷后重新 `up` 会自动重建。
