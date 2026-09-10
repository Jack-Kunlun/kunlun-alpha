# 日历快照身份与修正隔离证据

## 范围与交付状态

本轮为 P1-N07 的内存仓储隔离切片。前一项请求/响应范围校验已按用户授权提交为
`d1847c08750bf932cd6b63936d8617c29d91d623`，标题为
`fix(calendar): 校验采集请求与响应范围`。本轮新隔离代码尚未提交或部署。

修改 calendar `repository.py`、`collector.py`、`__init__.py` 和
`test_calendar_collector.py`，新增 `test_calendar_repository.py`；同步
`docs/runbooks/calendar-collection.md`，新增限定计划
`docs/superpowers/plans/2026-09-05-calendar-snapshot-identity-plan.md` 和本记录。
没有最终删除的文件，没有依赖、SQL、Schema 或容器配置变化。

## 设计与兼容性

- 最新指针使用 `(source, exchange, year)`，每个历史版本保留自身范围，包括空快照。
  `latest_version_id()` 区分空快照和从未采集，历史读取继续深复制。
- 保留 opaque `source:year:vN` 版本 ID，不从字符串解析范围。旧三位置参数保存仅对
  非空同质列表推导交易所；collector 始终显式传入交易所。
- source-only 读取在没有范围或只有一个范围时兼容，多个范围拒绝；显式读取必须同时
  提供交易所与年份。保存的身份校验、深复制先于版本分配、最新指针与审计更新。
- 手工修正绑定准确版本，省略版本仅在仓储恰有一个历史版本时兼容。修正日期必须是
  对应年份内的标准 ISO 日期；overlay 不再把无版本修正广播至其他版本。
- 新错误为固定 `CalendarScopeError` / `CalendarScopeAmbiguityError`；未知版本保留
  `KeyError` 类型但不回显任意输入。闭市记录覆盖状态仍为 `UNKNOWN`。

这不新增公共 HTTP/JSON 契约，不实现 PostgreSQL、PIT、完整交易日历或任务恢复。

## 验证记录

### 失败先行

主隔离测试先于实现添加。首轮命令如下，退出码为 2，因尚未提供
`CalendarScopeAmbiguityError` 而在收集阶段出现 `ImportError`；未进入业务断言执行，
不能把这次结果表述为已经观察到所有跨范围错误行为。

```text
PYTHONPATH=services/data-worker/src:python/packages/ashare-contracts/src:python/packages/market-core/src .venv/bin/python -m pytest --no-cov services/data-worker/tests/test_calendar_repository.py services/data-worker/tests/test_calendar_collector.py -k 'compound_scope or recollecting_one_scope or source_and_scope or legacy_three_argument or invalid_explicit_scope or mixed_exchange_or_year or invalid_row_type or implicit_correction_and_overlay or explicit_correction or correction_date or unknown_version_ids or explicit_scope_empty or collect_assigns_empty'
```

独立审核新增的身份字段与缺失字段回归均直接复现了错误行为：

```text
PYTHONPATH=services/data-worker/src:python/packages/ashare-contracts/src:python/packages/market-core/src .venv/bin/python -m pytest --no-cov services/data-worker/tests/test_calendar_repository.py -k 'fake_identity_types'
修复前：4 failed, 28 deselected（畸形身份字段被接受）
修复后：4 passed, 28 deselected

PYTHONPATH=services/data-worker/src:python/packages/ashare-contracts/src:python/packages/market-core/src .venv/bin/python -m pytest --no-cov services/data-worker/tests/test_calendar_repository.py -k 'missing_identity_fields'
修复前：2 failed, 32 deselected（未受控 AttributeError）
修复后：2 passed, 32 deselected
```

最终 collector/repository 组合由执行者验证为 `73 passed`；包含直接关联领域日历的
根代理组合结果见下文。

### 根代理复核

根代理在首次独立复核时执行：

