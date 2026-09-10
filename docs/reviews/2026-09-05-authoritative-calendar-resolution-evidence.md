# P1-N07 权威逐日日历判定切片证据

日期：2026-09-05

## 范围

本证据只覆盖 `market-core` 中的纯 typed domain module：不可变的全年逐日快照、
官方 authority 与交易所固定映射、available-at/PIT 版本选择、三态单日判定和脱敏的
次源冲突证据。没有接入采集器、数据库、旧 `TradingCalendar` 消费者、HTTP/API 或真实
官方 provider；authority enum 与 metadata 只校验内部契约，不证明外部真实性。

实现会严格拒绝 `datetime` 作为日历日期、布尔年份、naive/reversed timestamps、错误
scope、重复或缺失日期、非法单行类型和非布尔日状态。Pydantic `TradingDay` 会被复制为
不带 `note` 的 frozen 内部 row；完整年份使用 365/366 个自然日，支持 year 9999，且不
构造 year 10000。不可见父版本会阻断可见子版本选择；未关联同级 head 不按输入顺序选择。
在解析时，dangling、跨 scope lineage 和环形等语义问题只返回固定原因的
`INDETERMINATE`；未来不可见快照及其 lineage 不影响更早的 `as_of`。

## TDD 证据

实现前运行：

```text
PYTHONPATH=python/packages/ashare-contracts/src:python/packages/market-core/src .venv/bin/python -m pytest python/packages/market-core/tests/test_authoritative_snapshot.py -q --no-cov
```

结果：收集阶段失败，`ModuleNotFoundError: No module named 'market_core.calendar.authoritative_snapshot'`。

初轮实现通过 23 项；完成下述异常链修复后，同一条定向测试命令最终为 `28 passed`。

Round1 安全回归在修复前使用同一命令实际结果为：`5 failed, 23 passed`。失败覆盖
自定义 `tzinfo`、缺失 Pydantic 字段、`days` 迭代器、snapshot 迭代器和 secondary
迭代器；失败原因分别确认了原始异常可经 `__context__` 或 traceback 保留。修复后
traceback 与异常 context 均不再包含 sentinel，结果为 `28 passed`。

## 验证命令与结果

```text
.venv/bin/ruff format --check python/packages/market-core/src/market_core/calendar/authoritative_snapshot.py python/packages/market-core/src/market_core/calendar/__init__.py python/packages/market-core/tests/test_authoritative_snapshot.py
```

结果：`3 files already formatted`。

```text
.venv/bin/ruff check python/packages/market-core/src/market_core/calendar/authoritative_snapshot.py python/packages/market-core/src/market_core/calendar/__init__.py python/packages/market-core/tests/test_authoritative_snapshot.py
```

结果：`All checks passed!`。

```text
.venv/bin/basedpyright python/packages/market-core/src/market_core/calendar/authoritative_snapshot.py python/packages/market-core/src/market_core/calendar/__init__.py python/packages/market-core/tests/test_authoritative_snapshot.py
```

结果：`0 errors, 0 warnings, 0 notes`。

```text
PYTHONPATH=python/packages/ashare-contracts/src:python/packages/market-core/src .venv/bin/python -m pytest python/packages/market-core/tests/test_trading_calendar.py -q --no-cov
```

结果：`42 passed`。

另执行 `git diff --check`（限定本切片文件），无输出且退出成功。

本轮仅修改异常转换路径和上述安全回归；没有改变 snapshot、PIT、lineage、secondary
判定语义。

## 限制与后续边界

- 未启动真实 PostgreSQL、未执行迁移、未访问真实行情源、账户、凭据或生产数据。
- 未运行全仓测试；本轮只执行新切片、旧日历回归、ruff 和 basedpyright。
- 没有 runtime consumer，因此本切片不会改变现有覆盖状态或正式墙钟门禁；需独立
  provider 身份/证据校验和后续接线切片才能使用。
- Terra Max 最终独立审计无剩余代码阻断；详见下节，不替代真实来源接入验收。

## 最终独立与根代理验收

Terra Max 独立运行新切片与旧日历组合，`70 passed in 0.40s`；Ruff format/lint 和
BasedPyright 通过。另以 1,500 版本替代链确认迭代遍历不发生递归失败，重复
snapshot_id 返回 `OFFICIAL_LINEAGE_UNAVAILABLE`。最初异常上下文泄露的阻断已关闭。
最终审计提到的 23 项计数是初轮状态，本记录现已明确区分初轮与最终 28 项。

根代理实际运行新旧日历初轮组合 `65 passed in 0.30s`，初轮格式/lint/type 全部通过；
异常修复后再次运行新切片 `28 passed in 0.31s`，`git diff --check` 通过。没有重复
全仓测试或把元数据校验当作官方端点真实性证明。

本切片采用标准 Python 类型、UTC 与无宿主路径的纯计算；当前本机验证不能替代
Windows/Linux host 验证。没有新增依赖、改变数据库或实盘能力，没有删除文件或创建提交。
代码尚未进入运行镜像，因为没有生产消费者；公开证据运行更新单独记录，不与本切片混称。
