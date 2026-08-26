# P5-N03 实时特征计算

在线特征引擎消费行情或领域事件，通过 Redis 兼容原子端口生成事件时间窗口特征。本节点不引入真实 Redis 客户端；生产适配器必须使用 Redis Lua、事务或等价原子 compare-and-set 实现同一协议。

## FeatureSpec 与时间语义

- FeatureSpec.window_definition 必须使用 EVENT_TIME_TUMBLING 加 ISO 8601 时长，并与 OnlineWindowPolicy.size 完全一致；不支持的窗口定义失败关闭。
- 窗口归属只使用 event_time，固定为半开区间。
- available_time 表示事件可用于决策的时刻，`OnlineFeatureEvent.ingest_time` 表示受信任的在线到达/接收时刻；payload 内的 `ingestTime` 仍是源记录 provenance，二者不要求相等。processing_time 由引擎调用上下文提供，只用于执行、TTL、单调时钟和审计，不能由 payload 内的 `processingTime` 推进。
- 每个 stream 持久化 last_processing_time；处理时间倒退失败关闭。重算前再次确认所有窗口输入在 processing_time 已可用。
- watermark 等于已接受事件的 max_event_time 减 allowed_lateness，processing_time 不得推进 watermark。
- event_time 早于已有 watermark 的事件写入拒绝审计，不参与重算；允许迟到范围内的乱序事件重算其事件时间窗口。
- MAX_INPUT_AVAILABLE_TIME 取窗口输入最大可用时间；SOURCE_AVAILABLE_TIME 仅允许一个输入；MATERIALIZATION_TIME 使用本次 processing_time。
- market. 合同只能由 MARKET 来源事件承载，domain. 合同只能由 DOMAIN 来源事件承载。
- 合法事件先进入 accepted evidence stream。计算器通过公共 `OnlineCalculationResult` 显式返回 `MATERIALIZED`、`PENDING` 或 `TERMINAL`：缺少当前 FeatureSpec 声明的输入合同时返回 `PENDING`；输入已完整但业务计算得到拒绝或不可用结果时返回 `TERMINAL`，并携带稳定的 status/reason；只有数值结果返回 `COMMITTED`。三种结果都保留 accepted event/receipt，只有 `COMMITTED` 写在线值；`TERMINAL` 会移除同窗口旧值，后续新事件仍可触发新的计算。终态另存带完整 input lineage、原始 processing_time 和 retain_until 的 HMAC 状态记录，加载时由受信计算器重算；重复投递、CAS 回读和进程重启因此返回相同 status/reason。

## 原子状态、幂等与恢复

单一 stream state 原子保存 registry、FeatureSpec、计算器工件、窗口 policy、revision、last_processing_time、watermark、活动输入、event receipt、在线值 lineage 与拒绝审计。

同 event_id 与相同内容在 replay horizon 内返回 DUPLICATE，不增加 revision；同 event_id 不同内容属于冲突。每个 receipt 必须与以下证据双向一致：

- ACCEPTED 对应保留事件或在线值 input lineage；
- REJECTED 对应 reason 和 content checksum 相同的 rejection；
- value 的 input checksum 由完整 event lineage 重算。

每次 CAS 成功后必须 load 回读并逐字段比较。新进程使用相同完整性服务和 store 可恢复 watermark、去重收据与活动窗口输入。CAS 冲突使用固定上限重试，不能覆盖并发提交。

ACCEPTED receipt 在 replay horizon 内同时保留完整 accepted evidence，并记录首次转换的 processing_time 与 state_revision；即使活动窗口输入和已过期在线值被裁剪，receipt 仍有可验证证据。终态会把完整 input lineage 对应的较早 receipt 延长到本次终态的 retain_until，避免终态审计证据提前过期。加载时必须重新验证 canonical window、完整 transition 输入集、available/ingest 可见性和 policy 派生 replay horizon。更晚到达的 duplicate 会以 CAS 原子推进 last_processing_time，不能让后续新事件使用更早 processing_time。

## 完整性 envelope

Redis state 使用 OnlineStateEnvelope 保存 state、绝对 retain_until 与完整性 tag。仓库提供 HmacOnlineStateIntegrity，但密钥必须来自批准的 secret storage，不得写入代码、日志、fixture 或 Redis。生产环境还必须用 Redis ACL 和最小权限限制写者。

HMAC 用于发现外部状态损坏或越权改写；普通 checksum 仅用于 lineage 和可重复性，不能代替认证。HMAC 密钥持有者属于受信状态写入边界，但无权替换计算器工件。OnlineCalculatorTrust 根据 FeatureSpec 直接解析 OnlineCalculatorArtifact 的 identity 与 executable，process API 不接受调用方传入的任意 callable。加载状态时会用该受信工件和 accepted evidence 重算每个在线值。identity 进入 stream key 与 state；工件升级会切换新 stream，旧状态不会被新工件静默重算。

## TTL、降级与 replay horizon

stale_at 和 expires_at 以 FeatureSpec availability policy 得出的 available_time 为锚：

- as_of 早于 available_time：MISSING；
- as_of 早于 stale_at：FRESH；
- stale_at 不晚于 as_of 且早于 expires_at：DEGRADED_STALE，返回最后值；
- as_of 不早于 expires_at：EXPIRED，不返回值；
- 没有在线值：MISSING。

到达时已经超过值 TTL 的事件只写拒绝审计，不执行计算。receipt/rejection 使用独立 replay_horizon，且 replay_horizon 必须覆盖 ttl 加 allowed_lateness。envelope 明确携带 retain_until；生产 Redis 只能用 Redis 服务端或另一受信时钟在 retain_until 之后物理删除整个原子 state。查询 as_of 只影响可见性，load/read 绝不触发物理删除。值过期不等于去重和审计立即失效，避免物理 TTL 后重复事件重新提交。

replay horizon 结束后，历史 event_id 可以按明确的有限幂等窗口重新进入；这是受控生命周期语义，不宣称永久去重。长期不可变历史属于 P5-N04 存储范围。

## 边界与安全

- 只定义 Redis 兼容端口、HMAC 完整性边界和线程安全内存 fake，不连接真实 Redis。
- 不实现 P5-N04 ClickHouse 历史特征存储和 as-of 历史查询。
- 不实现策略、订单、券商或 QMT 路径。
- Phase 0 至 Phase 6 的在线特征只能提供研究和决策数据，不能触发真实订单。
