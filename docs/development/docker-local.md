# Phase 0–3 本地 Docker 部署

本部署只用于本地开发与验收，包含现有基础设施、NestJS API、React Web 和
`sample-engine`。Phase 0–6 仍不包含真实券商凭证、实盘网络或可调用下单路径。

## 1.0 精简启动

1.0 的本地单管理员启动使用 `docker-compose.v1.yml` 叠加基础和应用配置，要求 Docker
Compose 2.24.4 或更高版本。已有 `infra/docker/.env` 时保留原文件；首次使用才从
`.env.example` 复制，Windows 可使用 PowerShell `Copy-Item`。

```bash
pnpm v1:config:check
pnpm v1:up
pnpm v1:sync
pnpm v1:ps
```

`v1:up` 构建并启动 PostgreSQL、ClickHouse、必要迁移、本地标的目录、server 和 web。
不启动量化引擎、排名、涨跌停 fixture 物化、Redis、MinIO 或可观测性服务；原开发栈仍可用
`docker:up` 显式启动。数据库和应用发布端口只绑定 `127.0.0.1`，沿用现有数据目录与 named
volume，不复制、删除或重置数据。启动已有库前先备份；这套配置只用于本机受控使用。

`v1:sync` 显式运行一次 AKShare 日线采集，默认覆盖发布清单中的 8 个沪深标的，分钟采集
关闭。日线请求截止采集日期前一天，页面应按“截至上一可用交易日”读取；不会生成当天
实时行情。采集先保存 raw，再写 ClickHouse；raw 和检查点位于 `kunlun-market-raw` volume
中的 `v1-shares-v3` 子目录，旧目录保持原样，成交量修正说明见行情源手册。
`V1_MARKET_DATA_SYMBOLS` 可显式缩小或调整本地样本，不代表自动支持全市场。

这一精简入口固定使用 AKShare 与环境模式，不读取 managed settings，也不使用 Tushare token。
实例级来源设置仍按[行情源手册](../runbooks/market-data-source.md)单独启用和验收。首发菜单与
页面范围另按[1.0 发布计划](../superpowers/plans/2026-10-12-v1.0-release-plan.md)收敛；启动成功
不表示其他页面已可用。

Web 为 <http://localhost:5173/>，健康检查为 <http://localhost:3002/api/v1/health>。
登录复用已有管理员，不覆盖账户或密码。停止使用 `pnpm v1:stop`，恢复使用 `pnpm v1:up`。
重复执行 `v1:sync` 会读取持久化检查点；同一天已确认的日线不重复采集，次日执行才刷新。
进程中断后使用同一命令恢复，不通过删除检查点绕过校验。采集失败应查看安全摘要并修复
原因，不使用 fixture 替代真实行情。

### 备份与恢复

备份保存在 checkout 的忽略目录或外部受限目录，不提交到 Git。PostgreSQL 备份包含认证状态，
应限制目录和文件权限；使用同版本 `pg_dump -Fc` 保存业务库。ClickHouse 日线需同时保存
`bars_daily_v2` 的建表定义及包含所有字段、来源和修订版本的导出；raw volume 与检查点另行保留。

恢复演练应在无网络、无宿主端口的临时实例执行，不能覆盖运行库。PostgreSQL 使用
`pg_restore --exit-on-error --no-owner --no-privileges` 还原后，明确查询 `kunlun` schema 下的
规则修订、评估历史、outbox 和已读表；备份不会自动复制原账号的默认 `search_path`。
ClickHouse 使用保存的定义创建表并导入全部日线版本，按证券、日期、来源和修订版本排序后，
核对所有字段和行数。退出码为 0 只证明命令成功，仍须核对业务记录。

常规服务故障先使用 `pnpm v1:up` 恢复同一数据目录，再核对登录、日线日期、规则与已读状态。
数据库不可用时页面应显示错误，恢复后重新查询；不清空数据库或检查点，不替换成 fixture。
只有隔离恢复核对通过且明确授权后，才选择维护窗口替换运行库或数据卷。

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
