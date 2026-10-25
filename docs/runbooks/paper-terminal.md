# 模拟组合终端运行手册

## 当前能力

### 1.0.12 本地账户与只读账本

- v1 启动读取已有 `kunlun-quant-state` 独立卷。页面 `/paper` 展示模拟账户的初始资金、现金、
  持仓成本、持仓、账本时间和持久化状态；金额保留原始十进制文本。
- 没有账户时点击“创建账户”打开短弹窗。提交失败保留输入，相同输入重试沿用同一
  `clientRequestId`；修改输入才生成新键。成功关闭弹窗并显示服务端账本。
- 页面仅展示账本资金与持仓成本，不接实时行情，也不展示旧手工标记的市值或收益。
  数据时间按账本实际时间展示；
  无持仓明确为空，不补造股票、价格或估值。切换全局历史点时不会回放该当前模拟账本。
- v1 固定 `PAPER_TERMINAL_ACCOUNT_ONLY=true`，Nest 在转发前拒绝 `POST /paper/simulations`。
  `quant-engine` 仅在 Compose 内部提供服务，不发布主机端口。Web 不提供模拟成交控件。
- Nest 对引擎响应按模拟语义、金额、数量、时间、摘要和账本关系检查；异常返回不可用，
  不把坏金额替换为零或纠正后继续展示。账号与 CSRF 沿用单管理员现有认证。

### 1.0.13 只读仓位试算

已有正常账户时点击“试算仓位”打开抽屉，输入规范证券代码、人工假设价格、信号强度、
假设可信度和整手单位。价格不读取行情，参数不冒充模型输出。成功关闭抽屉，页面显示
目标持仓、增减数量、假设调整金额（未含费用）或拒绝原因；失败保留输入并允许重试。
刷新账本或重新打开抽屉清除上次试算结果，试算结果不保存到服务端日志。

- 固定策略口径 `paper-preview-allocation / 1.0.0`：目标权重为强度 × 可信度，单标的上限
  30%，组合总权重上限 95%，保留 5% 账面现金；假设可信度低于 0.5 时拒绝。
- 价格、信号和整手单位均为人工假设，不自动识别交易所最小委托、涨跌停、停复牌或可成交性；
  该结果不是交易建议、风控许可或可执行报价。仍不开放成交接口。
- 复用当前账本的既有估值作为分配基准，不引入新行情估值；异常账本停止试算。
  所有计算在 Python 通过 Decimal 进行，数量超过 JavaScript 安全整数范围时拒绝。
- `POST /api/v1/paper/previews` 使用现有管理员认证和 CSRF，内部对应 `/v1/paper/previews`。
  它只读取账户，不登记请求、不写命令、订单、风险结果、现金、持仓、估值或审计计数。
- 输入复用 `PaperTerminalSimulationCommand`（`paper-terminal-simulation-v1`），只是情景输入形状；
  端点决定只读语义，不能把此请求转发到 `/simulations`。`clientRequestId` 仅参与预览输入身份，
  不占用已提交命令的幂等登记，相同 ID 的不同预览可重新计算。既有创建／成交命令语义不变。
- 输出复用 `PaperAllocationDecision`（`paper-allocation-decision-v1`），保持
  `INTENT_ONLY_NO_BROKER_PATH`、`PAPER_ONLY` 和 `brokerExecutable=false`；字段兼容，无 Schema 变更。

请求示例（仅假设输入，不含账户或行情来源）：

```json
{
  "schemaVersion": "paper-terminal-simulation-v1",
  "clientRequestId": "manual-preview-example",
  "instrumentId": "600519.SH",
  "price": "100",
  "score": "0.3",
  "confidence": "1",
  "lotSize": 100
}
```

在账面基准为 100000 CNY、未持仓的隔离测试中，上述假设产生 300 股目标，
假设调整金额 30000 CNY（未含费用），原账户现金与持仓不变。

### 1.0.14 只读模拟风险检查

在有调整数量的仓位试算结果下点击“检查模拟风险”，展示账户、引擎、执行入口、实际账簿
核对、单笔金额、集中度、当日累计假设金额、活动订单、账面现金和仅模拟边界共十项结论。
模拟执行入口固定为“未开放／阻断”，整体结果不构成交易许可。金额仍是人工价格下的假设，
现金检查未计费用；没有订单、成交或账户变化。

- 新入口 `POST /api/v1/paper/risk-previews`（HTTP 200）沿用管理员认证及 CSRF；内部路径同名。
  请求是 `/previews` 返回的完整、未修改的 `paper-allocation-decision-v1` JSON，不能只发证券或数量。
  示例调用顺序：`allocation = POST /previews(上述情景)`，然后 `POST /risk-previews(allocation)`。
  无调整意图、快照被修改或计算不一致返回 400／422；账户基准已变化返回 409，须重新试算。
