"use client";
/* BO3 Auditor (live) + the details of BO4-12: checks, SHAP explanations, audit journal, drift, "why?". */
import {
  AlertTriangle, Bot, CheckCircle2, ChevronDown, Fingerprint, Link2, Loader2, Lock, Send, ShieldAlert,
  ShieldCheck, Sparkles, User, XCircle,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { Empty, Skeleton, fmtDate } from "@/components/ui/kit";
import {
  api, type AnomalyExplanation, type ComparisonReport, type DriftReport, type ExplanationPage, type IntegrityReport,
  type JournalEntry, useApi, type WhyAnswer,
} from "@/lib/client";
import { cn } from "@/lib/cn";

const STATUS_ICON = { ok: CheckCircle2, warning: AlertTriangle, blocking: XCircle } as const;
const STATUS_CLS = { ok: "text-ok bg-ok-soft", warning: "text-warn bg-warn-soft", blocking: "text-bad bg-bad-soft" } as const;

function Evidence({ data, label }: { data: unknown; label: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
              className="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline">
        <ChevronDown className={cn("h-3.5 w-3.5 transition", open && "rotate-180")} />{label}
      </button>
      {open && <pre className="mt-2 max-h-72 overflow-auto rounded-lg bg-surface-2 p-3 font-mono text-[11px] leading-relaxed text-muted">{JSON.stringify(data, null, 2)}</pre>}
    </div>
  );
}

// ---- the 5 checks -----------------------------------------------------------------------
export function ChecksPanel({ report }: { report: ComparisonReport }) {
  const t = useTranslations("app.checks");
  return (
    <div className="space-y-3">
      {report.checks.map((c) => {
        const Icon = STATUS_ICON[c.status as keyof typeof STATUS_ICON] ?? CheckCircle2;
        return (
          <div key={c.kind} className="card p-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className={cn("grid h-8 w-8 place-items-center rounded-lg", STATUS_CLS[c.status as keyof typeof STATUS_CLS])}><Icon className="h-4 w-4" /></span>
              <span className="font-semibold">{t(`kind.${c.kind}`)}</span>
              <span className={cn("chip", STATUS_CLS[c.status as keyof typeof STATUS_CLS])}>{t(`status.${c.status}`)}</span>
              <span className="ml-auto text-xs text-muted">{t(`what.${c.kind}`)}</span>
            </div>
            <p className="mt-2 text-sm">{c.message}</p>
            <Evidence data={c.evidence} label={t("evidence")} />
          </div>
        );
      })}
    </div>
  );
}

// ---- SHAP explanations --------------------------------------------------------------------
function Contributions({ e }: { e: AnomalyExplanation }) {
  const max = Math.max(...e.contributions.map((c) => Math.abs(c.shap_value)), 1e-9);
  return (
    <div className="mt-3 space-y-1.5">
      {e.contributions.slice(0, 5).map((c) => (
        <div key={c.feature} className="grid grid-cols-[minmax(0,140px)_minmax(0,1fr)_64px] items-center gap-3 text-xs">
          <span className="truncate font-medium" title={c.feature}>{c.feature}</span>
          <div className="relative h-2.5 rounded-full bg-surface-2">
            <div className={cn("absolute top-0 h-2.5 rounded-full", c.shap_value > 0 ? "left-1/2 bg-accent" : "right-1/2 bg-primary")}
                 style={{ width: `${(Math.abs(c.shap_value) / max) * 50}%` }} />
            <span className="absolute left-1/2 top-[-3px] h-4 w-px bg-line" />
          </div>
          <span className="text-right font-mono text-muted">{c.shap_value > 0 ? "+" : ""}{c.shap_value.toFixed(2)}</span>
        </div>
      ))}
    </div>
  );
}

export function ExplanationsPanel({ datasetRun }: { datasetRun: string }) {
  const t = useTranslations("app.shap");
  const [page, setPage] = useState(0);
  const size = 8;
  const { data, loading, error } = useApi<ExplanationPage>(`runs/${datasetRun}/explanations`, { limit: size, offset: page * size });
  if (error?.status === 404) return <Empty icon={Fingerprint} title={t("none")} />;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-muted">{t("intro")}</p>
        {data && <span className="chip bg-surface-2 text-muted">{t("count", { n: data.total, model: data.model_version })}</span>}
      </div>
      {loading && !data && <div className="grid grid-cols-1 gap-3 md:grid-cols-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-44" />)}</div>}
      {error && error.status !== 404 && <p className="text-sm text-bad">{t("error")}</p>}
      {data && (
        <>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {data.items.map((e) => (
              <article key={e.row_key} className="card p-4">
                <div className="flex items-center gap-2">
                  <span className="truncate font-mono text-xs font-semibold" title={e.row_key}>{e.row_key}</span>
                  <span className="chip ml-auto bg-accent-soft text-ink">{t("score")} {e.anomaly_score.toFixed(3)}</span>
                </div>
                <p className="mt-2 text-sm leading-relaxed">{e.narrative}</p>
                <Contributions e={e} />
                <div className="mt-2 flex justify-between text-[10px] text-subtle"><span>← {t("toward_normal")}</span><span>{t("toward_anomaly")} →</span></div>
              </article>
            ))}
          </div>
          <div className="flex items-center justify-between">
            <button type="button" className="btn-outline h-9" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>{t("prev")}</button>
            <span className="text-sm text-muted">{t("page", { from: page * size + 1, to: Math.min((page + 1) * size, data.total), total: data.total })}</span>
            <button type="button" className="btn-outline h-9" disabled={(page + 1) * size >= data.total} onClick={() => setPage((p) => p + 1)}>{t("next")}</button>
          </div>
        </>
      )}
    </div>
  );
}

