# 日历采集与数据质量界面本地部署记录

日期：2026-09-05。用户明确授权提交并更新现有本地容器部署。

## 提交与构建

- 源码提交：`2cf1f917c9e39aaf736450da010c98c4121175ba`。
- 标题：`fix(calendar): 修正缺失日期误报并限制采集分页`。
- 提交限定 7 个日历修复和审核记录文件，未包含原有 P6 修改，未推送远端。
- 包含前序提交的逐日行情入库明细与行情拒绝证据代码，但后者的公开卷仍未启用。
- 从该提交的 `git archive` 干净快照构建，不使用 dirty 工作目录作为 Docker context。
- 三个 Dockerfile target `server`、`web`、`data-worker` 构建均退出 0，未修改锁文件或依赖。

候选标签均为 `candidate-2cf1f91`，发布后的镜像 ID：

```text
kunlun-server:local
sha256:f1f02709e21d809204ef47f65dca61683f15e28d91d3c8657140b1c6f12c61a0

kunlun-web:local
sha256:70ce3e9ba76723dc01d58c76db702386269b20582014b50d5424a4dad6a471b5

kunlun-data-worker:local
sha256:aa16aecac3a822c06868318ba5dabf969db471d8de2ede50a1a900e5fa070a85
```

worker 只发布待用镜像，不启动或创建行情采集任务。镜像内确认日历 collector 和质量导出
模块存在；server/web 构建产物存在。构建验证用的停止状态临时容器已删除，不影响服务。

## 现有环境更新边界

复用 Compose project `docker`。保持仓库基础与应用两份 Compose 文件、现有外部
`market-data-settings.compose.yml` overlay，以及原有两份环境文件。

部署预检确认：外部 overlay 没有 `env_file`，其必需设置变量由外部
`market-data-settings.env` 提供，因此显式传入第二份 `--env-file`，不依赖 shell 环境。
检查只提取字段结构与变量名，不输出任何变量值或凭据。

执行形式如下；外部配置路径由现有部署定位，不是新建配置：

```sh
docker compose --project-name docker \
  --env-file infra/docker/.env \
  --env-file "$KUNLUN_SETTINGS_ENV" \
  -f infra/docker/docker-compose.yml \
  -f infra/docker/docker-compose.apps.yml \
  -f "$KUNLUN_SETTINGS_COMPOSE" \
  up -d --no-deps --no-build server web
```

仅替换 server/web；没有 `down`、删卷、新 Compose 项目、迁移、数据库写入、数据回填、
行情采集或墙钟门禁启动。预检未发现活跃 paper-soak 进程或相应 launchd 条目。

## 新鲜验证

- 提交前日历定向 pytest：`16 passed in 0.26s`；文档 Prettier 与差异检查通过。
- 更新后 server/web 镜像 ID 与候选完全一致，均 `running/healthy`，RestartCount 为 0。
- 主代理保存并比对 19 个 Kunlun 容器；17 个非目标容器的 ID、镜像、StartedAt、
  RestartCount、运行/健康状态完全不变，包括 PostgreSQL、ClickHouse、Redis、MinIO、
  quant-engine 及已退出的一次性迁移容器。
- `GET http://127.0.0.1:3002/api/v1/health` 返回 200。
- `GET http://127.0.0.1:5173/data-quality` 返回 200。
- 未登录访问 `/api/v1/data-quality/market-coverage/days` 与
  `/api/v1/data-quality/market-evidence` 均返回 401。
- 在更新后的 server 内通过已部署 `ClickHouseMarketCoverageDaysReadModel` 和既有配置
  只读查询 `000001.SZ`、`akshare-tencent`、`2026-06-08` 至 `2026-09-04`：返回 64 个
  日期，首尾日期与窗口一致。仅输出计数和日期范围，不输出凭据或原始行情。

第一次容器摘要模板对没有 Health 字段的一次性容器报错；改用可选字段访问后，完整
19 容器基线成功采样并完成比对。归档后的 Git 状态检查因 archive 不含 `.git` 报错，
不代表归档失败；之后通过归档文件和构建成功确认镜像来源。
执行者首次宿主 HTTP 探测受 sandbox 限制返回 000，获准重跑相同只读探测后通过。
主代理独立 HTTP 验证也通过，没有把沙箱连接限制误判为应用故障。

Terra Max 的部署后独立元数据审核通过：镜像、健康状态、Compose project 与三配置
标签匹配；server/web 均无新增挂载，market-data-sync 未启动，抽查基础服务与迁移
容器没有本轮重启。HTTP 与完整 17 个非目标容器比对由主代理独立完成。

## 回滚与限制

三个旧镜像均保留 `rollback-pre-2cf1f91` 标签。需要回滚时，将相应旧标签重新指向
`:local`，使用完全相同的双环境文件和三配置参数，仅更新 server/web；不得使用 `down`
或删除数据卷。worker 镜像回滚只需恢复标签，不应为回滚启动采集任务。

没有执行登录后的浏览器交互验收；401 证明未认证请求被拒绝，不代表所有角色权限验证。
只读 adapter 查询不等同于认证 HTTP 端到端测试，也不证明交易日覆盖完整。

日历修复已进入 worker 镜像，但本轮没有实际运行日历采集。行情拒绝证据代码已部署，
公开脱敏卷与发布链路未接线，因此仍保持证据不可用状态，不声称真实拒绝记录已展示。
该功能启用仍需精确挂载、唯一 writer/只读 server 权限和认证快照验收。

原有 P6 修改及历史门禁证据保持原状；不改变条件接受或最终连续墙钟资格结论。
