"use client";
/* The analysis page: the ANSWER first (navy hero: the number, and whether the comparison is fair),
   then "behind the answer": the 13 agents on a rail and an inspector showing what the selected one produced. */
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertCircle, ArrowLeft, ArrowRight, ChevronLeft, ChevronRight, Database, FileSpreadsheet, FlaskConical,
  MessageCircleQuestion, ShieldAlert, ShieldCheck, TrendingDown, TrendingUp, UserCheck,
} from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChecksPanel, DriftPanel, ExplanationsPanel, JournalPanel, WhyPanel } from "@/components/run/AuditPanels";
import { ComparisonBanner, KpiChart } from "@/components/run/ComparisonPanel";
import { DashboardCharts, DashboardDecisions } from "@/components/run/DashboardCharts";
import { ReviewCard, UploadProgress } from "@/components/run/UploadProgress";
import { ICONS, PipelineRail, StateDot } from "@/components/run/PipelineRail";
import {
  AnalysisPanel, CleaningPanel, ColumnTypesPanel, EtlPanel, Insights, LineagePanel, PiiPanel, ProfilingPanel,
  RequestPanel, SimilarityPanel, UploadPanel,
} from "@/components/run/StagePanels";
import { Skeleton, StatusBadge, fmtDate, fmtNum, fmtPct } from "@/components/ui/kit";
import { type Analysis, type ComparisonReport, type PipelineView, type Progress, type ProposedFix, type RunSummary, useApi } from "@/lib/client";
import { cn } from "@/lib/cn";
import { DATASET_INFO, STAGES, type StageState, isUploadRunId, stageState } from "@/lib/pipeline";

const AUDIT_TABS = ["explanations", "journal", "drift", "why"] as const;
type AuditTab = (typeof AUDIT_TABS)[number];

