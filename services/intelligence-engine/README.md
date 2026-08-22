# intelligence-engine

内容规范化（P3-N02）。把 event-core 的不可变 `RawContent` 转换为**可逆清洗记录**与**规范化文本**，
供下游检索、去重与情报处理消费。所有原始证据保留，任何清洗都可精确回放。

- 模块：`intelligence_engine`
- 规范化版本：`normalize-v1`（`NORMALIZATION_VERSION`）
- 依赖：仅标准库 + workspace 内 `event-core`（复用 `RawContent`，不重新定义原始契约）

## 偏移语义（核心约定）

所有偏移都是**零基、左闭右开** `[start, end)` 的字符区间，单位是 **Python `str` 码点**（不是字节、不是
grapheme cluster）：

- `original_*` 偏移指向不可变的 `RawContent` 原文；
- `normalized_*` 偏移指向最终规范化文本；
- 空区间 `start == end` 表示零宽锚点（某个替换被后续阶段消费掉后的落点）。

### EditRecord（可逆编辑记录）

每次清洗产生一条 `EditRecord`：

| 字段 | 含义 |
|------|------|
| `operation` / `reason` | 操作类型与原因（枚举） |
| `original_start/end` | 被改动片段在原文中的区间 |
| `normalized_start/end` | 替换后残留片段在规范化文本中的区间（可为零宽） |
| `original_fragment` | 原文该区间的精确切片，恒等于 `original[original_start:original_end]` |
| `replacement_fragment` | 创建时写入的替换内容 |
| `normalization_version` | 产出该记录的版本，跨版本拒绝 |

### SpanRun（运行映射）

`NormalizedText.runs` 是一串连续、单调递增的 `SpanRun`，把规范化文本的每个位置区间映射回原文区间。
1:1 传递的字符表现为 singleton run（两端各宽 1）。`original_range(start, end)` 用它把任意规范化区间
反查回覆盖的原文区间。

每个 `SpanRun` 还记录 `normalized_fragment` —— 该 run 覆盖区间的**权威规范化文本**，恒等于
`normalized_text[normalized_start:normalized_end]`（构造期校验长度）。审计据此检测**变换后字符被篡改**：
即使原文片段与谱系一致，只要最终文本切片与 run 记录的 `normalized_fragment` 不符即判为篡改。

### 偏移映射示例

原文 `"A&amp;B"`（HTML 剥离开启）→ 规范化 `"A&B"`：

```
edit: html_entity  orig[1,6) -> norm[1,2)  '&amp;' => '&'
run:  norm[0,1) -> orig[0,1)     # 'A' 原样
run:  norm[1,2) -> orig[1,6)     # '&' 来自 &amp; 的整段
run:  norm[2,3) -> orig[6,7)     # 'B' 原样
restore_original -> 'A&amp;B'    # 精确还原
```

## 处理管道（确定性、固定顺序）

`normalize_text` 按固定阶段执行，每阶段维护到原文的字符级 `starts/ends` 映射：

1. **BOM 去除**（UTF-8 BOM 前缀）
2. **乱码恢复**（可选，默认开）：仅当整段文本可无损 `latin-1` 编码、`utf-8` 解码、结果不同、
   **且恢复结果含 `>0xFF` 字符**（无歧义的整段乱码）才恢复；恢复结果仍在 latin-1 之内的有歧义文本
   （如 `prefix cafÃ©`）不改写，交质量审查。
   恢复**继承当前管道映射**（不锚定原始偏移 0）：`latin-1` 逐字符占一字节，字节区间 `i` 对应当前字符 index `i`，
   每个恢复字符的原文 span 由其消费的当前字符 `original span` 合并得到，`EditRecord` 的
   `original_start/end` 取自 `current_starts[0]` / `current_ends[-1]`。这保证 BOM 去除后仍无偏移失真，
   `restore_original` 可精确恢复含 BOM 的原文。