// ---- audit journal ------------------------------------------------------------------------
function EntryList({ entries, highlight }: { entries: JournalEntry[]; highlight?: number[] }) {
  const t = useTranslations("app.journal");
  const locale = useLocale();
  const ROUTINE = ["OK", "PASSED", "computed in SQL"];
  return (
    <ol className="relative space-y-2 border-l border-line pl-5">
      {entries.map((e) => (
        <li key={e.entry_id} id={`entry-${e.entry_id}`} className={cn("relative rounded-xl border bg-surface p-3",
          highlight?.includes(e.entry_id) ? "border-accent ring-4 ring-accent/15" : "border-line")}>
          <span className={cn("absolute -left-[27px] top-4 h-3 w-3 rounded-full border-2 border-bg",
            ROUTINE.includes(e.decision) ? "bg-line" : "bg-primary")} />
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-mono text-xs text-subtle">#{e.entry_id}</span>
            <span className="font-semibold">{e.agent}</span><span className="text-muted">·</span><span className="font-mono text-xs">{e.step}</span>
            <span className="ml-auto text-xs text-muted">{fmtDate(e.timestamp, locale)}</span>
          </div>
          <p className="mt-1 break-words text-sm">{e.decision}</p>
          <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[11px] text-subtle">
            {e.rule_version && <span>{t("rule")}: <span className="font-mono">{e.rule_version}</span></span>}
            <span className="inline-flex items-center gap-1 font-mono"><Link2 className="h-3 w-3" />{e.entry_hash.slice(0, 12)}…</span>
          </div>
          {Object.keys(e.evidence ?? {}).length > 0 && <Evidence data={e.evidence} label={t("evidence")} />}
        </li>
      ))}
    </ol>
  );
}

