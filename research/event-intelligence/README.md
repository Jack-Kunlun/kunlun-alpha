# Event Intelligence Offline Evaluation

`event-extraction-eval-v1.jsonl` 是 P3-N09 的脱敏、固定版本基准集。每行包含数据集版本/创建时间、样本 ID、
内容版本、原文、标签可用时间和零个或多个事件标签。禁止把生产原文、账号标识或未脱敏反馈直接加入 fixture。

## Reproduction

```text
uv --no-cache run pytest --no-cov services/intelligence-engine/tests/test_event_evaluation.py
```

评测输入必须声明 model、prompt、pipeline 和 configuration fingerprint。`evaluation_cutoff` 之后才产生的标签不
参与分数，并在 `excluded_future_label_count` 中显式报告。报告使用整数 BPS、策略指纹、数据集指纹、预测集指纹
和内容寻址 `report_id`，相同输入必得相同结果。

## Human feedback promotion

`event-feedback-v1` 记录是审计素材，不是真值。进入新基准集前必须：

1. 由第二名复核者确认反馈及证据；
2. 去除 reviewer、评论中的个人信息和生产标识；
3. 校验 span 与脱敏原文完全一致；
4. 创建新的 dataset version，不覆盖 `event-extraction-eval-v1`；
5. 在新旧数据集上同时运行评测并记录差异原因。

不得根据当前候选模型的错误直接修改旧 golden label，也不得把 cutoff 后反馈回填到历史评测。
