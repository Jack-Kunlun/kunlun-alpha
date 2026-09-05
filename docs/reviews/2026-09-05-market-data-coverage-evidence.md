# P1-N12 日线入库概览切片证据

## 结论与范围

本证据包只覆盖 `market-data-coverage-v1` 的只读日线观测切片：ClickHouse
`bars_daily_v2` → NestJS `GET /api/v1/data-quality/market-coverage` → Web 数据质量页面。
它不宣称整个 P1-N12 数据质量与对账面板、行情拒绝证据、缺口/来源差异或 Phase 1 已正式完成。
没有迁移、建表、采集启动、外网调用、秘密读取、提交或部署。

## 先红后绿

实现前运行：

```text
pnpm --filter @kunlun/server exec vitest run src/modules/data-quality/market-coverage.query.test.ts src/modules/data-quality/clickhouse-market-coverage.read-model.test.ts
```

结果：失败（2 suites / 0 tests），原因是待实现的 `market-coverage.query` 与
`clickhouse-market-coverage.read-model` 模块不存在。

实现后运行：

```text
pnpm --filter @kunlun/server exec vitest run src/modules/data-quality/market-coverage.query.test.ts src/modules/data-quality/clickhouse-market-coverage.read-model.test.ts src/modules/data-quality/market-coverage.service.test.ts src/modules/data-quality/market-coverage.controller.test.ts
```

结果：4 files / 15 tests passed。

```text
pnpm --filter @kunlun/web exec vitest run src/features/data-quality/market-coverage.test.ts src/features/data-quality/format-shanghai-time.test.ts src/features/data-quality/data-quality-panel.test.tsx src/features/data-quality/market-coverage-panel.test.tsx src/features/data-quality/data-quality-page.test.tsx
```

结果：5 files / 18 tests passed。

```text
pnpm --filter @kunlun/server typecheck
pnpm --filter @kunlun/web typecheck
```

结果：两条命令均通过。

```text
pnpm --filter @kunlun/contracts gen:check
pnpm --filter @kunlun/contracts exec vitest run src/data-quality/market-coverage-schema.test.ts
```

结果：TypeScript/Python 生成物均与 JSON Schema 同步；契约测试 1 file / 1 test passed。

最终模块范围回归与构建：

```text
pnpm --filter @kunlun/server exec vitest run src/modules/data-quality
pnpm --filter @kunlun/web exec vitest run src/features/data-quality
pnpm --filter @kunlun/server lint
pnpm --filter @kunlun/web lint
pnpm --filter @kunlun/contracts lint
pnpm --filter @kunlun/server build
pnpm --filter @kunlun/web build
git diff --check
```

结果：服务端 38 项通过、1 项跳过；Web 20 项通过；上述 lint、构建和差异检查通过。
跳过的是既有 PostgreSQL 集成测试，未设置 `KUNLUN_TEST_POSTGRES_DSN`，不将其计为通过。
主代理另复跑新增服务端 4 文件 15 项及 Web 数据质量模块 6 文件 20 项，均通过。
这不是仓库全量测试结果，也未执行浏览器登录后的端到端验收。

原有 15 个 P6 已修改文件的 SHA-256 与本次开工前一致；未修改其验收结论或启动墙钟门禁。

## SQL 只读核验

主代理在不启动服务、不写入 ClickHouse 的临时脚本中执行：

```text
node /private/tmp/kunlun-coverage-qa-mIFGWB/check.cjs apps/server/src/modules/data-quality/clickhouse-market-coverage.read-model.ts
```

该命令是一次手工只读真实 ClickHouse 验证，不是自动化联网测试，也不属于本仓库测试套件。
临时 helper 前两次分别因 TypeScript 模块位置解析和 SQL 导出常量别名解析在查询前失败；
修正 helper 后才执行以下真实查询，前两次没有触碰 ClickHouse 数据。
派生 fixture 共 9 行，包含重复日期、未来 `event_time`/`available_time`/`processing_time`、
未知 source、`MINUTE_1` 与 QFQ；查询只保留 2 个证券各 1 个观测日。证券与日期筛选也通过。
现有数据核验得到 4 个证券、每个 64 日，范围为 6 月 8 日至 9 月 4 日，来源为
`akshare-tencent`。该证据不改变原始数据，不创建表，不宣称全市场完整覆盖。

## HTTP stub smoke

构建后运行临时 stub（不进仓库、不启动现有服务、不写入数据）：

```text
node /private/tmp/kunlun-coverage-qa-mIFGWB/http-smoke.cjs
```

使用真实 controller/service/global validation pipe 与 fake read model，在随机 `127.0.0.1`
端口覆盖默认/合法筛选 200、未知 key/重复 `source` 数组/非法日期/日期混用/超过 366 日 400、
注入拒绝 authorizer 403、fake ClickHouse 故障 503（不泄漏原始错误），并确认旧列表路由 200；
最终 `app.close()`，命令 exit 0。前两次在受限 sandbox 监听端口遇到 EPERM，确认原因后经权限升级
重跑通过，属于环境限制而非代码失败。该 smoke 验证的是模块 authorizer 与服务边界，不是浏览器
登录认证 E2E；全局 AuthGuard 仍由应用负责。

## 边界与风险

- SQL 只计算 `uniqExact(date)`，不使用物理 `count()`，不使用 `FINAL`，不复制价格 winner 逻辑。
- 三类时钟在同一服务 `asOf` 下分别过滤；返回的三个 latest 值分别取最大值，可能来自不同记录。
- 查询固定用 101 行哨兵，API 响应最多 100 行并以 `truncated` 告知 UI。
- ClickHouse 未配置、查询失败、返回行校验失败均映射为 503；浏览器不会看到 raw Error。
- 当前拒绝证据仍保留在 worker raw JSON，尚未接入此 API；缺口、来源差异、全市场全集同样未接入。
