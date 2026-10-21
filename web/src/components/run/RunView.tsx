"use client";
import { motion } from "framer-motion";
import { ArrowLeft, BarChart3, BookLock, Database, FileSpreadsheet, Fingerprint, ListChecks, MessageCircleQuestion, Activity } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle } from "lucide-react";
import { ChecksPanel, DriftPanel, ExplanationsPanel, JournalPanel, WhyPanel } from "@/components/run/AuditPanels";
import { ComparisonBanner, KpiChart } from "@/components/run/ComparisonPanel";
import { Pipeline } from "@/components/run/Pipeline";
import { Skeleton, StatusBadge, fmtDate } from "@/components/ui/kit";
import { type Analysis, type RunSummary, useApi } from "@/lib/client";
import { cn } from "@/lib/cn";
import { DATASET_INFO } from "@/lib/pipeline";

const TABS = [
  { id: "dashboard", icon: BarChart3 }, { id: "checks", icon: ListChecks }, { id: "explanations", icon: Fingerprint },
  { id: "journal", icon: BookLock }, { id: "drift", icon: Activity }, { id: "why", icon: MessageCircleQuestion },
] as const;
type Tab = (typeof TABS)[number]["id"];

export function RunView({ id, isNew }: { id: string; isNew: boolean }) {
  const t = useTranslations("app");
  const locale = useLocale();
  const analysis = useApi<Analysis>(`/api/analyses/${id}`);
  const a = analysis.data;
  const summary = useApi<RunSummary>(a?.run_id ? `runs/${a.run_id}` : null);
  const [tab, setTab] = useState<Tab>("dashboard");
  const [version, setVersion] = useState(0);
  const [highlight, setHighlight] = useState<number[]>([]);
  const [showResults, setShowResults] = useState(!isNew);
  const results = useRef<HTMLDivElement>(null);

  const refresh = useCallback(() => { void summary.reload(); void analysis.reload(); setVersion((v) => v + 1); },
    [summary, analysis]);
  const onPipelineDone = useCallback(() => {
    setShowResults(true);
    setTimeout(() => results.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 150);
  }, []);
  useEffect(() => { if (isNew) window.history.replaceState(null, "", `/app/runs/${id}`); }, [id, isNew]);

  if (analysis.error?.status === 404) {
    return <div className="card p-8 text-center"><p className="font-semibold">{t("run.not_found")}</p>
      <Link href="/app/history" className="btn-outline mt-4">{t("run.back")}</Link></div>;
  }
  if (!a) return <div className="space-y-4"><Skeleton className="h-24" /><Skeleton className="h-96" /></div>;

  const datasetName = DATASET_INFO[a.dataset] ? t(`datasets.${DATASET_INFO[a.dataset].key}.name`) : a.dataset;
  const report = summary.data?.comparison ?? null;

  return (
    <div className="space-y-6">
      <div>
        <Link href="/app/history" className="inline-flex items-center gap-1.5 text-sm font-medium text-muted hover:text-ink">
          <ArrowLeft className="h-4 w-4" />{t("run.back")}
        </Link>
        <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-2xl font-bold [overflow-wrap:anywhere] sm:text-3xl">“{a.question}”</h1>
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted">
              <span className="inline-flex items-center gap-1.5"><Database className="h-4 w-4" />{datasetName}</span>
              {a.file_name && <span className="inline-flex items-center gap-1.5"><FileSpreadsheet className="h-4 w-4" />{a.file_name}</span>}
              <span>{a.metric} · {a.period_start} → {a.period_end} {t("run.vs")} {a.compare_start} → {a.compare_end}</span>
              <span>{fmtDate(a.created_at, locale)}</span>
            </div>
          </div>
          <StatusBadge status={a.status} label={t(`status.${a.status}`)} />
        </div>
      </div>

      {a.status === "failed" && (
        <div role="alert" className="flex items-start gap-2 rounded-xl border border-bad/30 bg-bad-soft p-4 text-sm text-bad">
          <AlertCircle className="mt-0.5 h-4 w-4" />{t("run.failed")}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[380px_minmax(0,1fr)]">
        <div className="xl:sticky xl:top-20 xl:self-start">
          <Pipeline a={a} summary={summary.data} animate={isNew} datasetName={datasetName} onDone={onPipelineDone} />
        </div>

        <div ref={results} className="min-w-0 scroll-mt-20">
          {!showResults ? (
            <div className="card grid h-full min-h-[320px] place-items-center p-8 text-center text-muted">{t("run.wait_pipeline")}</div>
          ) : (
            <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} className="space-y-5">
              <div role="tablist" aria-label={t("run.tabs_label")} className="flex gap-1 overflow-x-auto rounded-2xl border border-line bg-surface p-1">
                {TABS.map(({ id: tid, icon: Icon }) => (
                  <button key={tid} type="button" role="tab" aria-selected={tab === tid} aria-controls={`panel-${tid}`} id={`tab-${tid}`}
                          onClick={() => setTab(tid)}
                          className={cn("flex shrink-0 items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-medium transition",
                            tab === tid ? "bg-primary text-primary-fg shadow-card" : "text-muted hover:bg-surface-2 hover:text-ink")}>
                    <Icon className="h-4 w-4" />{t(`run.tabs.${tid}`)}
                  </button>
                ))}
              </div>
              <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
                {!a.run_id || !report ? (summary.loading ? <Skeleton className="h-96" /> : <p className="text-sm text-muted">{t("run.no_run")}</p>) : (
                  <>
                    {tab === "dashboard" && (
                      <div className="space-y-5">
                        <ComparisonBanner runId={a.run_id} report={report} canDecide onChanged={refresh} />
                        <KpiChart runId={a.run_id} version={version} />
                      </div>
                    )}
                    {tab === "checks" && <ChecksPanel report={report} />}
                    {tab === "explanations" && <ExplanationsPanel datasetRun={a.dataset} />}
                    {tab === "journal" && <JournalPanel runId={a.run_id} datasetRun={a.dataset} journalId={summary.data?.journal ?? null} highlight={highlight} />}
                    {tab === "drift" && <DriftPanel datasetRun={a.dataset} />}
                    {tab === "why" && <WhyPanel runId={a.run_id} canAsk metric={a.metric}
                                                onCite={(ids) => { setHighlight(ids); setTab("journal");
                                                  setTimeout(() => document.getElementById(`entry-${ids[0]}`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 400); }} />}
                  </>
                )}
              </div>
            </motion.div>
          )}
        </div>
      </div>
    </div>
  );
}
