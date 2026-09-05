# ADR-0011：实例级行情源配置的密钥边界

## 状态

Accepted for the P1-N04 provider-configuration extension.

## Context

AKShare 与 Tushare 需要在一个实例范围内选择，管理员需要能够更新配置，而 data-worker
又不能获得浏览器会话、数据库或 master key。Tushare token 属于 secret，不能进入 API
响应、审计值、raw manifest、日志或仓库。

## Decision

- PostgreSQL 保存一个 `default` instance row；Tushare token 只保存 AES-256-GCM envelope
  （随机 96-bit nonce、认证 tag、显式 encryption/key version）。master key 由
  `MARKET_DATA_SETTINGS_MASTER_KEY` 或 checkout 外的 `MARKET_DATA_SETTINGS_MASTER_KEY_FILE`
  提供，缺失、长度错误、篡改或错误 key 都 fail closed。
- 浏览器使用登录会话与现有 CSRF/origin 检查访问 `/api/v1/market-data/settings`。服务层
  在任何 repo/key 读取前再次检查 `platform_admin`，更新使用 `expectedRevision` CAS；配置
  与无 secret 的 audit row 在同一事务提交。
- worker 只访问 `/api/v1/internal/market-data/settings`，通过独立高熵 Bearer credential
  认证。该路径是 global guard 的 internal-service 分支，不是 `PublicRoute`；Cookie、Origin
  与 Fetch 元数据一律拒绝，响应 `Cache-Control: no-store`。worker 没有数据库或 master-key
  访问权。
- 未配置 managed endpoint 时，现有环境变量 provider 模式保持不变。页面文案只能说“已保存，
  下一采集周期生效”，不能把 settings GET 当作运行态 applied 确认。

## Consequences

配置迁移仍由现有 `@kunlun/db` migration definitions 显式执行，不在应用启动时运行；
`migrate.js --market-data-settings` 只应用 settings migration。迁移使用的特权 settings DSN
不注入运行时，运行时角色仅需配置行 `SELECT/INSERT/UPDATE` 与审计 `INSERT`，不授予 DDL 或
`DELETE`。连接池设置有界超时，避免锁等待或失联连接占住请求。生产环境的 worker URL 使用
HTTPS；Compose `server:3002` HTTP 仅在显式 local opt-in 时可用。

## Rejected alternatives

- 不把 token 放入 browser storage、普通 `.env` 模板、审计 JSON 或 URL query。
- 不让 worker 直接连接 PostgreSQL 或持有 master key。
- 不使用 `@PublicRoute` 绕过现有全局认证，也不把缺失配置降级成内存持久化。
