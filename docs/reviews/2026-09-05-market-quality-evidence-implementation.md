# 行情拒绝与过滤证据实现记录

## 结论与范围

P1-N12 本切片已实现 `REJECTED` / `FILTERED` 的白名单投影、完整快照导出、
只读 API 与页面查询。定向测试、跨语言互通和隔离 HTTP 验证通过。
本记录保存提交前验收结果；项目负责人随后授权将本切片单独提交。
**未部署、未挂载新卷、未回填真实证据。** 不代表整个 P1-N12 或 Phase 1 完成。

基线提交为 `8460e2128851a6814cf5c084ed7a270fc41a5f95`，工作分支保持 `master`。
原有 15 个 P6 修改文件的 SHA-256 与本切片开始前一致；不改变条件接受或最终墙钟门禁。
缺失交易日检测、来源价格对账、全市场覆盖和实盘功能均不属于本切片。

## 设计边界

- worker 从原始质量文件与 manifest 元数据逐项构造公开白名单，不读取 raw objects。
- 公开记录不包含原始 capture/object/checksum、请求、payload、自由文本原因或事件 detail。
  不合法的事件证券/时间转为 null，保留合法事件类型，未知类型和身份错配失败关闭。
- 单一扫描预算最多 10,000 个条目，单输入 1 MiB；流式投影，完整快照最多 10,000 条、8 MiB。
  容量超限整次失败，不截断，不把损坏或缺少目录解释为空结果。
- public 进程间锁覆盖扫描至发布，扫描后固定发布时间；不可变快照按完整字节 SHA-256 寻址，
  current 原子切换。提交前失败保旧；提交后 fsync 失败明确报告持久化不确定，不虚称回滚。
- 同一 capture 重放仍触发导出，并保留首次记录时间。启用导出后 FILTERED 发布失败阻止 Bar 写入。
  首次无异常的成功周期可发布合法零快照；未配置公开目录时保持原采集行为。
- API 授权先于读取，严格校验完整快照、微秒时间顺序、字段、容量和文件身份。
  后续页/明细固定 snapshotId；页面明确区别不可用、完整零记录与筛选零结果。
- 日期筛选表示采集请求窗口交集，不宣称历史时点可见性；UI 时间按上海时区显示。

## 文件清单

契约：

- `packages/contracts/schemas/data-quality/market-quality-evidence.json`
- `packages/contracts/src/data-quality/market-quality-evidence-schema.test.ts`
- `packages/shared-types/src/index.ts`
- `python/packages/ashare-contracts/src/ashare_contracts/data_quality_market_quality_evidence.py`
- `python/packages/ashare-contracts/src/ashare_contracts/__init__.py`

采集端：

- `services/data-worker/pyproject.toml`
- `services/data-worker/src/data_worker/jobs/market_data/quality_projection.py`
- `services/data-worker/src/data_worker/jobs/market_data/quality_export.py`
- `services/data-worker/src/data_worker/jobs/market_data/quality.py`
- `services/data-worker/src/data_worker/jobs/market_data/runtime.py`
- `services/data-worker/tests/test_market_quality_projection.py`
- `services/data-worker/tests/test_market_quality_export.py`
- `services/data-worker/tests/test_market_data_quality.py`
- `services/data-worker/tests/test_market_data_collector.py`
- `services/data-worker/tests/test_market_data_runtime.py`

服务端（以下均位于 `apps/server/src/modules/data-quality/`）：

- `data-quality.controller.ts`、`data-quality.module.ts`、`data-quality.service.ts`、`data-quality.tokens.ts`
- `market-quality-evidence.dto.ts`、`market-quality-evidence.query.ts`
- `market-quality-evidence.reader.ts`、`market-quality-evidence.read-model.ts`
- `market-quality-evidence.query.test.ts`、`market-quality-evidence.read-model.test.ts`
- `market-quality-evidence.service.test.ts`、`market-quality-evidence.http.integration.test.ts`

前端（以下均位于 `apps/web/src/features/data-quality/`）：

- `data-quality-page.tsx`、`data-quality-page.test.tsx`
- `market-quality-evidence.ts`、`market-quality-evidence.test.ts`
- `use-market-quality-evidence.ts`
- `market-quality-evidence-panel.tsx`、`market-quality-evidence-panel.test.tsx`

文档：本记录、`docs/runbooks/market-quality-evidence.md`、
`docs/superpowers/plans/2026-09-05-market-quality-public-evidence-plan.md`。

## 红灯与修复证据

实现者先验证 projection、reader/query 模块缺失的预期失败，再实现最小路径。
审阅过程中实际修复了旧扫描覆盖新快照、发布时间取样、FILTERED 两端语义不一致、
FIFO 阻塞打开、静态根/祖先符号链接、锁超时错误映射和全量 raw envelope 内存积累。
公开指针替换前后两个故障注入测试分别验证旧快照保留与提交后不确定状态。

