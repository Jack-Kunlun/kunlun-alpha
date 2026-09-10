# 计划 08：P3 事件与热点生产闭环

> 本文件是节点组合索引，不可作为单一开发任务派发。P3-N07、N08、N09、N10 开工前必须
> 分别建立独立 Execution Contract，并在上一节点通过 Codex 审核后再开始下一节点。

## 目标

保留 P3 已有领域实现，逐节点补齐新鲜验收，并将 P3-N07–N10 从 Protocol/纯计算/默认拒绝
状态推进到可运行、可持久、可审核的事件与热点闭环。

## 当前状态

- P3-N01–N06：实现、提交和节点测试存在；作为下游开工前回归基线，不先重写。
- P3-N07：consumer、校验和重试存在，但 ModelGateway/ExtractionStore 没有生产 adapter、
  队列入口或持久 writer。
- P3-N08：HotTopic/HotScore 为纯核心，缺版本化快照、物化和调度。
- P3-N09：离线评测/反馈 repository 存在，默认 `DenyAll`，没有可信 reviewer 接入。
- P3-N10：API/Web 存在，但没有来自 N07/N08 的真实上游写入。

## 节点计划

### P3-N01–N06 前置回归

按 N01→N06 分别运行契约、规范化、去重、实体解析、MarketEvent、模型/Prompt registry 的窄
测试、类型和安全检查。发现回归才重新打开对应节点修复，不把六个节点合并重写或一次提交。

### P3-N07 生产抽取适配

先测试非法 JSON、schema drift、超时、限流、低置信度、重复消息和重放，再实现受控
ModelGateway、追加式 ExtractionStore、队列入口、拒绝区、checkpoint 和审计。模型输出始终
作为 `unknown` 校验；模型/密钥选择沿用已批准配置，新增外部服务需另行授权。

### P3-N08 热点物化

把已验证 MarketEvent 与点时市场数据聚合成版本化 HotTopic snapshot；补持久化、checkpoint、
批流一致、迟到数据、回放和调度。事件数量不能直接等同热点强度。

### P3-N09 可信反馈与评测

当前没有可信 HTTP 身份提供方。此节点先记录 `BLOCKED_DECISION`，等待用户批准身份来源、
角色/权限、服务间信任边界和审计 actor 语义；此前保持 `DenyAll`，不得依赖客户端 Header 或
`AllowAll`。身份决定落地后冻结评测集，反馈先进入审核，通过后才能形成新数据集版本；线上
反馈不得直接成为真值。

### P3-N10 端到端工作台

用持久事件/热点 projection 驱动 API/UI，验证事实、模型推断、低置信度、删除、无证据、空、
错误和无权限状态；完成真实上游写入到已认证页面的最小 E2E。P3-N09 的可信身份决策未获批、
节点未关闭前，不得启动认证 E2E，也不得用 Header、`AllowAll` 或测试身份替代生产信任边界。

## 验收与顺序

- 严格按 N01→N10，一次执行一个节点；每个节点通过独立审查后再进入下一个。
- 来源、版权/许可、删除状态、证据偏移、prompt/model/schema/dataset 版本完整保留。
- 重试幂等，低置信度不强绑证券，不合并不同公司的同类公告。
- P3 阶段出口必须有生产 adapter、持久化、调度/队列、授权、API/UI 和恢复证据。
- P1 日历/行情仍不完整时，依赖市场表现的热点输出必须标记无法判定或只用受控 fixture。

## 验证范围

各节点窄测试、contracts gen:check、Ruff/BasedPyright、server/web 定向测试与构建、专用数据库
迁移/恢复、fake provider 自动测试和一次受控非生产真实链路 E2E。
