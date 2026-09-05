# 逐日入库明细验收记录

## 结论

P1-N12 本切片补足日线汇总不能查看具体已观测日期的缺口：新增单证券、单来源的
只读逐日查询，并从概览行打开分页明细。只表达 `OBSERVED_ONLY`，不判定不存在日期
的原因，不代表完整性或价格质量合格，也不代表整个 P1-N12 完成。

前一项行情拒绝/过滤证据已按用户要求提交为 `e2254cec517c5af7a11cfa25079c4f094da885f9`。
本切片在该提交之后开发并完成验收，项目负责人随后授权单独提交；实际提交号以包含
本记录的 Git 提交为准。**未部署**。分支保持 `master`，不更新既有容器，
不查询真实行情库，不启动采集，不读取凭据。公开拒绝证据的运行启用仍待其独立安全审核。

## 设计与边界

- 独立版本端点 `/api/v1/data-quality/market-coverage/days`，保留旧概览契约。
- 证券与支持来源必填，沿用日期参数校验，默认 90 日，最大 366 个自然日。
- ClickHouse 参数化查询严格限定单证券、单来源、RAW/DAILY，以日期分组升序返回。
  不使用 `FINAL` 或跨来源价格 winner；重复/修订行只形成一个日期，不排除停牌 Bar。
- 三类时间均不晚于同一服务端查询时点；两端以纳秒整数验证小数部分，避免毫秒截断。
  三个最新时间独立聚合，不能解读为同一条原始记录。
- SQL 防御上限为 367，返回超过 366、重复、乱序、窗外或非法时间时受控失败，不截断。
- 授权先于服务读取；无效参数为 400，拒绝访问为 403，不可用为 503，不暴露原始异常。
- 明细有自己的 `asOf`，不是旧汇总的冻结快照。选择身份包含汇总查询时间，切换或刷新
  重新挂载明细请求；不渲染晚返回的旧结果。每页最多 50 个日期。
- 不具备可靠持久化/PIT 日历、生命周期和任务终态前，不推断“缺失交易日”。

## 文件清单

服务端目录 `apps/server/src/modules/data-quality/`：

- 修改 `data-quality.controller.ts`、`data-quality.module.ts`、`data-quality.service.ts`、
  `data-quality.tokens.ts`。
- 新增 `clickhouse-market-coverage-days.read-model.ts` 及其测试。
- 新增 `market-coverage-days.query.ts` 及其测试、`market-coverage-days.read-model.ts`、
  `market-coverage-days.dto.ts`、`market-coverage-days.controller.test.ts`、
  `market-coverage-days.service.test.ts`。

前端目录 `apps/web/src/features/data-quality/`：

- 新增 `market-coverage-days.ts`、`market-coverage-days-panel.tsx`、
  `use-market-coverage-days.ts` 及三个对应测试。
- 修改 `market-coverage-panel.tsx`、`market-coverage-panel.test.tsx`、
  `data-quality-page.test.tsx`。

契约及生成物：

- `packages/contracts/schemas/data-quality/market-coverage-days.json`
- `packages/contracts/src/data-quality/market-coverage-days-schema.test.ts`
- `packages/shared-types/src/index.ts`
- `python/packages/ashare-contracts/src/ashare_contracts/data_quality_market_coverage_days.py`
- `python/packages/ashare-contracts/src/ashare_contracts/__init__.py`

文档：本记录、`docs/runbooks/market-data-coverage.md`、
`docs/superpowers/plans/2026-09-05-market-coverage-days-plan.md`。没有删除项目文件。

## 失败先行

实现者先运行新契约和前端 parser/panel 测试，观察到尚无 schema/模块的预期失败，
再生成类型并补齐实现。随后检查发现明细选择需要绑定汇总 `asOf`，已增加隔离和回归测试。
分页测试的初始合成日期曾直接拼接出非法月内日期，已改为合法跨月日期与相应窗口。

不是通过放宽时间、日期边界或更新历史基线使检查通过。审阅要求的 event、available、
processing 三字段各自超出 `asOf` 一微秒的拒绝用例均已覆盖。

