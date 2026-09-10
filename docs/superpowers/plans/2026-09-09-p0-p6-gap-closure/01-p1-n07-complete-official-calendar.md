# 计划 01：P1-N07 完整官方交易日历

## 目标

取得 SH、SZ、BJ 可回放的官方逐日交易日历，并把临时全市场休市变更纳入不可变版本链，
从而对任一查询日返回 `TRADING`、`NON_TRADING` 或有证据的 `INDETERMINATE`。

## 已有基础与缺口

- SSE 2026 年 19 条稀疏休市公告已持久化，但 coverage 为 `UNKNOWN`。
- SZSE V4 有 365 天快照，官方确认只到 2026-09-07；窗口外正确返回 `INDETERMINATE`。
- V4 raw-first 和 V5 quality ledger 已存在；V5 不负责采集来源，也不自动接 scheduler/API。
- SSE 完整逐日来源、SZSE 后续确认窗口、BSE 官方来源/授权、临时休市完整扫描和多年度滚动
  尚未闭环。

P1-N06 的已提交核心契约和本地目录能力足以保持本计划边界；按用户优先级先补完整日历。
P1-N06 的真实主数据/生命周期运行仍在计划 02 独立关闭，并且必须先于 P1-N12 缺失判定完成。

## 分片顺序

### A. SZSE 确认窗口续接

冻结官方目录/分页身份与采集终态，补齐 2026 剩余确认窗口；旧快照在 successor 可见前继续
有效，新快照不得通过调用方自报 `FINAL_YEAR`。

### B. SSE 逐日来源

寻找并固定 SSE 官方逐日或等价可穷尽来源。稀疏节假日公告只能作交叉证据，不能反推全部
开市日。若官方来源无法证明全年覆盖，保持 `INDETERMINATE`。

### C. BSE 逐日来源

在不绕过访问控制的前提下完成官方来源身份、授权和 raw capture。授权不可得时记录
`BLOCKED_EXTERNAL`，不得用第三方日历冒充官方。

### D. 临时休市与修正链

实现有界官方公告扫描、全天闭市证据、successor scan 复核、supersedes 链和冲突告警。
第三方冲突只保留证据并告警，不覆盖官方状态。

### E. V5 质量投影与只读查询

将通过 V4 验证的 accepted snapshots 投影到 V5 assessment/alerts，覆盖 missing coverage、
source conflict、临时休市证据不足和 as-of 可见性；V3 sparse 输入继续拒绝生成逐日缺口。

每个分片必须先红后绿、独立审核并形成证据包后再进入下一分片。

## 验收标准

- 每个 COMPLETE 年包含每个自然日且恰好一次，绑定 raw、manifest、capture、来源身份、
  `available_at`、parser/schema 版本和完整采集终态。
- 缺页、重定向、页面漂移、跨年/跨所替换、悬空/循环 supersedes、未确认未来日期全部失败关闭。
- 临时休市必须有独立全天证据和 successor scan；没有复核时不得形成肯定闭市结论。
- replay 幂等，历史版本不可更新/删除；同一 operation 的不同内容固定冲突。
- SH/SZ/BJ 的指定验收年份和查询窗口均有真实官方 raw、目标 PostgreSQL、镜像和 as-of 证据。

## 验证范围

- 各来源 parser/transport 单元测试、组合器和替换链属性测试。
- V4/V5 真实 PostgreSQL 迁移、约束、ACL、回放、并发和重启测试。
- wheel/镜像资源摘要、无网络 replay、受控真实官方抓取。
- Calendar Quality reader 的 API 接线留给 P1-N12；持续运行留给 P1-N11。