```text
uv --no-cache run --no-sync --package data-worker pytest --no-cov -q services/data-worker/tests/test_calendar_collector.py services/data-worker/tests/test_calendar_repository.py python/packages/market-core/tests/test_trading_calendar.py
109 passed in 0.29s
```

此记录对应独立审核的最终边界修复之前。
uv 的 `services/.gitkeep` 非目录 workspace 提示未影响测试执行。

最终字段类型及缺失字段修复完成后，根代理重新运行上述组合命令：

```text
115 passed in 0.39s

.venv/bin/ruff format --check services/data-worker/src/data_worker/jobs/calendars/repository.py services/data-worker/src/data_worker/jobs/calendars/collector.py services/data-worker/src/data_worker/jobs/calendars/__init__.py services/data-worker/tests/test_calendar_repository.py services/data-worker/tests/test_calendar_collector.py
5 files already formatted

.venv/bin/ruff check services/data-worker/src/data_worker/jobs/calendars/repository.py services/data-worker/src/data_worker/jobs/calendars/collector.py services/data-worker/src/data_worker/jobs/calendars/__init__.py services/data-worker/tests/test_calendar_repository.py services/data-worker/tests/test_calendar_collector.py
All checks passed!

.venv/bin/basedpyright services/data-worker/src/data_worker/jobs/calendars/repository.py services/data-worker/src/data_worker/jobs/calendars/collector.py services/data-worker/src/data_worker/jobs/calendars/__init__.py services/data-worker/tests/test_calendar_repository.py services/data-worker/tests/test_calendar_collector.py
0 errors, 0 warnings, 0 notes
```

执行者在补齐最终身份字段边界之前，仅运行一次 data-worker 完整离线测试目录：

```text
env -u KUNLUN_TEST_POSTGRES_DSN PYTHONPATH=services/data-worker/src:python/packages/ashare-contracts/src:python/packages/market-core/src:python/packages/emotion-core/src:python/packages/quant-core/src:python/packages/seat-core/src .venv/bin/python -m pytest --no-cov services/data-worker/tests
496 passed, 75 skipped
```

75 个跳过项需要测试专用 PostgreSQL DSN，本轮明确清除该变量，不访问真实数据库。
这不是全仓或 PostgreSQL 集成通过；`--no-cov` 不提供覆盖率达标结论。之后仅收紧
identity 字段守卫，最终重跑直接受影响的日历测试与静态检查，未重复运行整个包。

首次 Ruff lint 曾提示 `repository.py` 的 I001 导入排序问题，仅调整该文件导入后
重新检查通过，没有为消除检查失败而变更其他业务逻辑。

文档使用下列限定格式检查，另执行 `git diff --check` 检查最终差异：

```text
pnpm exec prettier --check docs/runbooks/calendar-collection.md docs/superpowers/plans/2026-09-05-calendar-snapshot-identity-plan.md docs/reviews/2026-09-05-calendar-snapshot-identity-evidence.md
```

## 审核与运行边界

Terra Max 独立审核发现：仅取 `.value` / `.year` 会允许绕过 Pydantic 校验构造的
date-like 或 enum-like 对象冒充合法身份字段。修复限定为生成交易所枚举和标准日期的
字段类型检查，不扩大到重验所有 Holiday 字段。根代理随后指出缺失字段需要保留
受控异常行为：字段检查已放入原有异常保护内，并补充缺字段模型回归。
Terra Max 最终独立复核未发现本切片代码级阻断；最终测试与静态检查见上文。

原有 15 个 P6 修改文件的 SHA-256 与本轮开始基线一致。没有变更数据库、凭据、
权限、网络、原始行情或门禁进程，不引入真实 broker 能力。

实现使用标准 Python 与既有契约，无新增平台路径或系统调用。本轮本机 macOS 验证，
不声称实际在 Windows/Linux 执行通过。没有构建配置变化，不执行 Docker 构建、部署
或全仓测试。内存隔离通过不能替代持久化隔离、时点查询、可信完整日历与正式门禁。
