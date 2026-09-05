# 节假日采集边界修复证据

## 结论与范围

P1-N07 有界修复已通过定向验证和 Terra XHigh 只读审查：纠正稀疏闭市记录的缺失日期
误报，并对分页设置循环与页数保护。本记录不是整个 P1-N07 完成证明，也不是完整
交易日历或缺失交易日检测验收。风险为中等，不涉及持久化、权限、迁移或真实订单。

此前逐日行情入库明细已按用户授权提交为 `6b62e938c5ce73f97866a3ab1d3304d7ec0a1538`，
标题为 `feat(data-quality): 增加逐日行情入库明细`。本轮日历修复未提交、未推送或部署。

## 文件与决策

- 修改 `services/data-worker/src/data_worker/jobs/calendars/collector.py`：不再由空集合或
  大间隔推断 `MISSING_DATE`；保留该内部类型成员，临时闭市与显式来源冲突逻辑不变。
- 修改 `services/data-worker/tests/test_calendar_collector.py`：覆盖稀疏、空集、正常分页、
  环路、页数边界、错误不保存及原有版本/修正审计回归，共 16 个测试用例。
- 新增 `docs/runbooks/calendar-collection.md` 和
  `docs/superpowers/plans/2026-09-05-calendar-collection-boundaries-plan.md`。
- 新增本证据记录；没有删除文件。

结果新增末尾默认字段 `coverage_status: Literal["UNKNOWN"] = "UNKNOWN"`，不破坏既有
位置参数。默认 keyword-only `max_pages: int = 100` 拒绝布尔值、非整数及非正数。
重复游标与超限抛出已有 `ProviderDataError`，保护错误不回显游标。取完所有页后才保存
一次；失败保留已有版本与审计。不新增自动重试、断点恢复或稳定上游快照承诺。

## TDD 与最终验证

Luna 在修改生产代码前执行以下定向红测，收集 16 项、选中 8 项，结果 `6 failed, 2 passed`：

```text
PYTHONPATH=services/data-worker/src:python/packages/ashare-contracts/src:python/packages/market-core/src .venv/bin/python -m pytest --no-cov services/data-worker/tests/test_calendar_collector.py -k 'sparse or empty_holiday or collect_saves or multi_page or exact_page or invalid_max or page_limit or provider_error'
```

稀疏/空结果误报、缺失
页数边界及缺失覆盖状态是预期失败原因。初次完整红测遇到旧实现无界循环，未在工具
等待窗口内结束。根代理随后确认遗留进程为本次日历 pytest，精确终止并核对其退出；
没有终止服务、数据库或门禁进程。完整旧实现红测不能表述为一次正常完成的测试运行。

最终根代理执行：

```text
uv --no-cache run --no-sync --package data-worker pytest --no-cov -q services/data-worker/tests/test_calendar_collector.py
16 passed in 0.30s

.venv/bin/ruff format --check services/data-worker/src/data_worker/jobs/calendars/collector.py services/data-worker/tests/test_calendar_collector.py
2 files already formatted

.venv/bin/ruff check services/data-worker/src/data_worker/jobs/calendars/collector.py services/data-worker/tests/test_calendar_collector.py
All checks passed!

.venv/bin/basedpyright services/data-worker/src/data_worker/jobs/calendars/collector.py services/data-worker/tests/test_calendar_collector.py
0 errors, 0 warnings, 0 notes

git diff --check
PASS
```

Luna 首次完整红测和最终绿测使用同一命令，最终结果为 `16 passed in 0.66s`：

```text
PYTHONPATH=services/data-worker/src:python/packages/ashare-contracts/src:python/packages/market-core/src .venv/bin/python -m pytest --no-cov services/data-worker/tests/test_calendar_collector.py
```

uv 的 `services/.gitkeep` 非目录 workspace 提示不影响结果。未执行全仓测试、包构建或
真实网络集成测试；变更不涉及打包、依赖、入口、数据库或部署配置，不将窄测称为全套通过。

## 审查、隔离与剩余缺口

Terra XHigh 只读核对参数类型、上限、自循环及一般环路、错误消息与保存顺序，没有本切片
阻断项。超限及 provider 错误有直接旧快照/audit 保持不变断言；环路测试验证受控失败、
调用次数及不泄漏游标，不保存性质同时由成功返回后才保存的控制流保证。

变更仅使用标准 Python 逻辑，无平台专属路径或命令进入生产代码。本机 macOS 验证通过；
未在 Windows/Linux 上实际运行，不能声称三平台执行通过。没有引入凭据、日志出口、网络
调用或真实 broker 能力。原有 15 个 P6 修改文件与本轮提交后的哈希基线一致。

仍需后续补齐：provider 返回交易所/年份校验、按交易所/年份隔离的持久化版本、来源证据、
时点可见性、修正层、多源对账及正式缺失交易日判定。当前内存 repository 与 `UNKNOWN`
不能用作完整日历合格证据。P6 条件接受和延期墙钟门禁保持原状。

另行完成的行情拒绝证据独立代码审核见
`2026-09-05-market-quality-evidence-security-audit.md`；实际只读卷挂载与认证运行验收仍待执行。