3. **换行归一**：CRLF / CR → LF
4. **Unicode NFC**：按 combining mark / Hangul jamo 组成的 cluster 做 NFC，保证等价于整体 NFC 且保留精确 span
5. **HTML 剥离**（可选）：`html.parser`，`script/style/head/title/noscript/template` 内容整体移除；
   `br`→`\n`，块级标签边界→`\n\n`，行内标签→空；实体解码，未知实体原样保留
6. **控制字符移除**：`Cc`/`Cf` 类，保留 `\t` `\n` 与 ZWJ（U+200D）
7. **空白折叠**：连续空白折叠为单空格，去除首尾空白
8. **截断**（可选）：超过 `max_length` 时在码点边界截断并记录

顺序固定 ⇒ 相同输入恒得相同输出（幂等 + 确定性）。

## 时间元数据

`normalize_times` 要求全部为 tz-aware `datetime`，naive 时间**拒绝**（`ValueError`）；统一转 UTC；
校验 `publish_time ≤ ingest_time ≤ available_time`。

## 作者元数据

`normalize_authors` 保留原文作者串，按配置分隔符拆分、折叠空白、稳定去重（保留首现顺序），
丢弃 `None`/空白，**不做身份或机构猜测**。

## 附件元数据

`normalize_attachments` 原样保留 URI/文件名/MIME/位置，产出确定性 `attachment_id = sha256(normalized_uri)`。
状态优先级：`INVALID_URI` > `DUPLICATE` > `UNSUPPORTED_SCHEME` > `MISSING_METADATA` > `OK`。
支持 scheme：`http/https/ftp/ftps/file`；相对 URI 视为 OK。纯元数据处理，不下载、不解析附件内容。

**有效附件判定**：`has_usable_attachment` 仅当**至少一个附件状态为 `OK`** 时返回真。
非空附件列表若全部无效（`INVALID_URI`/`DUPLICATE`/…）**不算**可用附件，据此避免把无效附件误判为
`ATTACHMENT_ONLY`。

## 空正文与拒绝

`normalize` 对空正文分类：`EMPTY` / `WHITESPACE_ONLY` / `CONTROL_CHARS_ONLY` / `HTML_INVISIBLE_ONLY`；
仅当存在**有效附件**（见上）时状态为 `ATTACHMENT_ONLY`，否则 `EMPTY_BODY`。
文本含 U+FFFD（replacement character，证明上游有损解码）→ 抛 `UnrecoverableTextError`，
`normalize` 将其转为 `REJECTED` 结果，仍保留完整 provenance。

## 墓碑（TOMBSTONE）—— 删除记录不得当作普通内容

`RawContent.deleted=True` 是墓碑：内容已被删除，但按 P3-N01 语义**证据从不物理擦除**。规范化对墓碑：

- 状态强制为 `NormalizationStatus.TOMBSTONE`，**绝不**进入 `OK` / `EMPTY_BODY` / `ATTACHMENT_ONLY` /
  `QUALITY_REVIEW_REQUIRED` 等普通可用分支（即使正文非空、即使带有效附件）；
- 完整保留 `raw`（含 `deleted`/`deleted_at`/`previous_version_id`/`original_source`/`license`/
  `fingerprint`）、`record_id`/`version_id`、时间与可逆清洗审计，正文与 title 文本不被物理删除、仍可
  `restore_original` 精确还原；
- `NormalizedContent.is_usable(decision_time)` 采用**白名单 fail-closed**：仅 `OK` / `EMPTY_BODY` /
  `ATTACHMENT_ONLY` 三个**可消费成功状态**才委托给不可变 `RawContent.is_usable`（可用时间 + 授权，
  fail-closed）；`TOMBSTONE`（已删除）、`REJECTED`（不可恢复）、`QUALITY_REVIEW_REQUIRED`（已确认编码质量风险）
  以及任何未知/未来状态**一律恒返回 `False`**。下游无法把删除/未授权/被拒/待人工复核内容当普通可消费文本。

状态优先级：文本本身无法规范化（U+FFFD）→ `REJECTED`（`raw.deleted` 仍为 `True`）；规范化成功且
`raw.deleted` → `TOMBSTONE`。

## 混合/部分乱码 —— 质量审查