export function RunView({ id, isNew }: { id: string; isNew: boolean }) {
  const t = useTranslations("app");
  const locale = useLocale();
  const analysis = useApi<Analysis>(`/api/analyses/${id}`);
  const a = analysis.data;
  const summary = useApi<RunSummary>(a?.run_id ? `runs/${a.run_id}` : null);
  const pipe = useApi<PipelineView>(a?.run_id ? `runs/${a.run_id}/pipeline` : null);
  // an uploaded dataset: the whole DAG runs in the API; its real progress is polled while it works
  const isUpload = isUploadRunId(a?.run_id);
  const prog = useApi<Progress>(isUpload && a?.run_id ? `runs/${a.run_id}/progress` : null);
  const progState = prog.data?.state;
  const okCount = prog.data?.steps.filter((s) => s.status === "SUCCESS").length ?? 0;
  const [selected, setSelected] = useState("analysis");
  const [auditTab, setAuditTab] = useState<AuditTab>("explanations");
  const [version, setVersion] = useState(0);
  const [highlight, setHighlight] = useState<number[]>([]);
  const [progress, setProgress] = useState(isNew ? 0 : STAGES.length);
  const inspector = useRef<HTMLDivElement>(null);

  useEffect(() => { if (isNew) window.history.replaceState(null, "", `/app/runs/${id}`); }, [id, isNew]);
  useEffect(() => {                                     // stages light up one after the other
    if (progress >= STAGES.length) return;
    const tm = setTimeout(() => setProgress((p) => p + 1), STAGES[progress].mode === "live" ? 380 : 220);
    return () => clearTimeout(tm);
  }, [progress]);

  useEffect(() => {
    if (progState !== "running") return;
    const tm = setInterval(() => { if (document.visibilityState === "visible") void prog.reload(); }, 2500);
    return () => clearInterval(tm);
  }, [progState]);                                                   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {                                                  // a step finished: show its output
    if (!isUpload) return;
    void pipe.reload(); void summary.reload(); void analysis.reload(); setVersion((v) => v + 1);
  }, [okCount, progState]);                                          // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = useCallback(() => { void summary.reload(); void analysis.reload(); void prog.reload(); setVersion((v) => v + 1); },
    [summary, analysis, prog]);
  const goTo = useCallback((stage: string, tab?: AuditTab) => {
    setSelected(stage); if (tab) setAuditTab(tab);
    setTimeout(() => inspector.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
  }, []);

  const report = summary.data?.comparison ?? null;
  const view = pipe.data;
  const states = useMemo(() => {
    const out: Record<string, StageState> = {};
    for (const s of STAGES) {
      const info = view?.stages.find((x) => x.step === s.id);
      let st = stageState(s, a?.dataset ?? "", info?.available);
      // the request is Malek's only when his parser proposed it (otherwise it was typed in the form)
      if (s.id === "request" && st === "live" && !Object.keys(view?.request?.matched_terms ?? {}).length) st = "demo";
      out[s.id] = st;
    }
    return out;
  }, [view, a?.dataset]);

  if (analysis.error?.status === 404) {
    return <div className="card p-8 text-center"><p className="font-semibold">{t("run.not_found")}</p>
      <Link href="/app/history" className="btn-outline mt-4">{t("run.back")}</Link></div>;
  }
  if (!a) return <div className="space-y-4"><Skeleton className="h-64 rounded-3xl" /><Skeleton className="h-40" /><Skeleton className="h-96" /></div>;

  const info = DATASET_INFO[a.dataset];
  const datasetName = info ? t(`datasets.${info.key}.name`) : a.dataset;
  const done = progress >= STAGES.length;
  const blocked = report?.checks.some((c) => c.status === "blocking") ?? false;
  const liveCount = Object.values(states).filter((s) => s === "live").length;
  const testDouble = summary.data?.journal === "integration";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link href="/app/history" className="inline-flex items-center gap-1.5 text-sm font-medium text-muted hover:text-ink">
          <ArrowLeft className="h-4 w-4" />{t("run.back")}
        </Link>
        <StatusBadge status={a.status} label={t(`status.${a.status}`)} />
      </div>

      <Hero a={a} report={report} view={view} done={done} datasetName={isUpload ? t("datasets.upload") : datasetName} liveCount={liveCount}
            working={isUpload && progState !== "done"} onWhy={() => goTo("auditor", "why")} onChecks={() => goTo("comparisons")} />

      {isUpload && prog.data && progState !== "done" && <UploadProgress p={prog.data} />}
      {isUpload && a.run_id && prog.data?.review && <ReviewCard runId={a.run_id} review={prog.data.review} onAnswered={refresh} />}

      {a.status === "failed" && !isUpload && (
        <div role="alert" className="flex items-start gap-2 rounded-xl border border-bad/30 bg-bad-soft p-4 text-sm text-bad">
          <AlertCircle className="mt-0.5 h-4 w-4" />{t("run.failed")}
        </div>
      )}
      {testDouble && (
        <p className="flex items-start gap-2 rounded-xl border border-line bg-surface-2 p-3 text-xs text-muted">
          <FlaskConical className="mt-0.5 h-4 w-4 shrink-0 text-primary" />{t("run.test_double")}
        </p>
      )}

      <AnimatePresence>
        {done && a.run_id && report && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="space-y-6">
            <ComparisonBanner runId={a.run_id} report={report} canDecide onChanged={refresh} />
            <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
              <div className="min-w-0">
                <DashboardCharts runId={a.run_id} version={version} unit={view?.analysis?.unit ?? ""}
                                 onEmpty={<KpiChart runId={a.run_id} version={version} />} />
              </div>
              <aside className="card p-5">
                <div className="flex items-center justify-between gap-2">
                  <h2 className="font-semibold">{t("run.insights")}</h2>
                  <span className="text-[11px] text-subtle">Rabeb · BO1</span>
                </div>
                {view?.analysis ? <Insights items={view.analysis.insights} /> : <p className="mt-2 text-sm text-muted">{t("run.no_analysis")}</p>}
                {view?.analysis && (
                  <button type="button" onClick={() => goTo("analysis")} className="mt-4 inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline">
                    {t("run.checks_passed", { ok: view.analysis.validations.filter((c) => c.passed).length, n: view.analysis.validations.length })}<ArrowRight className="h-3.5 w-3.5" />
                  </button>
                )}
              </aside>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <section className="card overflow-hidden p-0" aria-labelledby="behind-title">
        <div className="flex flex-wrap items-end justify-between gap-3 px-5 pt-5 sm:px-6">
          <div>
            <h2 id="behind-title" className="font-display text-xl font-bold">{t("rail.title")}</h2>
            <p className="text-sm text-muted">{t("rail.subtitle", { live: liveCount, total: STAGES.length })}</p>
          </div>
          <div className="flex flex-wrap gap-3 text-xs text-muted">
            {(["live", "demo", "missing"] as const).map((s) => <span key={s} className="inline-flex items-center gap-1.5"><StateDot state={s} />{t(`state.${s}`)}</span>)}
          </div>
        </div>
        <div className="px-4 pt-4 sm:px-5">
          <PipelineRail states={states} selected={selected} onSelect={setSelected} progress={progress}
                        real={isUpload ? Object.fromEntries((prog.data?.steps ?? []).map((s) => [s.step, s.status])) : undefined}
                        alerts={[...(blocked && report?.user_decision === "pending" ? ["comparisons"] : []),
                                 ...(prog.data?.steps ?? []).filter((s) => s.status === "NEEDS_REVIEW" || s.status === "FAILED").map((s) => s.step)]} />
        </div>
        <div ref={inspector} id="stage-inspector" role="tabpanel" className="scroll-mt-20 border-t border-line bg-bg/40 p-5 sm:p-6">
          {!done ? (
            <p className="py-10 text-center text-sm text-muted" aria-live="polite">{t("rail.working", { name: t(`stages.${STAGES[progress].id}.name`) })}</p>
          ) : (
            <Inspector stage={selected} state={states[selected]} a={a} view={view} viewLoading={pipe.loading} report={report}
                       summary={summary.data} datasetName={datasetName} auditTab={auditTab} setAuditTab={setAuditTab}
                       highlight={highlight} setHighlight={setHighlight} onSelect={setSelected} version={version}
                       pending={isUpload && progState !== "done"} />
          )}
        </div>
      </section>
    </div>
  );
}

