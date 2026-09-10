# 计划 12：冻结候选版与原位验收

## 目标

在功能缺口和门禁实现加固全部关闭后，冻结一个可复现候选版，并只更新现有 Docker 项目，
为正式 24 小时门禁提供唯一源码、镜像、配置和数据库基线。

## 前置依赖

- 计划 00–11 全部通过，且没有未解决的安全、数据完整性或阶段退出发现。
- 工作区所有文件已经归属；已取得明确提交授权，并形成工作区干净的候选 commit。dirty tree
  只能用于计划 00 的归属审查，不能成为正式候选。
- 没有运行中的采集迁移、手工回放或旧耐久进程。

## 执行步骤

1. 冻结 commit/source tree 摘要、依赖锁、迁移 checksum、镜像 digest 和非秘密配置摘要。
   manifest 还必须绑定 `endurance_evidence.py`、`check-paper-soak-evidence.py`、报告 schema、
   最低 24 小时资格和 `MAX_CLOCK_DRIFT_SECONDS=300.0`。
2. 按受影响节点运行最终 bounded checks；只有失败或公共契约/迁移影响才扩大验证范围。
3. 在专用临时数据库执行所有 destructive migration/recovery 测试并清理临时数据库。
4. 对正式 PostgreSQL/ClickHouse/卷做只读前置快照；迁移和必要回填另按受控步骤执行。
5. 构建不可变镜像并原位替换必要服务；不使用 `down`，不删卷，不重启无关数据服务。
6. 验证健康、restart count、迁移 ledger、runtime reader、采集停态、API/UI 关键路径和回滚镜像。
7. 生成候选 acceptance manifest；此后任何源码、配置、迁移或镜像变化都使候选失效。

## 验收标准

- sourceVersion、干净 commit、镜像、迁移和配置摘要形成单一不可变清单；候选 dirty 项为 0。
- `reliability.py`、`endurance_evidence.py`、`run-paper-soak.py`、测试与 runbook 的 24 小时基线
  完全一致，23 小时拒绝和 24 小时 durable PostgreSQL 资格测试来自该候选。
- 独立检查器从候选不可变制品运行，或其文件 SHA-256、schema、容差和版本被 manifest 单独绑定。
- P1、P3、P4、P6-N13 的数据、运行和页面证据均来自该候选或明确兼容的不可变数据版本。
- 回滚只替换目标服务/镜像，不删除数据库、raw 或公开证据卷。
- 所有持续任务在正式门禁前处于已知稳定配置；不得在门禁中修改候选。
- P0–P6 仍为 `PAPER_ONLY`，静态和运行探针均无真实 broker/order path。

## 停止条件

出现 dirty 漂移、镜像摘要不一致、迁移 ledger 异常、数据库权限漂移、无归属进程或需要修改
代码时，候选冻结失败并返回对应计划修复；不得带病启动 24 小时门禁。
