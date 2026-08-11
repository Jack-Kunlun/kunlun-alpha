# 昆仑智策项目总体规划与实施手册：文档设计稿

## 1. 文档目标

本文档定义《昆仑智策（Kunlun Alpha）项目总体规划与分阶段实施手册》的内容、执行颗粒度与质量门槛。最终交付物既是项目总纲，也是后续向 WorkBuddy 分派任务、再由 Codex 逐节点审核的统一依据。

项目定位为“A 股与场内贵金属基金智能投研、量化研究与交易平台”，品牌语为“观势 · 知势 · 策势”。首版贵金属范围仅包含沪深交易所上市的黄金及数据源可识别的白银相关 ETF/基金；不包含贵金属现货、期货、保证金、换月、交割或实物业务。真实交易能力只能在最后阶段开放。

## 2. 交付形式

- 一份正式、详细、可持续维护的 Word 文档。
- 前半部分描述产品定位、范围、架构、领域边界、数据流和开发规范。
- 后半部分将 Phase 0 至 Phase 7 拆为约 80–120 个小型开发节点。
- 附录提供 WorkBuddy 任务模板、Codex 审核清单、阶段退出标准和实盘门禁清单。

## 3. 开发节点模型

节点编号采用 `P{phase}-N{sequence}`，例如 `P0-N01`、`P2-N07`。

每个节点必须包含：

1. 节点目标与范围边界；
2. 前置依赖和明确的非目标；
3. 建议新增或修改的文件；
4. 核心接口、数据结构或配置；
5. 可执行的实施步骤；
6. 单元、集成及必要的端到端测试；
7. 静态检查、测试和构建命令；
8. 可验证的验收标准与 Definition of Done；
9. 建议提交信息；
10. WorkBuddy 应提供的审核材料；
11. Codex 审核时应重点检查的风险。

单节点原则上控制在 0.5–2 个开发日，只产生一个主要且可独立验收的结果。每个节点应可独立测试、提交和回退。数据库迁移、领域模型、接口实现与界面接入原则上分别拆分。贵金属扩展新增 `P1-N13`、`P1-N14`、`P5-N14`、`P6-N13`，总计 98 个节点。

## 4. 阶段结构

项目按以下阶段推进：

- Phase 0：工程基础设施；
- Phase 1：A 股数据底座；
- Phase 2：市场情绪与板块轮动；
- Phase 3：新闻、事件与热点 Intelligence；
- Phase 4：龙虎榜席位与 KOL Intelligence；
- Phase 5：Feature Store、量化研究与回测；
- Phase 6：智能决策终端与模拟组合；
- Phase 7：QMT、独立风控与实盘交易。

Phase 0–6 不得存在能够产生真实券商订单的调用路径。Phase 7 也必须依次经过适配器接入、模拟验证、风控演练、人工审批和小资金灰度。

## 5. 技术架构

### 5.1 前端与控制面

- React、TypeScript、Vite；
- shadcn/ui 与 Tailwind CSS；
- TradingView Lightweight Charts；
- NestJS 作为 API、权限、配置、任务和 WebSocket 控制面。

### 5.2 Python 引擎与数据设施

- Python 领域引擎和 Worker；
- PostgreSQL 保存业务与配置数据；
- ClickHouse 保存行情、快照、特征和分析数据；
- Redis 保存缓存、实时状态、锁和实时消息；
- MinIO 用作本地对象存储，腾讯 COS 用作生产对象存储；
- DuckDB、Polars 与 Parquet 支撑研究和可复现实验。

### 5.3 工程设施

- Turborepo 与 pnpm workspace；
- uv Python workspace；
- Docker Compose；
- OpenTelemetry、Prometheus、Grafana 与 Loki；
- ESLint、Prettier、Vitest/Jest、Ruff、Pyright 与 Pytest。

## 6. 技术版本策略

- 每个节点实施时采用对应技术的最新稳定版本，不使用 alpha、beta、RC 或 nightly。
- 根配置锁定 Node.js、pnpm、Python 和 uv 版本。
- JavaScript 依赖使用精确版本并提交 `pnpm-lock.yaml`。
- Python 依赖限定兼容范围并提交 `uv.lock`。
- Docker 镜像必须使用明确版本，禁止 `latest`。
- 依赖升级必须作为独立节点，附变更说明、测试结果和回滚方案。
- 业务节点不得顺带进行大范围依赖升级。

