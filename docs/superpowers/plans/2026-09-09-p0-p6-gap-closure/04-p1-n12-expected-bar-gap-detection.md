# 计划 04：P1-N12 应有行情与缺失判定

## 目标

把 `OBSERVED_ONLY` 日线概览升级为独立的点时完整性评估：对指定证券、来源和日期窗口明确
列出应有日、已观测日、缺失日、无法判定日及每个结论的证据。

## 前置依赖

- 计划 01 提供交易所逐日状态和临时休市结论。
- 计划 02 提供证券 listing/delisting/有效期及可见时间。
- 计划 03 提供采集 run 终态；未完成 run 不能生成“数据缺失”结论。

## 契约

按 `unifiedCode + source + interval + priceType + date + asOf` 评估。日线“应有”至少要求：

1. 证券在该日和 as-of 下已上市且未退市；
2. 对应交易所该日为官方 `TRADING`；
3. 全日停牌、部分停牌和未知停牌状态按显式规则处理；
4. 对应采集 run 已达到可用于完整性判断的终态；
5. source 对该 `unifiedCode/exchange/interval/priceType` 有能力和授权，且 run 明确声明并完整结束
   该请求范围；
6. 所有输入 `available_time <= asOf`。

输出状态固定为 `PRESENT`、`MISSING`、`NOT_EXPECTED`、`INDETERMINATE`。任何分母信息不足时
必须选择 `INDETERMINATE`，不能把零行、空列表、未请求子集或无告警当成完整。

## TDD 与实施顺序

1. 先写纯域真值表：上市首日/退市后、周末/节假日/临时休市、全日停牌、部分停牌、日历未知、
   生命周期冲突、采集未完成、迟到 bar、重复/修订 bar。
2. 定义版本化 JSON Schema 和 TypeScript/Python 生成类型。
3. 实现纯 projection，再实现 Calendar Quality/Instrument reader 与 ClickHouse observed bar adapter。
4. 持久化不可变 assessment/alerts，增加列表、详情和证据链接 API。
5. 更新数据质量页面，分开展示缺失、非预期、无法判定；保留 loading/empty/error/forbidden。
6. 用隔离 PostgreSQL/ClickHouse fixture 和现有只读数据做验收，不向现有行情表写假数据。

## 验收标准

- 能逐日回答“缺了哪些证券/来源/日期”，并显示分母、as-of、数据版本和证据。
- `MISSING` 只在全部前置为肯定且采集已完整结束时产生；其他情况失败关闭。
- 并发修订、重复 bar、未来可用数据和不同时间字段不会改变历史 as-of 结论。
- API 支持有界分页/筛选；异常明细不会被汇总遮蔽。
- 告警幂等，同一 assessment 重放不重复创建；新版本不覆盖历史结果。

## 验证范围

- 纯域真值表和 PIT 泄漏测试。
- PostgreSQL assessment/alert 约束与 ACL；ClickHouse 参数化只读查询。
- contracts gen:check、server/web 定向测试、类型检查和受影响构建。
- 已认证页面的正常、空、无法判定、错误和无权限状态。
