# P5-N02 批量特征计算

批量引擎只实现确定性的领域计算和持久化端口，不包含真实 ClickHouse、Parquet、在线特征或交易适配器。

## 输入与 PIT 边界

- 分区固定为半开区间 [start, end)，且 end 不晚于 decision_time。
- PartitionReadRequest 分开声明 SOURCE_CONTRACT 与 FEATURE_DEPENDENCY，来源返回后逐行复核分区、available_time、版本和上游特征指纹。
- 每个必需输入都有 COMPLETE 或 COMPLETE_EMPTY manifest 项；缺项、额外项、计数或 checksum 不一致均失败关闭。
- RegisteredFeature 将运行绑定到 P5-N01 registry 的 namespace_id、可信 head、FeatureSpec 指纹和算法版本。
- 输入 checksum 包含来源类型、不可变 snapshot、完整 manifest 和全部 canonical rows；Unicode 保持码点级语义，不做隐式归一化。

## 计算器信任边界

Python callable 无法被本进程可靠沙箱化。计算器是受信任纯计算边界，而不是被引擎证明无法访问外部状态的沙箱。引擎仅向它传递冻结后的输入 tuple，不传 source 或 store，并执行以下约束：

- 实现指纹与算法版本进入 run identity 和元数据；
- 计算器必须显式提供由构建流程产生的稳定 CalculatorIdentity 工件摘要；运行时不根据 Python 函数名称、repr、闭包或全局状态猜测身份；
- 相同输入在写入前计算两次，结果 checksum 不同则失败；
- 输出只能引用本轮输入 ID，引用、时序、PIT、重复 identity 和 per-row lineage 均由引擎复核；
- MATERIALIZATION_TIME 在 batch 中被拒绝；
- DECIMAL 输出规范化，-0、0.0 统一为 0，并去除无业务含义的尾随零。

计算器实际是否在数学上使用了其声明的输入仍属于受信任实现与代码审计责任，文档不对此作能力隔离承诺。

## 提交、重放与恢复

输出与 checkpoint 端口必须提供线性化、不可变的 compare-and-set 语义，并返回 CREATED、EXISTING_SAME 或 CONFLICT。所有结果都必须携带实际持久实体，引擎不会把布尔 no-op 推断为成功。

1. 有 checkpoint 时，输出必须存在；引擎从持久 rows 重算 output checksum、逐行血缘、输入 checksum、manifest、registry、分区、snapshot 和完整 result checksum，并重新双算当前候选逐字段比较，之后才返回 REPLAYED。
2. 无 checkpoint 时，先双算并本地重验候选，再提交输出；CONFLICT 立即失败且不写 checkpoint。
3. 输出创建后进程崩溃会留下 orphan output。重跑获得 EXISTING_SAME，重验后补 checkpoint 并返回 RECOVERED。
4. checkpoint 冲突、checkpoint 存在但输出缺失、持久内容被篡改或适配器返回无效提交结果均失败关闭，不得报告成功。
5. output 与 checkpoint 提交后都必须通过 get 回读并再次复核；仅返回 CREATED 或 EXISTING_SAME 而没有真实持久实体属于完整性错误。

生产适配器必须用数据库唯一约束、事务或等价原子条件写实现上述协议；内存 fake 使用锁提供同进程线性化语义。

FEATURE_DEPENDENCY 输入还必须由 FeatureDependencyResolver 解析到不可变上游结果，并核对 run ID、FeatureSpec 版本/指纹、output checksum 与 result checksum；只有字符串形式的 provenance 声明不能通过。

## 可追溯元数据

每次结果保留 registry namespace/head、FeatureSpec 与算法指纹、计算器实现指纹、分区起止、decision/data cutoff、来源 snapshot、manifest/input/output/result checksum、每行输入 lineage 和可用时间。新的算法、来源版本、manifest 或输入会产生新的 run ID，不覆盖历史结果。

## 非目标与安全

- 不实现 P5-N03 在线特征计算。
- 不连接真实 ClickHouse、Parquet、券商、QMT 或真实账户。
- Phase 0 至 Phase 6 的特征引擎只能产出研究数据，不能生成或发送真实订单。
