import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import type { InstrumentDailyBar, ServerWatchlistItem } from "@kunlun/shared-types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { useTerminalFilters } from "@/app/filter-context";
import {
  parseWatchlistText,
  personalWatchlistHref,
  type PersonalWatchlistItem,
} from "./personal-watchlist";
import { usePersonalWatchlist, usePersonalWatchlistQuote } from "./use-personal-watchlist";
import { WatchlistDailyComparison } from "./watchlist-daily-comparison";
import {
  PERSONAL_WATCHLIST_MARKETS,
  selectPersonalWatchlistPage,
  type PersonalWatchlistMarketFilter,
} from "./personal-watchlist-filters";

function taskStatus(item: ServerWatchlistItem): string {
  switch (item.market.status) {
    case "PENDING":
      return "已保存，等待真实行情采集";
    case "RUNNING":
      return "正在采集真实日线";
    case "SUCCEEDED":
      return "采集已完成";
    case "EMPTY":
      return "采集已完成，行情源暂无日线";
    case "FAILED":
      return `行情采集失败（${item.market.errorCode ?? "未知原因"}）`;
    case "UNSUPPORTED":
      return `当前行情源暂不支持此市场（${item.market.errorCode ?? "UNSUPPORTED_MARKET"}）`;
  }
}

function QuoteValue({ item, enabled }: { item: ServerWatchlistItem; enabled: boolean }) {
  const query = usePersonalWatchlistQuote(item.code, enabled);
  const bar = query.data?.status === "AVAILABLE" ? query.data.bars[0] : undefined;

  if (!personalWatchlistHref(item)) {
    return (
      <div className="mt-2 text-xs leading-5 text-muted-foreground">
        {item.market.status === "UNSUPPORTED"
          ? `已保存在服务端；港股、新三板和上金所暂未接入当前真实日线源（${item.market.errorCode ?? "UNSUPPORTED_MARKET"}）`
          : `观察项，当前没有可查询的 A 股日线接口 · ${taskStatus(item)}`}
      </div>
    );
  }

  if (bar !== undefined) {
    return <RealDailyQuote bar={bar} task={taskStatus(item)} />;
  }

  if (query.status === "forbidden") {
    return <p className="mt-2 text-xs text-destructive">当前账号无权读取真实日线行情</p>;
  }
  if (query.status === "error") {
    return (
      <p className="mt-2 text-xs text-destructive">
        日线查询失败：{query.error?.message ?? "请求失败"} · {taskStatus(item)}
      </p>
    );
  }
  if (query.status === "loading") {
    return (
      <p className="mt-2 text-xs text-muted-foreground">正在查询真实日线 · {taskStatus(item)}</p>
    );
  }
  if (item.market.status === "PENDING" || item.market.status === "RUNNING") {
    return (
      <p className="mt-2 text-xs text-muted-foreground">尚无可查询日线 · {taskStatus(item)}</p>
    );
  }
  if (item.market.status === "FAILED" || item.market.status === "UNSUPPORTED") {
    return <p className="mt-2 text-xs text-destructive">{taskStatus(item)}</p>;
  }
  return (
    <p className="mt-2 text-xs text-muted-foreground">
      真实行情源尚无可查询日线 · {taskStatus(item)}
    </p>
  );
}

function RealDailyQuote({ bar, task }: { bar: InstrumentDailyBar; task: string }) {
  return (
    <p
      className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground"
      title={`${bar.source} · ${bar.sourceVersion}`}
    >
      <span className="font-medium text-foreground">收盘 {bar.close}</span>
      <span>{bar.date}</span>
      <span>{bar.source}</span>
      <span aria-label={`行情采集状态：${task}`}>· {task}</span>
    </p>
  );
}

