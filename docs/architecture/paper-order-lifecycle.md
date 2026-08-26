# 模拟订单生命周期

## 状态机

模拟订单只允许以下主路径：

```text
CREATED -> CHECKED -> SUBMITTED -> PARTIALLY_FILLED -> FILLED
                    -> CANCEL_PENDING -> CANCELLED
                    -> PARTIALLY_FILLED -> CANCEL_PENDING -> CANCELLED
CREATED -> REJECTED
```

`CANCEL_PENDING` 期间仍可能先收到成交。若成交补满，订单进入 `FILLED`，之后到达的撤单确认会被拒绝并产生告警；若只部分成交，撤单确认将剩余数量置为 `CANCELLED`。

## 幂等与顺序

- `clientOrderId` 在账户内唯一，相同意图重试不重复建单，不同意图复用会产生 `IDEMPOTENCY_CONFLICT`。
- `eventId` 完全重复是无操作，同 ID 不同内容直接拒绝。
- `fillId` 完全重复不重复累计，不同成交内容复用会产生 `FILL_CONFLICT`。
- 全局事件序号和 `previous_event_digest` 必须连续，`available_time` 不得倒退。

## 非法转换

非法状态转换不会修改订单状态，但事件仍进入不可变审计带，并产生 `ILLEGAL_ORDER_TRANSITION`。超量成交、未知订单和幂等冲突分别保留明确告警。

## 安全边界

该生命周期只消费 `PaperOrderIntent`，执行能力固定为 `PAPER_ONLY`。模块不包含 broker SDK、真实账户、网络提交或可切换到实盘的适配器。
