"use client";
/**
 * The bell in the header: notifications when an analysis finishes (ready, needs a decision, failed).
 * Polls every 8 s while the tab is visible, and at once when the app fires "askboard:notifications".
 * A new notification also shows a toast, so you can leave the "new analysis" page while it runs.
 */
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, Bell, CheckCircle2, CircleAlert, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";

type Kind = "completed" | "needs_review" | "failed";
type Item = { id: string; kind: Kind; analysis_id: string | null; question: string | null; created_at: string; read: boolean };
type Feed = { unread: number; items: Item[] };

export const NOTIFY_EVENT = "askboard:notifications";
export const ANALYSES_EVENT = "askboard:analyses-changed";
const ICONS = { completed: CheckCircle2, needs_review: AlertTriangle, failed: CircleAlert } as const;
const TONE = { completed: "text-ok bg-ok-soft", needs_review: "text-warn bg-warn-soft", failed: "text-bad bg-bad-soft" } as const;

function ago(iso: string, locale: string) {
  const s = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  if (Math.abs(s) < 60) return rtf.format(s, "second");
  if (Math.abs(s) < 3600) return rtf.format(Math.round(s / 60), "minute");
  if (Math.abs(s) < 86400) return rtf.format(Math.round(s / 3600), "hour");
  return rtf.format(Math.round(s / 86400), "day");
}

export function NotificationBell() {
  const t = useTranslations("app.notifications");
  const locale = useLocale();
  const router = useRouter();
  const [feed, setFeed] = useState<Feed>({ unread: 0, items: [] });
  const [open, setOpen] = useState(false);
  const [toast, setToast] = useState<Item | null>(null);
  const seen = useRef<Set<string> | null>(null);
  const box = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    const res = await fetch("/api/notifications", { cache: "no-store" }).catch(() => null);
    if (!res?.ok) return;
    const data = (await res.json()) as Feed;
    if (seen.current === null) seen.current = new Set(data.items.map((i) => i.id));   // first load: no toast
    else {
      const fresh = data.items.filter((i) => !i.read && !seen.current!.has(i.id));
      fresh.forEach((i) => seen.current!.add(i.id));
      if (fresh.length) {
        setToast(fresh[0]);
        router.refresh();                                          // server pages (overview) show the new analysis
        window.dispatchEvent(new Event(ANALYSES_EVENT));           // client lists (history) reload
      }
    }
    setFeed(data);
  }, [router]);

  useEffect(() => {
    load();
    const tick = setInterval(() => { if (document.visibilityState === "visible") load(); }, 8000);
    const now = () => load();
    window.addEventListener(NOTIFY_EVENT, now);
    document.addEventListener("visibilitychange", now);
    return () => { clearInterval(tick); window.removeEventListener(NOTIFY_EVENT, now); document.removeEventListener("visibilitychange", now); };
  }, [load]);

  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 7000);
    return () => clearTimeout(id);
  }, [toast]);

  useEffect(() => {
    const close = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, []);

  const markRead = async (body: { ids: string[] } | { all: true }) => {
    const res = await fetch("/api/notifications", { method: "POST", headers: { "Content-Type": "application/json" },
                                                   body: JSON.stringify(body) }).catch(() => null);
    if (res?.ok) setFeed((await res.json()) as Feed);
  };
  const openItem = (i: Item) => {
    setOpen(false); setToast(null);
    if (!i.read) void markRead({ ids: [i.id] });
    if (i.analysis_id) router.push(`/app/runs/${i.analysis_id}`);
  };

  return (
    <div ref={box} className="relative">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-haspopup="dialog"
              aria-label={feed.unread ? t("bell_unread", { count: feed.unread }) : t("bell")}
              className="relative grid h-10 w-10 place-items-center rounded-full border border-line bg-surface transition hover:bg-surface-2">
        <Bell className="h-[18px] w-[18px]" />
        {feed.unread > 0 && (
          <span className="absolute -right-1 -top-1 grid h-5 min-w-5 place-items-center rounded-full bg-accent px-1 text-[11px] font-bold text-accent-fg">
            {feed.unread > 9 ? "9+" : feed.unread}
          </span>
        )}
      </button>

      {open && (
        <div role="dialog" aria-label={t("title")} className="card absolute right-0 top-12 z-50 w-[min(22rem,calc(100vw-2rem))] overflow-hidden">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <h2 className="text-sm font-semibold">{t("title")}</h2>
            {feed.unread > 0 && (
              <button type="button" onClick={() => markRead({ all: true })} className="text-xs font-semibold text-primary hover:underline">
                {t("mark_all")}
              </button>
            )}
          </div>
          {feed.items.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-muted">{t("empty")}</p>
          ) : (
            <ul className="max-h-96 overflow-y-auto">
              {feed.items.map((i) => {
                const Icon = ICONS[i.kind];
                return (
                  <li key={i.id}>
                    <button type="button" onClick={() => openItem(i)}
                            className={cn("flex w-full gap-3 px-4 py-3 text-left transition hover:bg-surface-2", !i.read && "bg-primary-soft/40")}>
                      <span className={cn("grid h-8 w-8 shrink-0 place-items-center rounded-full", TONE[i.kind])}><Icon className="h-4 w-4" /></span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm font-semibold">{t(`kind.${i.kind}`)}</span>
                        {i.question && <span className="mt-0.5 block truncate text-xs text-muted">“{i.question}”</span>}
                        <span className="mt-0.5 block text-[11px] text-subtle">{ago(i.created_at, locale)}</span>
                      </span>
                      {!i.read && <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-accent" aria-label={t("unread")} />}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}

      {/* toast for a notification that just arrived */}
      <AnimatePresence>
        {toast && (
          <motion.div role="status" aria-live="polite" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 16 }}
                      className="card fixed bottom-5 right-5 z-[60] flex w-[min(24rem,calc(100vw-2.5rem))] items-start gap-3 p-4 shadow-lift">
            {(() => { const Icon = ICONS[toast.kind]; return <span className={cn("grid h-9 w-9 shrink-0 place-items-center rounded-full", TONE[toast.kind])}><Icon className="h-[18px] w-[18px]" /></span>; })()}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold">{t(`kind.${toast.kind}`)}</p>
              {toast.question && <p className="mt-0.5 truncate text-xs text-muted">“{toast.question}”</p>}
              {toast.analysis_id && (
                <button type="button" onClick={() => openItem(toast)} className="mt-2 text-xs font-semibold text-primary hover:underline">
                  {t("open")}
                </button>
              )}
            </div>
            <button type="button" onClick={() => setToast(null)} aria-label={t("dismiss")} className="rounded-md p-1 text-subtle hover:text-ink">
              <X className="h-4 w-4" />
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
