# 模拟交易运行恢复与耐久门禁

本文定义模拟账户与模拟执行链路的故障恢复、耐久证据和验收边界。所有流程仅允许
`PAPER_ONLY` 执行能力，不连接券商、不读取真实账户凭据，也不产生可执行的真实订单。

## 运行不变量

- 消息必须先持久化再确认，持久化不可用时失败关闭。
- 每个事件使用稳定的 `event_id` 幂等；同一 ID 的不同内容视为冲突。
- 事件按连续序号和摘要链保存，恢复时逐条验证，损坏时停止恢复。
- 缓存只保存可丢弃投影；账簿、订单和成交事实必须来自持久事件。
- 并发写使用流头摘要比较并交换，冲突最多重试两次，不允许无限重试。
- 恢复后仍须完成风险决策、执行状态和结算账簿对账，存在差异时禁止继续提交模拟订单。

## 故障矩阵

| 故障             | 注入方式                         | 通过条件                                   |
| ---------------- | -------------------------------- | ------------------------------------------ |
| 进程重启         | 使用同一持久事件流创建全新运行时 | 摘要链通过校验，事件数和事件 ID 完整恢复   |
| 重复消息         | 重放相同 `event_id` 和内容       | 返回 `DUPLICATE`，持久流只增加一次         |
| 数据库短暂不可用 | 在追加前关闭持久存储             | 请求失败关闭且无写入；恢复后重试只应用一次 |
| 缓存丢失         | 清空全部投影缓存                 | 从持久流重建的事件 ID、数量和流头摘要一致  |

`FaultInjectablePaperStore` 是故障测试替身，不是持久化适配器。正式运行使用
`PostgresPaperEventStore`，每次操作重新建立受限连接，并通过流头行锁完成比较交换。故障
harness 只允许操作名称以 `kunlun_paper_endurance_` 开头且带 UUID 后缀的隔离数据库；它不会
停止或禁用主业务数据库，也不会接触券商、真实账户或真实订单路径。每次运行必须创建全新
数据库；harness 会在 PostgreSQL database catalog metadata 中写入本次运行的随机 ownership marker，所有
禁用连接、恢复和删除动作都会先核验该 marker。marker 不进入命令行、日志、报告或进度文件。
管理 DSN 的 `current_database()` 还必须位于 `kunlun_paper_endurance_` 命名空间之外，不能把旧的
耐久数据库误当作控制库。

正常持久化读写遇到 `OperationalError` 或 `InterfaceError` 时，适配器会以 100 ms、200 ms 的
有界退避最多尝试 3 次；全部失败后仍以 `PersistenceUnavailableError` 失败关闭。追加操作的整段
事务可以安全重试：`event_id` 唯一约束会把“提交成功但确认丢失”的重试识别为 `DUPLICATE`，
不会产生第二次持久变更。故障注入的管理连接及 `ALLOW_CONNECTIONS=true` 恢复路径则在 30 秒
恢复窗口内有界重试；每次重连仍重新核验控制库和本次 ownership marker，不能绕过隔离保护。

## 工程快速检查

虚拟时钟用于快速验证 72 个逻辑小时内的故障矩阵。它只产生工程证据，不能替代正式
耐久验收：

```bash
uv run --package paper-core python scripts/run-paper-soak.py \
  --clock-mode virtual \
  --duration-hours 72 \
  --output /tmp/kunlun-paper-endurance-virtual.json \
  --allow-engineering-evidence
```

预期 `qualification` 为 `ENGINEERING_EVIDENCE_ONLY`。不传
`--allow-engineering-evidence` 时，非正式资格报告以退出码 2 结束，避免被 CI 误判为正式
通过。

## 墙钟耐久证据与正式门禁

不传 `--store postgres` 时，runner 使用 `FaultInjectablePaperStore`，即使墙钟运行满 24
小时也只能形成 `TEST_DOUBLE` 工程证据。正式运行必须连接具备建库、切换连接许可和终止
隔离数据库会话权限的 PostgreSQL 管理数据库。DSN 只通过环境变量注入，不得写入命令参数、
日志或报告：

```bash
export KUNLUN_PAPER_ENDURANCE_ADMIN_DSN='postgresql://USER:PASSWORD@HOST:PORT/postgres'
uv run --package paper-core python scripts/run-paper-soak.py \
  --store postgres \
  --clock-mode wall \
  --duration-hours 24 \
  --tick-seconds 60 \
  --progress-output /var/tmp/kunlun-paper-endurance-progress.json \
  --output /var/tmp/kunlun-paper-endurance-wall.json
```

runner 默认生成带不可预测 UUID 的全新隔离数据库；显式传入的名称也必须带合法 UUID 后缀，
已存在的同名前缀数据库一律拒绝复用。数据库短断场景先核验本次 ownership marker，再将该隔离
数据库设为拒绝新连接并终止它的既有会话；追加必须失败关闭。`finally` 路径恢复连接许可前会
再次核验 marker，随后使用新连接验证数据库已恢复。主业务数据库名称不满足前缀和 UUID 保护，
不能成为故障目标。
进度文件每轮原子更新，正式报告只在整段运行结束后生成；报告同时记录 Python 堆内存起止与
峰值、隔离数据库起止连接数，以及当前 Git 提交与关键运行源码的 SHA-256 指纹。正式资格
要求结束连接数为零；审核时必须用源码指纹确认报告对应的精确代码状态。

