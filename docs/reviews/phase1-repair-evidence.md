# Phase 1 / Phase 2 修复验收证据

日期：2026-08-24

范围：`P2-R02`、`P2-R03`、`P2-R04`、`P1/P2-R05`

## 结论

Phase 1 和 Phase 2 已知剩余修复项已闭合。板块历史、PIT 快照、生命周期、轮动事件、持久化查询 API、Web 页面、数据库迁移、重启恢复和完整日重放均有直接验证证据。Phase 0 至 Phase 6 的实盘隔离边界未改变。

## 实施前失败证据

修复前的定向验证得到以下结果：

```text
P2-R02 history_records 1
P2-R02 current_members []
P2-R02 future_bar_included 600000.SH
P2-R03 empty_strengths ValueError max() iterable argument is empty
P2-R03 reverse_equal False 1 2
```

这些结果分别证明了历史覆盖、查询时成员解析、未来数据泄漏、空输入处理和逆序重放不稳定问题。

## 关键修复

### P2-R02

- 板块和成员关系改为带有效区间、可用时间、来源版本和证据标识的查询时解析。
- 同优先级且语义冲突的记录 fail-closed，不再依赖写入顺序静默覆盖。
- 快照只使用决策时点前已可用的规范修订记录。
- 快照补齐速度、`Decimal` 成交额、广度、龙头、强度、样本量、成员数、新鲜度、置信度和排除原因。
- 生命周期配置、状态迁移、证据和稳定标识显式版本化。

### P2-R03

- 输入统一规范为 UTC 并按事件时间排序。
- 空板块强度映射跳过；同时间冲突记录 fail-closed。
- 并列强度作为 barrier，短暂抖动不伪造直接 crossover。
- 事件标识使用稳定 SHA-256，携带版本、证据窗口、样本量和来源版本。
- 批处理、流式和逆序重放使用相同规范化语义。

### P2-R04

- 新增情绪快照和轮动事件 JSON Schema 及生成的 TypeScript/Python 类型。
- API 从持久化 repository 查询，不再注入空数组占位数据。
- 查询参数验证交易日、版本和板块标识，并区分 forbidden 状态。
- ClickHouse 新增版本化情绪快照和轮动事件表，金额与评分字段不使用二进制浮点。
- Web 新增 `/market-regime` 页面，覆盖 loading、empty、error、forbidden 和成功状态。
- 页面展示时间、新鲜度、样本量、置信度、算法版本和证据窗口。

### P1/P2-R05

- 修复全仓 Python 严格类型债务：`630` 个错误降至 `0`。
- 修复全仓 Prettier 和 ESLint 基线，使根级门禁通过。
- PostgreSQL 与 ClickHouse 均完成真实 Compose 集成验收。

## 验证结果

### 格式、静态检查和生成契约

```text
pnpm format:check
PASS - All matched files use Prettier code style

pnpm lint
PASS - 9 successful, 9 total

pnpm typecheck
PASS - 9 successful, 9 total

pnpm python:lint
PASS - All checks passed

pnpm python:typecheck
PASS - 0 errors, 0 warnings, 0 notes

pnpm --filter @kunlun/contracts gen:check
PASS - TypeScript and Python types are in sync with JSON Schema
```

### 自动化测试和构建

```text
rotation-core targeted tests
23 passed

Phase 1/2 Python suite without external DSN
638 passed, 67 skipped

PostgreSQL database subset with local isolated DSN
78 passed

Contracts
134 passed

Web
30 passed

API standard run
42 passed, 2 skipped

API with KUNLUN_TEST_POSTGRES_DSN and Turbo --env-mode=loose
44 passed, 0 skipped

API and Web production builds
PASS - 5 successful, 5 total
```

标准测试中的数据库跳过项已由带本地隔离 DSN 的专门运行实际覆盖，不存在未执行的数据库验收路径。

### ClickHouse

```text
node scripts/ci/clickhouse-migration-smoke.mjs --check-config
PASS - ClickHouse migration wiring passed

node scripts/ci/clickhouse-migration-smoke.mjs --self-test
PASS - ClickHouse migration smoke self-test passed

node scripts/ci/clickhouse-migration-smoke.mjs --smoke
PASS - ClickHouse smoke passed for kunlun_p1_r06_6f2db66e0b1d464890b59acec3a28895
```

真实 smoke 覆盖 Compose 启动、全部迁移、重复应用、重启和 schema 校验。

### PostgreSQL

```text
Container health: healthy
Restart persistence marker: true
Isolated schema cleanup: true
Post-restart database tests: 78 passed
```

重启验证创建随机隔离 schema，写入持久化标记，重启容器后读取成功，并在结束时删除 schema。

### 完整交易日重放

```text
trading_minutes=242
events=1
batch_stream_bytes_equal=true
reverse_replay_equal=true
batch_stream_sha256=0c63c8e107201c5578c66ebc747f3b245ce5f5a1e22230a4155c246e5fc0dd82
```

夹具覆盖 `Asia/Shanghai` 交易日的上午和下午分钟窗口。

### 静态安全与跨平台扫描

```text
ClickHouse Float32/Float64 columns: none
Callable live-trading markers: none
Obsolete prefix-form security codes in production: none
Hard-coded platform paths in changed runtime scope: none
CRLF in source/config/docs: none
```

旧前缀形式只保留在负向测试和说明注释中，用于证明输入会被拒绝。

## 安全、数据完整性和实盘影响

- 未新增 broker、QMT、真实订单或真实账户路径。
- 所有查询和派生结果遵守 `available_time <= decision_time`。
- 价格、金额和数据库精度敏感字段继续使用 `Decimal` 或数据库 `Decimal` 类型。
- 冲突修订、同权威来源冲突和非法生命周期跳转均 fail-closed。
- 测试仅使用本地 Compose、示例凭据和随机隔离 schema；未访问生产数据。

## 跨平台说明

- 新增运行时代码不包含 `/tmp`、盘符或路径分隔符硬编码。
- 文本文件保持 UTF-8 和 LF。
- 数据库 smoke 通过仓库 Compose 和跨平台入口脚本执行。

## 剩余风险

None。

## 提交状态

本轮修改尚未提交。
