# 昆仑智策 (Kunlun Alpha)

**观势 · 知势 · 策势**

## About

昆仑智策是一套面向 A 股与场内贵金属 ETF/基金的智能投研、量化研究、回测与模拟交易平台。项目围绕时点可见的数据基础、可追溯的市场情报、版本化研究结果和独立风险控制构建，覆盖从数据接入到决策终端的完整研究链路。

> 本项目仅用于研究、工程验证与模拟交易，不构成投资建议。当前代码不接入真实券商账户，也不提供可调用的实盘下单路径。

## 当前范围

- **数据基础**：统一 A 股证券标识，区分事件、发布、接入与可用时间，保留原始数据、修订版本和来源证据。
- **市场情报**：支持市场情绪、板块轮动、新闻事件、热点、龙虎榜席位与 KOL 公开观点研究；KOL 内容始终作为带证据的 `Claim`，不视为已确认交易。
- **量化研究**：提供版本化特征、时点一致性研究、回测、回归基线与研究报告能力，避免使用决策时点之后才可见的数据。
- **决策与模拟**：提供市场、个股、板块、研究与提醒工作台，以及模拟账户、订单意图、风险决策、对账和恢复链路。
- **贵金属范围**：仅覆盖交易所上市并经来源确认的贵金属 ETF/基金；NAV 与 iNAV 只作为研究参考，不作为可执行价格。

## 能力边界

- 当前仓库只支持研究与模拟交易；QMT 和真实账户接入属于未来路线图，未经独立授权、隔离环境和完整门禁不得启用。
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

质量门禁：`pnpm check`（format + lint + typecheck + vitest + pytest）。所有更改按 AGENTS.md 中的节点粒度推进，并遵循该文件定义的 WorkBuddy/Codex 协作流程。

## 文档

- [AGENTS.md](./AGENTS.md) — 仓库级 Agent 操作规范
- [开发者启动手册](./docs/development/index.md) — 环境搭建、启动、端口与故障排查
- [项目设计稿](./docs/superpowers/specs/)
- [实施计划](./docs/superpowers/plans/)
- [项目总体规划与实施手册](./outputs/昆仑智策项目总体规划与分阶段实施手册.docx) — 当前能力之外的路线图与开发节点目录
- [架构决策记录](./docs/adr/)
