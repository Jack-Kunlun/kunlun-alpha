# FeatureSpec 注册表

P5-N01 定义特征的静态语义和依赖关系，不负责计算、物化或在线读取。

## 注册不变量

- 一个注册表快照内，特征 `name` 唯一；名称使用小写点分形式，例如 `market.raw_close`。
- `version` 使用单调递增的 `vN`。描述、实体、频率、值类型、计算定义、算法版本、窗口、过滤、PIT 规则、来源契约或依赖发生变化时，必须提升版本。
- 依赖固定到精确的 `name@version`，且必须存在于同一注册表快照。contract 使用名称到版本的对象映射，结构上不允许同名重复。
- 依赖图必须是 DAG；注册表输出确定性的依赖优先顺序。
- `owner` 必填，用于责任归属；仅 owner 交接不改变特征语义指纹，因此不要求升版，但会追加一条 lineage 记录。
- `semanticFingerprint` 由全部语义字段规范化后计算，使用 `sha256:` 前缀。外部载荷必须经 `FeatureSpec.from_contract` 重算校验，不能直接信任传入值。

## 有效时点

每个 FeatureSpec 同时声明事件字段、可用字段和可用策略：

- `SOURCE_AVAILABLE_TIME`：原始特征沿用来源记录的 `available_time`。
- `MAX_INPUT_AVAILABLE_TIME`：派生特征在所有实际输入可用后才可用。
- `MATERIALIZATION_TIME`：仅在物化完成后可见，后续节点必须保存实际物化时点。

任何研究、训练或回测读取都必须以决策时点过滤可用时间；事件时间不能替代可用时间。

## 演进校验

命名空间只能通过 `FeatureRegistry.empty` 建立空 genesis，不能携带 FeatureSpec。后续变更必须从已验证注册表调用 `evolve`，并提供可信的父 head fingerprint。每次有效变化都会生成新 head，保留 append-only 版本与 owner lineage，禁止删除旧名称、禁止版本回退；语义指纹变化但版本未严格增加也会失败。注册表构建成功后是不可变快照，依赖图和排序可供后续物化节点使用。

JSON Schema 负责结构约束；指纹真实性由 `FeatureSpec.from_contract` 重算并 fail-closed 校验。canonical JSON 使用 UTF-8、递归二进制键排序、紧凑分隔符，不做 locale 排序或 Unicode 归一化；文本禁止首尾空白。共享 fixture 使用多依赖、多来源和 Unicode 固定 TypeScript 与 Python 的结果。

feature-core 不负责持久化 canonical namespace head。跨进程加载方必须把 `namespace_id` 与最新 `head_fingerprint` 存入受控的 append-only 存储，并在重放后比对；若丢弃可信 head 后重新建立空 genesis，纯 domain 库无法判断它是否属于另一个分支，因此不得宣称完成持久化演进校验。

## 非目标

P5-N01 不实现批量计算、在线/离线存储、数据集构建或回测。这些能力由后续节点基于本注册表扩展。
