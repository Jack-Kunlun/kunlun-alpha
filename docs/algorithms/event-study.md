# P5-N08 事件研究工具

## 范围与版本

- 算法版本：`1.0.0`
- 公共入口：`quant_core.research.events`
- 研究对象：事件窗口收益、市场基准调整收益、横截面对照差异
- 非目标：成交模拟、可交易性推断、订单生成、券商或 QMT 接口

所有价格收益输入仅表示观察到的日线研究路径。结果对象固定标记为
`observational_only`，不得解释为可成交价格或真实订单依据。NAV、iNAV、现货和期货价格
不能作为场内基金的可执行价格。

## 点时选择契约

调用方必须提供完整的 `EventCandidateSnapshot` 归档包，分析器在包内执行
`EventSelectionRule`，不接受只有筛选后事件的隐式样本。归档包可以在研究截止时点生成，
但其中每个事件还必须引用一个事件时点已经完整可用的 `EventEligibilitySnapshot`；
历史选样只依赖后者，不能用归档包的事后完整性替代历史候选全集证据。
历史快照必须同时记录 `as_of_time`、`available_time` 和 `processing_time`，三者均不得
晚于事件时点。

事件记录保留 `event_time`、`publish_time`、`ingest_time`、`available_time` 和
`processing_time`。用于规则匹配的每个 `EventSelectionField` 还必须提供
`effective_time`、`available_time` 和 `processing_time`。

`EventSelectionRule` 自身携带 `effective_time`、`available_time` 和
`processing_time`，证明规则在事件前已预注册。规则如下：

1. 规则、历史 eligibility snapshot、聚类字段、控制组快照和用于筛选的字段都必须在
   `event_time` 前完整可用；筛选字段 `effective_time` 也不得晚于 `event_time`。
2. 事件本身、历史快照、聚类字段、控制组快照、规则和规则字段的最大
   `processing_time` 为
   `selection_time`。
3. 版本化 `EventWindowSchedule` 必须证明
   `anchor_predecessor_time <= selection_time < anchor_session_time`，从而把锚点固定为
   选择完成后的首个声明交易会话。
4. 候选快照与所有筛选输入不得晚于 `data_cutoff_time`。
5. 窗口收益可以晚于事件发生，但只有 `processing_time <= data_cutoff_time` 的结果
   才能进入研究结果。

任何时区缺失、时间顺序冲突、冲突重复事件或事件后筛选字段都会 fail closed。
`TradingStatus`、`OverlapPolicy`、`NonTradablePolicy` 和 `ReturnSemantics` 也在运行时
严格验证，字符串或未知枚举值不能走默认放行分支。

## 窗口、重叠与缺失路径

`EventWindow` 使用交易会话偏移并包含首尾端点。调用方通过版本化
`EventWindowSchedule` 提供每个偏移的会话时间及锚点前一会话；分析器逐偏移校验事件、
基准和每个控制路径，不只检查首日、锚日和末日。工具不使用自然日推断，不顺延缺失
日期。

默认重叠策略为 `EXCLUDE_ALL_SAME_ENTITY_OVERLAP`。同一证券的窗口区间只要相交，
整个重叠组件都会在读取结果路径之前排除。可选 `KEEP_CLUSTERED` 会保留事件，并使用
同一重叠组件作为一维聚类 ID。

事件路径或基准路径缺少任一会话时，整个事件样本被排除。控制成员可单独排除，但剩余
数量低于 `min_controls_per_event` 时，事件样本以 `INSUFFICIENT_CONTROLS` 排除，
不会退化为裸收益。

## 收益口径

对事件 `i` 和相对会话 `t`：

```text
AR[i,t] = R[event,i,t] - R[benchmark,i,t]
CAR[i] = sum(AR[i,t])
ControlCAR[i,j] = sum(R[control,i,j,t] - R[benchmark,i,t])
CrossSectionalEffect[i] = CAR[i] - mean(ControlCAR[i,*])
```

事件与基准的窗口原始累计收益另用 `product(1 + R[t]) - 1` 输出。异常收益、原始
累计收益和横截面对照差异是不同字段，不混用口径。

路径的 `ReturnSemantics` 必须与 `BenchmarkSpec` 一致。V1 只支持日线收盘收益语义，
不推断盘中成交能力。

## 停牌与不可交易

每个 `ReturnPoint` 必须显式携带 `TradingStatus`。

- `EXCLUDE_EVENT`：窗口中出现停牌或不可交易点时排除整个事件。
- `KEEP_OBSERVED_MARKED`：保留观察收益，但样本设置
  `contains_non_tradable_observation=true`，且仍为 `observational_only`。

工具不前填、不顺延、不把停牌收益改为零。完整路径分析会产生事件后 complete-case
选择偏差，输出只能用于描述性研究，不能声称是无偏因果估计。

## 一维 CR1 聚类标准误

对预先定义、且在事件选择时可见的一维聚类 `g`：

```text
mean = sum(y[i]) / n
u[i] = y[i] - mean
S[g] = sum(u[i] for i in g)
Var_CR1(mean) = (G / (G - 1)) * sum(S[g]^2) / n^2
SE_CR1 = sqrt(Var_CR1(mean))
```

`ClusteredMeanSummary` 同时输出样本数、簇数、自由度、有限样本修正和状态：

- `NO_VALID_SAMPLES`：`n = 0`
- `INSUFFICIENT_EVENT_SAMPLES`：`n < 2`
- `INSUFFICIENT_CLUSTERS`：`G < 2`
- `SMALL_CLUSTER_COUNT`：`2 <= G < 30`
- `ZERO_CLUSTER_VARIATION`：聚类残差方差为零
- `OK`：`G >= 30` 且存在聚类变异

V1 不输出 p 值或置信区间，避免在没有明确参考分布时制造显著性结论。一维聚类不能
同时解决证券内重复事件和跨日期市场共振；调用方必须选择并记录主要相关结构。

## 输出与审计

结果保留算法版本、截止时间、归档候选快照、每事件历史 eligibility snapshot、筛选
规则版本及预注册时间、窗口策略、基准来源与版本、控制快照/规则/宇宙版本、事件与控制
路径来源版本、候选/筛中/完整路径样本数、逐原因排除数、控制组排除数、样本级选择时间
和完整结果可用时间。样本与聚合结果都通过不可覆盖字段固定
`observational_only=true`。图表数据分别使用
`average_abnormal_return`、
`cumulative_average_abnormal_return` 和 `cross_sectional_effect` 系列。
