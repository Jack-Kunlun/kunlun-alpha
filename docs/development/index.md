# 开发者启动手册

本手册面向无项目上下文的开发者，指导从零搭建昆仑智策（Kunlun Alpha）本地开发环境。

- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [相关文档](#相关文档)

更详细的参考见 [端口与环境变量](reference.md) 和 [故障排查](troubleshooting.md)。

## 环境要求

| 工具             | 版本            | 说明                                                                                       |
| ---------------- | --------------- | ------------------------------------------------------------------------------------------ |
| Node.js          | 24.19.0         | 见 `.node-version`；可用 [Volta](https://volta.sh) 或 nvm 安装                             |
| pnpm             | 11.21.0         | `packageManager` 字段声明，Corepack 可自动启用                                             |
| Python           | 3.12（3.12.13） | 见 `.python-version`；`requires-python = ">=3.12,<3.13"`                                   |
| uv               | 0.12.3          | Python 包管理，`pyproject.toml` 中 `[tool.uv] required-version`                            |
| Docker + Compose | 任意较新版本    | 本地数据基础设施（PostgreSQL、ClickHouse、Redis、MinIO、Prometheus、Grafana、Loki、Tempo） |

Windows 开发者请勿使用中文/空格路径放置仓库；如遇"文件被占用/写入被拒"类错误，先看 [故障排查](troubleshooting.md)。

## 快速开始

### 1. 克隆并安装依赖

```bash
git clone <repository-url> kunlun-alpha
cd kunlun-alpha

# Node 侧（lockfile 一致性校验）
pnpm install --frozen-lockfile

# Python 侧（uv workspace，含 python/packages/* 与 services/*）
uv sync --locked
```

> 依赖变更流程：修改依赖后运行 `pnpm install` / `uv sync`，**提交更新后的锁文件**（`pnpm-lock.yaml`、`uv.lock`），CI 会用 `--frozen-lockfile` / `--locked` 校验一致性。

### 2. 启动本地数据基础设施

首次使用需从模板创建环境文件（默认值仅用于本地开发，**禁止**用于生产）：

```bash
cp infra/docker/.env.example infra/docker/.env
pnpm infra:up        # docker compose up -d
pnpm infra:ps        # 查看服务状态
```

等待所有服务 healthy 后再启动应用。完整端口清单见 [端口与环境变量](reference.md)。

### 3. 启动应用

```bash
pnpm dev
```

这会并行启动：

- 控制面 API：<http://localhost:3002>，健康检查 <http://localhost:3002/api/v1/health>，指标 <http://localhost:3002/api/v1/metrics>
- Web 终端：<http://localhost:5173>

> API、Grafana、ClickHouse native 与 MinIO 已使用不同宿主端口；可在同一开发机并行启动。

Python 引擎按服务单独启动（引擎是长驻进程，由 `pnpm dev` 之外的终端运行）：

```bash
cd services/sample-engine
uv run sample-engine
# 健康检查: http://localhost:8080/health；指标: http://localhost:8080/metrics
# KUNLUN_PORT 可覆盖端口
```

### 4. 验证环境就绪

```bash
# 全量质量门禁：format + lint + typecheck + vitest + pytest
pnpm check
```

所有检查通过即环境就绪。常用命令见 [端口与环境变量](reference.md#常用命令)。

## 相关文档

- [端口与环境变量](reference.md) — 端口清单、环境变量、常用命令、数据重置
- [故障排查](troubleshooting.md) — 常见问题与解决方案
- [AGENTS.md](../../AGENTS.md) — 仓库级 Agent 协作规范（按节点推进）
- [架构决策记录](../../docs/adr/) — 关键架构决策
- 完整实施手册：`../../outputs/昆仑智策项目总体规划与分阶段实施手册.docx`
