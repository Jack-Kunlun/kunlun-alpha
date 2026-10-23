# 昆仑智策 (Kunlun Alpha)

**观势 · 知势 · 策势**

## About

昆仑智策的长期目标是面向 A 股与场内贵金属 ETF/基金的投研、量化研究和模拟交易平台。首发 `1.0.0` 收敛为单管理员、单实例的历史日线研究终端，供本人或受控内部环境使用。已登记并推送至 `v1.0.6`：服务端个人自选、真实日线、每日更新、站内提醒、日线样本对比，以及管理员覆盖与异常详情。本地已更新为 `1.0.6`，真实登录页面验收与源码三平台 CI 已通过。交付状态见[小版本计划](docs/superpowers/plans/2026-10-16-post-v1-roadmap.md)。

> 本项目仅用于研究、工程验证与模拟交易，不构成投资建议。当前代码不接入真实券商账户，也不提供可调用的实盘下单路径。

## 1.0.0 范围

- 现有本地管理员登录与退出。
- AKShare 真实历史日线、交互图表、来源版本与行情日期；默认显式配置 8 个沪深股票样本，不代表全市场。
- 已入库样本涨跌分布和成交额，不把面板完整度当作全市场覆盖率。
- 价格与涨跌幅站内提醒、规则名称和阈值修改、启停、评估历史与已读状态持久化。
- raw、行情修订和规则版本可追溯；日线通过 `pnpm v1:sync` 显式更新，页面刷新不会触发行情采集。

1.0.0 不提供实时行情、模拟交易或股票/ETF 买卖。情绪轮动、事件热点、席位/KOL、量化回测、贵金属基金和 QMT 按[模块开发任务](docs/superpowers/plans/2026-10-16-post-v1-roadmap.md)分片推进；代码保留，首发入口不开放。正式发布状态与剩余验收以[发布清单](docs/superpowers/plans/2026-10-12-v1.0-release-plan.md)为准。

## 1.0.1 增量

市场总览和标的日线页显示实际采集任务的最近尝试、最近成功与结果。任务失败保留先前成功记录；尚未运行时显示未知。零新增的成功检查不改变行情日期，页面仍分别显示数据截止时间。

## 1.0.2 增量

显式运行 `pnpm v1:auto:start` 后，每天北京时间 09:00 检查当前样本；可通过 `V1_MARKET_DATA_DAILY_AT` 调整时间。迟启动补跑当天一次，重启沿用成功记录与每日最多 3 轮尝试预算。暂时失败按 60/120 秒退避，永久错误当天停止。普通启动保持原样，手动更新仍用 `v1:sync`；停止自动任务用 `v1:auto:stop`，查看日志用 `v1:auto:logs`。日线日期仍以页面数据截止时间为准。

## 1.0.3–1.0.4 增量

标的日线页可带入代码打开提醒创建抽屉，规则列表支持标的和启用状态筛选。个人自选按登录账号保存在服务端，支持批量导入、旧浏览器清单迁移和逐项行情状态；旧清单保留为迁移备份。日线展示收盘价、日期与来源，港股、新三板和上金所观察项明确标为未接入，详情见[自选日线运行说明](docs/runbooks/personal-watchlist.md)。

## 日线对比（1.0.5 切片，随 1.0.6 交付）

市场日线页增加原有 8 个沪深样本的收盘价、较前一可见日线涨跌幅和成交额对比，支持排序与历史详情跳转。日期、来源或数据版本不一致时明确提示，不混算涨跌幅；使用未复权价格，不表示已处理除权除息的收益率。该表不代表全市场排名，个人自选仍在服务端单独管理。已通过定向测试、独立审查和真实登录页面的历史点时、排序与详情跳转验收，随 `1.0.6` 一并交付。

## 1.0.6 增量

管理员日线数据质量入口按日期、来源和证券查看已入库日期与公开异常证据。分组数量、最新日期只描述本次返回结果；缺少应有交易日依据时，缺口判断显示未知。异常证据按实际快照发布时间展示，不把历史记录当成当前健康状态。详细口径见[日线入库概览](docs/runbooks/market-data-coverage.md)与[异常证据说明](docs/runbooks/market-quality-evidence.md)。

## 1.0.7 增量（收尾中）

