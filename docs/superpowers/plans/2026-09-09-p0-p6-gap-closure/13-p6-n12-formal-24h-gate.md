# 计划 13：P6-N12 正式 24 小时墙钟门禁

## 目标

在计划 12 的冻结候选版上，从零执行一次全新 UUID 隔离、连续 24 小时的模拟耐久与恢复门禁，
并由独立只读检查器给出正式 `QUALIFIED`。

## 已有证据与边界

- R4 已证明累计约 24 小时有效运行和四类场景通过，但独立结论是
  `INVALID / CLOCK_ELAPSED_MISMATCH`。
- R4 不得修改、拼接或追溯改判；它只能作为条件接受的工程证据。
- 正式门禁不等于实盘资格。P0–P6 始终禁止真实券商、真实账户和真实订单。

## 启动前硬预检

1. 候选 acceptance manifest 完整且源码/镜像/配置/迁移/检查器摘要无漂移；工作区保持干净。
2. 使用全新随机 UUID 数据库、进度文件和报告文件；路径不复用历史运行。
3. 宿主禁止自动睡眠；UTC 与单调时钟基线一致，时钟回拨/跳变检查通过。
4. PostgreSQL、Redis 和依赖服务 healthy，连接基线和 restart count 已记录。
5. 无其他 endurance runner、未知 paper 进程或会写同一证据域的任务。
6. 隔离数据库 marker、schema、权限和清理方案通过；任何失败均不得启动 runner。

## 运行与监控

- 从零运行 24 小时，覆盖 `PROCESS_RESTART`、`DUPLICATE_MESSAGE`、`DATABASE_OUTAGE`、
  `CACHE_LOSS`。
- 监控只做小时级只读 heartbeat；不得编辑进度/报告、重启 runner 或修改候选。
- 记录 wall UTC、monotonic elapsed、服务 restart count、连接数、场景计数和摘要链。
- 任一中断、时钟不一致、证据漂移或资源泄漏立即判失败；不续跑、不拼接旧时长。

## 正式验收

- runner 正常结束，四类场景均通过，末端连接/租约/未决消息为零或符合固定契约。
- UTC 墙钟差、单调计时和报告 `elapsedWallSeconds` 在候选已哈希检查器固定的 300.0 秒容差内
  一致；运行人员不得临时调整或解释该值。
- sourceVersion、数据库 UUID、进度/报告摘要和候选 manifest 精确绑定。
- 独立只读检查器使用 `--expected-source-version` 精确绑定候选，从候选不可变镜像/制品运行，
  exit 0 且返回 `QUALIFIED`、`gateSatisfied=true`，无 warning/ignored failure。
- 生成最终证据包后停止监控；经 Sol 独立审查无阻断，才关闭 P6-N12 和 Phase 6。

## 失败处理

保留原始证据并标记具体 failure code。代码/配置缺陷返回对应开发计划；环境中断在重新满足
全部预检后创建新的 UUID 从零重跑。不得降低 24 小时标准，也不得使用 R4 抵扣时长。
