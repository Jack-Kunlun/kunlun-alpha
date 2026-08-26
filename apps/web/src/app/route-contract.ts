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
  | "data-quality";

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
  node: string;
  navigation: boolean;
}

export const terminalNavigationGroups: ReadonlyArray<{
  id: TerminalRouteGroup;
  label: string;
  description: string;
}> = [
  { id: "decision", label: "决策视野", description: "从市场到标的的解释链" },
  { id: "workspace", label: "行动工作台", description: "自选、预警与模拟组合" },
  { id: "research", label: "研究与审计", description: "历史证据与回归验证" },
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
    label: "决策总览",
    shortLabel: "总览",
    description: "跨模块入口、状态与解释链索引",
    group: "decision",
    permission: "terminal:read",
    status: "ready",
    node: "P6-N01",
    navigation: true,
  },
  {
    id: "market-overview",
    path: "/market-overview",
    href: "/market-overview",
    label: "市场总览",
    shortLabel: "市场",
    description: "指数、宽度、成交额、情绪与风险状态",
    group: "decision",
    permission: "terminal:read",
    status: "ready",
    node: "P6-N02",
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
    status: "ready",
    node: "P6-N03",
    navigation: true,
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
    status: "ready",
    node: "P6-N04",
    navigation: true,
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
    status: "ready",
    node: "P6-N05",
    navigation: true,
  },
  {
    id: "instruments",
    path: "/instruments",
    href: "/instruments",
    label: "个股透视",
    shortLabel: "个股",
    description: "行情、事件、席位、KOL 与特征聚合",
    group: "decision",
    permission: "terminal:read",
    status: "ready",
    node: "P6-N06",
    navigation: true,
  },
  {
    id: "instrument-detail",
    path: "/instruments/:instrumentId",
    href: "/instruments/600519.SH",
    label: "个股 Intelligence 详情",
    shortLabel: "个股详情",
    description: "标的级点时一致详情与证据链接",
    group: "decision",
    permission: "terminal:read",
    status: "ready",
    node: "P6-N06",
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
    node: "P6-N13",
    navigation: true,
  },
  {
    id: "watchlists",
    path: "/watchlists",
    href: "/watchlists",
    label: "自选与预警",
    shortLabel: "自选",
    description: "组合条件、静默期、通知历史与预览",
    group: "workspace",
    permission: "terminal:read",
    status: "planned",
    node: "P6-N07",
    navigation: true,
  },
  {
    id: "paper",
    path: "/paper",
    href: "/paper",
    label: "模拟组合",
    shortLabel: "模拟",
    description: "PaperAccount、OrderIntent、模拟成交与对账",
    group: "workspace",
    permission: "paper:read",
    status: "planned",
    node: "P6-N08",
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
    status: "ready",
    node: "P2-N10",
    navigation: true,
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
    status: "ready",
    node: "P3-N06",
    navigation: true,
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
    status: "ready",
    node: "P4-N10",
    navigation: true,
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
    status: "ready",
    node: "P5-N13",
    navigation: true,
  },
  {
    id: "data-quality",
    path: "/data-quality",
    href: "/data-quality",
    label: "数据质量",
    shortLabel: "质量",
    description: "数据异常、恢复状态与运维证据",
    group: "research",
    permission: "operations:read",
    status: "ready",
    node: "P1-N12",
    navigation: true,
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
  return terminalRoutes.filter((route) => route.navigation && canAccessTerminalRoute(route, roles));
}