正式资格必须由接入真实持久化适配器的 runner 执行，并同时满足以下条件：

1. `clockMode` 为 `wall`。
2. 请求时长不少于 24 小时。
3. 实际单调墙钟时长达到请求时长。
4. 四种故障场景每次迭代均为 `PASS`。
5. `executionCapability` 为 `PAPER_ONLY`。
6. `evidenceScope` 为 `DURABLE_ADAPTER`，不能是 `TEST_DOUBLE`。

虚拟时钟、测试替身、低于 24 小时、缺失场景或任一失败都不能取得正式资格。报告包含版本、
证据范围、起止时间、实际时长、迭代数、资格状态和证据摘要；审核时需保留原始 JSON 与
运行日志。适配器和快速 PostgreSQL 故障矩阵通过不等于 24 小时 P6 门禁通过；墙钟报告生成前，
P6-N12 继续保持待验收。

截至 2026-09-05，第四轮已完成累计 24 小时有效运行且四类场景全部通过，但宿主睡眠导致
独立检查器返回 `CLOCK_ELAPSED_MISMATCH`。项目负责人已将本轮作为开发阶段证据条件接受，
允许继续非实盘与模拟态开发，并把最终连续 24 小时墙钟门禁延期到候选版本冻结后执行。
该决定不把第四轮标记为 `QUALIFIED`，也不关闭 P6-N12 或 Phase 6；证据与边界见
[`2026-09-05-p6-n12-r4-conditional-acceptance.md`](../reviews/2026-09-05-p6-n12-r4-conditional-acceptance.md)。

24 小时资格只用于 P6-N12 退出和后续模拟开发，不构成实盘资格。任何真实账户或真实订单
能力启用前，仍须取得独立、全新 UUID 隔离环境下连续 72 小时且全部故障场景通过的正式
耐久证据，并同时满足 Phase 7 的监管、券商、环境隔离、独立风控、对账、Kill Switch 和人工
批准门禁。基线调整记录见
[`2026-09-03-p6-n12-duration-baseline-decision.md`](../reviews/2026-09-03-p6-n12-duration-baseline-decision.md)。

可在不连接证据数据库、不发送信号且不改写进度或报告文件的前提下运行只读检查器：

```bash
uv run --package paper-core python scripts/check-paper-soak-evidence.py \
  --progress /var/tmp/kunlun-paper-endurance-progress.json \
  --report /var/tmp/kunlun-paper-endurance-wall.json \
  --expected-source-version 'git:COMMIT;source-sha256:DIGEST'
```

检查器对进行中的合规运行返回 `IN_PROGRESS` 和退出码 3；只有报告摘要、墙钟时长、四类故障、
资源释放、执行能力、持久化范围、源码指纹及进度/报告绑定全部通过时才返回 `QUALIFIED` 和
退出码 0。`INVALID` 使用退出码 2。进行中没有最终报告是正常状态，不能据此宣称门禁通过；
可预测的证据库名称、陈旧进度或已退出进程均失败关闭。检查器没有 DSN 参数，也不会停止门禁
进程、查询或修改 PostgreSQL。

若进程在数据库连接被禁用的极短窗口内遭遇不可捕获终止，不得按数据库名前缀手工执行
`ALTER DATABASE`、`DROP DATABASE` 或拼接中断前后的时长。ownership marker 只由本次 harness
保存在进程内，无法由报告或命令行重建；应将该数据库交给管理员按 catalog marker 做人工隔离
清理，然后使用新生成的数据库重新开始完整 24 小时 P6 运行。

此前固定名称运行的 `kunlun_paper_endurance_p6n12` 属于旧源码运行，不是新基线下的验收证据；
调整后必须启动全新的 24 小时墙钟运行，使用新的 UUID 隔离数据库和证据文件，不能续用或
拼接旧运行时长。历史轮次继续按原始请求时长和实际结果保留；任何已失败报告都不得因本次
基线调整追溯改判为通过。

## 恢复步骤

1. 停止新的模拟订单入口并保持执行链路断开。
2. 确认持久存储可读写，记录故障窗口与最后已确认事件 ID。
3. 创建空缓存和新运行时，从持久事件流开始完整回放。
4. 校验连续序号、事件唯一性、前序摘要和事件摘要；任一失败立即停止。
5. 重建模拟账户、订单、成交、现金和持仓投影。
6. 执行风险决策、执行状态与结算账簿三方对账，并记录全部差异。
7. 仅在差异为零且健康检查通过后恢复模拟订单入口；否则继续保持失败关闭。

## 告警与留证

- 持久化不可用、摘要不一致、重复 ID 冲突、并发重试耗尽和对账差异必须产生高优先级告警。
- 日志不得包含凭据、真实账户标识或未脱敏的生产数据。
- 耐久报告是一次运行证据，不应覆盖历史报告；文件名或外部归档元数据应包含运行时间。
- 任何真实券商适配器、真实订单入口或真实账户凭据一经发现，应立即停止流程并上报。
