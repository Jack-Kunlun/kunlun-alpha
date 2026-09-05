export function formatShanghaiTime(value: string | null): string {
  if (value === null) return "未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "未知";
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const fields = new Map(parts.map((part) => [part.type, part.value]));
  return `${fields.get("year") ?? "----"}-${fields.get("month") ?? "--"}-${fields.get("day") ?? "--"} ${fields.get("hour") ?? "--"}:${fields.get("minute") ?? "--"}:${fields.get("second") ?? "--"}（上海）`;
}
