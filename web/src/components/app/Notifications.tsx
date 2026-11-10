"use client";
/**
 * The bell in the header: notifications when an analysis finishes (ready, needs a decision, failed).
 * Polls every 8 s while the tab is visible, and at once when the app fires "askboard:notifications".
 * A new notification also shows a toast, so you can leave the "new analysis" page while it runs.
 */
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, ArrowRight, Bell, CheckCircle2, CircleAlert, X } from "lucide-react";
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
const STRIPE = { completed: "bg-ok", needs_review: "bg-warn", failed: "bg-bad" } as const;
const BTN = { completed: "bg-ok text-white", needs_review: "bg-warn text-white", failed: "bg-bad text-white" } as const;

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
        <Bell className={cn("h-[18px] w-[18px]", feed.unread > 0 && "origin-top animate-[bellRing_1.2s_ease-in-out_2]")} />
        {feed.unread > 0 && <span aria-hidden className="absolute -right-1 -top-1 h-5 w-5 animate-pulseRing rounded-full bg-accent" />}
        {feed.unread > 0 && (
          <span className="absolute -right-1 -top-1 grid h-5 min-w-5 place-items-center rounded-full bg-accent px-1 text-[11px] font-bold text-accent-fg">
            {feed.unread > 9 ? "9+" : feed.unread}
          </span>
        )}
      </button>

      {open && (
        <motion.div role="dialog" aria-label={t("title")} initial={{ opacity: 0, y: -6, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
                    className="card absolute right-0 top-12 z-50 w-[min(26rem,calc(100vw-2rem))] origin-top-right overflow-hidden shadow-lift">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <h2 className="flex items-center gap-2 text-sm font-semibold">{t("title")}
              {feed.unread > 0 && <span className="rounded-full bg-accent px-1.5 py-px text-[10px] font-bold text-accent-fg">{feed.unread}</span>}
            </h2>
            {feed.unread > 0 && (
              <button type="button" onClick={() => markRead({ all: true })} className="text-xs font-semibold text-primary hover:underline">
                {t("mark_all")}
              </button>
            )}
          </div>
          {feed.items.length === 0 ? (
            <div className="px-6 py-10 text-center">
              <span className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-surface-2 text-subtle"><Bell className="h-5 w-5" /></span>
              <p className="mt-3 text-sm text-muted">{t("empty")}</p>
            </div>
          ) : (
            <div className="max-h-[28rem] overflow-y-auto">
              {([["group_new", feed.items.filter((i) => !i.read)], ["group_earlier", feed.items.filter((i) => i.read)]] as const)
                .filter(([, list]) => list.length > 0).map(([label, list]) => (
                <div key={label}>
                  <div className="sticky top-0 z-10 bg-surface/95 px-4 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-subtle backdrop-blur">
                    {t(label)}
                  </div>
                  <ul className="space-y-1.5 px-2 pb-2">
                    {list.map((i) => <li key={i.id}><NotifCard item={i} onOpen={() => openItem(i)} locale={locale} /></li>)}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </motion.div>
      )}

      {/* toast for a notification that just arrived */}
      <AnimatePresence>
        {toast && (
          <motion.div role="status" aria-live="polite" initial={{ opacity: 0, y: 24, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, x: 40 }} transition={{ type: "spring", stiffness: 300, damping: 26 }}
                      className="card fixed bottom-5 right-5 z-[60] w-[min(25rem,calc(100vw-2.5rem))] overflow-hidden p-0 shadow-lift">
            <span aria-hidden className={cn("absolute inset-y-0 left-0 w-1", STRIPE[toast.kind])} />
            <div className="flex items-start gap-3 p-4 pl-5">
              {(() => { const Icon = ICONS[toast.kind]; return <span className={cn("grid h-10 w-10 shrink-0 place-items-center rounded-xl", TONE[toast.kind])}><Icon className="h-5 w-5" /></span>; })()}
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold">{t(`kind.${toast.kind}`)}</p>
                <p className="mt-0.5 text-xs leading-snug text-muted">{t(`desc.${toast.kind}`)}</p>
                {toast.question && <p className="mt-1.5 truncate rounded-md bg-surface-2 px-2 py-1 text-xs text-ink/80">“{toast.question}”</p>}
                {toast.analysis_id && (
                  <button type="button" onClick={() => openItem(toast)}
                          className={cn("mt-3 inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition hover:opacity-90", BTN[toast.kind])}>
                    {t(`action.${toast.kind}`)}<ArrowRight className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
              <button type="button" onClick={() => setToast(null)} aria-label={t("dismiss")} className="rounded-md p-1 text-subtle hover:bg-surface-2 hover:text-ink">
                <X className="h-4 w-4" />
              </button>
            </div>
            {/* time left before it closes by itself */}
            <motion.span aria-hidden className={cn("absolute bottom-0 left-0 h-0.5", STRIPE[toast.kind])}
                         initial={{ width: "100%" }} animate={{ width: "0%" }} transition={{ duration: 7, ease: "linear" }} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function NotifCard({ item, onOpen, locale }: { item: Item; onOpen: () => void; locale: string }) {
  const t = useTranslations("app.notifications");
  const Icon = ICONS[item.kind];
  return (
    <button type="button" onClick={onOpen}
            className={cn("group relative flex w-full gap-3 overflow-hidden rounded-xl border px-3 py-3 pl-4 text-left transition",
              item.read ? "border-transparent hover:bg-surface-2" : "border-line bg-surface shadow-sm hover:shadow-card")}>
      <span aria-hidden className={cn("absolute inset-y-0 left-0 w-1", STRIPE[item.kind], item.read && "opacity-30")} />
      <span className={cn("grid h-9 w-9 shrink-0 place-items-center rounded-xl", TONE[item.kind], item.read && "opacity-70")}><Icon className="h-[18px] w-[18px]" /></span>
      <span className="min-w-0 flex-1">
        <span className="flex items-start justify-between gap-2">
          <span className={cn("text-sm", item.read ? "font-medium text-muted" : "font-semibold text-ink")}>{t(`kind.${item.kind}`)}</span>
          <span className="shrink-0 text-[10px] text-subtle">{ago(item.created_at, locale)}</span>
        </span>
        {!item.read && <span className="mt-0.5 block text-xs leading-snug text-muted">{t(`desc.${item.kind}`)}</span>}
        {item.question && <span className="mt-1 block truncate text-xs text-subtle">{t("about")} “{item.question}”</span>}
        {!item.read && item.analysis_id && (
          <span className="mt-1.5 inline-flex items-center gap-1 text-xs font-semibold text-primary">
            {t(`action.${item.kind}`)}<ArrowRight className="h-3.5 w-3.5 transition group-hover:translate-x-0.5" />
          </span>
        )}
      </span>
      {!item.read && <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-accent" aria-label={t("unread")} />}
    </button>
  );
}