`detect_suspected_mojibake` 对**原始文本**做岛屿扫描（跳过 `>0xFF` 字符划分岛屿），在可 `latin-1`
编码的岛屿内查找有效 UTF-8 多字节序列（2–4 字节，lead byte `0xC2–0xF4`、连续字节合法），当该序列的
**UTF-8 解码结果与其 latin-1 解释不同**即判为乱码证据。判据不再要求解码字符 `>0xFF`，因此能识别常见的
**部分 BMP 乱码**如 `cafÃ©`（`café` 的 UTF-8 字节被当 latin-1，恢复为 BMP 字符 `é`=U+00E9）。它**不误判**
纯 CJK/emoji（`>0xFF` 打断岛屿）、纯 ASCII、真正的重音文本（`café`/`résumé`/`français`/`中文 café`/
`naïve`/`Zoë`，其重音是单个 latin-1 字节，后继为普通 ASCII 而非 `0x80–0xBF` 连续字节，构不成多字节序列）
以及单独重音字符。检测在原始文本上进行，因为控制字符移除会抹掉 UTF-8 连续字节的 C1/Cf 签名。

恢复与放行的判据是 `is_confidently_recoverable_mojibake`：整段可 `latin-1`+`utf-8` 无损往返、结果不同、
**且恢复结果含 `>0xFF` 字符**（证明原字节是真正的多字节内容如 CJK/emoji 被误当 latin-1）。只有这种
**无歧义**的整段乱码才会被 `_recover_mojibake` 自动修复并记录 `EditRecord`。恢复结果仍停留在 latin-1 之内的
文本（如 `prefix cafÃ© suffix`→`prefix café suffix`）是**有歧义**的（可能是真重音、也可能是部分乱码），
**绝不静默改写**。

`normalize` 的路由（`_review_reason`）：检测到疑似乱码后——

- 若 `recover_mojibake` 开启且**无歧义可恢复** → 放行（自动恢复，`OK`）；
- 否则若**非无歧义可恢复**（混合/部分乱码，如 `中文 cafÃ©`、`prefix cafÃ© suffix`）→
  `QUALITY_REVIEW_REQUIRED` + `quality_review_reason = PARTIAL_MOJIBAKE_SUSPECTED`，原文保留不变；
- 否则（无歧义可恢复但因 `recover_mojibake=False` 未恢复）→ `QUALITY_REVIEW_REQUIRED` +
  `SUSPECTED_MOJIBAKE`。

即：已识别的部分乱码或残留乱码**永不**静默变成 `OK`。且 `QUALITY_REVIEW_REQUIRED` 因缺少人工复核工作流，
`is_usable` 对其**恒返回 `False`**（与 `TOMBSTONE`/`REJECTED` 同为白名单外状态），不会在无人复核时被下游放行。

## 自动审计（fail-closed，独立重放）

规范化审计的**信任根是从可信原文 + 可信策略独立重放**，不信任待审计结果对象的任何字段
（`text`/`runs`/`edits`/`normalized_fragment`/摘要都可能被攻击者同时篡改成自洽）：

- `_normalize_pure(text, ...)` 是唯一执行管道各阶段的**纯转换**（不做审计）。公共 `normalize_text` 与
  重放审计都调用它，审计重放时**不再进入**公共审计入口，故**无递归**。
- `audit_faithful_normalization(original, normalized, *, strip_html, max_length, recover_mojibake)`：
  用可信 `original` + 可信策略参数经 `_normalize_pure` **重算 expected**，与 `normalized` 做**完整结构相等**
  比较（`text` / `runs`（含每个 `normalized_fragment`）/ `edits` 及其 span）；再叠加 `audit_normalization`
  的结构 + 精确重建检查作纵深防御。任一不符抛 `NormalizationAuditError`。
- **可信策略来源**：策略参数由调用方 / 服务层显式传入，**不从待审计结果对象读取**，也**不使用模块全局可变
  状态**。`normalize_text` 用调用时参数审计；`normalize` 在生产返回前用**实际 active policy** 对 title 与
  body 各再审计一次（fail-closed）。
