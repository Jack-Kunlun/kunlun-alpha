# 日历稀疏快照持久化证据

## 结论与范围

P1-N07 PostgreSQL 稀疏日历快照基础已通过定向验证与独立代码审计，工作区尚未提交、
未迁移实际数据库、未部署或接入运行采集器。这不是完整交易日历或缺失交易日验收。

新增 `jobs/calendars/postgres_repository.py`、`calendar_snapshot_migration.sql` 和
`tests/jobs/calendars/test_postgres_repository.py`；更新日历 repository/exports、
storage migrations/exports、worker wheel 配置、内存仓储测试、seat 测试账本预期及
日历运行手册。没有新增依赖或修改 seat 生产逻辑。原有 P6 文件不属于本切片。

## 设计决策

- `(source, exchange, year)` 隔离最新指针；UUID 版本独立保存，包括空快照，闭市记录
  按 ordinal 保序保重复。版本、记录、修正和审计追加不覆盖，只有 latest 可更新。
- 可选操作标识仅存摘要；同标识同 scope/内容重试返回旧版本，不倒退最新指针；冲突
  拒绝。无操作标识时每次新版本，不按内容合并采集。
- 每个公开方法借用 IDLE 连接、自行完成事务，调用者已有事务时拒绝而不接管。
  同 scope writer 使用 advisory lock；header/rows/latest/audit 原子提交，失败回滚。
- V3 接入现有 worker ledger 与迁移锁，SQL 为单一打包资源。精确核对列、默认值、
  collation、约束/FK、backing index、trigger 与函数定义；同名弱化也拒绝。
- 保存前精确检查 Holiday 身份、reason 和 note，畸形/缺字段模型受控拒绝，避免
  fingerprint 抛原始异常。错误不回显来源 note、操作标识或数据库参数。
- `persisted_at` 是 PostgreSQL 仓储事务时间，不是来源可用时间或精确提交时刻。
  correction overlay 不定义覆盖优先级；当前无业务消费者依赖其列表顺序应用修正。

## 失败与修复记录

初始 TDD 命令在 adapter 尚未实现时因导入失败，未进入全部业务断言：

```text
PYTHONPATH=services/data-worker/src:python/packages/ashare-contracts/src:python/packages/market-core/src .venv/bin/python -m pytest --no-cov services/data-worker/tests/jobs/calendars/test_postgres_repository.py -k 'postgres_calendar_repository'
1 collected / failed
```

实施中首次 18 项数据库测试为 16 通过、2 失败，分别修正空 correction overlay 行为
及 drift matcher 后 18 项通过。V3 catalog 查询曾有 oid 歧义，已修复。格式检查、
E501/SIM117 与类型诊断均在最终检查前修复。

主验收移除了超出借用连接边界的 `from_dsn` 和无依据别名，收紧 initialize 互斥和
受控异常处理，并补齐 caller 事务、四历史表 UPDATE/DELETE、跨 scope 重试冲突、
无标识新版本、修正年份和回滚检查。

独立审计另外发现同名弱化 catalog 可能绕过初版校验，以及畸形 reason/note 进入
fingerprint 时抛原始异常。对应精确 catalog 比对、固定类型前检及回归均已补齐。
最后追加 FK action、时间默认值和 initialize 异常三个测试，使组合从 66 增至 69。

## 实际 PostgreSQL 验证

执行者使用已缓存 PostgreSQL 17.10 的一次性 fixture、临时数据和随机回环端口，
凭据仅在私有进程环境中传递；测试配置 `KUNLUN_TEST_POSTGRES_DSN`，使用 UUID 独立
schema，不访问实际应用库。容器名称使用时间戳/进程 ID，与计划的 UUID 容器命名
不同；数据库 schema 仍随机隔离。这些是短期测试 fixture，绝非正式墙钟门禁。
每次退出精确清理本次容器；根代理最终只读检查无 `kunlun-calendar-` 容器残留。

