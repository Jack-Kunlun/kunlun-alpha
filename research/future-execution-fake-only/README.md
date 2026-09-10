# EXPERIMENTAL / FAKE_ONLY / OFFLINE / NOT_DEPLOYABLE / NOT_A_P7_NODE

> **EXPERIMENTAL / FAKE_ONLY / OFFLINE / NOT_DEPLOYABLE / NOT_A_P7_NODE**
>
> 这是一个 `planned` / `future` 的研究级安全语义原型，仅用于离线验证失败关闭、`PAPER_ONLY`、幂等和精度边界。它没有服务入口、外部 I/O 或任何可执行柜台路径，不能部署，也不是正式 P7 开发。

本目录不构成 Phase 6 exit，不构成 P7-N01、P7-N02 或 P7-N03 的验收，不构成程序化交易报告，不构成任何券商准入或 QMT 权限证明，也不构成实盘能力、实盘连接或实盘交易证明。当前 Phase 6 的 24 小时墙钟门禁与本目录相互隔离；本目录的存在、测试或实验结果都不会缩短、替代或改变该门禁。真实交易前另需独立的连续 72 小时合格耐久证据。

## 隔离设计

- 只使用 Python 3.12 标准库；数据只存在调用期间的内存对象和内存 `FakeOnlyLedger` 中。
- 没有 HTTP、CLI、服务入口、环境变量、文件 I/O、socket、subprocess、数据库、Docker、QMT、`xtquant` 或 broker SDK。
- 不创建账户、持仓、订单提交/撤单或柜台连接；`FakeOnlyIntent` 的 `account_ref` 必须是 `fixture-account-...` 形式。
- `instrument` 只接受内部 canonical 形式 `六位数字.SH` 或 `六位数字.SZ`，不接受 vendor-specific symbol。
- 运行时固定并验证 `broker_executable=False` 与 `execution_capability="PAPER_ONLY"`；任何不匹配都返回 `REJECTED`。
- 本目录不接入主应用、耐久门禁进程、Docker、数据库或共享运行环境；复制到任何分支都不得改变这一隔离边界。

## 数据流与安全语义

```text
FakeOnlyIntent
    │  shape / fixture account / canonical instrument / Decimal / policy
    ▼
FakeOnlyEnvironment ── risk_ready && simulated_transport_ready
                    ── reconciliation_matched && !kill_switch_active
    │
    ▼
deterministic payload digest ── key: (account_ref, client_order_id)
    │
    ├── first valid key       → ACCEPTED  + one in-memory ledger record
    ├── same key, same payload→ DUPLICATE + ledger unchanged
    ├── same key, new payload → IDEMPOTENCY_CONFLICT + ledger unchanged
    └── any failed check      → REJECTED  + ledger unchanged
```

`reference_price` 必须是有限、正的 `Decimal`；float、NaN、Infinity、零和负数都会失败关闭。`quantity` 必须是正整数，且必须能在当前 Python 整数字符串安全限制内完成确定性序列化；超出限制时返回 `REJECTED`，不抛出异常或写入账本。没有 wall clock、随机数或 UUID，摘要使用固定字段和 SHA-256 生成，因此相同输入在独立 ledger 上产生相同摘要。账本只记录成功的首次模拟，不会被拒绝、重复或冲突请求增加或覆盖。

### 威胁与失败关闭边界

| 边界                                                           | 处理                   | 账本影响 |
| -------------------------------------------------------------- | ---------------------- | -------- |
| intent、environment 或 ledger 类型错误                         | `REJECTED`             | 不写入   |
| 任一正向环境门禁为 false 或不是 `bool`                         | `REJECTED`             | 不写入   |
| Kill Switch 激活或不是 `bool`                                  | `REJECTED`             | 不写入   |
| broker 可执行标志或能力字符串不符合固定策略                    | `REJECTED`             | 不写入   |
| account、instrument、side、quantity、price 或 client ID 不合法 | `REJECTED`             | 不写入   |
| 幂等 key 已存在且 payload 相同                                 | `DUPLICATE`            | 不新增   |
| 幂等 key 已存在但 payload 不同                                 | `IDEMPOTENCY_CONFLICT` | 不覆盖   |

这组语义只说明一个确定性的内存边界。`FakeOnlyLedger` 只提供进程内线程级原子性，不提供跨进程原子性、持久化或重启恢复。它也没有证明网络隔离、权限隔离、柜台重连、真实订单状态机、持仓对账、风控服务可用性或监管合规。

测试中的 AST/import 与危险调用扫描只是 defense-in-depth（纵深防御），不能替代操作系统/进程隔离、人工审查、依赖审计或正式安全评估，也不是完整的安全沙箱。

