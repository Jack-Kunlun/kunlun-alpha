# P1-R08 数据质量 API 与终端

把 data-worker 持久化的质量事件（`fund_quality_events`）通过 repository port
接入 NestJS API，并通过共享 API client 接入 Web 数据质量页面。

## API 端点

全局前缀 `api/v1`：

- `GET /api/v1/data-quality` — 查询质量事件，可选过滤：
  - `date`（单交易日，`YYYY-MM-DD`）
  - `dateFrom` / `dateTo`（交易日区间，含端点）
  - `source`（来源）
  - `unifiedCode`（后缀式证券代码，如 `600519.SH`）
  - `kind`（质量事件类型，如 `SOURCE_CONFLICT`）
- `GET /api/v1/data-quality/:id/evidence` — 按安全内部 ID 查询证据（仅返回
  `id`、`source`、`schemaVersion`、`availableAt`，绝不返回 raw object 路径、
  DSN、token、Cookie、Authorization 头或原始异常文本）。

## 校验与安全边界

- 证券代码必须是后缀式 `^\d{6}\.(SH|SZ|BJ)$`；`SH.600519` 之类的前缀式被拒绝。
- 日期必须是合法 `YYYY-MM-DD`；`dateFrom > dateTo` 被拒绝。
- `source` 仅允许 `[A-Za-z0-9._-]{1,64}`，拒绝路径穿越（`../`、`/`、`\`）。
- `kind` 仅允许大写 ASCII 标识符。
- 未知查询字段被全局 `ValidationPipe`（`forbidNonWhitelisted`）拒绝。
- 证据 ID 仅允许 `^[a-z0-9-]{1,128}$`。

## 失败语义

- 授权失败 → 受控 `403`。
- 过滤器非法 → 受控 `400`。
- repository/数据库错误 → 传播为 `500`，绝不伪造空成功。

## 配置

- `DATA_QUALITY_POSTGRES_DSN`：数据质量仓库的 PostgreSQL 连接串。缺失时模块
  启动即失败（fail-closed），不静默回退到空结果。
- 该 DSN 只从环境变量读取，不写入日志、文档或 fixture。

## 集成测试

```bash
KUNLUN_TEST_POSTGRES_DSN="postgresql://<user>:<password>@localhost:5432/kunlun" \
  pnpm --filter @kunlun/api exec vitest run \
    src/modules/data-quality/postgres-quality.repository.integration.test.ts
```

测试在隔离 schema 中建表、插入带敏感 raw 字段的证据，并断言查询结果绝不
暴露 raw object id、capture id、checksum 或 payload digest。
