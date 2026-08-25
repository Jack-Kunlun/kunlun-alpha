# 回测回归与报告

P5-N13 为 P5-N10 回测引擎、P5-N11 A 股成交模拟和 P5-N12 组合会计/估值/绩效建立可复现的回归证据链。它只保存和比较回测制品，不产生真实交易能力。

## 制品

`RegressionRunArtifact` 使用 `schemaVersion=backtest-regression-run-v1` 和 `canonicalizationVersion=backtest-regression-c14n-v1`。制品包含 suite/run/fixture 身份、trust、完整 manifest 及其摘要、执行输入、组合历史引用、估值 lineage、NAV/RF observations、版本矩阵、结果和 `artifactSha256`。

规范化 JSON 是 UTF-8、LF、无 BOM、sorted keys、compact JSON、恰好一个末尾 LF。为保证 Python code-point 和 TypeScript/JavaScript UTF-16 runtime 的 canonical semantics 一致，canonicalization-v1 递归拒绝任何非 ASCII JSON object key；ASCII key 按字节序一致排序。manifest 的任意 JSON 内容也经过同一递归约束。Decimal 使用有限的固定点字符串，不接受指数、正号、负零、尾随零或 float；允许 `-0.5`、`0`、`0.5`、`1.5`。时间为 UTC RFC3339 六位小数。数组由调用方按业务顺序提供，规范化器不会替调用方排序。

`artifactSha256` 对删除自身字段后的 canonical bytes 计算。`CONTENT_SHA256` 表示内容摘要；`OPAQUE_EXTERNAL` 仅表示外部证据引用，不把外部值误当作内容摘要。trust 的 evidence-integrity confidence 是证据完整性信心，不是投资置信度。

`provenance.code` 从 repo root 构造显式、排序的 POSIX-relative source closure，覆盖 quant-engine regression、backtest-core、quant-core 和 ashare-contracts 源码，并保存真实的每文件 SHA-256 与 aggregate tree digest；不包含 baseline、tests、cache、mtime 或 host。dependencies 保存实际 package source aggregate 和 repo-root `uv.lock` SHA-256；toolchain 同时绑定实际 root `pyproject.toml`、`services/quant-engine/pyproject.toml` 和 `uv.lock` 的 bytes digest，以及 Python/uv/Hatchling pin。config/dependencies 必须各有唯一命名 entry 对应这些文件，`evidenceSha256` 由其他 toolchain 字段重新计算；这是内部完整性绑定，不是签名。CLI candidate builder 只在 checkout root 存在时工作，并把声明绑定到当前 checkout bytes。artifact 排除 OS host、wall-clock duration、随机 ID 和绝对路径。版本矩阵明确记录 engine、manifest、event order、execution、matching、portfolio、valuation、metrics、strategy、policy、fixture 版本。

## 基线和人工审核

checked-in baseline 位于 `services/quant-engine/fixtures/regression/p5-core-chain.baseline.json`，包括完整 expected artifact、artifact digest 和 approval。approval 必须绑定 `reviewedArtifactSha256`，并记录 approval ID、审核人、固定格式审核时间、外部变更引用、原因和有序 evidence refs。nested artifact、expected digest 和 approval digest 任一不一致都视为损坏并拒绝。

基线只能经过人工审核后由开发流程显式更新 checked-in 文件；公开 CLI、API 和 UI 没有 update、accept、generate-overwrite 或自动接受路径。结果、算法、依赖或工具链漂移都必须保留为差异并使比较失败。

## Integrity repository

只读 `FileRunArtifactRepository` 在设置 `BACKTEST_REGRESSION_ARTIFACT_ROOT` 后使用显式 layout，写入型 repository 的默认根目录仍只用于受控的 append-only recovery 测试：

```text
objects/sha256/<prefix>/<artifactSha256>.json
identities/<suiteId>/<runId>.ref.json
baselines/<baselineId>.baseline.json
```

对象、identity 和 baseline 都只读暴露给 Nest；任何 root、objects、identities、baselines、suite、prefix、object/ref/baseline file 的已存在 symlink 都拒绝，最终路径必须 lexical 和 realpath containment 于 explicit root。ID 与 digest 在 path join 前严格校验。写入先校验制品，再写同目录临时文件、flush/fsync，并用 exclusive hard-link 发布；不支持该发布语义时 fail closed，不使用 overwrite/replace。相同内容重复 append 幂等；相同 identity 绑定不同 digest、损坏对象、ref/object 不一致和 symlink 都失败。对象先发布、ref 尚未发布的崩溃状态可重试恢复。

读取拒绝非法 UTF-8、BOM、CR、重复 key、非 canonical JSON、错误 digest、路径穿越和不安全 ID。该仓库是 integrity store，不是签名系统。CI 不实例化 writer；CI 只读 checked-in baseline 和 candidate。

## 确定性比较

比较器使用 RFC6901 JSON Pointer，先按 `SCHEMA`、`MANIFEST_INPUT`、`ALGORITHM_CONFIG`、`DEPENDENCY_TOOLCHAIN`、`RESULT` 分类，再按明确 ASCII/code-point pointer 顺序排序；非法 `~` escape、重复 category+pointer 和未排序 diffs 均拒绝。addition、removal、replacement 保留数组顺序，Decimal 按规范字符串精确比较；只从直接 tree diff 排除 `artifactSha256`，仍验证双方 digest。固定五类 `categoryCounts`、status、diff values 和 canonical `diffLines` 由 shared semantic validator 一致校验，server 不绕过该 trusted boundary。

