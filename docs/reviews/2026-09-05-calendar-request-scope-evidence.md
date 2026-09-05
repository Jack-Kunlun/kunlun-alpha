# 交易日历采集范围校验证据

## 结论与变更范围

P1-N07 的请求/响应范围一致性缺口已修复：非法请求在 provider 调用前失败，任何一页
的跨交易所或跨年份记录都会拒绝整次结果，不保存部分快照。本轮没有提交或部署，
不能将工作区修复当作现有容器行为。

修改 `services/data-worker/src/data_worker/jobs/calendars/collector.py` 与
`services/data-worker/tests/test_calendar_collector.py`，同步
`docs/runbooks/calendar-collection.md`；新增限定计划
`docs/superpowers/plans/2026-09-05-calendar-request-scope-plan.md` 和本记录，没有删除文件。

请求复用生成的 `calendar_holiday.Exchange`，不复制值域或修改 JSON Schema。
交易所必须为合法字符串，年份为严格整数 `1..9999`，布尔值不合法。不接受静默的
大小写、空白、别名或类型转换。错误使用固定 `ProviderDataError`，枚举验证错误以
`from None` 隐藏可能带原请求值的异常链。

逐页检查位于 `fetch_holidays()` 之后、`extend()` 之前。合法全部页取完后才保存一次。
不改变仓储、来源标识、手工修正、分页保护、重试或 `coverage_status=UNKNOWN`。

## 失败先行与根代理复核

新增测试在生产代码修改前收集 36 项、选中 20 项，结果为 `15 failed, 5 passed`。
失败对应尚未实现的非法请求与响应范围拒绝；不是修改历史断言使实现看似通过。
后续补充了第二页跨所/跨年对称用例、合法年份端点及旧版本不变断言。

执行者的红测命令：

```text
PYTHONPATH=services/data-worker/src:python/packages/ashare-contracts/src:python/packages/market-core/src .venv/bin/python -m pytest --no-cov services/data-worker/tests/test_calendar_collector.py -k 'supported_exchange_requests or valid_multi_page_response or first_page_identity_mismatch or subsequent_mixed_page_identity or invalid_exchange or invalid_year or legal_empty_response'
```

同一选择器在补充边界并实现后为 `22 passed, 16 deselected`；collector 全文件为
`38 passed`，直接关联的 `market-core/tests/test_trading_calendar.py` 为 `42 passed`。

根代理实际执行：

```text
uv --no-cache run --no-sync --package data-worker pytest --no-cov -q services/data-worker/tests/test_calendar_collector.py python/packages/market-core/tests/test_trading_calendar.py
80 passed in 0.21s

.venv/bin/ruff format --check services/data-worker/src/data_worker/jobs/calendars/collector.py services/data-worker/tests/test_calendar_collector.py
2 files already formatted

.venv/bin/ruff check services/data-worker/src/data_worker/jobs/calendars/collector.py services/data-worker/tests/test_calendar_collector.py
All checks passed!

.venv/bin/basedpyright services/data-worker/src/data_worker/jobs/calendars/collector.py services/data-worker/tests/test_calendar_collector.py
0 errors, 0 warnings, 0 notes

git diff --check
PASS
```

测试补写期间的首次 Ruff 格式检查提示测试文件需格式化；执行者仅格式化该文件后，
根代理重新执行检查通过。uv 提示忽略非目录 workspace 条目 `services/.gitkeep`，未影响结果。

## 包级离线验证

执行者先验证 453 个排除显式外部集成项的测试，通过后又执行下列完整 data-worker
测试目录命令，清除测试专用 DSN，让数据库 fixture 按既有规则自行跳过：

```text
env -u KUNLUN_TEST_POSTGRES_DSN PYTHONPATH=services/data-worker/src:python/packages/ashare-contracts/src:python/packages/market-core/src:python/packages/emotion-core/src:python/packages/quant-core/src:python/packages/seat-core/src .venv/bin/python -m pytest --no-cov services/data-worker/tests
468 passed, 75 skipped
```

75 个跳过项需要测试专用 PostgreSQL DSN，本轮未提供或访问该数据库。该结果是包级
离线测试，不是全仓或 PostgreSQL 集成验收；`--no-cov` 不产生覆盖率达标结论。

## 独立审核与剩余边界

Terra Max 独立审查未发现本切片阻断项。直接检查前置验证、每页检查位置及成功后才
保存的控制流；测试覆盖不再请求下一页、旧版本/当前来源记录/audit/correction 保持不变。
审核提出的运行手册瞬态 Git 状态措辞已修正为部署边界说明并复核。

原有 15 个 P6 修改文件与本轮开始时的 SHA-256 基线完全一致。未修改凭据、数据库、
网络权限、部署、原始行情、历史门禁证据或真实 broker 能力。

代码使用标准 Python、现有契约枚举与日期字段，无新增平台路径、依赖或系统调用；
本机 macOS 验证，不声称实际在 Windows/Linux 运行通过。本次无构建配置变化，没有
执行 Docker 构建、部署或全仓测试。

仍未解决 source-only 最新版本指针：同一来源的不同合法交易所/年份请求依旧共享最新
指针。持久化身份隔离、PIT、可信完整日历及缺失交易日判定仍需后续独立实现，不能因
本次范围校验通过就宣称 P1-N07 或完整数据质量链路已经完成。
