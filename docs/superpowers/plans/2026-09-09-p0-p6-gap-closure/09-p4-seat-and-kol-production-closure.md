# 计划 09：P4 席位与 KOL 生产闭环

> 本文件是节点组合索引，不可作为单一开发任务派发。每个开放节点开工前必须建立独立
> Execution Contract，并按 P4 前置依赖逐一审核。

## 目标

逐节点复验 P4 已有领域逻辑，并补齐真实龙虎榜采集、持久媒体证据、可信 Claim 审核、特征
物化和持久工作台投影；始终把 KOL Claim 与券商确认成交严格分离。

## 当前状态

- P4-N01/N02/N04/N05/N06：实现、提交和节点测试存在；作为下游开工前回归基线。
- P4-N03：SeatListProvider 仅 Protocol，缺真实 provider/任务入口。
- P4-N07：媒体管线为 fake/in-memory，缺对象存储及受控 ASR/OCR adapter。
- P4-N08：候选/CAS/审核服务存在，但抽取端为 fake/in-memory，审核默认 `DenyAll`。
- P4-N09：绩效/共识算法存在，但缺版本化持久物化任务、调度和重放。
- P4-N10：页面/API 存在，生产使用空 repository，本地仅 `LOCAL_PREVIEW`。

## 节点计划

1. **P4-N01/N02 逐节点复验：** 固定稳定 seat_id、有效期、别名黄金集、低置信度审核与错误
   合并回滚；两个节点分别审核。
2. **P4-N03 真实龙虎榜采集：** 实现受限 provider adapter、不可变 raw、修订、买卖分项对账、
   checkpoint、错误分类、PostgreSQL 写入和调度。净买入不得替代明细。
3. **P4-N04/N05/N06 逐节点复验：** 在 P1 日历/行情与真实席位样本上验证 PIT、停牌/涨跌停、
   Decimal、小样本、组合爆炸限制和 Claim 非 Trade 语义。
4. **P4-N07 持久媒体证据：** 引入对象清单、时间码/坐标、质量分、删除/版权策略、CAS checkpoint
   和受控 ASR/OCR adapter。选择新的外部服务/依赖必须先获用户批准。
5. **P4-N08 Claim 生产审核：** 持久候选与 revision 链。当前没有可信 HTTP 身份提供方，先以
   `BLOCKED_DECISION` 等待用户批准身份来源、角色/权限、服务间信任和审计 actor；此前保持
   `DenyAll`，不得依赖客户端 Header/`AllowAll`。批准后再接审核队列和拒绝审计；否定、
   条件句、引述和时间指代失败关闭。
6. **P4-N09 特征物化：** 只使用决策时可见的 Claim、行情和日历，生成版本化、持久的
   attention/consensus/claim score；补 checkpoint、调度、重放和时间可见性约束，删除或修订
   内容不回填历史。
7. **P4-N10 持久工作台：** 用生产 projection 替换 `LOCAL_PREVIEW`/空仓库，显示版本、样本量、
   数据截止时间、证据等级和 Claim 标签，并完成认证 E2E。P4-N08 的可信身份决策未获批、
   节点未关闭前不得启动认证 E2E，也不得用 Header、`AllowAll` 或测试身份替代生产信任边界。

## 验收与顺序

- 严格按 N01→N10 的前置依赖，一次执行和提交一个节点。
- 真实数据来源、使用许可、删除状态和证据保留政策完整；未经授权不采集。
- 低置信度别名/Claim 不自动进入高等级特征；审核权限保持最小化。
- 所有收益与绩效使用可交易时点和 PIT 数据，不使用未来修订；金额用 Decimal。
- P4 阶段出口包括真实适配、持久化、恢复、特征物化和 API/UI 证据，不以 fake 或本地预览替代。

## 验证范围

逐节点领域测试、黄金集、PIT/精度测试、真实 PostgreSQL/对象存储 fixture、contracts/类型/构建、
权限测试、fake 自动测试和受控非生产真实输入 E2E。
