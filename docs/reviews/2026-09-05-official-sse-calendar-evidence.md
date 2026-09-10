# SH 官方 2026 休市公告窄接入证据

最新状态（2026-09-06）：候选镜像、wheel 与入口验证已通过，且用户授权后的单次受控
SH/2026 运行已完成 V3 migration、官方 capture 和离线 replay 验证。ledger 为 V1/V2/V3，
capture、raw/state、receipt 与 19 条稀疏休市记录的完整性校验通过，coverage 仍为
`UNKNOWN`。这不是持续任务、全年逐日完整日历、全市场 coverage 或生产发布结论。参见
[候选构建与运行状态](2026-09-05-official-sse-calendar-runtime.md)。

## 边界

本切片只接受 `SH/2026` 与固定 SSE 公告地址：

`https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml`

它保留公告原始响应，严格核对标题、发布日期 `2025-12-22`、上证公告〔2025〕45 号、发布方和七段日期范围。解析结果只写七段范围内的 19 个工作日 `PUBLIC_HOLIDAY` 行；公告列出的周末调休日不写入 `Holiday`，也不反推交易日。该切片不创建 authoritative snapshot `COMPLETE`，结果与 receipt 的 coverage 仍为 `UNKNOWN`。

## 持久化与恢复

响应先经 `RawStorage` 保存为不可变 capture，成功读取并校验摘要后才解析和调用现有 `CalendarRepository.save_version`。操作标识由 capture id、固定 parser 版本和原文 SHA-256 组成；相同 capture 重试幂等，相同 bytes 的不同 capture 仍是不同事件。receipt 是单独的严格白名单 JSON raw object，连接 capture、摘要、parser、版本和原始观察/可用时间，不把公告正文或自由文本写入日历表。

每个有界 HTTP 响应还保存独立、不可变的 capture-state raw object，绑定 capture、raw object/checksum/size/date、HTTP status、redirect 标志和规范化 content type，并显式给出是否允许 replay。replay 必须找到并完整校验该 state，且只接受 `200`、HTML、非 redirect；缺少 state 不默认成功。因 `503`、redirect 或非 HTML 保存的完整原文仍可审计，但 state 将其标为不可 replay；网络失败和超限只保留固定错误码的 attempt 证据。

receipt 写入失败不回滚已保存的日历版本；后续 replay 只读取并校验原 capture 的 manifest/bytes/state 摘要，使用同一操作标识恢复 receipt，不重新联网。若 receipt 已存在，collect/replay 会先通过 repository 的只读 `find_operation_version` 校验同 scope、同内容和同 operation 是否关联该版本：缺失或冲突在任何 save/latest/audit 写入前固定失败；匹配时复用已有版本。超限响应不以截断 bytes 冒充完整原文。受控错误不携带外部异常文本或异常上下文。

## TDD 与定向验证

初始缺模块红测：

```text
.venv/bin/pytest services/data-worker/tests/jobs/calendars/test_official_sse.py -q --no-cov
1 error during collection: ModuleNotFoundError: No module named 'data_worker.jobs.calendars.official_sse'
```

capture-state 回归在实现前先复现 replay 绕过：

```text
.venv/bin/pytest services/data-worker/tests/jobs/calendars/test_official_sse.py -q --no-cov -k unusable_response_capture_cannot_be_replayed
3 failed, 23 deselected
Failed: DID NOT RAISE OfficialSseCalendarError (503/redirect); state list was empty (non-HTML)
```

receipt 预写校验回归在实现前先复现 collect/replay 写入或成功绕过：

```text
.venv/bin/pytest services/data-worker/tests/jobs/calendars/test_official_sse.py -q --no-cov -k existing_receipt
2 failed, 26 deselected
Failed: DID NOT RAISE OfficialSseCalendarError (collect and replay)
```

两项 P1 修复分别是：capture-state 将完整但不可用的 `503`、redirect、非 HTML
响应标为不可 replay；receipt 已存在时，collect/replay 先以 repository 只读查找核验
scope、内容指纹、operation 和 version，缺失/冲突在 save 前拒绝。两项回归均已绿。

当前本地受影响模块组合检查（PG 独立验收不包含在此命令中）：

```text
.venv/bin/ruff format services/data-worker/src/data_worker/jobs/calendars/official_sse.py services/data-worker/src/data_worker/jobs/calendars/official_sse_runtime.py services/data-worker/src/data_worker/jobs/calendars/repository.py services/data-worker/src/data_worker/jobs/calendars/postgres_repository.py services/data-worker/tests/jobs/calendars/test_official_sse.py services/data-worker/tests/test_calendar_repository.py
6 files left unchanged
.venv/bin/ruff check services/data-worker/src/data_worker/jobs/calendars/official_sse.py services/data-worker/src/data_worker/jobs/calendars/official_sse_runtime.py services/data-worker/src/data_worker/jobs/calendars/repository.py services/data-worker/src/data_worker/jobs/calendars/postgres_repository.py services/data-worker/tests/jobs/calendars/test_official_sse.py services/data-worker/tests/test_calendar_repository.py
All checks passed!
.venv/bin/basedpyright services/data-worker/src/data_worker/jobs/calendars/official_sse.py services/data-worker/src/data_worker/jobs/calendars/official_sse_runtime.py services/data-worker/src/data_worker/jobs/calendars/repository.py services/data-worker/src/data_worker/jobs/calendars/postgres_repository.py services/data-worker/tests/jobs/calendars/test_official_sse.py services/data-worker/tests/test_calendar_repository.py
0 errors, 0 warnings, 0 notes
.venv/bin/pytest services/data-worker/tests/jobs/calendars/test_official_sse.py services/data-worker/tests/test_calendar_repository.py services/data-worker/tests/test_calendar_collector.py services/data-worker/tests/test_raw_storage.py services/data-worker/tests/jobs/calendars/test_postgres_repository.py -q --no-cov
183 passed, 26 skipped in 0.73s
```