- 复用 `paper-risk-decision-v1`：`intentId`、`accountId`、`accountStateDigest` 绑定原试算，
  `decisionTime` 为本次检查时间，`allowed=false`、`PAPER_ONLY`、
  `SERVER_SIDE_RISK_NO_BROKER_PATH`。字段及 Schema 兼容；控制面校验十项完整性、金额、
  状态、策略指纹与结论摘要，不把异常响应当作通过。
- 风险口径 `paper-terminal-risk / 1.0.0`：单笔假设金额不超过 100000000 CNY，目标权重不超过
  0.35，当日累计假设金额不超过 1000000000 CNY，活动模拟订单不超过 20，试算后现金不低于 0。
  这些是既有隔离模拟规则，不能作为真实交易规则或费用充足性证明。
- 引擎在同一锁内读取账户和执行投影，重算试算并核对完整快照，重新比较实际账簿。
  不沿用旧的对账“通过”状态；对账差异或不可用按阻断处理。执行入口始终关闭。
- 检查不登记幂等命令，也不写入风险结果、日志、审计、订单、现金、持仓或估值。
  失败保留本次试算并可重试；重新打开试算抽屉或刷新账本清除试算和风险结果。
  检查结果只留在当前页面，不保存为服务端历史记录。

### 既有引擎能力与开发栈

- `quant-engine` 维护一个模拟账户、账户事件链和模拟执行事件链；本地 Compose 通过独立持久卷保存命令日志。
- 既有开发引擎可运行 Signal 到 OrderIntent、服务端风控、模拟全额成交和双账簿对账闭环；
  此能力未在当前产品中开放，后续需独立完成其适用验收。
- 金额使用十进制字符串；订单固定为 `PAPER_ONLY`，不存在真实账户、券商连接或真实下单入口。
- `clientRequestId` 对创建账户与模拟命令提供幂等保护；相同键的不同载荷会 fail closed。

## 持久化与恢复

- 设置 `KUNLUN_QUANT_STATE_DIR` 后，创建账户和模拟命令在执行前写入 `paper-workspace.jsonl`。日志按序号和 SHA-256 前序摘要连接，写入后执行 `fsync`；重启会从头验证并重放，再重新生成账户、订单、风控和对账状态。
- 日志缺字段、顺序断裂、摘要不符、载荷不合法或重复命令时，quant-engine 拒绝启动，不会用空工作区掩盖损坏。
- 未设置 `KUNLUN_QUANT_STATE_DIR` 的测试进程仍使用 `VOLATILE_IN_MEMORY`；正式本地 Compose 使用 `DURABLE_COMMAND_JOURNAL`。
- 本地日志只支持单个 quant-engine 实例，不是多副本共用的分布式日志。备份或恢复时必须把服务停在单实例边界，并保留整个 `kunlun-quant-state` 卷。

## 已知限制

- 既有开发引擎仅支持手工多头信号的全额模拟成交，不提供真实行情执行、部分成交输入或跨日可卖数量释放。
  当前页面与产品控制面不开放该成交能力。
- 24 小时 P6 墙钟门禁使用独立 PostgreSQL 证据库；本地命令日志恢复不能替代该门禁，也不能据此宣称 Phase 6 已退出。该资格不构成实盘许可；真实交易前仍须取得独立的连续 72 小时合格耐久证据并通过全部 Phase 7 门禁。

## 启动与健康检查

本地产品使用现有 `pnpm v1:up`。行情自动采集仍单独使用 `pnpm v1:auto:start`。
停止本地产品使用 `pnpm v1:stop`，同时停止模拟引擎并保留独立持久卷。
只读健康检查可经控制面读取 `/api/v1/paper/workspace`；内部引擎健康由 Compose 检查，
v1 不使用主机 `8081`。已有命令日志必须保留，不能因不可用而删除或重建账户。

以下为保留的开发栈入口，不代表 1.0.12 的产品能力或范围：

```text
docker compose -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.apps.yml --env-file infra/docker/.env up -d --build
curl http://localhost:8081/health
curl http://localhost:3002/api/v1/paper/workspace
```

Web 页面：`http://localhost:5173/paper`。

Ranking 正式页面只读取 quant-engine 已发布的版本化快照。若尚未发布，页面显示空状态；测试验收 JSON 不会作为运行时回退数据。

## 故障处理

1. `quant-engine` 不健康时检查容器日志和 `KUNLUN_PORT`。
2. Nest 返回 `UNAVAILABLE` 时检查 `PAPER_ENGINE_URL` 与容器网络。
3. quant-engine 因日志损坏拒绝启动时，先复制并保全 `kunlun-quant-state` 卷；不要删除日志或改写摘要来强行启动。
4. 对账结果为 `DRIFTED` 时停止新增模拟命令，保留响应中的摘要和差异，再调查命令日志与账户/执行摘要。
5. 不要通过重试更换 `clientRequestId` 绕过冲突；先确认原命令是否已提交。