export function JournalPanel({ runId, datasetRun, journalId, highlight }:
  { runId: string; datasetRun: string; journalId: string | null; highlight?: number[] }) {
  const t = useTranslations("app.journal");
  const own = useApi<JournalEntry[]>(`runs/${runId}/journal`);
  const base = useApi<JournalEntry[]>(datasetRun !== runId ? `runs/${datasetRun}/journal` : null);
  const [check, setCheck] = useState<IntegrityReport | null>(null);
  const [busy, setBusy] = useState(false);
  async function verify() {
    if (!journalId) return;
    setBusy(true);
    try { setCheck(await api<IntegrityReport>(`journals/${journalId}/verify`)); } finally { setBusy(false); }
  }
  return (
    <div className="space-y-6">
      <div className="card flex flex-wrap items-center gap-4 p-5">
        <div className="grid h-12 w-12 place-items-center rounded-xl bg-primary-soft text-primary"><Lock className="h-6 w-6" /></div>
        <div className="min-w-0 flex-1">
          <div className="font-semibold">{t("chain_title")}</div>
          <p className="text-sm text-muted">{t("chain_text")}</p>
        </div>
        <button type="button" className="btn-primary" disabled={!journalId || busy} onClick={verify}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}{t("verify")}
        </button>
        {check && (
          <div className={cn("w-full rounded-xl p-3 text-sm", check.ok ? "bg-ok-soft text-ok" : "bg-bad-soft text-bad")} role="status">
            {check.ok ? t("intact", { n: check.entries_checked }) : `${t("tampered")} ${check.problem}`}
          </div>
        )}
      </div>
      <section>
        <h3 className="mb-3 font-semibold">{t("this_analysis")}</h3>
        {own.loading && !own.data ? <Skeleton className="h-40" /> : own.data?.length ? <EntryList entries={own.data} highlight={highlight} /> : <p className="text-sm text-muted">{t("empty")}</p>}
      </section>
      {datasetRun !== runId && (
        <section>
          <h3 className="mb-1 font-semibold">{t("data_prep")}</h3>
          <p className="mb-3 text-sm text-muted">{t("data_prep_text")}</p>
          {base.loading && !base.data ? <Skeleton className="h-40" /> : base.data?.length ? <EntryList entries={base.data} /> : <p className="text-sm text-muted">{t("empty")}</p>}
        </section>
      )}
    </div>
  );
}

