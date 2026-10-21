"use client";
import { ArrowRight, FileSearch, Loader2, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { Empty, Skeleton, StatusBadge, fmtDate } from "@/components/ui/kit";
import { api, type Analysis, useApi } from "@/lib/client";
import { cn } from "@/lib/cn";
import { DATASET_INFO } from "@/lib/pipeline";

const FILTERS = ["all", "needs_review", "completed", "failed"] as const;

export function HistoryList() {
  const t = useTranslations("app");
  const locale = useLocale();
  const { data, loading, setData } = useApi<Analysis[]>("/api/analyses");
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");
  const [removing, setRemoving] = useState<string | null>(null);

  const items = useMemo(() => (data ?? []).filter((a) =>
    (filter === "all" || a.status === filter) &&
    `${a.question} ${a.metric} ${a.dataset}`.toLowerCase().includes(q.trim().toLowerCase())), [data, q, filter]);

  async function remove(a: Analysis) {
    if (!window.confirm(t("history.confirm"))) return;
    setRemoving(a.id);
    try {
      await api(`/api/analyses/${a.id}`, { method: "DELETE" });
      setData((d) => (d ?? []).filter((x) => x.id !== a.id));
    } finally { setRemoving(null); }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold sm:text-3xl">{t("history.title")}</h1>
          <p className="mt-1 text-muted">{t("history.subtitle")}</p>
        </div>
        <Link href="/app/new" className="btn-primary">{t("overview.cta")}</Link>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-[220px] flex-1">
          <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle" />
          <label htmlFor="hq" className="sr-only">{t("history.search")}</label>
          <input id="hq" className="input pl-10" placeholder={t("history.search")} value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="flex gap-1 rounded-xl border border-line bg-surface p-1" role="group" aria-label={t("history.filter")}>
          {FILTERS.map((f) => (
            <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}
                    className={cn("rounded-lg px-3 py-1.5 text-sm font-medium transition", filter === f ? "bg-primary text-primary-fg" : "text-muted hover:text-ink")}>
              {f === "all" ? t("history.all") : t(`status.${f}`)}
            </button>
          ))}
        </div>
      </div>

      {loading && !data ? <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-20" />)}</div>
        : items.length === 0 ? (
          <Empty icon={FileSearch} title={data?.length ? t("history.no_match") : t("overview.empty_title")}
                 text={data?.length ? undefined : t("overview.empty_text")}
                 action={!data?.length ? <Link href="/app/new" className="btn-primary">{t("overview.cta")}</Link> : undefined} />
        ) : (
          <ul className="space-y-3">
            {items.map((a) => (
              <li key={a.id} className="card group flex flex-wrap items-center gap-4 p-4 transition hover:shadow-lift">
                <Link href={`/app/runs/${a.id}`} className="flex min-w-0 flex-1 items-center gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="line-clamp-2 break-words font-semibold [overflow-wrap:anywhere]" title={a.question}>{a.question}</div>
                    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
                      <span>{DATASET_INFO[a.dataset] ? t(`datasets.${DATASET_INFO[a.dataset].key}.name`) : a.dataset}</span>
                      <span>{a.metric}{a.dimensions[0] ? ` · ${a.dimensions[0].replace(/_/g, " ")}` : ""}</span>
                      <span>{a.period_start} → {a.period_end}</span>
                      {a.decision && a.decision !== "pending" && <span>{t(`history.decision.${a.decision}`)}</span>}
                      <span>{fmtDate(a.created_at, locale)}</span>
                    </div>
                  </div>
                  <StatusBadge status={a.status} label={t(`status.${a.status}`)} />
                  <ArrowRight className="hidden h-4 w-4 text-subtle transition group-hover:translate-x-0.5 sm:block" />
                </Link>
                <button type="button" onClick={() => remove(a)} disabled={removing === a.id} aria-label={t("history.remove")}
                        title={t("history.remove")} className="btn-ghost h-9 w-9 p-0 text-muted hover:text-bad">
                  {removing === a.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                </button>
              </li>
            ))}
          </ul>
        )}
      <p className="text-xs text-muted">{t("history.note")}</p>
    </div>
  );
}