日线覆盖行的日期明细可选择历史起止日期，包含起止日，最多 366 个自然日。支持同条件重查、
恢复汇总窗口和分页重置；空结果保留查询区间与时间，不推断行情缺口。复用已有只读接口，
具体用法见[历史窗口检索](docs/runbooks/market-data-coverage.md#107-历史窗口检索)。

## 1.0.x 本地启动

已有 `infra/docker/.env` 时保留原文件；首次使用才从 `.env.example` 复制，并按[登录手册](docs/runbooks/local-authentication.md)交互式创建管理员。

```bash
pnpm v1:config:check
pnpm v1:up
pnpm v1:sync
```

打开 <http://localhost:5173/>。只启动必要服务，端口仅绑定本机；沿用现有数据，启动已有库前先备份。停止与恢复、日线覆盖和故障边界见[启动说明](docs/development/docker-local.md#10-精简启动)。

## 能力边界

- 1.0.0 只开放历史日线与站内提醒；仓库中保留的模拟研究模块属于后续版本。QMT 和真实账户接入需独立授权、隔离环境和完整门禁。
- 不包含实物贵金属、现货合约、商品期货、保证金、移仓换月、交割或仓单业务。
- 外部数据源、模型或服务在完成配置与运行验证前，不应被视为当前实例已可用。

## 技术栈

| 层          | 技术                                                                                             |
| ----------- | ------------------------------------------------------------------------------------------------ |
| 前端        | React, TypeScript, Vite, shadcn/ui, Tailwind CSS, TradingView Lightweight Charts, Apache ECharts |
| 控制面      | NestJS, TypeScript, PostgreSQL, TypeORM                                                          |
| Python 引擎 | Python 3.12, FastAPI, Pydantic, Polars, DuckDB, PyArrow                                          |
| 数据        | PostgreSQL（业务状态）, ClickHouse（时序/分析）, Redis（缓存/实时）, MinIO/COS（对象存储）       |
| 工程        | Turborepo + pnpm workspace, uv workspace, Docker Compose                                         |
| 可观测      | OpenTelemetry, Prometheus, Grafana, Loki                                                         |

## 项目结构

```text
apps/                 React 终端和 NestJS 控制面
services/             独立可部署的引擎和 Worker
python/packages/      可复用 Python 领域库
packages/             UI、契约、客户端、类型、配置
infra/                本地与生产基础设施
research/             笔记本、实验、评估和报告
data/                 仅 fixtures 和脱敏样本
docs/                 架构、ADR、算法、运维手册
scripts/              跨平台开发、CI 和运维入口
```

## 开发

完整的环境搭建见 [开发者启动手册](./docs/development/index.md)。快速开始：

```bash
# 1. 安装依赖（Node + Python）
pnpm install --frozen-lockfile
uv sync --locked

# 2. 启动本地数据基础设施（首次需 cp infra/docker/.env.example infra/docker/.env）
pnpm infra:up

# 3. 启动应用（API:3002, Web:5173）
pnpm dev
```

日常改动按 [AGENTS.md](./AGENTS.md#16-testing-and-verification) 的风险与影响范围选择检查，复用仍有效的结果；文档修改不启动服务或运行应用测试。`pnpm check` 是全仓聚合检查（format + lint + typecheck + vitest + pytest），不作为每次改动的默认命令。发布收尾只做一次核心流程验收、保留一份简短回执；高风险专项检查和正式交易门禁仍按对应要求执行。

版本按 `1.0.0 → 1.0.1 → 1.0.2` 推进，小功能和修复用补丁号，明确产品里程碑才升次版本。每版交付一项可用模块增量，目标 2–5 个自然日，包含调研和验收的总周期最多 7 个自然日；详细任务见[小版本计划](docs/superpowers/plans/2026-10-16-post-v1-roadmap.md)。

## 文档

- [AGENTS.md](./AGENTS.md) — 仓库级 Agent 操作规范
- [小版本开发任务](./docs/superpowers/plans/2026-10-16-post-v1-roadmap.md) — 1.x.x 模块切片、可用结果和一周内交付预算
- [开发者启动手册](./docs/development/index.md) — 环境搭建、启动、端口与故障排查
- [项目设计稿](./docs/superpowers/specs/)
- [实施计划](./docs/superpowers/plans/)
- [项目总体规划与实施手册](./outputs/昆仑智策项目总体规划与分阶段实施手册.docx) — 当前能力之外的路线图与开发节点目录
- [架构决策记录](./docs/adr/)
