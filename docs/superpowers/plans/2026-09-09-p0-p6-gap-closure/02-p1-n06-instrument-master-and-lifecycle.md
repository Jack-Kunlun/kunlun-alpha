# 计划 02：P1-N06 证券主数据与生命周期闭环

## 目标

把当前工作区中的 Tushare 证券主数据实现收敛为可审计、可点时查询的正式 P1-N06 交付，
为后续“某证券在某交易日应有行情”提供可信分母。

## 已有基础与缺口

- 已有一次性 `instrument-master-sync`、五个固定 Tushare 分区、raw-first replay、私有 provider
  PostgreSQL schema、生命周期纯域模型和定向测试。
- 当前定向离线结果为 37 passed、33 skipped；跳过项包含真实 PostgreSQL 边界。
- 尚缺正式角色/迁移受控验收、真实 Tushare 全分区采集、镜像运行、重放幂等和点时查询证据。
- 证券缺席不能自动推断退市；只有 provider 明确状态或退市日期才能形成退市证据。

## 范围

- 股票与交易所基金的 listing/pre-listing/delisting 状态、有效区间和 `available_time`。
- raw manifest、检查点、完整性终态、accepted head、冲突/过期运行和审计记录。
- 独立 migrator/runtime/reader 权限与 fail-closed verifier。
- 面向后续质量引擎的只读生命周期查询接口；不在本计划中计算行情缺口。

## TDD 与实施顺序

1. 先补真实 PostgreSQL 失败用例：空库、重复迁移、部分对象、错误 owner/ACL、并发/过期运行、
   越权读取和非法生命周期跳转。
2. 修复迁移与仓储，保证 raw-first、stable operation identity、追加审计和点时可见性。
3. 构建冻结 wheel/镜像，在专用 `kunlun_test_*` 数据库完成 destructive 测试并清理测试库。
4. 只读检查现有正式库前置状态；经单独授权后执行角色 bootstrap 和 provider migration。
5. 使用真实 Tushare 凭据执行一次全分区采集和一次离线 replay；记录计数、摘要和终态，不记录
   token、请求体或个人路径。
6. 用 reader 角色验证 listing、暂停上市、退市、基金有效期和 as-of 查询。

## 验收标准

- 五个固定分区从 offset 0 连续到短页终止；缺页、分页上限、结构漂移或身份冲突返回
  `INDETERMINATE/REJECTED`，不移动 accepted head。
- 同一 operation 重放不新增 snapshot/audit；同一坐标不同内容固定冲突。
- 新增、变更、退市均有来源证据和点时可见审计；缺席不产生虚假退市。
- runtime 只能写私有 provider schema，reader 只读，PUBLIC 无访问权，秘密不进入日志或证据。
- 镜像内资源摘要与源码一致；正式库验收不依赖测试替身。

## 验证范围

- instrument-master 单元/契约测试、真实 PostgreSQL 测试、Ruff、BasedPyright。
- wheel 安装/资源探针、Compose profile 静态解析、镜像 CLI/replay。
- 一次受控真实 Tushare E2E 和一次无网络 replay。
- 不运行 P6 门禁，不重启无关基础服务。

## 外部阻塞

没有用户授权且可用的 Tushare 凭据时记录 `BLOCKED_EXTERNAL`，停在隔离测试、权限、wheel/
镜像和无网络 replay 验收。不得读取、索取、输出或复用未明确授权的现有 token。
