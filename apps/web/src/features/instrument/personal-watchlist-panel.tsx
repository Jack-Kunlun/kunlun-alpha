import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router";
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
  readPersonalWatchlist,
  savePersonalWatchlist,
  watchlistStorageKey,
  type PersonalWatchlistItem,
} from "./personal-watchlist";

export function PersonalWatchlist({ ownerId }: { ownerId: string | null }) {
  const [items, setItems] = useState<PersonalWatchlistItem[]>([]);
  const [readError, setReadError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const { hrefForRoute } = useTerminalFilters();
  const key = ownerId === null ? null : watchlistStorageKey(ownerId);

  useEffect(() => {
    function read() {
      try {
        setItems(key === null ? [] : readPersonalWatchlist(window.localStorage, key));
        setReadError(null);
      } catch {
        setItems([]);
        setReadError("本机自选暂时无法读取，原内容未覆盖。请检查浏览器存储后刷新页面。");
      }
    }
    read();
    function onStorage(event: StorageEvent) {
      if (event.key === key || event.key === null) read();
    }
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [key]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving || key === null || readError !== null) return;
    setError(null);
    setSaving(true);
    try {
      const incoming = parseWatchlistText(draft);
      if (!navigator.locks) throw new Error("当前浏览器不支持安全的自选保存，请使用新版浏览器");
      const next = await navigator.locks.request(key, () =>
        savePersonalWatchlist(window.localStorage, key, incoming),
      );
      setItems(next);
      setQuery("");
      setMessage(
        `已合并 ${incoming.length} 项自选，当前共 ${next.length} 项。重复代码保留原名称。`,
      );
      setDraft("");
      setOpen(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存失败，输入已保留，请重试");
    } finally {
      setSaving(false);
    }
  }

  const normalized = query.trim().toUpperCase();
  const visible = items.filter((item) =>
    `${item.code} ${item.name}`.toUpperCase().includes(normalized),
  );
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
            保存在当前浏览器，按登录用户分开保存。加入清单不代表行情已覆盖，日线以查询结果为准。
          </p>
        </div>
        <Dialog
          open={open}
          onOpenChange={(next) => {
            if (!saving) {
              setOpen(next);
              setError(null);
            }
          }}
        >
          <DialogTrigger asChild>
            <Button type="button" variant="outline" disabled={key === null || readError !== null}>
              导入自选
            </Button>
          </DialogTrigger>
          <DialogContent showCloseButton={!saving}>
            <DialogHeader className="pr-6 text-left">
              <DialogTitle>导入自选</DialogTitle>
              <DialogDescription>
                每行填写“统一代码 名称”，重复代码会自动合并。取消保留草稿，保存成功后关闭。
              </DialogDescription>
            </DialogHeader>
            <form
              onSubmit={(event) => void submit(event)}
              aria-busy={saving}
              className="grid gap-4"
            >
              <div className="grid gap-2">
                <Label htmlFor="personal-watchlist-import">自选代码与名称</Label>
                <textarea
                  id="personal-watchlist-import"
                  className="min-h-48 w-full resize-y rounded-md border border-input bg-background p-3 font-mono text-sm disabled:opacity-50"
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  disabled={saving}
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
              {error && (
                <p role="alert" className="text-sm text-destructive">
                  {error}
                </p>
              )}
              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  disabled={saving}
                  onClick={() => setOpen(false)}
                >
                  取消
                </Button>
                <Button type="submit" disabled={saving}>
                  {saving ? "保存中…" : "保存自选"}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>
      {readError && (
        <p role="alert" className="text-sm text-destructive">
          {readError}
        </p>
      )}
      {message && (
        <p role="status" className="text-sm text-emerald-700 dark:text-emerald-400">
          {message}
        </p>
      )}
      <div className="grid gap-2">
        <Label htmlFor="personal-watchlist-search">搜索我的自选</Label>
        <Input
          id="personal-watchlist-search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="名称或代码"
        />
      </div>
      <p role="status" className="text-xs text-muted-foreground">
        显示 {visible.length} / {items.length} 项自选
      </p>
      {visible.length === 0 ? (
        <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
          {items.length === 0
            ? "尚未添加自选，点击“导入自选”批量添加。"
            : "没有匹配的自选，请调整搜索。"}
        </p>
      ) : (
        <ul className="grid gap-2 sm:grid-cols-2">
          {visible.map((item) => {
            const href = personalWatchlistHref(item);
            return (
              <li key={item.code} className="min-w-0">
                {href ? (
                  <Link
                    to={hrefForRoute(href)}
                    className="flex h-full items-center justify-between gap-3 rounded-lg border p-3 text-sm outline-none hover:bg-muted focus-visible:ring-[3px] focus-visible:ring-ring/50"
                  >
                    <span className="min-w-0 break-words font-medium">{item.name}</span>
                    <span className="shrink-0 font-mono text-xs text-muted-foreground">
                      {item.code}
                    </span>
                  </Link>
                ) : (
                  <div className="rounded-lg border border-dashed p-3 text-sm">
                    <span className="font-medium">{item.name}</span>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {item.code} · 观察项，行情未接入
                    </p>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
