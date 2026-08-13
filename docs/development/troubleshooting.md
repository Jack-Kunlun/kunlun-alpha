# 故障排查

按从常见到少见排列。每个条目给出症状、原因与解决步骤。

## 端口冲突

**症状**：`EADDRINUSE` / `Address already in use`；浏览器访问到错误服务。

**原因**：其他本机程序可能占用 API 3002、Grafana 3001、ClickHouse native 9002、MinIO 9000，或 5432/6379/5173 等端口。

**解决**：

```bash
# 查看占用
netstat -ano | findstr :3002        # Windows
lsof -i :3002                        # macOS / Linux

# 用其他端口启动 API（推荐，不改 Grafana）
PORT=3012 pnpm --filter @kunlun/api dev
```

Web 侧 Vite 会自动跳空闲端口；如固定端口被占，可在 `apps/web/vite.config.ts` 调整 `server.port`。

## 依赖安装失败（lockfile 不一致）

**症状**：`ERR_PNPM_OUTDATED_LOCKFILE` / `uv sync` 报 `frozen lockfile` 错。

**原因**：`package.json` / `pyproject.toml` 被修改但锁文件未同步。CI 与 `--frozen-lockfile` / `--locked` 模式强制锁文件一致。

**解决**：本地执行普通安装更新锁文件并提交：

```bash
pnpm install          # 更新 pnpm-lock.yaml
uv sync               # 更新 uv.lock
```

## Windows：写入文件被拒（EPERM / 权限错误）

**症状**：`EPERM: operation not permitted`、`error creating log file`、`rename ... Access is denied`；集中在构建产物、`.turbo/`、`node_modules/.package-map.json`、SQLite/`tsbuildinfo` 等已存在文件上。

**原因**：目标目录被同步/安全软件或驱动器写保护锁定；pnpm、turbo、tsc 以"覆盖已存在文件"方式写入被拒（新建文件通常正常）。

**解决**：

1. 关闭 OneDrive 同步 / 目录锁定的安全软件，或将仓库移出同步目录。
2. 以普通（非管理员提权依赖）终端重跑失败命令；多数工具会自动重试或删除后重建。
3. 清理残留产物后重跑：

```bash
pnpm clean
rm -rf node_modules
pnpm install
```

4. 避免把仓库放在受保护卷（如某些网络盘 / 只读分区）。

## pnpm / turbo 缓存或日志异常

**症状**：`Failed to replay logs`、`error creating log file`、任务重复执行无缓存。

**原因**：`.turbo/` 残留日志或 store 索引损坏；本仓库 turbo 任务已统一 `cache: false`，无缓存是预期行为，不会影响正确性。

**解决**：

```bash
# 删除本地构建缓存后重试
pnpm clean
```

## Docker 基础设施问题

**症状**：`pnpm infra:up` 后应用连不上数据库；`pnpm infra:ps` 显示 `unhealthy` / `restarting`。

**排查**：

```bash
pnpm infra:logs            # 查看全部容器日志
docker compose -f infra/docker/docker-compose.yml --env-file infra/docker/.env ps
# 单服务日志，如 PostgreSQL
docker logs kunlun-postgres
```

常见原因与处理：

- **端口被本机服务占用**：停用占用进程或修改 compose 映射。
- **容器反复重启**：数据目录损坏时删除对应 `infra/docker/data/<service>` 目录后 `pnpm infra:up`。
- **首次启动慢**：ClickHouse 初始化较久，等待 healthy 后再连。

## Python 侧问题

**症状**：`uv` 命令不存在 / `command not found: uv`。

**解决**：按 [uv 官方文档](https://docs.astral.sh/uv/getting-started/installation/) 安装；`pyproject.toml` 精确要求 `uv 0.12.3`。安装后重启终端使 PATH 生效。

**症状**：`uv sync` 报 workspace member 缺失。

**原因**：`[tool.uv.workspace] members` 包含 `python/packages/*` 与 `services/*`，新增目录未纳入。在根目录执行 `uv sync --locked`，勿在子目录单独执行。

## 门禁失败但本机正确

**症状**：本地 `pnpm check` 通过，CI 报 `check-clean-tree` / 行尾检查失败。

**原因**：

- 构建产物被提交：`dist/`、`.next/`、`*.tsbuildinfo`、`coverage/` 需保持 git 忽略，仅提交源码。
- 行尾不一致：提交了 CRLF 文件。CI 运行 `scripts/ci/check-line-endings.mjs` 校验，运行 `pnpm format` 后重新提交。

## 仍无法解决

- 查看服务日志与上述命令输出，携带完整报错（含退出码）反馈。
- 遵循仓库 [AGENTS.md](../../AGENTS.md) 的节点推进流程，单节点验证通过后再继续。
