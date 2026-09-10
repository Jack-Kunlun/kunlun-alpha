# 计划 06：AKShare/Tushare 配置到真实采集 E2E

## 目标

证明现有管理员行情源配置真正驱动 worker 完成一次受控采集，并把 raw、质量事件、Bar、覆盖/
缺失和来源差异证据贯通到认证页面。

## 前置依赖

- 计划 01–05 已完成，数据契约和判定语义冻结。
- 已有管理员会话、独立 worker credential、加密 key 和用户提供/现有的 provider token。
- 外部凭据不可得时本计划为 `BLOCKED_EXTERNAL`，不能用 fake 或历史镜像代替。

## 场景矩阵

1. Tushare：保存有效配置，worker 读取新 revision，完成一个有界日线窗口。
2. AKShare：保存支持的 source，完成相同证券/日期窗口，验证无需 Tushare token。
3. 配置切换：revision 单调前进，旧 worker marker 不得覆盖新配置。
4. 错误场景：无效 token、限流、超时、结构漂移、部分页和公开证据发布失败。
5. 重放：禁网 replay 不读取 token，不重复写 Bar/quality/assessment。
6. UI：认证页面展示 run 状态、观测、缺失/无法判定、来源差异和脱敏证据。
7. 重叠样本：对真实 AKShare/Tushare 同证券、同日期、同 RAW 日线执行计划 05 的价格差异
   对账，记录可比较/不可比较原因、阈值版本和证据引用。

## 执行步骤

1. 在 fake/fixture 中先补全失败矩阵并确认预期红灯。
2. 构建固定源码摘要的 worker/server/web 镜像，验证 secret mount 和最小权限。
3. 使用现有 Docker 项目启动一次性/短时有界任务；不启动无限持续采集。
4. 记录配置 revision、run/capture/snapshot 的不透明 ID、计数、时间和镜像摘要，不读取或输出 token。
5. 验证 ClickHouse/质量账本/API/UI，随后停止任务；保留原始证据，不删除成功或失败记录。
6. 执行禁网 replay 和配置切换回归，核对基础服务未被无关重启。

## 验收标准

- 配置 revision 与实际 worker run 可追溯；浏览器只看到 configured/unconfigured，不看到 token。
- 每个 provider 的真实请求、raw manifest、规范化/拒绝、Bar、assessment 和页面记录可串联。
- 错误分类、重试、partial terminal 和公开证据发布均失败关闭。
- 重放不访问网络、不重复提交，切换 source 不混用 checkpoint/raw namespace。
- 不创建第二套 Compose 项目，不改变数据卷，不影响纸面交易运行或实盘隔离。

## 证据包

分别记录 fake 自动测试、真实 provider E2E、数据库/ClickHouse 只读核验、镜像/Compose 状态和
认证页面截图/交互。HTTP 200、容器 healthy 或有 Bar 任一项都不能单独作为通过结论。
