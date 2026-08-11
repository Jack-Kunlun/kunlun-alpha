# 运行时与包管理器版本基线

> 记录于 2026-08-11，对应 P0-N03。

## 锁定版本

| 工具 | 版本 | 状态 | 锁定日期 |
|---|---|---|---|
| Node.js | 24.19.0 | Active LTS | 2026-08-11 |
| pnpm | 11.21.0 | Current | 2026-08-11 |
| Python | 3.12.13 | Security-only | 2026-08-11 |
| uv | 0.12.3 | Current | 2026-08-11 |

## 版本选择依据

- **Node.js 24 (Krypton)**: 当前 Active LTS，支持至 2028-04-30。26 尚在 Current 阶段，预计 2026-10-28 进入 LTS。
- **pnpm 11**: 最新主版本，要求 Node.js >= 22。
- **Python 3.12.13**: 项目要求 3.12 系列的最新安全补丁版本。3.12 处于 security-only 维护期至 2028-10。
- **uv 0.12**: 最新稳定版，Rust 重写的高性能 Python 包管理器。

## 配置方式

| 方式 | 文件 | 适用范围 |
|---|---|---|
| `.node-version` | 根目录 | fnm/nodenv/asdf 等版本管理器 |
| `package.json#engines` | 根目录 | pnpm/npm 运行时约束 |
| `package.json#packageManager` | 根目录 | Corepack 自动切换 |
| `package.json#volta` | 根目录 | Volta 版本管理器 |
| `.python-version` | 根目录 | pyenv/asdf 等版本管理器 |
| `pyproject.toml#requires-python` | 根目录 | uv/pip 依赖解析约束 |
| `pyproject.toml#[tool.uv].required-version` | 根目录 | uv 自身版本约束 |

## 升级策略

升级遵循以下原则：

1. **不在业务节点中顺带升级。** 升级运行时或包管理器是独立变更。
2. **升级须有明确动机。** 不因为"有新版本"而升级，因为"需要新特性/修复已知问题/安全通告"而升级。
3. **升级前在 CI 中验证。** 新版本在三端（Windows、macOS、Linux）CI 通过后，才更新本文件。
4. **使用精确版本。** 不写范围，不写 floating tag。
5. **一并更新所有版本文件。** `.node-version`、`package.json`、`pyproject.toml` 等必须同步。

### 何时升级 Node.js

- 当前 LTS 线进入 Maintenance 阶段，且新 LTS 线已稳定（至少 2 个 minor release）
- 目标：始终使用最新 Active LTS

### 何时升级 Python

- 项目明确切换到更新的 Python 大版本（如 3.13、3.14）
- 当前锁定版本有安全漏洞需要修复
- 注意：Python 3.12 进入 security-only 后不再提供二进制安装包，但源码安装可用

### 何时升级 pnpm / uv

- 有新 major 版本且社区迁移成熟
- 当前版本修复了已知的安全或稳定性问题
- 新版本提供了项目实际需要的新特性