// ---- the answer -------------------------------------------------------------------------------------------------
function Hero({ a, report, view, done, datasetName, liveCount, working, onWhy, onChecks }:
  { a: Analysis; report: ComparisonReport | null; view: PipelineView | null; done: boolean; datasetName: string;
    liveCount: number; working: boolean; onWhy: () => void; onChecks: () => void }) {
  const t = useTranslations("app.hero");
  const locale = useLocale();
  const res = view?.analysis ?? null;
  const fixes = report ? ([report.proposed_fix, ...report.alternatives].filter(Boolean) as ProposedFix[]) : [];
  const chosen = report?.user_decision === "accepted" ? fixes.find((f) => f.method === report.chosen_fix) ?? null : null;
  const blocking = report?.checks.some((c) => c.status === "blocking") ?? false;
  const warning = report?.checks.some((c) => c.status === "warning") ?? false;
  const head = chosen ? { cur: chosen.value_current, prev: chosen.value_previous, chg: chosen.change_pct, unit: chosen.unit, label: t("fair") }
    : res ? { cur: res.value_current, prev: res.value_previous, chg: res.change_pct, unit: res.unit, label: t("as_asked") } : null;
  const verdict = !report?.has_comparison ? null
    : chosen ? { tone: "ok", icon: ShieldCheck, text: t("v_fixed") }
    : blocking && report.user_decision === "pending" ? { tone: "bad", icon: ShieldAlert, text: t("v_blocked") }
    : blocking ? { tone: "warn", icon: ShieldAlert, text: t("v_kept") }
    : { tone: warning ? "warn" : "ok", icon: ShieldCheck, text: warning ? t("v_warning") : t("v_fair") };
  const Up = (head?.chg ?? 0) >= 0 ? TrendingUp : TrendingDown;

  return (
    <section className="relative overflow-hidden rounded-3xl bg-navy p-6 text-white shadow-lift sm:p-8">
      <div aria-hidden className="pointer-events-none absolute inset-0 opacity-[0.07] [background-image:linear-gradient(white_1px,transparent_1px),linear-gradient(90deg,white_1px,transparent_1px)] [background-size:28px_28px]" />
      <div aria-hidden className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-accent/25 blur-3xl" />
      <div className="relative grid gap-8 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-white/60">
            <span className="inline-flex items-center gap-1.5"><Database className="h-3.5 w-3.5" />{datasetName}</span>
            {a.file_name && <span className="inline-flex items-center gap-1.5" title={a.file_name}><FileSpreadsheet className="h-3.5 w-3.5" />
              {a.file_name.includes(", ") ? t("files", { n: a.file_columns.length || a.file_name.split(", ").length }) : a.file_name}</span>}
            <span>{fmtDate(a.created_at, locale)}</span>
          </div>
          <h1 className="mt-3 font-display text-2xl font-bold leading-tight [overflow-wrap:anywhere] sm:text-[2rem]">“{a.question}”</h1>
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            {a.metric && <span className="rounded-full bg-white/10 px-2.5 py-1">{a.metric}{a.dimensions[0] ? ` · ${a.dimensions[0].replace(/_/g, " ")}` : ""}</span>}
            {a.period_start && <span className="rounded-full bg-white/10 px-2.5 py-1 tabular-nums">{a.period_start} → {a.period_end}</span>}
            {a.compare_start && <span className="rounded-full bg-white/10 px-2.5 py-1 tabular-nums">{t("vs")} {a.compare_start} → {a.compare_end}</span>}
          </div>
        </div>
        <div className="min-w-[260px]">
          {!done ? (
            <div className="space-y-2" aria-hidden><div className="h-4 w-24 animate-pulse rounded bg-white/15" /><div className="h-12 w-56 animate-pulse rounded-lg bg-white/15" /><div className="h-4 w-40 animate-pulse rounded bg-white/10" /></div>
          ) : !head ? (
            <p className="max-w-xs text-sm text-white/60">{working ? t("computing") : t("no_number")}</p>
          ) : (
            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
              <div className="text-xs font-semibold uppercase tracking-[0.14em] text-white/55">{head.label}</div>
              <div className="mt-1 flex items-baseline gap-3">
                <span className="font-display text-4xl font-bold tabular-nums sm:text-5xl">{fmtNum(head.cur, locale, 0)}</span>
                <span className="text-sm text-white/60">{head.unit}</span>
              </div>
              <div className={cn("mt-1 inline-flex items-center gap-1.5 text-lg font-semibold", (head.chg ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300")}>
                <Up className="h-5 w-5" />{fmtPct(head.chg, locale)}
                <span className="text-sm font-normal text-white/55">{t("vs_prev", { v: fmtNum(head.prev, locale, 0) })}</span>
              </div>
              {chosen && res && <div className="mt-1 text-xs text-white/50">{t("asked_was")} <s>{fmtPct(res.change_pct, locale)}</s></div>}
            </motion.div>
          )}
        </div>
      </div>
      <div className="relative mt-6 flex flex-wrap items-center gap-3 border-t border-white/10 pt-5">
        {done && verdict && (
          <button type="button" onClick={onChecks}
                  className={cn("inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 text-sm font-semibold transition hover:brightness-110",
                    verdict.tone === "ok" ? "bg-emerald-400/15 text-emerald-200" : verdict.tone === "bad" ? "bg-rose-400/20 text-rose-200" : "bg-amber-300/15 text-amber-200")}>
            <verdict.icon className="h-4 w-4" />{verdict.text}
          </button>
        )}
        <span className="text-xs text-white/50">{t("agents", { live: liveCount, total: STAGES.length })}</span>
        <button type="button" onClick={onWhy} className="ml-auto inline-flex items-center gap-2 rounded-full bg-accent px-4 py-2 text-sm font-semibold text-accent-fg transition hover:brightness-105">
          <MessageCircleQuestion className="h-4 w-4" />{t("why")}
        </button>
      </div>
    </section>
  );
}

// ---- the inspector -------------------------------------------------------------------------------------------------
function Inspector({ stage, state, a, view, viewLoading, report, summary, datasetName, auditTab, setAuditTab, highlight, setHighlight, onSelect, version, pending }:
  { stage: string; state: StageState; a: Analysis; view: PipelineView | null; viewLoading: boolean; report: ComparisonReport | null;
    summary: RunSummary | null; datasetName: string; auditTab: AuditTab; setAuditTab: (x: AuditTab) => void;
    highlight: number[]; setHighlight: (x: number[]) => void; onSelect: (s: string) => void; version: number;
    pending?: boolean }) {
  const t = useTranslations("app");
  const i = STAGES.findIndex((s) => s.id === stage);
  const s = STAGES[i];
  const Icon = ICONS[s.icon];
  const info = view?.stages.find((x) => x.step === stage);
  const fromDataset = s.scope === "dataset";
  const Missing = () => <MissingNote pending={pending} />;

  let body: React.ReactNode;
  if (viewLoading && !view) body = <Skeleton className="h-64" />;
  else if (stage === "upload") body = state === "missing" ? <Missing /> : <>{state === "demo" && <DemoNote text={t("inspect.demo_script")} />}<UploadPanel v={view} a={a} /></>;
  else if (stage === "dashboard") body = a.run_id && state !== "missing" ? <DashboardDecisions runId={a.run_id} version={version} /> : <Missing />;
  else if (stage === "comparisons") body = report && a.run_id ? (
    <div className="space-y-6"><ChecksPanel report={report} />
      <div><h4 className="mb-3 text-sm font-semibold">{t("inspect.bo412_chart")}</h4><KpiChart runId={a.run_id} version={version} /></div></div>) : <Missing />;
  else if (stage === "auditor") body = a.run_id ? (
    <div className="space-y-5">
      <div role="tablist" aria-label={t("stages.auditor.name")} className="inline-flex flex-wrap gap-1 rounded-xl border border-line bg-surface p-1">
        {AUDIT_TABS.map((x) => (
          <button key={x} type="button" role="tab" aria-selected={auditTab === x} onClick={() => setAuditTab(x)}
                  className={cn("rounded-lg px-3 py-1.5 text-sm font-medium transition", auditTab === x ? "bg-primary text-primary-fg" : "text-muted hover:text-ink")}>
            {t(`run.tabs.${x}`)}
          </button>
        ))}
      </div>
      {auditTab === "explanations" && <ExplanationsPanel datasetRun={a.dataset} />}
      {auditTab === "journal" && <JournalPanel runId={a.run_id} datasetRun={a.dataset} journalId={summary?.journal ?? null} highlight={highlight} />}
      {auditTab === "drift" && <DriftPanel datasetRun={a.dataset} />}
      {auditTab === "why" && <WhyPanel runId={a.run_id} canAsk metric={a.metric}
                                       onCite={(ids) => { setHighlight(ids); setAuditTab("journal");
                                         setTimeout(() => document.getElementById(`entry-${ids[0]}`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 400); }} />}
    </div>) : <Missing />;
  else if (!view || state === "missing") body = <Missing />;
  else {
    const panels: Record<string, React.ReactNode> = {
      similarity: view.similarity && <SimilarityPanel v={view} />,
      column_types: view.column_types && <ColumnTypesPanel v={view} />,
      pii: view.pii && <PiiPanel v={view} />,
      profiling: view.profiling && <ProfilingPanel v={view} onAudit={() => { setAuditTab("explanations"); onSelect("auditor"); }} />,
      cleaning: view.cleaning && <CleaningPanel v={view} />,
      etl: view.etl && <EtlPanel v={view} />,
      lineage: view.lineage && <LineagePanel v={view} />,
      request: view.request && <RequestPanel v={view} />,
      analysis: view.analysis && <AnalysisPanel v={view} />,
    };
    body = <>{state === "demo" && <DemoNote text={stage === "request" ? t("inspect.request_form") : t("inspect.demo_script")} />}{panels[stage] ?? <Missing />}</>;
  }

  return (
    <div>
      <div className="flex flex-wrap items-start gap-4">
        <span className={cn("grid h-12 w-12 shrink-0 place-items-center rounded-2xl",
          state === "live" ? "bg-accent text-accent-fg" : "border border-dashed border-muted/60 bg-surface text-muted")}><Icon className="h-6 w-6" /></span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-display text-lg font-bold">{t(`stages.${stage}.name`)}</h3>
            <span className={cn("chip text-[10px] uppercase tracking-wider", state === "live" ? "bg-accent text-accent-fg" : "border border-line bg-surface-2 text-muted")}>{t(`state.${state}`)}</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted">
            <span className="font-mono">{t("pipeline.step", { n: s.step })}</span><span>·</span><span>{s.owner}</span>
            {s.bo.map((b) => <span key={b} className="rounded bg-surface-2 px-1.5 py-0.5 font-semibold">{b}</span>)}
            <span>·</span>
            <span>{fromDataset ? t("inspect.scope_dataset", { name: datasetName }) : t("inspect.scope_question")}</span>
          </div>
          <p className="mt-2 max-w-3xl text-sm text-muted">{t(`stages.${stage}.what`)}</p>
        </div>
        <div className="flex gap-1">
          <button type="button" className="btn-ghost h-9 w-9 border border-line p-0" disabled={i === 0} onClick={() => onSelect(STAGES[i - 1].id)} aria-label={t("inspect.prev")}><ChevronLeft className="h-4 w-4" /></button>
          <button type="button" className="btn-ghost h-9 w-9 border border-line p-0" disabled={i === STAGES.length - 1} onClick={() => onSelect(STAGES[i + 1].id)} aria-label={t("inspect.next")}><ChevronRight className="h-4 w-4" /></button>
        </div>
      </div>
      <motion.div key={stage} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }} className="mt-5">
        <Approvals items={(view?.approvals ?? []).filter((x) => x.step === stage)} />
        {body}
      </motion.div>
      {info && fromDataset && info.available && state === "live" && (
        <p className="mt-5 text-[11px] text-subtle">{t("inspect.source", { run: info.source_run })}</p>
      )}
    </div>
  );
}

/** Who approved or decided this step, and when (audit journal, or the approved playbook). */
function Approvals({ items }: { items: PipelineView["approvals"] }) {
  const t = useTranslations("app.inspect");
  const locale = useLocale();
  if (!items?.length) return null;
  return (
    <ul className="mb-4 space-y-1.5">
      {items.map((x, i) => {
        const ok = !/REJECTED/.test(x.decision) && !/^rejected/.test(x.decision);
        return (
          <li key={i} className={cn("flex flex-wrap items-center gap-2 rounded-xl border px-3 py-2 text-sm",
            ok ? "border-ok/30 bg-ok-soft/60" : "border-bad/30 bg-bad-soft/60")}>
            <UserCheck className={cn("h-4 w-4 shrink-0", ok ? "text-ok" : "text-bad")} />
            <span className="font-semibold">{x.source === "playbook" ? t("approval.playbook") : ok ? t("approval.approved") : t("approval.rejected")}</span>
            <span>{t("approval.by", { who: x.reviewer ?? t("approval.unknown") })}</span>
            {x.at && <span className="text-muted">· {fmtDate(String(x.at), locale)}</span>}
            {x.source !== "playbook" && <span className="ml-auto font-mono text-[11px] text-subtle">{x.decision.replace(/ by .*/, "")}</span>}
          </li>
        );
      })}
    </ul>
  );
}

function DemoNote({ text }: { text: string }) {
  return <p className="mb-4 flex items-start gap-2 rounded-xl border border-dashed border-line bg-surface p-3 text-sm text-muted"><FlaskConical className="mt-0.5 h-4 w-4 shrink-0" />{text}</p>;
}
function MissingNote({ pending }: { pending?: boolean }) {
  const t = useTranslations("app.inspect");
  return <div className="rounded-xl border border-dashed border-line p-8 text-center text-sm text-muted">{pending ? t("pending") : t("missing")}</div>;
}