## 主代理实际复跑

```bash
pnpm --filter @kunlun/server exec vitest run src/modules/data-quality
pnpm --filter @kunlun/web exec vitest run src/features/data-quality
pnpm --filter @kunlun/contracts exec vitest run src/data-quality/market-coverage-days-schema.test.ts
pnpm --filter @kunlun/server exec vitest run src/modules/data-quality/clickhouse-market-coverage-days.read-model.test.ts
pnpm --filter @kunlun/web exec vitest run src/features/data-quality/market-coverage-days.test.ts
```

服务端模块结果为 **67 passed / 1 skipped**。跳过项是既有 PostgreSQL 仓储集成测试，
未设置 `KUNLUN_TEST_POSTGRES_DSN`，本次没有为它获取凭据或启动数据库。
前端模块首轮 32 passed；补充三字段对称断言后再次完整执行本模块，最终 **35 passed**。
新增契约 **1 passed**。单独读模型测试 **3 passed**；parser 窄测当时为 **6 passed**，
之后的新增对称用例已包含在最终 35 项前端模块测试中。没有执行或宣称全仓测试。

主代理还对九个变更前端文件执行 `pnpm exec prettier --check`，结果通过；
对本次文档执行 Prettier，检查本次目录的 `git diff --check`，均通过。

## 实现者检查

实现者执行了以下受影响范围检查并返回成功结果：

```bash
pnpm --filter @kunlun/server lint
pnpm --filter @kunlun/server typecheck
pnpm --filter @kunlun/server build
pnpm --filter @kunlun/web typecheck
pnpm --filter @kunlun/web lint
pnpm --filter @kunlun/web build
pnpm --filter @kunlun/shared-types build
pnpm --filter @kunlun/contracts gen:check
pnpm --filter @kunlun/contracts exec vitest run src/data-quality
```

契约 data-quality 范围为 4 passed，TypeScript/Python 生成物同步；服务端和前端的
lint、类型检查、构建均通过。前端五个直接相关测试文件最终为 22 passed；服务端
格式检查通过。一次 Vitest 使用带引号 glob 未匹配测试文件，属于命令筛选失败，
已用目录参数完整重跑通过，没有把“无测试文件”记为成功。

## 浏览器合成交互证据

主代理在临时目录启动只监听回环地址的 Vite 验收页，导入真实 React 概览组件、hook、
parser 和明细组件，用合成 fetch 响应替代 API；没有代理到现有服务或数据库。
在 Codex 内置浏览器中执行真实 DOM 按钮交互，并读取页面断言结果，以下十项通过：

1. 初始渲染。
2. 请求中加载状态。
3. 首屏仅 50 行。
4. 下一页显示余下 10 行。
5. 汇总刷新清空旧明细。
6. 快速切换证券显示新证券。
7. 旧请求迟返不覆盖新结果。
8. 空数据状态。
9. 403 无权限状态。
10. 503 不可用状态。

临时服务首次因沙箱回环监听限制未启动，获准后启动；临时根目录经 macOS 实路径修正后
页面正常加载。开发热更新期间一次断言运行碰到旧挂载，整页重新加载后上述完整流程通过。
这不是已部署环境的认证端到端或真实 ClickHouse 验收。验收结束已关闭临时服务，并清理
本次合成页面、脚本与缓存；没有删除真实数据或历史证据。

## 审阅与剩余风险

Terra XHigh 完成了本切片的只读定向审阅，未发现阻断项；主代理复核最终差异、
生成类型、相关测试和浏览器结果。该审阅不是之前公开证据卷的独立安全审核。

原有 15 个 P6 修改文件的 SHA-256 保持不变；未更改墙钟门禁、条件接受或任何实盘能力。
使用跨平台 TypeScript/既有 SQL 客户端，没有新增平台专用生产路径。本机实际验证平台
是 macOS，未声称 Windows/Linux 实机验收。

本切片无已知阻断；运行环境验证与部署尚未进行。缺失交易日判定、来源价格对账和全市场
覆盖仍是未完成事项，不能用逐日存在性明细替代它们。