- 因此同时改写 `text` 与匹配的 `normalized_fragment`（乃至任何摘要）的**自洽篡改**必被独立重放捕获——这些
  字段都不参与 expected 的计算。

## 审计（结构层）

- `restore_original(normalized, original_length)`：编辑片段为权威原始证据优先回填，
  singleton 身份字符次之，逐位置重建并要求全覆盖。
- `audit_normalization(original, normalized)`：**四重结构检查** —— ① runs 连续覆盖且单调；
  ② `normalized.text[run.normalized_start:run.normalized_end]` 等于 `run.normalized_fragment`；
  ③ 编辑片段真实性（`original_fragment` 等于原文切片）；④ 精确重建一致。是独立重放之上的纵深防御层，
  任一不满足抛 `NormalizationAuditError`。

## 内容级可信审计（结果层，fail-closed）

`audit_faithful_normalization` 只审计单个 `NormalizedText`，看不到结果外层的 `normalization_policy_id`
及 `status`/`quality_review_reason`/provenance。`audit_faithful_content` 把信任根提升到**整个
`NormalizedContent` 结果**：

- `audit_faithful_content(trusted_raw, trusted_policy, candidate, *, authors=(), attachments=()) -> bool`：
  唯一可信输入是不可变 `trusted_raw`、**显式传入**的 `trusted_policy` 及同一套作者/附件元数据；**不信任**
  `candidate` 的任何字段。
- 审计以生产 `normalize(trusted_raw, authors, attachments, policy=trusted_policy)` **重放** `expected`，
  然后校验两点：① `candidate.normalization_policy_id == trusted_policy.fingerprint()`（声明的策略身份必须正是
  可信策略指纹，结果不能冒充并非其产出的策略）；② `expected == candidate`。由于结果内每个 dataclass
  （`NormalizedContent` 及其 `raw`、title/body 的 `NormalizedText`（含 runs/edits）、times、authors、
  attachments、status、empty-body/rejection/quality-review reason）都是 frozen dataclass，这一次结构相等即
  覆盖 **文本 / runs / edits / 状态 / 质量问题 / 完整 provenance**。
- 因为 `normalize` 内部只做**文本级** `audit_faithful_normalization`（不调用本函数），故内容级审计**不递归**、
  且复用同一纯规范化边界，两层审计不会逻辑漂移。
- 自洽篡改（如改写 body 文本并配上匹配 runs、或把 `QUALITY_REVIEW_REQUIRED` 伪造成 `OK`、或换用另一份真实但
  错误的 policy 冒充）都无法通过——审计对比的是独立重放而非候选自带字段。任一不符、或重放可信输入时发生任何异常，
  均 fail-closed 返回 `False`。

## 版本化与策略指纹

所有产物携带 `normalization_version`。跨版本记录被 `EditRecord` / `NormalizationPolicy` 拒绝
（`UnsupportedNormalizationVersionError`），保证升级时旧数据可识别、可重算。

`normalization_version` 只标识**格式/契约版本**；同一 version 下改动策略参数（如 `max_body_length`、
`strip_html`、`recover_mojibake`、`author_separators`）时，版本不变会导致**不同产物无法区分来源**。
为此 `NormalizationPolicy.fingerprint()` 输出 **策略指纹**：把全部影响结果的参数写成
canonical JSON（`sort_keys=True`、`separators=(",",":")`、`ensure_ascii=False`）后取 **SHA256**
（不使用不稳定的内建 `hash()`）。`normalize` 结果携带 `normalization_policy_id = fingerprint()`，
使同 version 下的每套参数都可**唯一追溯**。

## Provenance 保留

`NormalizedContent` 携带对不可变原始 `RawContent` 的引用字段 `raw`（frozen dataclass），
连同 `normalization_policy_id`，完整保留使用限制与审计关联：`license`、`original_source`、
`deleted`/`deleted_at`、`fingerprint_algorithm_version`、`content_type`、`url` 等在结果中始终可回溯，
不因规范化而丢失。
