# 官方休市公告候选构建与运行授权状态

## 当前结论

P1-N07 的 SH/2026 官方休市公告采集代码、隔离 PostgreSQL 验证和独立审查已通过。
2026-09-06 用户授权后已完成一次受控 V3 migration、官方 capture 及离线 replay 验证：
ledger 已由 V1/V2 变为 V1/V2/V3，单次 capture、19 条稀疏休市记录和 receipt/state/raw
完整性校验通过，coverage 仍为 `UNKNOWN`。这证明了本次受控运行链路，不等同于持续任务、
API 接线、全年逐日完整覆盖或生产发布。

- 候选标签：`kunlun-data-worker:official-sse-candidate-80d7dc35eb9c`
- 镜像 ID：`sha256:42c4286efc5577e25fc5e2aee68d143b3a469295057d4f94601305ff24850fe8`
- 构建基线：`d1847c08750bf932cd6b63936d8617c29d91d623`，仅覆盖 13 个明确白名单文件。
- 上一条构建记录中的受限环境 hatchling 下载失败已通过受控候选构建及 wheel 构建复核解决，未更改依赖版本。

## 已核验的构建证据

Docker `data-worker` 目标构建和 wheel 构建均 exit 0；镜像 UID 为 10001，官方采集入口
`official-sse-calendar-sync --help`、模块导入和 SQL 资源检查通过。
V3 SQL 的工作区、构建上下文及镜像摘要一致：
`d998b3cb7598d3ba819fb1de95210e20b8b5171afdcc11c7eefcc2ebd331e1ab`。
wheel 包含该 SQL 和官方采集入口。构建上下文无真实环境文件，也未包含独立逐日领域快照模块。

独立 PostgreSQL 最终结果为 10 项集成测试及 56 项相关回归通过，测试容器已精确清理。
第二轮代码审查确认失败响应重放、回执与数据库不一致时写后拒绝两项阻断均已修复；
独立领域组合 70 项通过。上述结果不是全仓测试或应用数据库验收。

## 2026-09-06 受控运行成功（当前状态）

成功运行 artifact 为 `/private/tmp/kunlun-official-sse-runtime-b3ea47b0201a45c0a2536f6922e7e5d4.json`，
最终运行脚本 SHA-256 为
`3561a459e10d9295b3d2e278fb3450d64c1ef0399f98ee6be031c7922668f0e8`。临时 6 项测试、Compose
配置检查、代表性 replay 配置检查和 NOOP 预检均 exit 0。

本次受控运行结果如下：

- migration ledger 从 V1/V2 变为 V1/V2/V3；worker 与 migrate 的 `:local` 标签本轮已更新至
  本地候选摘要 `sha256:42c4286efc5577e25fc5e2aee68d143b3a469295057d4f94601305ff24850fe8`，
  旧标签保留。
- capture 为 `capture-0fd4cbe763154c3f94cafbda62ea3604`，版本为
  `f46a78c8-626e-4627-a0e3-c4ab258246ec`，原文 SHA-256 为
  `31a7485aac90814727a0bb9a30763cb81b753863e51a6c986ad2ffc9c76a697`。
- raw、capture-state 和 receipt 均通过完整性校验；保存 19 条 `PUBLIC_HOLIDAY` 记录，
  coverage 保持 `UNKNOWN`。replay 未新增 capture、version 或 audit；最终 scope 为 1 个
  version、19 行和 1 条 audit。
- 5 个一次性任务未残留，baseline 未变化；本次不启动 scheduler/API 或宣称生产发布。
  回滚只依据 artifact 中的非秘密元数据和保留的旧标签。

## 2026-09-06 受授权尝试：历史失败记录

首轮运行 artifact 为 `771c1a20b140447280515f4e19b36429`：compose argv 缺少 Docker，
在 preflight 前失败，migration 与 capture 均为 `None`。随后修复 argv 与 replay YAML，
临时 5 项测试及 config quiet 检查通过，运行脚本 SHA-256 为
`bc6cba85d9e7050badc9b2617e14a39a5bcfa3c355adab2b4a9e06aeee6c8828`。

第二轮 artifact 为 `/private/tmp/kunlun-official-sse-runtime-9761f646c3be408fb04bfb4594d578b1.json`：
主机 `docker compose run` 不支持 `--no-build`，三处 run 参数被 CLI 拒绝并返回 exit 1，
`apply_data_worker_migrations` 未运行、没有日历 DDL；候选资源 import 正常。数据库 ledger
仍为 V1/V2，五张 V3 日历表不存在，capture/replay/promotion 均未运行，baseline 与 local
tags 未变化。该次失败的直接原因是 Compose CLI 参数不兼容；它没有启动产品迁移或采集，
也没有产生重复 capture。随后修正参数并完成上面的受控成功运行；本历史段不代表当前
数据库状态。

## 首轮权限阻断（历史记录）

首轮权限审查曾拒绝实际启用步骤，要求用户明确授权共享数据库和原始证据卷的持久化写入；
该状态仅保留为历史，2026-09-06 的用户授权已明确给出。首轮没有绕过拒绝，也未尝试替代
写入路径。

首轮失败时现有数据库只有 worker V1/V2；五张日历 V3 表尚不存在。以下操作在首轮失败
阶段均未执行：

1. 对现有 `kunlun` 数据库执行追加式 V3 日历迁移。
2. 向现有 raw 卷写入一次官方公告 capture、capture-state 和 receipt，并保存对应休市版本。
3. 切换本地 worker/migrate 标签或启动采集任务。

`kunlun-data-worker:local` 构建前后仍为
`sha256:8696781db8331f367e94172ec70e0eb17c6181554232fedec9d8bb872fbca6d1`。
未重启现有容器，未修改运行数据卷，未启动行情轮询或墙钟门禁。

上述历史失败已由后续受控运行闭合；覆盖状态仍保持 `UNKNOWN`，不等同全年完整日历。
任何后续修改仍须单独授权，不因本次 one-off 成功而启动持续采集、API 接线或再次推广标签；
本轮 `:local` 标签更新仅限受控候选运行，不触达实盘路径。