比较输出双方 digest、分类计数和稳定 diff lines。只有 zero diff 返回成功；缺失、损坏、schema 不支持、非法制品或任意漂移均返回非零。依赖/工具链漂移不会因为最终结果相同而被忽略。

## Smoke chain

固定 fixture 通过真实 public API 串联：P5-N10 manifest/engine、P5-N11 public execution interfaces、P5-N12 trusted portfolio/replay、valuation 和 quant metrics。它使用两笔明确的 `SimulationOrder`、T+1 calendar、至少四个 NAV observations 及对齐 RF observations。输入、时钟、策略/policy 和版本固定，结果由真实事件、成交、会计和 metrics 计算，不硬编码 PnL；portfolio history 和 valuation lineage 随制品保存。

T+1 证据使用固定的 BUY/SELL `SimulationOrder`：BUY 成交后，SELL 在同日通过 P5-N11 public matcher/sellability API 被 `T_PLUS_ONE_NOT_SELLABLE` 拒绝，下一交易日再次评估同一 SELL 并成交。两次 SELL evaluation 的 execution input、sellability、batch、result lineage，以及 reject/next-day-fill counts 都进入 artifact。所有 source 都是本地 fixture/in-memory public interfaces。P5-N13 不启动 Python server，不访问网络、Broker、QMT、credential、account、贵金属或 P6 能力，也不包含 corporate-action 扩展。

## CLI 和 CI

唯一公开根命令是：

```text
pnpm backtest:regression
```

它通过 `scripts/ci/backtest-regression-no-write.mjs` 将 root `pyproject.toml`、`uv.lock`、quant-engine 及依赖包的 source/metadata/baseline 复制到私有临时 checkout，保持相同 relative paths 和 bytes，然后从 isolated cwd 以 `KUNLUN_REPO_ROOT`、`PYTHONPATH` 和 `path.delimiter` 指向该副本，执行 `uv --project <original-checkout> --no-cache run --no-sync python -B -m quant_engine.regression check --baseline ...`。wrapper 在 child 前后比较隔离 closure 的全部文件、目录、symlink 和 bytes，不对任何 `infra`、`docker`、`data` 路径豁免，也不 cleanup 后再比较；另行比较原 checkout git status。临时副本最终才删除，因此它证明的是“零隔离 tree mutation”。wheel build 只证明 wheel 可构建，不承诺 installed wheel 执行 repo regression。`compare` 也只输出比较结果；没有写入或接受基线命令。CLI 使用固定 uv/python pin，跨 Windows、macOS、Linux，不依赖 shell-specific 语法、网络或 Git mutation。

“零隔离 tree mutation”与“git-clean”是两个独立证据：三个 CI 操作系统在 Quality Gates 后运行 `pnpm backtest:regression` 的 snapshot wrapper。wrapper 不要求初始工作树 clean，但必须保持原 checkout git status 前后一致；随后 CI 再运行 `scripts/ci/check-clean-tree.mjs` 检查 `git status --porcelain`。Linux 继续执行 build，并在 build 后再次检查 clean tree。CI 的 uv 版本与根仓库实际 pin 一致，任何算法、schema、输入、依赖、工具链或结果漂移都会阻断流水线。

## 只读 API

Nest 控制面提供：

```text
GET /api/v1/backtest/regressions
GET /api/v1/backtest/regressions/:runId
GET /api/v1/backtest/regressions/:runId/comparison?baselineId=<safe-id>
```

默认数据源是明确标记的 `LOCAL_PREVIEW` in-memory fixture；配置 `BACKTEST_REGRESSION_ARTIFACT_ROOT` 后只读文件对象。ID 在 repository 访问前校验，内容经过 contract parser。错误分别映射为 invalid 400、denied 403、missing 404、corrupt/unavailable 503。无 POST、PUT、PATCH、DELETE 路由，Nest 不启动 Python。

## Web 报告

`/backtest/regressions` 是“证据账本”页面，复用现有 shadcn/ui Card、Badge、Table、Button。页面展示状态、candidate/baseline digest、数据窗口、availability、evidence confidence、preview label、版本矩阵、counts、PnL、NAV、metrics 和按分类/JSON Pointer 的差异表；底部明确显示人工审核和“基线不会自动更新”。

页面覆盖 loading、empty、error、forbidden、matched、drifted 状态，保留键盘焦点、语义 heading/caption、dark mode、移动端表格溢出和 reduced-motion 兼容。不提供 accept/update 控件。

## 恢复和信任边界

写入中断后可以保留已 fsync 的对象，下一次 append 会校验对象并重新发布缺失 ref；不同字节不会覆盖已有对象。读取遇到 malformed JSON、digest mismatch、symlink 或 approval chain mismatch 时 fail closed，不将内容降级为可用报告。

artifact 的 `FIXTURE_SELF_CONTAINED`/`VERIFIED` 只描述制品证据来源和完整性。它不代表投资建议、收益保证或真实成交可信度。P5-N13 仅面向 Phase 0-6 的模拟回测；架构上没有 broker adapter、QMT、真实账户、credential 或 real-order path。
