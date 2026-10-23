export const LOCAL_TERMINAL_STOCKS = [
  { instrumentId: "000001.SZ", name: "平安银行", sector: "银行" },
  { instrumentId: "002594.SZ", name: "比亚迪", sector: "汽车" },
  { instrumentId: "300750.SZ", name: "宁德时代", sector: "电力设备" },
  { instrumentId: "301236.SZ", name: "软通动力", sector: "计算机" },
  { instrumentId: "600000.SH", name: "浦发银行", sector: "银行" },
  { instrumentId: "600519.SH", name: "贵州茅台", sector: "食品饮料" },
  { instrumentId: "601318.SH", name: "中国平安", sector: "非银金融" },
  { instrumentId: "688981.SH", name: "中芯国际", sector: "电子" },
] as const;

export type LocalTerminalStock = (typeof LOCAL_TERMINAL_STOCKS)[number];
