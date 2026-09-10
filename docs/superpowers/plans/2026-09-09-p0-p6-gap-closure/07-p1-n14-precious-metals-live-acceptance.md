# 计划 07：P1-N14 贵金属基金真实采集验收

## 目标

在不引入现货、期货或真实交易语义的前提下，验证交易所上市贵金属 ETF/基金的 metadata、
NAV 和 iNAV 从真实 provider 到 raw、规范化、PostgreSQL、质量告警和监控的链路。

## 已有基础与缺口

- P1-N13 契约、P1-N14 collector/validator/storage 代码和自动测试已经存在。
- NAV/iNAV 已定义为参考字段，不是可成交价格；未知分类不得按名称猜测。
- 尚缺真实 provider、实际 PostgreSQL、镜像运行、时效告警和重放恢复证据。

## TDD 与实施顺序

1. 复验现有负值、过期、来源冲突、重复记录、币种、有效期和 `available_time` 用例。
2. 增加真实 adapter 契约测试：能力缺失、限流、空页、部分页、结构漂移和 revision 冲突。
3. 以 raw-first 方式接入 provider；保存 source、request scope、manifest、可用时间和版本。
4. 在专用测试库执行迁移、约束、幂等、修订和恢复测试，再构建冻结 wheel/镜像。
5. 使用受控真实凭据运行一个小范围 metadata/NAV/iNAV 采集和无网络 replay。
6. 验证质量事件、时效告警、指标和数据质量/贵金属终端的只读输入。

## 验收标准

- 真实输入的标的分类、来源、有效期、币种、benchmark、NAV/iNAV 时间含义均可追溯。
- 缺字段、过期、负值、来源冲突和 partial run 失败关闭，不静默推断或覆盖。
- replay 不访问网络、不重复提交；新版本不覆盖历史结果。
- 页面和 API 不把 NAV/iNAV 表述为可成交价，不提供现货/期货/真实订单入口。
- token、账户、raw body 和个人路径不进入日志、证据或前端。

## 外部阻塞

没有合法 provider 凭据或数据使用授权时状态为 `BLOCKED_EXTERNAL`。不得下载不明代码、使用
生产账户或扩大服务权限来绕过。