export function PersonalWatchlist({ ownerId }: { ownerId: string | null }) {
  const watchlist = usePersonalWatchlist(ownerId);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [market, setMarket] = useState<PersonalWatchlistMarketFilter>("ALL");
  const [page, setPage] = useState(0);
  const { hrefForRoute, value: filters } = useTerminalFilters();
  const items = watchlist.data?.items ?? [];

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving || watchlist.data === null || ownerId === null) return;
    setFormError(null);
    setMessage(null);
    setSaving(true);
    try {
      const incoming: PersonalWatchlistItem[] = parseWatchlistText(draft);
      const result = await watchlist.importItems(incoming);
      setQuery("");
      setMarket("ALL");
      setPage(0);
      setMessage(
        result.nameConflicts.length === 0
          ? `服务端已确认保存 ${incoming.length} 项自选，当前共 ${result.data.items.length} 项。`
          : `服务端已确认保存全部代码；${result.nameConflicts.length} 项已有条目保留服务端名称。`,
      );
      setDraft("");
      setOpen(false);
    } catch (cause) {
      setFormError(cause instanceof Error ? cause.message : "保存失败，输入已保留，请重试");
    } finally {
      setSaving(false);
    }
  }

  const {
    items: visiblePage,
    matchedCount,
    pageCount,
    currentPage,
  } = selectPersonalWatchlistPage(items, { market, query }, page);
  const canImport =
    ownerId !== null &&
    watchlist.data !== null &&
    watchlist.status !== "forbidden" &&
    watchlist.migrationStatus !== "migrating";

  return (
    <section
      aria-labelledby="personal-watchlist-title"
      className="mt-8 space-y-4 rounded-2xl border bg-card p-4 sm:p-6"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id="personal-watchlist-title" className="text-lg font-semibold">
            我的自选
          </h3>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            自选保存在登录账号的服务端。沪深北标的展示真实日线价格、日期和来源；观察项会标明行情支持状态。
          </p>
        </div>
        <Dialog
          open={open}
          onOpenChange={(next) => {
            if (!saving) {
              setOpen(next);
              setFormError(null);
            }
          }}
        >
          <DialogTrigger asChild>
            <Button
              type="button"
              variant="outline"
              disabled={!canImport || watchlist.isImporting}
              title={ownerId === null ? "请先登录" : undefined}
            >
              导入自选
            </Button>
          </DialogTrigger>
          <DialogContent showCloseButton={!saving}>
            <DialogHeader className="pr-6 text-left">
              <DialogTitle>导入自选</DialogTitle>
              <DialogDescription>
                每行填写“统一代码 名称”，重复代码自动合并。保存到服务端成功后关闭；失败时保留输入。
              </DialogDescription>
            </DialogHeader>
            <form
              onSubmit={(event) => void submit(event)}
              aria-busy={saving || watchlist.isImporting}
              className="grid gap-4"
            >
              <div className="grid gap-2">
                <Label htmlFor="personal-watchlist-import">自选代码与名称</Label>
                <textarea
                  id="personal-watchlist-import"
                  className="min-h-48 w-full resize-y rounded-md border border-input bg-background p-3 font-mono text-sm disabled:cursor-not-allowed disabled:opacity-50"
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  disabled={saving || watchlist.isImporting}
                  required
                  maxLength={250000}
                  placeholder={"600519.SH 示例股票\n512400.SH 示例基金"}
                  aria-describedby="personal-watchlist-format"
                />
                <p
                  id="personal-watchlist-format"
                  className="text-xs leading-5 text-muted-foreground"
                >
                  沪深北代码需带 .SH / .SZ / .BJ；HK:、NEEQ:、SGE: 前缀仅作为观察项保存。
                </p>
              </div>
              {formError && (
                <p role="alert" className="text-sm text-destructive">
                  {formError}
                </p>
              )}
              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  disabled={saving || watchlist.isImporting}
                  onClick={() => setOpen(false)}
                >
                  取消
                </Button>
                <Button type="submit" disabled={saving || watchlist.isImporting}>
                  {saving || watchlist.isImporting ? "保存中…" : "保存自选"}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      {ownerId === null && (
        <p role="status" className="text-sm text-muted-foreground">
          请登录后查看和保存服务端自选。
        </p>
      )}
      {watchlist.status === "loading" && watchlist.data === null && (
        <p role="status" className="text-sm text-muted-foreground">
          正在从服务端读取自选…
        </p>
      )}
      {watchlist.status === "forbidden" && (
        <p role="alert" className="text-sm text-destructive">
          当前账号无权读取服务端自选。
        </p>
      )}
      {watchlist.status === "error" && watchlist.data === null && (
        <div className="flex flex-wrap items-center justify-between gap-3" role="alert">
          <p className="text-sm text-destructive">
            服务端自选读取失败：{watchlist.error?.message ?? "请求失败"}。本机迁移备份保持不变。
          </p>
          <Button type="button" variant="outline" onClick={watchlist.refresh}>
            重试读取
          </Button>
        </div>
      )}
      {watchlist.data !== null && watchlist.error !== null && (
        <p role="status" className="text-sm text-destructive">
          服务端刷新失败，当前显示上次已读取的数据：{watchlist.error.message}
        </p>
      )}
      {watchlist.refreshing && (
        <p role="status" className="text-xs text-muted-foreground">
          正在刷新服务端自选…
        </p>
      )}

      {watchlist.migrationStatus === "migrating" && (
        <p role="status" className="text-sm text-muted-foreground">
          正在将本机自选安全迁移到服务端；本机原清单会继续保留为备份。
        </p>
      )}
      {watchlist.migrationStatus === "error" && (
        <div className="flex flex-wrap items-center justify-between gap-3" role="alert">
          <p className="text-sm text-destructive">
            本机自选尚未得到服务端完整确认：{watchlist.migrationError?.message ?? "迁移失败"}
            。原清单已保留。
          </p>
          <Button type="button" variant="outline" onClick={() => void watchlist.retryMigration()}>
            重试迁移
          </Button>
        </div>
      )}
      {watchlist.migrationStatus === "complete" && (
        <div role="status" className="space-y-1 text-sm text-emerald-700 dark:text-emerald-400">
          <p>本机自选已由服务端确认；浏览器原清单继续保留为迁移备份。</p>
          {watchlist.migrationNameConflicts.length > 0 && (
            <p className="text-xs leading-5">
              {watchlist.migrationNameConflicts.length} 项已有自选保留服务端原名称。
            </p>
          )}
        </div>
      )}
      {message && (
        <p role="status" className="text-sm text-emerald-700 dark:text-emerald-400">
          {message}
        </p>
      )}

      {watchlist.data !== null && (
        <>
          <div className="flex flex-wrap items-end gap-4">
            <div className="grid min-w-40 gap-2">
              <Label htmlFor="personal-watchlist-market">市场</Label>
              <select
                id="personal-watchlist-market"
                value={market}
                onChange={(event) => {
                  const selected = PERSONAL_WATCHLIST_MARKETS.find(
                    (option) => option.value === event.target.value,
                  );
                  if (selected !== undefined) {
                    setMarket(selected.value);
                    setPage(0);
                  }
                }}
                aria-describedby="personal-watchlist-market-hint"
                className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-input/30"
              >
                {PERSONAL_WATCHLIST_MARKETS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="grid min-w-40 flex-1 gap-2">
              <Label htmlFor="personal-watchlist-search">搜索我的自选</Label>
              <Input
                id="personal-watchlist-search"
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setPage(0);
                }}
                placeholder="名称或代码"
              />
            </div>
            <Button
              type="button"
              variant="outline"
              disabled={market === "ALL" && query === ""}
              onClick={() => {
                setMarket("ALL");
                setQuery("");
                setPage(0);
              }}
            >
              重置筛选
            </Button>
            <WatchlistDailyComparison
              key={`${ownerId}|${filters.asOf ?? "CURRENT"}|${market}|${query}|${currentPage}`}
              items={visiblePage}
            />
          </div>
          <p id="personal-watchlist-market-hint" className="text-xs text-muted-foreground">
            未接入观察项按代码分类，不等同于采集失败或行情缺失。
          </p>
          <p role="status" className="text-xs text-muted-foreground">
            显示 {matchedCount} / {items.length} 项自选
            {matchedCount > 0 ? ` · 第 ${currentPage + 1} / ${pageCount} 页` : ""}
          </p>
          {matchedCount === 0 ? (
            <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
              {items.length === 0
                ? "服务端尚未保存自选，点击“导入自选”批量添加。"
                : "没有匹配的自选，请调整市场或搜索条件。"}
            </p>
          ) : (
            <>
              <ul className="grid gap-2 sm:grid-cols-2">
                {visiblePage.map((item) => {
                  const href = personalWatchlistHref(item);
                  return (
                    <li key={item.code} className="min-w-0">
                      <div className="h-full rounded-lg border p-3 text-sm">
                        <div className="flex items-start justify-between gap-3">
                          {href ? (
                            <Link
                              to={hrefForRoute(href)}
                              className="min-w-0 break-words font-medium outline-none hover:underline focus-visible:ring-[3px] focus-visible:ring-ring/50"
                            >
                              {item.name}
                            </Link>
                          ) : (
                            <span className="min-w-0 break-words font-medium">{item.name}</span>
                          )}
                          <span className="shrink-0 font-mono text-xs text-muted-foreground">
                            {item.code}
                          </span>
                        </div>
                        <QuoteValue item={item} enabled />
                      </div>
                    </li>
                  );
                })}
              </ul>
              {pageCount > 1 && (
                <div className="flex items-center justify-between gap-3">
                  <Button
                    type="button"
                    variant="outline"
                    disabled={currentPage === 0}
                    onClick={() => setPage(Math.max(0, currentPage - 1))}
                  >
                    上一页
                  </Button>
                  <span className="text-xs text-muted-foreground">
                    {currentPage + 1} / {pageCount}
                  </span>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={currentPage + 1 >= pageCount}
                    onClick={() => setPage(Math.min(pageCount - 1, currentPage + 1))}
                  >
                    下一页
                  </Button>
                </div>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
