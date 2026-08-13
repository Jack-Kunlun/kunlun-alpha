# 情绪评分 V1（emotion_score_v1）

## 目标

把一个交易日的市场情绪压缩为一个 0~1 的确定性分数，用于回放与对比。同一输入必然得到同一分数。

## 分项与权重

| 分项 | 原始指标 | 标准化 | 权重 |
|---|---|---|---|
| 涨停 | limit_up_count | sigmoid((count-50)/30) | 0.30 |
| 跌停 | limit_down_count | 1 - sigmoid((count-10)/20) | 0.20 |
| 连板高度 | max_board | min(max_board/10, 1) | 0.20 |
| 晋级率 | advancement_rate | clamp(rate, 0, 1) | 0.15 |
| 溢价 | premium | sigmoid(premium*20) | 0.15 |

## 总分

```
total = Σ(component_score * weight) / Σ(available_weight)
```

## 缺失数据降级

某个分项缺失（值为 `None` 或键不存在）时，该分项不参与加权平均，剩余分项权重重新归一化；解释字段标记为 `missing`。全部分项缺失时总分为 0。

## 版本策略

`emotion_score_v1` 固定在本模块。任何算法或权重变更必须新建 `scoring/v2`，不得覆盖 v1 的历史分数（回放依赖版本稳定性）。