## 7. 跨平台与文件格式规范

- 所有源代码、脚本、Markdown、JSON、YAML、TOML、SQL 和配置文件统一使用 LF。
- 根目录必须提供统一的 `.editorconfig`，作为编辑器和 IDE 的基础格式约束；代码格式化工具在此基线上补充语言级规则。
- 通过根目录 `.gitattributes` 统一文本归一化，并对确需 CRLF 的 Windows 专用文件做显式例外。
- 开发、测试和脚本必须适应 Windows、macOS、Linux 三端。
- 路径处理必须使用跨平台 API，不硬编码分隔符、盘符、用户主目录或 `/tmp`。
- 命令脚本优先使用跨平台 Node/Python 实现；确需平台脚本时必须提供三端兼容入口或明确替代方案。
- CI 至少覆盖 Linux，关键基础设施与开发脚本应增加 Windows、macOS 验证矩阵。

### 7.1 统一 `.editorconfig` 基线

Phase 0 必须创建并验证以下根配置：

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
indent_style = space
indent_size = 2
trim_trailing_whitespace = true

[*.py]
indent_size = 4

[*.{md,mdx}]
trim_trailing_whitespace = false

[*.{yaml,yml}]
indent_size = 2

[Makefile]
indent_style = tab

[*.bat]
end_of_line = crlf

