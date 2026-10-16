# 本地管理员登录运行手册

昆仑智策 Web 终端默认要求登录。当前仅支持一个本地 `platform_admin`，不提供开放注册、OAuth、
找回密码、MFA、真实账户或真实下单权限。密码只在交互式初始化进程内出现，PostgreSQL 保存
版本化 scrypt 哈希；浏览器只持有 `HttpOnly` 会话 Cookie，数据库只保存会话令牌的 SHA-256
摘要。

## 首次初始化

1.0 使用精简入口应用现有 PostgreSQL migration 并启动本地应用：

```bash
pnpm v1:up
```

随后在交互式终端中创建首个管理员。密码输入不会回显，也不能通过参数或环境变量传入：

```bash
docker compose \
  -f infra/docker/docker-compose.yml \
  -f infra/docker/docker-compose.apps.yml \
  --env-file infra/docker/.env \
  exec server node apps/server/dist/auth-bootstrap.js \
  --username admin \
  --display-name 本地管理员
```

命令为 create-only：只要 `auth_users` 已有记录就会 fail closed，不会覆盖密码或角色。不要把密码
写入 `.env`、shell history、日志、截图或仓库文件。

直接在宿主机运行时，先构建 Server，并把 `AUTH_POSTGRES_DSN` 指向已经执行 migration 的本地
PostgreSQL，再运行同一交互式命令：

```bash
pnpm --filter @kunlun/server build
pnpm --filter @kunlun/server auth:bootstrap -- --username admin --display-name 本地管理员
```

## Cookie、会话与 CSRF

- 会话闲置 30 分钟失效，绝对有效期 8 小时；退出会在 PostgreSQL 撤销会话。
- 登录后可从页眉用户名进入“账户安全”，查看当前有效会话、撤销其他会话并修改密码。界面只展示
  不可用于认证的派生会话引用，不返回 Cookie、原始 token 或数据库中的 token 摘要。
- 修改密码必须再次验证当前密码；密码哈希更新和其他会话撤销在同一个 PostgreSQL 语句中提交。
  当前会话保留，以避免更新成功后丢失结果确认；其他会话立即失效。
- 修改类请求必须同时通过精确 Origin/Referer 检查、Fetch Metadata 检查（存在时）和绑定当前
  会话的 `X-CSRF-Token`。
- 本地 HTTP 只能显式设置 `AUTH_ALLOW_INSECURE_COOKIE=true`，且
  `AUTH_PUBLIC_ORIGIN` 必须是 `localhost`、`127.0.0.1` 或 `[::1]` 的精确 origin。
- 非本地部署必须使用 HTTPS、`AUTH_ALLOW_INSECURE_COOKIE=false` 和精确的
  `AUTH_PUBLIC_ORIGIN`；此时 Cookie 名为 `__Host-kunlun_session`，并带 `Secure`、`HttpOnly`、
  `SameSite=Strict` 和 `Path=/`。

## 故障排查

- `401`：会话缺失、被撤销、闲置超时或达到绝对有效期，重新登录。
- `403 请求来源验证失败`：检查浏览器地址是否与 `AUTH_PUBLIC_ORIGIN` 完全一致。
- `403 CSRF 验证失败`：刷新页面重新取得会话绑定的 CSRF token，不要重放旧请求。
- `429`：15 分钟窗口内失败次数超过限制，等待窗口结束；不要通过删除审计记录绕过限制。
- Bootstrap 报告已有用户：当前命令不会覆盖既有账户。能够登录时应使用“账户安全”修改密码；
  无法登录时先保留数据库与会话证据，再走经批准的凭据恢复流程，不要直接删除 `auth_users` 或
  `auth_sessions`。

健康检查、Prometheus metrics 与 API 根路径保持公开；其他控制面路由由全局认证守卫默认拒绝
匿名访问。登录只授予研究终端管理角色，不会增加 Broker、QMT 或真实订单能力。
