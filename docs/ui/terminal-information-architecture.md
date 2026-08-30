# P6-N01 终端信息架构

## 目标

昆仑智策终端按用户决策流程组织，不按 API、worker 或数据库名称组织。稳定路径先于业务页面落地，后续 P6 节点只能替换对应占位内容，不能私自改动深链接或权限含义。

## 站点地图

| 视野       | 路径                                         | 模块              | 节点          | 当前状态 |
| ---------- | -------------------------------------------- | ----------------- | ------------- | -------- |
| 决策视野   | `/`                                          | 决策总览          | P6-N01        | 已就绪   |
| 决策视野   | `/market-overview`                           | 市场总览          | P6-N02        | 页面就绪 |
| 决策视野   | `/limit-pool`                                | 涨跌停与连板      | P6-N03        | 路由就绪 |
| 决策视野   | `/rotation`                                  | 轮动与热点        | P6-N04        | 路由就绪 |
| 决策视野   | `/ranking`                                   | Intelligence 排行 | P6-N05        | 路由就绪 |
| 决策视野   | `/instruments`、`/instruments/:instrumentId` | 个股 Intelligence | P6-N06        | 路由就绪 |
| 决策视野   | `/precious-metals`                           | 贵金属基金        | P6-N13        | 路由就绪 |
| 行动工作台 | `/watchlists`                                | 自选与预警        | P6-N07        | 路由就绪 |
| 行动工作台 | `/paper`                                     | 模拟组合          | P6-N08–P6-N12 | 路由就绪 |
| 研究与审计 | `/market-regime`                             | 市场状态回放      | P2-N10        | 已就绪   |
| 研究与审计 | `/event-workbench`                           | 事件证据台        | P3-N06        | 已就绪   |
| 研究与审计 | `/seat-kol`                                  | 席位与 KOL        | P4-N10        | 已就绪   |
| 研究与审计 | `/backtest/regressions`                      | 回测回归          | P5-N13        | 已就绪   |
| 研究与审计 | `/data-quality`                              | 数据质量          | P1-N12        | 已就绪   |

规划路由只显示节点边界和模块说明，不得展示伪造行情、排名、组合或交易状态。

## 权限矩阵

| 角色             | `terminal:read` | `research:read` | `paper:read` | `operations:read` |
| ---------------- | --------------- | --------------- | ------------ | ----------------- |
| `viewer`         | 是              | 否              | 否           | 否                |
| `researcher`     | 是              | 是              | 否           | 否                |
| `paper_operator` | 是              | 否              | 是           | 否                |
| `platform_admin` | 是              | 是              | 是           | 是                |

- 前端矩阵控制导航可见性并为直接深链接提供明确 forbidden 状态。
- 服务端授权仍是最终安全边界，前端角色不得替代 API 权限校验。
- `main.tsx` 只在 Vite 开发环境且缺少会话时注入 `platform_admin`；生产环境缺少或拒绝非法会话角色时降级为 `viewer`。
- 生产角色来自服务端注入的 `window.__KUNLUN_SESSION__.roles`；该值只控制前端呈现，不能代替 API 授权。
- `paper:read` 仅指模拟组合。Phase 0–6 不定义 Broker、QMT、真实账户或真实下单权限。

## 响应式与键盘约定

- `lg` 及以上使用固定侧栏；窄屏使用原生 `details/summary` 导航，不依赖鼠标事件。
- 页面首个可聚焦入口是“跳到主内容”，主内容容器可被程序化聚焦。
- 每个导航区有独立可访问名称，当前链接由 React Router 的 `NavLink` 语义标识。
- 所有链接保留可见 focus ring；减少动画偏好不会被强制覆盖。
- 未知路径进入可返回首页的 404；已知但无权路径进入 forbidden，而不是伪装成 404。

## 路由契约

`apps/web/src/app/route-contract.ts` 是前端站点地图与权限的单一来源，包含：

- 稳定 `id`、`path` 和导航 `href`；
- 用户语言标签、所属视野和说明；
- 所需 permission；
- 对应开发节点与 `ready/planned` 状态；
- 是否进入主导航。

后续节点接入真实页面时必须复用对应 route id，不得复制一套导航或权限系统。

Router 由 `terminalRoutes` 与 `route-elements.tsx` 的 `routeId -> element` 注册表生成，路径不会在 `App.tsx` 二次手写。TypeScript `Record` 和路由遍历测试共同保证每个契约都有页面注册。

## 跨模块筛选上下文

`TerminalFilterContextV1` 以 URL query 为单一来源，只定义跨模块最小公共语义：

- `asOf`：必须是带时区的 RFC3339，解析后规范为 UTC ISO 时间；
- `instrument`：可重复参数，必须是 `600519.SH`、`000001.SZ` 或 `430047.BJ` 形式；
- `version`：运行时固定为 `v1`，供后续兼容升级。

Provider 位于 Layout 边界，所有桌面、移动和首页模块链接都会序列化并保留当前上下文。非法 query 不进入受信筛选值，同时通过 `rejected` 留下明确反馈。P6-N01 不提供业务筛选控件，也不触发 API 请求；后续页面只能消费或更新该公共 Context，不得创建互不兼容的副本。

## 非目标

- 不在 P6-N01 接入市场、排行、预警或模拟组合数据。
- 不新增 API、数据库表、通知或订单逻辑。
- 不把 NAV/iNAV 描述为成交价。
- 不新增任何真实交易入口或凭证配置。