[*.cmd]
end_of_line = crlf
```

统一规则说明：

- TypeScript、JavaScript、JSON、CSS、HTML、SQL、TOML 和常规配置使用 2 空格缩进。
- Python 使用 4 空格缩进。
- Makefile 保留 Tab，避免构建语义被破坏。
- Markdown 允许保留行尾空格，以兼容显式换行语法。
- 仅 Windows 批处理文件允许 CRLF；其他文本文件一律 LF。
- 二进制文件不受 EditorConfig 的文本规则影响。
- CI 必须增加行尾与格式检查，防止不兼容编辑器写回 CRLF。

## 8. 代码与架构规范

- TypeScript 开启严格模式，禁止无理由使用 `any`。
- Python 使用完整类型标注，领域边界使用明确的数据模型。
- 文件和模块保持单一职责，避免大型万能 Service 和超长入口文件。
- API、事件和数据模型先定义契约，再开发生产者与消费者。
- 模块只能依赖公开接口，不跨层访问内部实现。
- 时间统一存储为带时区的标准时间，展示时转换为 Asia/Shanghai。
- 金额、价格和数量不得使用不受控的二进制浮点运算。
- 证券代码统一使用 `600519.SH`、`000001.SZ` 等内部格式。
- 算法、特征、评分和数据口径必须携带版本，历史结果不得覆盖。
- 外部数据源、对象存储和券商均通过适配器接入。

### 8.1 场内贵金属 ETF/基金规范

- 沿用统一 `Instrument` 与场内基金模型，不建立平行的现货或期货交易体系。
- 使用 `fundAssetClass = PRECIOUS_METALS`，并以 `underlyingCommodity = GOLD | SILVER | OTHER` 标识底层类别。
- 保存交易币种、净值币种、跟踪基准、费率、NAV、iNAV、溢折价、来源、有效期与可用时间。
- 不允许仅凭产品名称猜测底层类别；缺失或低置信度分类进入质量告警或人工审核。
- NAV/iNAV 是研究参考数据，不得被回测当作可成交价格。
- 现货、期货、保证金、换月、交割和实物贵金属必须另行设计与批准。

## 9. 前端规范

- shadcn/ui 是基础组件体系；不得重复实现已有的 Button、Dialog、Form、Table 等基础组件。
- 基础 UI、业务组件和页面容器分层。
- 服务端数据、客户端交互状态和表单状态分别管理。
- 页面组件不得直接拼接后端请求。
- 图表通过统一适配层接入。
- 页面默认覆盖加载、空数据、错误和无权限状态。
- 无障碍、键盘操作、暗色模式和响应式布局为默认验收要求。

## 10. 数据流与领域边界

主数据流为：外部数据源 → Provider Adapter → Collector → Normalizer → Validator → Deduplicator → Event Bus → 存储 → 领域引擎 → Feature Store → Research/Backtest/Decision Terminal → Paper Portfolio → Risk Engine → Execution Gateway → QMT Broker Adapter。

- 数据采集层不包含业务评分逻辑。
- 情绪、轮动、热点、席位和 KOL 为独立领域模块。
- AI 仅负责内容理解、抽取和辅助归类，不直接形成真实订单。
- KOL 公开交易信息统一建模为 `Claim`，不能视作券商成交事实。
- 实时、历史和研究环境共享同一套特征定义。
- 策略只产生 `Signal` 或 `OrderIntent`，不得直接调用券商。
- 订单必须经过组合管理、风险检查、订单管理和券商适配器。

## 11. 质量与协作规范

- 功能与缺陷修复默认采用测试先行。
- 每个节点至少覆盖正常路径、边界条件与失败路径。
- 外部数据源和券商适配器必须提供可重复的模拟实现。
- 提交遵循 Conventional Commits，并保持范围聚焦。
- 密钥、账户、Cookie、Token 和生产配置不得进入仓库。
- 节点需同步更新相关文档、示例配置和变更记录。
- 未通过格式化、静态检查、测试、构建和审核的节点不得合并。
- WorkBuddy 每次只领取一个节点，并提交变更摘要、文件清单、测试证据、风险说明和未决事项。
- Codex 按需求符合性、架构边界、代码质量、测试充分性、安全性、性能与可维护性审核。

## 12. 阶段退出门槛

- Phase 0：开发环境、质量工具、可观测性和 CI 均可运行。
- Phase 1：股票、ETF 与场内贵金属基金主数据、行情、NAV/iNAV 流水线可重复、可校验、可追溯。
- Phase 2：情绪与轮动指标具有算法版本、历史快照和回放能力。
- Phase 3：事件与热点结果保留证据、置信度和模型版本。
- Phase 4：席位别名、KOL Claim 与绩效统计具有审计链。
- Phase 5：特征不存在未来数据泄漏，回测覆盖 A 股及场内基金交易约束；贵金属 NAV/iNAV 不被视作成交价。
- Phase 6：模拟组合稳定运行并通过故障、恢复和对账测试；贵金属基金专题终端能展示数据时效、来源与溢折价。
- Phase 7：QMT 模拟链路、风控演练、人工审批和小资金灰度均通过。

## 13. 实盘交易红线

- 默认关闭真实交易，且缺少配置时必须安全失败。
- 模拟与实盘账户、数据库、凭证和部署环境必须隔离。
- Kill Switch 独立于策略服务。
- 下单重试必须幂等。
- 断线恢复后必须先完成对账。
- 紧急平仓需要二次确认和独立权限。
- Phase 7 开始前必须重新核实券商接口要求和届时有效的监管规则。

## 14. 最终文档结构

1. 封面与文档控制；
2. 执行摘要；
3. 品牌、愿景与产品定位；
4. 目标、范围、非目标与核心原则；
5. 总体架构、模块边界与数据流；
6. 技术栈、版本与跨平台策略；
7. Monorepo 目录及职责；
8. 数据、情绪、轮动、事件、热点、席位、KOL、特征、量化、回测与交易设计；
9. 完整开发规范；
10. Phase 0–7 的路线图和阶段门槛；
11. 约 80–120 个原子开发节点；
12. WorkBuddy 任务模板；
13. Codex 审核清单与返工规则；
14. 实盘开放检查表；
15. 术语表与附录。

## 15. 完成标准

最终 Word 文档必须内容完整、无占位符和内部矛盾；98 个开发节点大小合理、依赖明确、验收可执行；开发规范覆盖 LF、三端兼容、shadcn/ui、最新稳定版策略、测试、提交、安全和可观测性；场内贵金属 ETF/基金范围及现货/期货排除边界必须明确；文档完成后必须进行 DOCX 渲染并逐页检查。