受影响组合（最终三个补充测试加入之前）：

```text
PYTHONPATH=services/data-worker/src:python/packages/ashare-contracts/src:python/packages/market-core/src .venv/bin/python -m pytest --no-cov services/data-worker/tests/jobs/calendars/test_postgres_repository.py services/data-worker/tests/jobs/seats/test_postgres_repository.py services/data-worker/tests/test_calendar_collector.py services/data-worker/tests/test_calendar_repository.py services/data-worker/tests/test_precious_metals_migration_audit.py services/data-worker/tests/test_precious_metals_storage_migration.py
156 passed in 7.94s
```

最终组合（28 项日历 PostgreSQL/资源测试及 41 项内存测试）：

```text
PYTHONPATH=services/data-worker/src:python/packages/ashare-contracts/src:python/packages/market-core/src .venv/bin/python -m pytest --no-cov services/data-worker/tests/jobs/calendars/test_postgres_repository.py services/data-worker/tests/test_calendar_repository.py
69 passed in 4.27s
```

根代理已读取上述命令的原始工具输出，确认退出码 0、结果未截断，不仅依赖执行者总结。
此前组合依次为 66 通过、68 通过，增加测试而非放宽基线；未运行全仓测试。

## 根代理复核、静态检查与打包

```text
uv --no-cache run --no-sync --package data-worker pytest --no-cov -q services/data-worker/tests/test_calendar_repository.py services/data-worker/tests/test_calendar_collector.py python/packages/market-core/tests/test_trading_calendar.py
122 passed in 0.27s

.venv/bin/basedpyright services/data-worker/src/data_worker/jobs/calendars services/data-worker/src/data_worker/storage/migrations.py services/data-worker/src/data_worker/storage/__init__.py services/data-worker/tests/test_calendar_repository.py services/data-worker/tests/jobs/calendars/test_postgres_repository.py services/data-worker/tests/jobs/seats/test_postgres_repository.py
0 errors, 0 warnings, 0 notes

git diff --check
通过
```

执行者针对八个直接变更 Python 文件执行 Ruff format/check、BasedPyright，结果为
8 files already formatted、All checks passed、0 errors/warnings/notes。
独立审计的子目录 BasedPyright 调用最初未发现根配置而报告 192 条依赖解析诊断；
从仓库根目录加载正确配置后为 0，未将失败调用算作通过。

执行者用 `uv --no-cache build --package data-worker --out-dir "$wheel_dir"` 生成
wheel/sdist 并确认资源存在。根代理解压 wheel 内 SQL，与工作区 SQL 分别计算 SHA-256，
均为 `d998b3cb7598d3ba819fb1de95210e20b8b5171afdcc11c7eefcc2ebd331e1ab`。
这证明 SQL 资源打包一致，不等于已更新运行镜像。

## 独立审计与剩余边界

Terra Max 复核最终差异，确认两项阻断已修复，没有新代码阻断；独立运行 80 项内存
日历/采集器回归、Ruff 和根配置 BasedPyright。它未另行运行写隔离数据库的 fixture，
真实 PostgreSQL 证据来自以上执行输出，职责和证据来源分别记录。

生产启用、可信逐日日历、来源完整性、可见时间、生命周期和任务恢复仍是独立事项。
本轮不写实际数据库、不读取真实 raw/凭据、不新增 broker 路径，不改变 P6 条件接受
和正式连续 24 小时门禁的延期安排。使用标准 Python、资源 API 与 PostgreSQL；
本机 macOS 和 Linux 数据库容器验证不代表 Windows/Linux host 全栈验收。

## 后续镜像状态

稀疏快照仓储已随公开质量证据候选进入本地 worker 镜像；该次仅运行公开证据导出，
没有运行日历采集或实际数据库迁移。详见 `2026-09-05-public-quality-runtime-enablement.md`。
以上保留本切片实施时的测试与边界证据。
