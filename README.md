# 昆仑智策 (Kunlun Alpha)

**观势 · 知势 · 策势**

A 股智能投研、量化研究与交易决策平台。覆盖 A 股及 ETF 的数据采集、市场情绪、板块轮动、事件热点、席位 KOL 情报、特征工程、量化回测与模拟交易能力。

真实交易仅在最终阶段（Phase 7）开放，且须通过风控、对账、审批和灰度门禁。

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

## 开发阶段

| 阶段    | 主题                          | 节点数 |
| ------- | ----------------------------- | ------ |
| Phase 0 | 工程基础设施                  | 15     |
| Phase 1 | A 股数据底座                  | 14     |
| Phase 2 | 市场情绪与板块轮动            | 10     |
| Phase 3 | 新闻、事件与热点 Intelligence | 10     |
| Phase 4 | 龙虎榜席位与 KOL Intelligence | 10     |
| Phase 5 | Feature Store、量化研究与回测 | 14     |
| Phase 6 | 智能决策终端与模拟组合        | 13     |
| Phase 7 | QMT、独立风控与实盘交易       | 12     |

完整实施手册见 `outputs/昆仑智策项目总体规划与分阶段实施手册.docx`。

## 开发

开发遵循 AGENTS.md 中定义的 WorkBuddy/Codex 协作流程。所有更改按单节点粒度推进。

```bash
# 安装和启动（待 Phase 0 完成后可用）
pnpm install
pnpm dev
```

## 文档

- [AGENTS.md](./AGENTS.md) — 仓库级 Agent 操作规范
- [项目设计稿](./docs/superpowers/specs/)
- [实施计划](./docs/superpowers/plans/)
- [架构决策记录](./docs/adr/)
