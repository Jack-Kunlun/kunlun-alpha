# P4-N03 龙虎榜采集与规范化口径

## 边界

`SeatListProvider` 只定义 provider adapter 边界，当前节点不实现网络访问。provider 返回的
`RawSeatListRecord` 保存原始字节、SHA-256、供应商证券字段、席位原名、上榜原因、买卖分项、
供应商净额、时间字段和 revision 链；raw 对象是 frozen 且旧 revision 永不覆盖。

证券代码只在 adapter/normalize 边界转换为内部 `######.SH`、`######.SZ` 或 `######.BJ`。
金额只接受 `Decimal` 或精确十进制字符串，买卖额必须非负，规范化净额严格计算为
`buy_amount - sell_amount`。供应商净额不一致、负金额或浮点金额进入 rejected/quarantine，
不会被修正后静默接受。

## 批次与修订

`SeatCollectionRequest.request_fingerprint` 覆盖 `batch_id`、交易日、决策时间、source、
source version、route 和 checkpoint token。`SeatProviderBatch.batch_fingerprint` 覆盖 source、
version、checkpoint 和按确定性顺序排列的完整 immutable raw record fingerprints。每次重试
必须先 fetch 并校验 provider batch，再按 route + `batch_id` 比较 request/batch fingerprint；
只有完全一致才返回已持久化结果，任何 PIT 或 provider 内容变化都冲突，不能仅凭 batch ID
返回旧结果。

`SeatCollectionJob` 完成全部 raw/revision/normalization 校验后一次性提交。provider 失败或
不可接受的 revision 冲突不会推进 route-scoped checkpoint，也不会留下部分 normalized trade。
revision identity 至少是 `(source, revision_id)`；previous revision 必须是同一 identity key
的当前 latest，stale fork 以 `stale_previous_revision` 拒绝。缺前序和乱序前序保留 raw，
分别以 `missing_previous_revision`、`out_of_order_revision` 进入 rejected；合法 revision 使用
新的 `revision_id` 和 `previous_revision_id` 追加历史。provider batch 在进入 collector 前会对
完全相同 raw record 去重，并拒绝冲突 duplicate。

`SeatRepository` 是 collector 依赖的 Protocol。`InMemorySeatRepository` 仅是测试 adapter，
使用 `RLock` 并在锁内基于最新状态重新校验；`PostgresSeatRepository` 使用
`seat_collection_migration.sql` 定义的最小 durable 表，在一个数据库事务中提交 raw bytes/hash、
revision state、normalized/rejected、batch fingerprints 和 route checkpoint。事务失败 rollback，
新 repository instance 可按 route 读取历史 batch 与 checkpoint。

## 席位决策与时间

只有 P4-N02 `ResolutionStatus.AUTO` 才能生成 `NormalizedSeatTrade`/`Trade`。`REVIEW` 和
`REJECT` 都保留 raw、候选 seat_id、候选 alias evidence 和机器可读拒绝原因。resolver 的
`decision_time` 来自 job request；因此 available time 晚于决策时间的 raw 或未来可用 alias
不会泄漏到规范化事实。

标准化 Trade 保留 `listing_reason`、内部 instrument、trade date、精确 buy/sell/net、
raw_record_id、provider evidence 和选中 alias evidence。它是龙虎榜公开事实，不是 broker
订单，也不包含真实账户、凭证或下单路径。

## PostgreSQL durable boundary

seat tables are migration version 2 in the existing
`data_worker_schema_migrations` ledger. Production data-worker startup uses
`data_worker.storage.migrations.apply_data_worker_migrations` through
`PostgresFundStorage.migrate`; `PostgresSeatRepository.initialize` is only a
test helper and does not parse SQL by semicolon.

Each commit transaction acquires `seat-route:{route_key}` first, then the
lexicographically sorted `seat-raw`, `seat-revision`, and
`seat-revision-key` advisory transaction locks. Only after those locks does it
read the batch, route checkpoint, raw revision state, and normalized/rejected
content. A batch retry is idempotent only when the full immutable content and
fingerprints match. The route checkpoint is updated with an expected-previous
checkpoint CAS; stale workers cannot move it backwards.
