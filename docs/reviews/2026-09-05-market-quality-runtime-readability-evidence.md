# 公开质量证据跨用户可读性修复证据

## 结论与范围

P1-N12 的公开文件跨用户读取缺陷已修复并通过定向验证；代码尚未提交或部署。
worker UID 10001 发布的快照、指针原来是 `0600`，API UID 1000 无法读取。
这次仅修改新脱敏公开产物，不变更 raw、manifest、API 用户/组或既有数据库权限。

修改文件为 `Dockerfile`、`services/data-worker/src/data_worker/jobs/market_data/quality_export.py`、
`services/data-worker/tests/test_market_quality_export.py`，同步证据运行手册与限定计划。
没有删除源码文件、增加依赖或改变公开 JSON Schema。

## 行为

- 新文件在替换前通过 descriptor 设置 `0644`，随后同步并原子替换。snapshot 先于 current。
- 新 public 根与 snapshots 目录为 `0755`，既有不符合模式的目录拒绝而不自动放宽。
- 同摘要旧快照复用前要求普通文件且为 `0644`，不能新指针指向不可读历史产物。
- snapshot 或 current 阶段权限设置失败，均不提交新 current；新目录创建失败转为受控错误。
- Docker worker stage 预建归 UID/GID 10001 的 public 根；实际卷仍需 producer-first 初始化。
- Windows 在没有 fchmod 时走 chmod fallback；本轮 POSIX 测试不能证明 Windows ACL。

## 失败先行

根代理用隔离临时目录调用原 `_atomic_write`，实际得到 `public_artifact_mode=0o600`。
首次探测使用 macOS 临时目录别名被既有符号链接防护拒绝；改为解析后的真实临时路径
再探测，未读取实际行情或凭据。

```text
PYTHONPATH=services/data-worker/src:python/packages/ashare-contracts/src:python/packages/market-core/src .venv/bin/python -m pytest --no-cov services/data-worker/tests/test_market_quality_export.py -k 'public_export_files_are_owner_writable or public_export_chmod_failure_preserves_current_pointer'
2 failed, 16 deselected
```

审核边界补充中，目录创建 PermissionError 未受控包装被直接复现：

```text
PYTHONPATH=services/data-worker/src:python/packages/ashare-contracts/src:python/packages/market-core/src .venv/bin/python -m pytest --no-cov services/data-worker/tests/test_market_quality_export.py -k 'public_current_fchmod_failure or existing_snapshots_directory_with_unsafe_mode or public_directory_creation_permission_error'
修复前：3 passed, 1 failed, 20 deselected
修复后：4 passed, 20 deselected
```

## 新鲜验证

根代理执行：

```text
uv --no-cache run --no-sync --package data-worker pytest --no-cov -q services/data-worker/tests/test_market_quality_export.py
24 passed in 0.53s

.venv/bin/ruff check services/data-worker/src/data_worker/jobs/market_data/quality_export.py services/data-worker/tests/test_market_quality_export.py
All checks passed!

.venv/bin/ruff format --check services/data-worker/src/data_worker/jobs/market_data/quality_export.py services/data-worker/tests/test_market_quality_export.py
2 files already formatted

.venv/bin/basedpyright services/data-worker/src/data_worker/jobs/market_data/quality_export.py services/data-worker/tests/test_market_quality_export.py
0 errors, 0 warnings, 0 notes
```

执行者另运行 export、projection、market collector 相关测试，50 项通过；未重复整个
data-worker 包测试。Terra Max 独立权限选择器验证为 `8 passed, 16 deselected`，复核
失败顺序、旧目录拒绝、原始文件不变及 Dockerfile，未发现本切片剩余代码级阻断。

uv 的非目录 workspace 条目提示未影响测试执行。本轮本机 macOS 验证；镜像构建、
跨 UID 容器文件系统和真实部署另行记录，不在此处预先声称通过。

## 剩余边界

真实 public 卷尚未创建或接线。新卷需要 producer-first 初始化，API 只读；真实
脱敏导出及认证页面验收尚未完成。
日历持久化、PIT、完整性规则及最终墙钟资格不因本切片通过而关闭。
原有 P6 与日历工作区改动保持原状，没有启动真实行情采集或任何券商路径。

## 候选镜像与隔离卷验收

执行者以 `d1847c08750bf932cd6b63936d8617c29d91d623` 的干净归档为基础，仅覆盖
Dockerfile、日历的 `__init__.py`、`collector.py`、`repository.py` 和
`market_data/quality_export.py`，排除既有 P6 工作区修改与环境文件。
构建 data-worker target 成功；未替换 `:local` 标签或任何运行中容器。

候选镜像为 `kunlun-data-worker:quality-evidence-candidate-x0jbrj`，镜像 ID：

```text
sha256:98159391c60a6f458252264466bb07357ff79495e5f17fee2a3b1e5c424de41c
```

使用唯一 UUID 临时卷进行 producer-first 验收：候选 worker 为 UID/GID 10001，
预建目录归该用户且模式为 `0755`；无网络、空 tmpfs 质量 fixture 导出成功，
`published=true`、`recordCount=0`。已有 server 镜像以 UID/GID 1000 只读挂载
同一临时卷，指针及快照均为 `0644` 且可读取，写入探测被拒绝。
临时卷已精确移除，未使用实际原始行情卷或写入数据库。

新增可选 `infra/docker/docker-compose.market-quality-evidence.yml` 并通过合并配置
校验；server 仅挂 public 只读，一次性 exporter 无网络、raw 只读/public 可写。
该 overlay 尚未用于真实部署，零条隔离 fixture 不代表真实证据为空。

构建首次受 Docker socket 沙箱限制，授权提权后成功；初次镜像探测误用文件判定检查
目录，改为目录判定后成功；归档断言误以为某已提交测试不存在，随后改以选定文件摘要
及未跟踪 overlay 排除验证。上述失败均未修改现有运行环境。
