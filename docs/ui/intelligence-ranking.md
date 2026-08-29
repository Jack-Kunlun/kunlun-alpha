# P6-N05 股票 Intelligence Ranking

## 节点边界

P6-N05 提供可版本化、可复现、可解释的股票研究排序。节点包含：

- `quant_core.ranking` 纯领域实现；
- 版本化 `RankingSpec`、输入指纹与稳定快照 ID；
- 基于 `available_time <= as_of` 的点时特征选择；
- 横截面标准化、方向处理、缺失策略与逐项贡献；
- quant-engine 发布/读取 API 与不可变快照持久化；
- Web 排名、筛选、状态、空态和证据展示。

正式 Web 运行时只读取 Nest 控制面代理的 quant-engine 已发布快照；没有已发布快照时展示明确空态，不回退到测试 fixture。设置 `KUNLUN_QUANT_STATE_DIR` 后，每个已验证快照以 `snapshotId` 命名并原子写入本地持久卷；进程启动会重新验证全部文件，损坏或 ID/内容冲突时 fail closed。未设置该变量的测试进程仍使用隔离的内存仓库。

脱敏验收快照由 `quant_core.ranking` 使用固定输入生成，Python parity 测试逐字段核对 Web JSON 与核心输出。禁止手工修改分数、贡献、方向、版本或指纹；更新输入后必须重新生成整个快照。

## RankingSpec v1 语义

- 权重使用整数基点，合计必须为 `10000`；分值和贡献也使用整数基点。
- 原始数值使用 Python `Decimal`，不使用二进制浮点参与领域计算。
- `HIGHER_IS_BETTER` 与 `LOWER_IS_BETTER` 明确控制标准化方向。
- `RENORMALIZE` 将缺失权重按原配置比例分配给可用特征。
- `ZERO` 保留缺失项权重并记录零贡献。
- `EXCLUDE` 将缺失指定特征的证券排除，并保留原因。
- 覆盖率低于 `minimum_coverage_bps` 时不进入排名。
- 同分时依次按覆盖率降序和标准证券 ID 升序确定稳定顺序。

RankingSpec 指纹包含特征标签与声明顺序，因为二者都会改变解释输出。输入指纹包含 RankingSpec 指纹、as-of、证券、点时特征值、可用时间和来源。`generated_at` 必须不早于 as-of，但不参与快照身份，因此相同点时输入在不同执行时间仍得到相同快照 ID。

## 展示与安全约束

Web 只过滤已经生成的快照，不在浏览器中重算分数或名次。页面持续展示：

- as-of、生成时间和 `Asia/Shanghai` 显示；
- RankingSpec、算法版本、快照 ID 和输入指纹；
- 原始值、标准化分、配置/有效权重、贡献、来源和可用时间；
- 缺失和未入榜原因；
- “研究排序，不构成收益保证”与快照来源标识。

服务端使用 URL 的 `asOf` 选择不晚于该时点的已发布快照。`instrument` 仍不是 Ranking 查询条件，页面会明确提示该上下文未应用，避免把全市场快照误解为单一证券结果。

P6-N05 不产生 `Signal`、`OrderIntent` 或订单，不包含券商、QMT、实盘凭据或任何真实下单路径。