期间发现并修正前端 RFC3339 捕获组偏移、React effect lint 问题和新增测试的 Pyright 类型告警。
没有通过修改历史基线或跳过失败测试使检查变绿。

## 最终定向验证

主代理实际重新执行：

```bash
uv --no-cache run --no-sync --package data-worker pytest --no-cov -q \
  services/data-worker/tests/test_market_data_runtime.py \
  services/data-worker/tests/test_market_data_collector.py \
  services/data-worker/tests/test_market_data_quality.py \
  services/data-worker/tests/test_market_quality_projection.py \
  services/data-worker/tests/test_market_quality_export.py \
  services/data-worker/tests/test_market_data_remote_settings.py
```

结果：**98 passed**。`--no-cov` 仅关闭不适用于窄测的全局覆盖率门槛，没有跳过测试。

```bash
pnpm --filter @kunlun/server exec vitest run src/modules/data-quality
pnpm --filter @kunlun/web exec vitest run src/features/data-quality
pnpm --filter @kunlun/contracts exec vitest run src/data-quality/market-quality-evidence-schema.test.ts
pnpm --filter @kunlun/contracts gen:check
uv --no-cache run --package data-worker market-quality-export --help
```

结果依次为：**55 passed / 1 skipped**、**24 passed**、**2 passed**、
TypeScript/Python 生成物一致、CLI 帮助正常启动。
唯一跳过项是既有 PostgreSQL 质量仓储集成测试，因未配置 `KUNLUN_TEST_POSTGRES_DSN`。
没有为这次检查获取数据库凭据或启动数据库。

主代理对上述四个 worker 生产文件及五个修改测试文件执行 `.venv/bin/ruff check`、
`.venv/bin/ruff format --check`、`.venv/bin/basedpyright`：全部通过，9 个文件格式正确，
Pyright 为 0 errors / 0 warnings / 0 notes。

实现者执行并返回通过结果：

```bash
pnpm --filter @kunlun/server typecheck
pnpm --filter @kunlun/server lint
pnpm --filter @kunlun/server build
pnpm --filter @kunlun/web typecheck
pnpm --filter @kunlun/web lint
pnpm --filter @kunlun/web build
```

文档 Prettier 检查与本切片 `git diff --check` 通过。未执行全仓测试；不宣称全仓通过。

## 主代理独立联通验证

在临时目录中生成两条合成记录（REJECTED + FILTERED），调用实际 Python exporter。
同一份快照通过实际 TypeScript reader 与 Web list/detail parser，6 位微秒时间保留；
固定 snapshot 查询一致，公开内容不含原始 ID、校验和、detail 和秘密哨兵。

随后用已构建的实际 Controller、Service、ValidationPipe、FileReadModel 启动临时回环
HTTP 服务，以同一合成快照验证列表、详情、筛选、固定快照两页为 200；非法和重复参数为 400、
授权拒绝为 403 且未调用 reader、合法但不存在的 ID 为 404、受控读取故障为 503。
错误和响应未泄漏哨兵。临时服务结束后关闭；不访问已有容器、数据库、行情源或凭据。
验收后清理了本次新建的合成原始文件、公开快照和临时脚本；未清理任何真实或历史证据。
这些不是已部署环境的认证浏览器端到端验收。

初次直接 pytest 因默认 uv 缓存权限失败，改用 `--no-cache` 后通过；临时 HTTP 首次因
sandbox 禁止 listen 失败，获准仅监听本机随机端口后通过。CLI 起初因离线缓存缺少
已固定的 `hatchling==1.27.0` 且网络受限无法构建，获准获取既有构建依赖后构建和帮助验证通过；
未改依赖版本或锁文件，没有将环境失败记成测试通过。

## 安全审核与剩余工作

已完成 Terra XHigh 只读审阅并修复其中可证实的问题；本轮未使用 Terra Max。
当前 agent slot 限制使独立 Max 安全审核不可用，不用实现者自测冒充该审核。
实际启用前仍需独立安全审核、新脱敏卷最小权限挂载检查，以及真实证据回填/API/页面验收。

两端使用跨平台路径 API、非阻塞普通文件读取和文件身份复核，POSIX 特有检查按平台处理。
本机实际测试在 macOS 执行，未声称 Windows/Linux 实机验收。
实现不提供完整 fd-relative openat 保证；部署必须满足唯一受信任 producer 可写、API 只读、
父目录不可由不可信主体改写的威胁模型。哈希绑定不是签名，不防拥有原始卷写权限者的自洽伪造。

未修改 Docker/Compose 或当前运行环境；待后续明确部署任务更新既有 Compose 项目，
不建立第二套环境。实际提交号以包含本记录的 Git 提交为准，没有任何真实下单能力变化。