入口配置的无副作用解析检查通过：`official-sse-calendar-sync` 指向 `data_worker.jobs.calendars.official_sse_runtime:main`。worker wheel 检查命令 `UV_CACHE_DIR=/private/tmp/kunlun-official-sse-uv-cache uv build --package data-worker --out-dir /private/tmp/kunlun-official-sse-wheel-check` 未完成，因受限环境无法解析 PyPI 的 `hatchling==1.27.0`；未改依赖。

## 分层证据与限制

本次自动化单元/回归验证使用脱敏的固定 HTML fixture、注入 transport、in-memory repository 和本地临时 RawStorage；没有在这些测试中访问真实 SSE、真实 PostgreSQL、凭据或迁移。新增窄测试覆盖成功七段解析、范围/公告锚点拒绝、raw-first、19 条工作日、UNKNOWN、同 bytes 不合并、非 200/非 HTML/redirect/oversize、网络和时区异常脱敏、capture-state replay fail-closed、receipt 预写冲突、receipt 失败后 replay，以及一次性 CLI 的 raw-root/DSN 边界。

协调方两次只读真实来源 probe 均记录 HTTP `200`、`text/html`、`29251` bytes，且 SHA-256 均为 `31a7485aac90814727a0bb9a30763cb81b753863e51a6c986ad2ffc9c76a697`；固定页面正文采用“一、休市安排”下的“（一）”至“（七）”两层结构。第一次真实 `200` body 按错误的七个顶层节假日结构解析失败；收敛为唯一“一、休市安排”区段及七个子段后，第二次同 SHA 真实 body 与 fixture 均解析为 19 条工作日。该 probe 只用于来源结构诊断，不代表生产部署或持续联网。

最新独立 PostgreSQL 验收由集成代理在隔离 fixture 中运行，结果为 `10 passed`，另有相关组合 `56 passed`；artifact 为 `/private/tmp/kunlun-calendar-pg-it-1282483902a04797a2cf6dbb7c417810.json`。更早的 PG 结果不作为本轮最终证据；上述结果也不计入本地 `183 passed, 26 skipped`，本文件不宣称全仓通过。

代码独立审计已通过；候选构建摘要为 `sha256:42c4286efc5577e25fc5e2aee68d143b3a469295057d4f94601305ff24850fe8`，
15 个 P6 保护文件的 root hash 前后不变。

### 2026-09-06 受控运行成功

成功运行 artifact 为
`/private/tmp/kunlun-official-sse-runtime-b3ea47b0201a45c0a2536f6922e7e5d4.json`，最终运行
脚本 SHA-256 为 `3561a459e10d9295b3d2e278fb3450d64c1ef0399f98ee6be031c7922668f0e8`；临时
6 项测试、Compose 配置、代表性 replay 配置及 NOOP 预检均 exit 0。ledger 从 V1/V2 变为
V1/V2/V3；capture 为 `capture-0fd4cbe763154c3f94cafbda62ea3604`，版本为
`f46a78c8-626e-4627-a0e3-c4ab258246ec`，原文 SHA-256 为
`31a7485aac90814727a0bb9a30763cb81b753863e51a6c986ad2ffc9c76a697`。raw/state/receipt
完整性校验通过，保存 19 条 `PUBLIC_HOLIDAY` 行且 coverage 为 `UNKNOWN`；replay 未新增
capture、version 或 audit，最终 scope 为 1 个 version、19 行和 1 条 audit。5 个一次性
任务未残留，baseline 未变化；worker/migrate 的 `:local` 标签本轮已更新至
`sha256:42c4286efc5577e25fc5e2aee68d143b3a469295057d4f94601305ff24850fe8`，旧标签保留，
回滚信息仅使用 artifact 中的非秘密元数据。

### 两次早先失败（历史记录）

2026-09-06 用户已明确授权 V3 migration 与一次
官方采集，但首轮 artifact `771c1a20b140447280515f4e19b36429` 在 compose argv 缺 Docker
的 preflight 失败；修复 argv/replay YAML 后，临时 5 项测试与 config quiet 通过，脚本
SHA-256 为 `bc6cba85d9e7050badc9b2617e14a39a5bcfa3c355adab2b4a9e06aeee6c8828`。第二轮
artifact `/private/tmp/kunlun-official-sse-runtime-9761f646c3be408fb04bfb4594d578b1.json`
记录主机 `docker compose run` 不支持 `--no-build`，三处 run 参数被 CLI 拒绝并返回 exit 1；
`apply_data_worker_migrations` 未运行、没有日历 DDL，候选资源 import 正常。ledger 仍为 V1/V2，
五张 V3 日历表不存在，capture/replay/promotion 均未运行，baseline/local tags 未变化。
当时的只读诊断未把未确认的 schema 原因写成结论；随后修正 Compose 参数并完成上面的
受控运行。本地自动化验证未执行
Windows/Linux 跨平台运行，不能据此宣称跨平台已验收。该入口只生成稀疏日历 provenance，
系统仍为 `PAPER_ONLY`，不创建 authoritative snapshot `COMPLETE`、不提供正向交易日推断，
也不触达实盘下单路径。
