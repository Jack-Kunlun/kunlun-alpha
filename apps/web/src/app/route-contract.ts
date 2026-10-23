export type TerminalPermission =
  "terminal:read" | "research:read" | "paper:read" | "operations:read";

export type TerminalRole = "viewer" | "researcher" | "paper_operator" | "platform_admin";

export type TerminalRouteGroup = "decision" | "workspace" | "research";

export type TerminalRouteId =
  | "home"
  | "market-overview"
  | "limit-pool"
  | "rotation"
  | "ranking"
  | "instruments"
  | "instrument-detail"
  | "precious-metals"
  | "watchlists"
  | "paper"
  | "market-regime"
  | "event-workbench"
  | "seat-kol"
  | "backtest-regressions"
  | "data-quality"
  | "market-data-settings";

export interface TerminalRouteContract {
  id: TerminalRouteId;
  path: string;
  href: string;
  label: string;
  shortLabel: string;
  description: string;
  group: TerminalRouteGroup;
  permission: TerminalPermission;
  status: "ready" | "planned";
  navigation: boolean;
}

export const terminalNavigationGroups: ReadonlyArray<{
  id: TerminalRouteGroup;
  label: string;
  description: string;
}> = [
  { id: "decision", label: "行情研究", description: "市场日线与标的查询" },
  { id: "workspace", label: "研究工作区", description: "自选、提醒与模拟账本" },
  { id: "research", label: "数据与运维", description: "行情来源和运行状态" },
];

export const terminalRolePermissions: Readonly<
  Record<TerminalRole, readonly TerminalPermission[]>
> = {
  viewer: ["terminal:read"],
  researcher: ["terminal:read", "research:read"],
  paper_operator: ["terminal:read", "paper:read"],
  platform_admin: ["terminal:read", "research:read", "paper:read", "operations:read"],
};

export const terminalRoutes: readonly TerminalRouteContract[] = [
  {
    id: "home",
    path: "/",
    href: "/",
    label: "首页",
    shortLabel: "首页",
    description: "沪深日线行情与自选提醒入口",
    group: "decision",
    permission: "terminal:read",
    status: "ready",
    navigation: true,
  },
  {
    id: "market-overview",
    path: "/market-overview",
    href: "/market-overview",
    label: "市场日线",
    shortLabel: "市场",
    description: "已接入标的的历史日线和行情日期",
    group: "decision",
    permission: "terminal:read",
    status: "ready",
    navigation: true,
  },
  {
    id: "limit-pool",
    path: "/limit-pool",
    href: "/limit-pool",
    label: "涨跌停与连板",
    shortLabel: "涨停池",
    description: "池、梯队、晋级率与个股证据",
    group: "decision",
    permission: "terminal:read",
    status: "planned",
    navigation: false,
  },
  {
    id: "rotation",
    path: "/rotation",
    href: "/rotation",
    label: "轮动与热点",
    shortLabel: "轮动",
    description: "热点生命周期、板块交叉事件与历史回放",
    group: "decision",
    permission: "terminal:read",
    status: "planned",
    navigation: false,
  },
  {
    id: "ranking",
    path: "/ranking",
    href: "/ranking",
    label: "Intelligence 排行",
    shortLabel: "排行",
    description: "版本化特征贡献与可解释排行",
    group: "decision",
    permission: "terminal:read",
    status: "planned",
    navigation: false,
  },
  {
    id: "instruments",
    path: "/instruments",
    href: "/instruments",
    label: "标的日线",
    shortLabel: "标的",
    description: "已接入沪深标的的历史日线和行情来源",
    group: "decision",
    permission: "terminal:read",
    status: "ready",
    navigation: true,
  },
  {
    id: "instrument-detail",
    path: "/instruments/:instrumentId",
    href: "/instruments/600519.SH",
    label: "标的日线详情",
    shortLabel: "日线详情",
    description: "单个标的的历史日线详情",
    group: "decision",
    permission: "terminal:read",
    status: "ready",
    navigation: false,
  },
  {
    id: "precious-metals",
    path: "/precious-metals",
    href: "/precious-metals",
    label: "贵金属基金",
    shortLabel: "贵金属",
    description: "场内黄金、白银基金的行情、估值参考与事件",
    group: "decision",
    permission: "terminal:read",
    status: "planned",
    navigation: false,
  },
  {
    id: "watchlists",
    path: "/watchlists",
    href: "/watchlists",
    label: "自选与提醒",
    shortLabel: "自选",
    description: "管理自选标的及价格、涨跌幅站内提醒",
    group: "workspace",
    permission: "terminal:read",
    status: "ready",
    navigation: true,
  },
  {
    id: "paper",
    path: "/paper",
    href: "/paper",
    label: "模拟组合",
    shortLabel: "模拟",
    description: "本地模拟账户的资金与持仓账本，不开放模拟成交",
    group: "workspace",
    permission: "paper:read",
    status: "ready",
    navigation: true,
  },
  {
    id: "market-regime",
    path: "/market-regime",
    href: "/market-regime",
    label: "市场状态回放",
    shortLabel: "状态回放",
    description: "已落库的情绪与轮动历史快照",
    group: "research",
    permission: "research:read",
    status: "planned",
    navigation: false,
  },
  {
    id: "event-workbench",
    path: "/event-workbench",
    href: "/event-workbench",
    label: "事件证据台",
    shortLabel: "事件",
    description: "事件、主题、证据与人工反馈",
    group: "research",
    permission: "research:read",
    status: "planned",
    navigation: false,
  },
  {
    id: "seat-kol",
    path: "/seat-kol",
    href: "/seat-kol",
    label: "席位与 KOL",
    shortLabel: "席位 KOL",
    description: "席位证据、Claim 与绩效审计",
    group: "research",
    permission: "research:read",
    status: "planned",
    navigation: false,
  },
  {
    id: "backtest-regressions",
    path: "/backtest/regressions",
    href: "/backtest/regressions",
    label: "回测回归",
    shortLabel: "回归",
    description: "确定性制品、差异与基线审计",
    group: "research",
    permission: "research:read",
    status: "planned",
    navigation: false,
  },
  {
    id: "data-quality",
    path: "/data-quality",
    href: "/data-quality",
    label: "数据质量",
    shortLabel: "质量",
    description: "日线行情覆盖与已发布异常证据",
    group: "research",
    permission: "operations:read",
    status: "ready",
    navigation: true,
  },
  {
    id: "market-data-settings",
    path: "/settings/market-data",
    href: "/settings/market-data",
    label: "行情源配置",
    shortLabel: "行情源",
    description: "实例级 AKShare / Tushare 采集配置与 token 状态",
    group: "research",
    permission: "operations:read",
    status: "planned",
    navigation: false,
  },
];

export function getTerminalRoute(id: TerminalRouteId): TerminalRouteContract {
  const route = terminalRoutes.find((candidate) => candidate.id === id);
  if (!route) throw new Error(`Unknown terminal route: ${id}`);
  return route;
}

export function canAccessTerminalRoute(
  route: TerminalRouteContract,
  roles: readonly TerminalRole[],
): boolean {
  return roles.some((role) => terminalRolePermissions[role].includes(route.permission));
}

export function visibleTerminalRoutes(roles: readonly TerminalRole[]): TerminalRouteContract[] {
  return terminalRoutes.filter(
    (route) => route.status === "ready" && route.navigation && canAccessTerminalRoute(route, roles),
  );
}