## 使用方式

```python
from decimal import Decimal

from fake_only_execution import (
    FakeOnlyEnvironment,
    FakeOnlyIntent,
    FakeOnlyLedger,
    simulate_fake_only,
)

intent = FakeOnlyIntent(
    account_ref="fixture-account-001",
    instrument="518880.SH",
    side="BUY",
    quantity=100,
    reference_price=Decimal("1.2345"),
    client_order_id="fixture-order-001",
)
environment = FakeOnlyEnvironment(
    risk_ready=True,
    simulated_transport_ready=True,
    reconciliation_matched=True,
    kill_switch_active=False,
)
receipt = simulate_fake_only(intent, environment, FakeOnlyLedger())
assert receipt.status == "ACCEPTED"
assert receipt.broker_executable is False
assert receipt.execution_capability == "PAPER_ONLY"
```

`simulate_fake_only(intent, environment, ledger) -> FakeOnlyReceipt` 是唯一的实验 API。`FakeOnlyReceipt.status` 可能为 `ACCEPTED`、`DUPLICATE`、`IDEMPOTENCY_CONFLICT` 或 `REJECTED`。

## 法规基线（核查日：2026-08-27）

以下是用于后续研究边界的公开官方资料链接，不是法律意见，也不表示任何具体券商已经批准本项目或任何 QMT 权限：

- [中国证监会：程序化交易管理规定相关资料](https://www.csrc.gov.cn/csrc/c101954/c7480579/content.shtml)
- [上海证券交易所：程序化交易实施细则相关规则](https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20250612_10781696.shtml)
- [深圳证券交易所：程序化交易管理实施细则](https://www.szse.cn/lawrules/rule/trade/t20250403_612770.html)
- [上交所新闻：程序化交易规则公开资料](https://star.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20250403_10776805.shtml)
- [深交所新闻：程序化交易规则公开资料](https://www.szse.cn/aboutus/trends/conference/t20250403_612773.html)
- [ThinkTrader：QMT 产品公开资料](https://www.thinktrader.net/products/qmt)
- [南京证券：QMT/相关业务公开资料](https://www.njzq.com.cn/njzq/business/nxt.html)

这些资料支持“先报告、后交易”的研究前提和交易所实施细则的核查方向；适用范围、实施细节、账户权限、QMT 接入条件和券商内部审批仍必须由目标券商及合规人员当期书面确认。公共资料不得解读为具体券商已批准。

### 券商人工确认清单

在任何正式 P7 设计或实现之前，必须针对目标券商取得可追溯的人工确认：

1. 适用市场、证券品种、账户类型和程序化交易定义是否覆盖目标策略。
2. 程序化交易报告的主体、时点、材料、变更/撤销流程和留痕要求。
3. QMT 产品、版本、行情/交易权限、仿真与生产环境的准入条件。
4. 账户开通、人工审批、身份认证、网络边界和最小权限要求。
5. 报单频率、单笔/日限额、异常行为处置、独立风控和 Kill Switch 要求。
6. 订单、成交、撤单、持仓、资金和重连后的对账接口及保留期限。
7. 幂等键、重试、状态转换、断线恢复和人工接管的书面约束。
8. 确认材料的版本、生效日期、联系人和适用范围；不得以产品网页或宣传材料替代书面批准。

## 测试与验证

在本目录使用 PATH 中的 Python 3.12 运行以下命令，不调用 `uv`、`pnpm`、Docker 或网络；`-B` 用于避免测试在源码目录写入字节码缓存：

```text
python -B -m unittest discover -v -p "test_fake_only*.py"
```

测试覆盖成功模拟、完整环境门禁真值表、Kill Switch 失败关闭、非法策略、短序列 first-write-wins 性质、拒绝请求不占用或覆盖幂等 key、账户级幂等隔离、相同和冲突 payload 的线程并发原子性、Decimal 等值规范化与上下文精度、超大整数序列化失败关闭、float/NaN/Infinity、字符串 price、fixture account 与 canonical instrument 边界、所有 receipt 的 fake-only 不变量、确定性摘要、导入前 AST allowlist，以及运行时禁止文件 I/O 的边界。测试本身是离线单元测试，不调用真实外部服务、账户或 broker。

## 非目标

- 正式 P7-N01、P7-N02、P7-N03 或任何正式 Phase 7 节点实施。
- `BrokerAdapter`、`QmtAdapter`、`ExecutionService`、真实或仿真柜台连接。
- 账户/持仓查询、提交/撤单、生产 API、公共合同、部署、Compose 或迁移现有 `paper-core` 代码。
- 程序化交易报告提交、券商准入申请、QMT 权限申请、实盘连接或实盘交易。
