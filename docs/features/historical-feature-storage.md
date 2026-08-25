# 历史特征存储

P5-N04 在 ClickHouse 中保存不可变、可追溯的特征修订，并通过
`FeatureHistoryRepository.query_as_of` 提供批量时间点查询。该能力服务于研究和
回测，不包含数据集构建、研究环境或任何交易执行能力。

## 数据语义

- 唯一特征身份由 `namespace_id`、`feature_name`、`feature_version` 和
  `feature_fingerprint` 共同确定，查询必须精确匹配，禁止跨版本拼接。
- 逻辑值由特征身份、`entity_id` 和 `event_time` 确定；每次更正写入新的
  `revision_id`，历史行不得覆盖或删除。
- `event_time` 是业务事件发生时间，`available_time` 是该修订首次可用于决策的
  时间，`processing_time` 是系统完成处理的时间。系统强制
  `event_time <= available_time <= processing_time`。
- `as_of` 查询只读取 `available_time <= as_of` 的候选行，再从每个逻辑值中选择
  可见顺序最大的修订。`available_time == as_of` 视为可见。
- 同一 `revision_id` 出现不同载荷，或同一逻辑值在相同可见时间和处理时间存在
  多个不同修订时，查询失败关闭，不猜测正确结果。
- 每行保存 `value_type`、`calculator_implementation_fingerprint`、
  `input_manifest_checksum` 和逐行 `input_checksum`。这些字段与运行 ID、来源版本和
  注册表引用共同生成 `lineage_checksum`；任一字段被单独修改都会在读回时失败。
- 记录只能由 P5-N02 的 `MaterializedFeatureRow` 与 `BatchRunMetadata` 构造；工厂
  会核对注册表身份、分区、来源、决策时间和确定性验证。`revision_nonce` 随行保存，
  读回时重新计算 `revision_id`，不能用另一个合法 SHA-256 替换修订身份。
- DECIMAL 必须以无多余尾零的十进制字符串保存，禁止二进制浮点进入历史存储；
  INTEGER、BOOLEAN 和 STRING 同样在领域边界按显式类型校验。

## ClickHouse 布局

迁移文件为
`infra/clickhouse/migrations/004_feature_history.sql`。该文件进入 fresh-volume、
existing-volume 和 CI schema smoke 共用的唯一迁移链。表使用普通
`MergeTree`，不使用会折叠历史的 `ReplacingMergeTree`。分区仅按
`toYYYYMM(event_time)`，避免实体或特征造成高基数分区；排序键直接遵循
特征身份、实体和事件时间查询前缀。`revision_id` 的 Bloom filter 用于重试时的
修订核对，`available_time` 的 min-max 索引辅助时间点裁剪。

查询最多接收 500 个不重复实体，并使用半开事件区间 `[event_start, event_end)`。
所有 ClickHouse 参数均通过驱动绑定，实体、版本和时间不得拼接进 SQL。候选行和
最终行数都有上限；达到候选上限时存储层拒绝返回不完整结果。

## 写入与恢复

写入前按 `revision_id` 检查已有行。完全相同的修订视为幂等重试，不同载荷视为
完整性冲突。ClickHouse MergeTree 不提供唯一约束，因此并发的完全相同写入可能
保留物理重复行；读取会按修订号折叠相同载荷。若并发写入产生冲突载荷，读取会
检测并失败关闭。

部署迁移前先备份 ClickHouse 元数据和相关分区。该迁移只创建新表，回滚时应先
停止写入并保留表用于审计；确认没有消费者后才允许由运维人员单独执行删除。没有
TTL，历史清理必须走后续经审批的数据保留节点。

## 示例

```python
query = FeatureAsOfQuery(
    namespace_id="cn_equity",
    feature_name="close_return_1d",
    feature_version="1.0.0",
    feature_fingerprint="sha256:...",
    entity_ids=("600519.SH", "000001.SZ"),
    event_start=start,
    event_end=end,
    as_of=decision_time,
)
page = repository.query_as_of(query)
```

调用方必须保存查询使用的 `as_of`、注册表指纹和返回记录的来源快照版本，才能重放
研究结果。页面展示仍需明确数据时间、算法版本和新鲜度。
