# 日线入库概览本地部署验证

日期：2026-09-05。节点：P1-N12 的日线入库概览切片。

## 提交与部署范围

- 应用源码提交：`8460e2128851a6814cf5c084ed7a270fc41a5f95`。
- 提交标题：`feat(data-quality): 展示日线入库概览与更新时间`。
- 精确提交 31 个相关文件；未推送远端，未包含原有 P6 改动。
- 镜像从该提交的 `git archive` 干净快照构建，不使用含未提交代码或本地采集内容的工作目录。
- 复用现有 Compose project `docker`、原有 Compose 文件和外部配置文件。
- 仅执行 `up -d --no-deps --no-build server web` 替换两个应用容器。
- 未创建第二套部署，未执行迁移、采集或墙钟门禁，未重启数据服务和量化引擎。

新镜像：

```text
server sha256:74513bb0272676e5fa91c3542f90bd48e87b615dd19b46ec4ee4fec2bcaf2287
web    sha256:764d32811e249b68f3e09f25a2f190646244d3d370ebe972fe4e9971f8e31060
```

旧镜像以应用各自的 `rollback-8460e21` 标签保留。回滚只应复用原配置替换这两个应用，
不得使用 `down`、删卷或重启依赖服务。

## 主代理独立检查

- `GET http://127.0.0.1:3002/api/v1/health`：200。
- `GET http://127.0.0.1:5173/data-quality`：200。
- 未登录请求 `/api/v1/data-quality/market-coverage`：401。
- `kunlun-server` 与 `kunlun-web` 的实际镜像匹配上述新镜像，均 healthy，restartCount 为 0。
- PostgreSQL、ClickHouse、Redis、MinIO 和 quant-engine 的容器 ID、StartedAt、RestartCount
  与替换前基线一致，均 healthy。
- 前后安全摘要对比确认：17 个非目标 Kunlun 容器的 ID、镜像、启动时间与重启次数均未改变。
- 更新后的 server 容器内，通过新 adapter 只读查询现有 ClickHouse：`000001.SZ`、`300750.SZ`、
  `601318.SH`、`688981.SH` 各有 64 个观测日，范围为 `2026-06-08` 至 `2026-09-04`，
  `truncated=false`。未写入新行情。

首次宿主 HTTP 检查在受限 sandbox 中无法连接本机端口；获得只读检查权限后重跑通过。
这不是应用故障。未读取登录凭据，未执行登录后的浏览器端到端验收；HTTP 401 仅证明
未认证访问仍被拒绝，不代表已完成角色权限审计。

## 下一切片边界

项目负责人已批准独立脱敏证据卷，但本次部署没有创建或挂载该卷。
后续方案见[行情质量证据安全投影接入计划](../superpowers/plans/2026-09-05-market-quality-public-evidence-plan.md)。
原始行情、数据库和凭据权限不得扩大，权限及证据文件接线需独立安全审核后实施。
当前日线概览仍只表达已观测到的入库日数，不代表拒绝证据、缺失交易日或全市场覆盖已经接入。