// ---- drift --------------------------------------------------------------------------------
export function DriftPanel({ datasetRun }: { datasetRun: string }) {
  const t = useTranslations("app.drift");
  const own = useApi<DriftReport>(`runs/${datasetRun}/drift`);
  const all = useApi<DriftReport[]>("drift");
  const tone = (s: string) => (s === "stable" ? "bg-ok-soft text-ok" : s === "not_available" ? "bg-surface-2 text-muted" : "bg-warn-soft text-warn");
  return (
    <div className="space-y-6">
      <div className="card p-5">
        <h3 className="font-semibold">{t("this_data")}</h3>
        {own.loading && !own.data ? <Skeleton className="mt-3 h-16" /> : own.data ? (
          <div className="mt-3 flex items-start gap-3">
            <span className={cn("chip shrink-0", tone(own.data.status))}>{t(`status.${own.data.status}`)}</span>
            <p className="text-sm">{own.data.narrative}</p>
          </div>
        ) : <p className="mt-2 text-sm text-muted">{t("none")}</p>}
      </div>
      <div className="card p-5">
        <h3 className="font-semibold">{t("monitor_title")}</h3>
        <p className="mt-1 text-sm text-muted">{t("monitor_text")}</p>
        <div className="mt-4 space-y-2">
          {all.loading && !all.data && <Skeleton className="h-32" />}
          {all.data?.length === 0 && <p className="text-sm text-muted">{t("monitor_empty")}</p>}
          {all.data?.map((d) => (
            <details key={d.current_run} className="group rounded-xl border border-line p-3">
              <summary className="flex cursor-pointer list-none items-center gap-3">
                <span className="font-mono text-sm">{d.current_run}</span>
                <span className={cn("chip", tone(d.status))}>{t(`status.${d.status}`)}</span>
                {d.flagged_agents.length > 0 && <span className="text-xs text-muted">{d.flagged_agents.join(", ")}</span>}
                <ChevronDown className="ml-auto h-4 w-4 text-muted transition group-open:rotate-180" />
              </summary>
              <p className="mt-3 text-sm">{d.narrative}</p>
            </details>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---- "why?" -------------------------------------------------------------------------------
type Turn = { q: string; a?: WhyAnswer; error?: boolean };

export function WhyPanel({ runId, canAsk, metric, onCite }:
  { runId: string; canAsk: boolean; metric: string; onCite: (ids: number[]) => void }) {
  const t = useTranslations("app.why");
  const locale = useLocale();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const suggestions = [t("s1"), t("s2", { kpi: metric }), t("s3")];
  async function ask(question: string) {
    if (!question.trim() || busy) return;
    setBusy(true); setQ("");
    setTurns((x) => [...x, { q: question }]);
    try {
      const a = await api<WhyAnswer>(`runs/${runId}/why`, { method: "POST", body: { question }, lang: locale });
      setTurns((x) => x.map((tt, i) => (i === x.length - 1 ? { ...tt, a } : tt)));
    } catch {
      setTurns((x) => x.map((tt, i) => (i === x.length - 1 ? { ...tt, error: true } : tt)));
    } finally { setBusy(false); }
  }
  return (
    <div className="card flex flex-col p-5">
      <div className="flex items-start gap-3">
        <div className="grid h-10 w-10 place-items-center rounded-xl bg-accent text-accent-fg"><Sparkles className="h-5 w-5" /></div>
        <div><h3 className="font-semibold">{t("title")}</h3><p className="text-sm text-muted">{t("subtitle")}</p></div>
      </div>
      <div className="mt-5 space-y-4" aria-live="polite">
        {turns.length === 0 && (
          <div className="flex flex-wrap gap-2">
            {suggestions.map((s) => (
              <button key={s} type="button" disabled={!canAsk || busy} onClick={() => ask(s)}
                      className="rounded-full border border-line bg-surface-2 px-3.5 py-2 text-left text-sm transition hover:border-primary hover:text-primary disabled:opacity-50">{s}</button>
            ))}
          </div>
        )}
        {turns.map((tt, i) => (
          <div key={i} className="space-y-3">
            <div className="flex justify-end gap-2">
              <div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-primary px-4 py-2.5 text-sm text-primary-fg">{tt.q}</div>
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-surface-2"><User className="h-4 w-4" /></span>
            </div>
            <div className="flex gap-2">
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-accent text-accent-fg"><Bot className="h-4 w-4" /></span>
              <div className="max-w-[85%] rounded-2xl rounded-tl-sm border border-line bg-surface px-4 py-3 text-sm">
                {!tt.a && !tt.error && <span className="flex items-center gap-2 text-muted"><Loader2 className="h-4 w-4 animate-spin" />{t("thinking")}</span>}
                {tt.error && <span className="text-bad">{t("error")}</span>}
                {tt.a && (
                  <>
                    <p className="whitespace-pre-line leading-relaxed">{tt.a.answer}</p>
                    <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                      <span className={cn("chip", tt.a.source.startsWith("llm:") ? "bg-ok-soft text-ok" : "bg-surface-2 text-muted")}>
                        {tt.a.verified ? <ShieldCheck className="h-3.5 w-3.5" /> : <ShieldAlert className="h-3.5 w-3.5" />}
                        {tt.a.source.startsWith("llm:") ? t("verified_llm") : t("template")}
                      </span>
                      {tt.a.citations.length > 0 && (
                        <button type="button" onClick={() => onCite(tt.a!.citations)} className="chip bg-primary-soft text-primary hover:underline">
                          <Link2 className="h-3.5 w-3.5" />{t("sources", { ids: tt.a.citations.map((c) => `#${c}`).join(", ") })}
                        </button>
                      )}
                      {tt.a.tool_calls.length > 0 && <span className="text-muted">{t("tools", { n: tt.a.tool_calls.length })}</span>}
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
      <form className="mt-5 flex gap-2" onSubmit={(e) => { e.preventDefault(); void ask(q); }}>
        <label htmlFor="why-q" className="sr-only">{t("placeholder")}</label>
        <input id="why-q" className="input" value={q} onChange={(e) => setQ(e.target.value)} maxLength={500}
               placeholder={canAsk ? t("placeholder") : t("not_owner")} disabled={!canAsk || busy} />
        <button type="submit" className="btn-primary w-11 shrink-0 p-0" disabled={!canAsk || busy || q.trim().length < 3} aria-label={t("send")}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
        </button>
      </form>
    </div>
  );
}
