# 项目手册构建工具

本目录保存《昆仑智策项目总体规划与分阶段实施手册》的可重复构建与结构审计脚本。脚本以仓库根目录为基准定位文件，不依赖个人绝对路径。

## 环境要求

- Python 3.12 或项目锁定的最新稳定版本
- `python-docx`
- 项目 Python 工作区建立后，统一通过 `uv` 执行

## 重建手册

```shell
uv run python scripts/docs/build_handbook.py
```

在 Phase 0 的 `uv` 工作区尚未建立前，可使用已安装依赖的 Python：

```shell
python scripts/docs/build_handbook.py
```

生成文件：

```text
outputs/昆仑智策项目总体规划与分阶段实施手册.docx
```

## 运行结构审计

```shell
uv run python scripts/docs/audit_handbook.py
```

或在 `uv` 工作区建立前运行：

```shell
python scripts/docs/audit_handbook.py
```

审计会检查 DOCX 压缩包完整性、必需章节、开发节点数量、各阶段节点分布、占位符，以及表格的固定布局信息。修改手册生成逻辑后，应先重建，再执行审计。

## 仓库约定

- 构建脚本和审计脚本需要提交到 Git。
- 最终 DOCX 属于用户交付物，需要提交到 Git。
- `work/` 只用于临时脚本、草稿、渲染缓存和审计中间结果，已通过 `.gitignore` 排除。
- 所有文本文件使用 UTF-8 与 LF；不要提交机器专属绝对路径。
