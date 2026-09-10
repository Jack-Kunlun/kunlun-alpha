# 基金拒绝诊断字段名安全边界修复

## 范围与结论

P1-R07 trust-chain Task 2 的补充修复，定向验证及独立安全审计通过，当前工作区未提交、未部署。
不是重新实施旧计划的全部任务，也不是扩大基金或真实交易能力。

独立对账发现：旧逻辑仅按敏感字段名黑名单及字符规则筛选，不可信字段名仍可能携带
敏感内容，经 `FundCollectionResult.rejected` 返回。持久化前的二次清洗无法保护此前
已经返回给调用者的诊断对象。

修改 `storage/precious_metals.py`、`test_precious_metals_audit_semantics.py` 和
`test_precious_metals_postgres_adapter.py`：
诊断字段只保留当前 normalizer 支持的规范业务字段名，未知字段名不再输出；不通过
strip 将未知拼写变成允许字段。item 派生字段和显式 `field_names` 使用同一白名单。
不改变 digest、证据身份、拒绝 reason、原始数据、正常归一化或数据库 Schema。

## 根代理新鲜验证

执行者先添加真实 collector 回归并观察到失败：

```text
PYTHONPATH=python/packages/ashare-contracts/src:python/packages/market-core/src:services/data-worker/src .venv/bin/python -m pytest services/data-worker/tests/test_precious_metals_audit_semantics.py::test_rejection_field_names_use_a_strict_business_allowlist -q --no-cov
1 failed
```

预期 `field_names` 仅有 `validFrom`，旧实现却包含 `opaqueFieldWithoutMarker` 和
`token-embedded-synthetic`。修复后根代理执行以下组合。

```text
uv --no-cache run --no-sync --package data-worker pytest --no-cov -q services/data-worker/tests/test_precious_metals_audit_semantics.py services/data-worker/tests/test_precious_metals_postgres_adapter.py services/data-worker/tests/test_precious_metals_pipeline.py
21 passed in 0.31s

.venv/bin/ruff format --check services/data-worker/src/data_worker/storage/precious_metals.py services/data-worker/tests/test_precious_metals_audit_semantics.py
2 files already formatted

.venv/bin/ruff check services/data-worker/src/data_worker/storage/precious_metals.py services/data-worker/tests/test_precious_metals_audit_semantics.py
All checks passed!

.venv/bin/basedpyright services/data-worker/src/data_worker/storage/precious_metals.py services/data-worker/tests/test_precious_metals_audit_semantics.py
0 errors, 0 warnings, 0 notes
```

uv 的非目录 workspace 提示未影响执行。未跑全仓、真实 provider 或实际 PostgreSQL；
postgres_adapter 文件使用 fake adapter，不应称作真实数据库集成通过。

随后补充同未知键的 fake SQL 参数验收，证明字段名及对应值不进入 SQL 参数，合法
evidence digest 仍保留、伪造 digest 丢弃。这是实现后的覆盖追加，未人为制造红测。
执行者运行对应文件 6 项通过，格式/lint/typecheck 通过；根代理另执行：

```text
uv --no-cache run --no-sync --package data-worker pytest --no-cov -q services/data-worker/tests/test_precious_metals_postgres_adapter.py::test_postgres_rejection_uses_evidence_digest_for_canonical_looking_payload
1 passed in 0.28s
```

## 相关文档补正

独立检查同时发现恢复手册的调用示例漏传 `attempt_id`。根代理仅更新
`docs/development/precious-metals-fund-ingestion.md` 示例，说明复用目标 capture/checkpoint
已有 attempt、不能新建或拼接，并对照当前方法签名及重放测试。该文档 Prettier
检查通过，未修改恢复逻辑。此为低风险文档修正，不据此声称重新运行全部恢复验收。

## 边界

Terra Max 独立检查最终三文件差异，运行新增/扩展回归得到 `2 passed in 0.37s`，
确认精确白名单、显式列表、返回及持久化边界和 digest 保持，无本切片阻断。

白名单随当前规范字段定义，不接纳任意 provider 扩展字段；未来新增规范字段应显式
评审后更新。不新增依赖、平台路径或 broker 入口。本机 macOS 验证不能替代其他 host
平台实际执行。原有 P6 条件接受、延期正式墙钟门禁及工作区内容保持不变。
