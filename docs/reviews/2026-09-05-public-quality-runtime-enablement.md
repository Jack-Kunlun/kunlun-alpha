# 公开行情证据原位启用记录

## 范围与验收

节点 P1-N12。用户已授权新增独立脱敏证据卷、补齐缺口后更新现有环境，并于本轮
确认完成登录。只使用现有 Compose 项目 `docker`；API 只读公开卷，导出器只读原始
卷并写公开卷。不启动行情采集、数据库迁移、正式墙钟门禁或券商连接。

依次核对候选镜像、producer-first 发布、公开卷权限、精确服务更新与已认证页面。
失败时保留原始证据，不删除异常文件使检查变绿。公开证据运行启用和认证页面验收
现已完成；日历及全市场完整性不在本次关闭范围。

## 更新前基线

2026-09-05 已认证 `/data-quality` 显示 10 个证券来源组合的日线观测；公开证据区
明确显示暂不可用。目录项数不作为有效证据条数，观测日数不作为完整覆盖结论。

现有 server 镜像 ID 为
`sha256:f1f02709e21d809204ef47f65dca61683f15e28d91d3c8657140b1c6f12c61a0`，
启动时间 `2026-09-05T09:35:11.796706711Z`；web 启动时间
`2026-09-05T09:35:17.66222463Z`。公开卷不存在，raw 命名卷已存在。

基础服务重启计数均为零，后续必须保持以下启动时间：

| 服务 | StartedAt（UTC） |
| --- | --- |
| PostgreSQL | 2026-09-03T02:31:45.038812751Z |
| ClickHouse | 2026-09-03T02:31:45.034152626Z |
| Redis | 2026-09-03T02:31:45.036892626Z |
| MinIO | 2026-09-03T02:31:45.026946376Z |

普通沙箱首次 Docker 查询被 socket 权限拒绝，经工具审批后只读查询成功。未输出环境
配置、凭据、会话令牌或原始行情内容。

## 代码及其他门禁边界

候选只能包含经过验证的明确文件，不包含既有 P6 工作区修改。日历持久化代码入镜像
不意味着迁移或启用实际日历采集。完整日历及点时完整性切片独立验收；既有 R4 条件
接受与延期正式墙钟门禁不变。

## 候选和预检

干净归档基线为 `d1847c08750bf932cd6b63936d8617c29d91d623`；仅叠加 11 个已验证的
production 文件，包含质量公开文件权限与基金拒绝字段名保护，以及已验收的稀疏日历
仓储。未包含正在开发的独立权威逐日判定。manifest 检查没有其他 dirty 字节、非白名单
未跟踪文件或真实 env 文件。原有 15 个 P6 保护文件的工作区 SHA256 仍与执行前一致。

候选：`kunlun-alpha/data-worker:candidate-d1847c0-1e060457`，镜像 ID
`sha256:8696781db8331f367e94172ec70e0eb17c6181554232fedec9d8bb872fbca6d1`。
构建日志显示完成；无网络 import、公开 CLI help、默认 UID/GID 10001 与 public 根
owner/mode 检查通过。SQL wheel 资源与工作区摘要为
`d998b3cb7598d3ba819fb1de95210e20b8b5171afdcc11c7eefcc2ebd331e1ab`。

根代理重新执行 `uv --no-cache run --no-sync --package data-worker pytest --no-cov -q
services/data-worker/tests/test_market_quality_export.py`，24 项通过（0.63 秒）。
四份 Compose 合并的 `config --quiet` 成功，未输出配置值。真实旧标签为
`kunlun-data-worker:local`，其镜像 ID
`sha256:aa16aecac3a822c06868318ba5dabf969db471d8de2ede50a1a900e5fa070a85`；
执行者最初检查的是另一个不存在的命名空间标签，已由根代理纠正，不将其缺失作为旧环境
不存在的证据。此次验证没有更新 server/web 镜像，也未执行数据库迁移。

## 实际启用与回滚

先保留旧 worker 标签 `kunlun-data-worker:rollback-pre-p1-n12-57ae8bbb`，再将
`kunlun-data-worker:local` 指向上述候选。对现有四份 Compose 配置执行
`--profile evidence-export run --rm --no-deps market-quality-evidence-export`，
得到 `published=true, recordCount=14`。新卷 producer-first 初始化成功，root/snapshots
为 `10001:10001/0755`，current/snapshot 为 `0644`，公开 schema/摘要/记录数通过核对。

随后仅执行 `up -d --no-deps --no-build server`。server 仍使用原镜像，启动时间变为
`2026-09-05T12:21:11.753356335Z`，healthy、HTTP health 200、重启计数零；唯一挂载
为 public 且 `rw=false`，没有 raw 挂载。UID1000 可读取公开产物，写入探针得到 EROFS。
根代理复核 web 与四个基础服务的镜像、StartedAt 和重启计数均未变化；导出容器查询
无残留。原始证据与公开卷均保留，未删除数据或启动 market-data-sync。

如需撤销接线，保留其余三份既有 Compose/环境文件，仅不再加入 evidence overlay，
原位重建单个 server；worker 可将上述 rollback 标签恢复至 local。回滚不删除任何卷。
后续维护此环境时须继续包含 evidence overlay，否则公开证据挂载会被移除。

## 已认证页面验收

既有浏览器会话刷新后，页面显示固定公开快照 `2c16ce76990d…125a850d`，发布时间
2026-09-05 20:19:49（上海），共 14/14 条。均是已记录的 `akshare-sina` 分钟数据
`FILTERED / SINA_OVERFETCH_OUTSIDE_REQUEST`，不是 14 条 REJECTED，也不代表新增行情。
原始记录时间仍显示 2026-08-27，未被回填发布时间替代。

- 日期 2026-08-27、来源 akshare-sina、证券 000001.SZ、FILTERED 联合筛选返回 2/2。
- 17:24:50 的记录详情可读取，过滤数 1732；明细由 1/35 翻至 2/35，显示行号 50–99，
  不透明证据 ID 保持一致。只显示允许的时间、行号、原因码，没有价格/raw 下载。
- 改为 REJECTED 返回“当前筛选条件下暂无”，同时保留快照发布时间，没有混淆为读取错误。
- 已清空验收筛选，恢复默认查询。顶层仅 14 条，小于每页 20 条，上一页/下一页禁用正确；
  没有为了制造顶层多页而写入假数据。跨快照分页回归沿用既有自动测试证据，本次实际验证
  的是单个快照及长明细分页，不宣称测试过并发发布换页。

一次整行文本定位因 DOM 空白差异未匹配，改为唯一时间定位成功；浏览器空字符串 fill
没有清空受控输入，使用全选/Backspace 后确认清空。上述是验收工具交互问题，不更改
产品代码来迁就自动化。没有读取 Cookie、Token、密码或服务端配置行。

根代理补执行 `pnpm --filter @kunlun/web test -- src/features/data-quality/market-quality-evidence-panel.test.tsx`。
该脚本没有按预期把 `--` 后的路径作为 Vitest 筛选，实际运行了 web 包全部 57 文件、
233 项测试，均通过（3.61 秒）。这是一次参数导致的意外验证范围扩大，未重复运行；
仅可称 web 包测试通过，不能称仓库全套通过。

## 限制

Terra Max 独立检查当前 19 个容器与部署前后元数据、实际 server 挂载、worker 镜像
及 overlay，没有剩余运行接线阻断；18 个非 server 容器的 ID、镜像、StartedAt、
RestartCount、state、health 均一致。该元数据审核不能单独证明容器内部没有执行 SQL，
只支持未启动新的迁移/采集容器及基础服务未重启；执行入口与无网络导出边界另有上述证据。
后续再次运行 exporter 前应核对镜像 ID，不把可变 local 标签当永久版本标识。

这关闭了已记录行情拒绝/过滤证据的公开卷接线缺口。真实 REJECTED 非空、公开零条与
禁止访问状态没有在本环境制造样本；离线/组件测试与生产样本验证分别记录。
完整官方日历、生命周期、全市场缺口判定、实际日历迁移与正式墙钟门禁仍独立跟踪。
