"use client";
/* An uploaded dataset in the pipeline (Samar's orchestrator, live): how far it is, and the human reviews
   (PII, ETL) answered here. The comparison review is the usual BO4-12 banner. */
import { AlertCircle, Check, Database, Loader2, ShieldQuestion, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { api, type Progress, type Review } from "@/lib/client";
import { cn } from "@/lib/cn";

export function UploadProgress({ p }: { p: Progress }) {
  const t = useTranslations("app.upload");
  const ok = p.steps.filter((s) => s.status === "SUCCESS").length;
  const running = p.steps.filter((s) => s.status === "RUNNING");
  return (
    <section className={cn("card p-5 sm:p-6", p.state === "failed" || p.state === "stopped" ? "border-bad/30" : "")} aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className={cn("grid h-10 w-10 place-items-center rounded-xl",
            p.state === "running" ? "bg-primary-soft text-primary" : p.state === "needs_review" ? "bg-warn-soft text-warn"
              : p.state === "done" ? "bg-ok-soft text-ok" : "bg-bad-soft text-bad")}>
            {p.state === "running" ? <Loader2 className="h-5 w-5 animate-spin" /> : p.state === "needs_review" ? <ShieldQuestion className="h-5 w-5" />
              : p.state === "done" ? <Check className="h-5 w-5" /> : <AlertCircle className="h-5 w-5" />}
          </span>
          <div>
            <h2 className="font-semibold">{t(`state.${p.state}`)}</h2>
            <p className="text-sm text-muted">
              {p.state === "running" && running.length
                ? t("running", { steps: running.map((s) => s.step.replace("_", " ")).join(", ") }) : t("steps_done", { ok, n: p.steps.length })}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="h-2 w-40 overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-valuemin={0} aria-valuemax={p.steps.length} aria-valuenow={ok}>
            <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${(ok / p.steps.length) * 100}%` }} />
          </div>
          <span className="font-mono text-xs text-muted">{ok}/{p.steps.length}</span>
        </div>
      </div>
      {p.error && <p role="alert" className="mt-4 rounded-xl bg-bad-soft p-3 text-sm text-bad">{p.error}</p>}
    </section>
  );
}

export function ReviewCard({ runId, review, onAnswered }: { runId: string; review: Review; onAnswered: () => void }) {
  const t = useTranslations("app.upload");
  const locale = useLocale();
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState(false);
  // PII: the proposal is pre-selected when it is a real type; 'UNKNOWN' must be chosen by the person
  const [types, setTypes] = useState<Record<string, string>>(() => Object.fromEntries((review.pii ?? [])
    .filter((q) => (review.pii_types ?? []).includes(q.proposed)).map((q) => [`${q.table}.${q.column}`, q.proposed])));
  const missing = review.step === "pii" && (review.pii ?? []).some((q) => !types[`${q.table}.${q.column}`]);
  if (review.step === "comparisons") return null;           // the BO4-12 banner asks this one
  const step = review.step === "other" ? "other" : review.step;

  async function answer(decision: "approve" | "reject") {
    setBusy(decision); setErr(false);
    try {
      await api(`runs/${runId}/review`, { method: "POST", lang: locale,
        body: { step, decision, ...(step === "pii" ? { pii_types: types } : {}) } });   // the server adds WHO
      onAnswered();
    } catch { setErr(true); } finally { setBusy(null); }
  }

  return (
    <section className="overflow-hidden rounded-2xl border border-warn/40" aria-labelledby="review-title">
      <div className="flex items-start gap-3 bg-warn-soft p-5">
        <ShieldQuestion className="mt-0.5 h-6 w-6 shrink-0 text-warn" />
        <div className="min-w-0">
          <h2 id="review-title" className="font-display text-lg font-bold">{t(`review.${step}.title`)}</h2>
          <p className="mt-1 text-sm">{t(`review.${step}.text`)}</p>
          {review.message && <p className="mt-1 text-xs text-muted">{review.message}</p>}
        </div>
      </div>
      <div className="space-y-4 bg-surface p-5">
        {step === "cleaning" && (
          review.rules?.length ? (
            <ul className="divide-y divide-line rounded-xl border border-line">
              {review.rules.map((r, i) => (
                <li key={i} className="flex flex-wrap items-center gap-3 px-4 py-2.5 text-sm">
                  <span className="min-w-0 flex-1 font-mono text-[12px]">{r.table}.{r.column}</span>
                  <span className="chip bg-primary-soft text-primary">{t(`review.cleaning.actions.${r.action}`)}</span>
                  {r.value != null && <span className="text-xs text-muted">= {String(r.value)}</span>}
                </li>
              ))}
            </ul>
          ) : <p className="text-sm text-muted">{review.approvable ? t("review.cleaning.no_rules") : t("review.cleaning.fix_data")}</p>
        )}
        {step === "pii" && (
          review.pii?.length ? (
            <ul className="divide-y divide-line rounded-xl border border-line">
              {review.pii.map((q) => {
                const key = `${q.table}.${q.column}`;
                return (
                  <li key={key} className="flex flex-wrap items-center gap-3 px-4 py-2.5 text-sm">
                    <span className="min-w-0 flex-1 font-mono text-[12px]">{key}</span>
                    {q.confidence != null && <span className="text-xs tabular-nums text-muted">{t("review.pii.proposed", { type: q.proposed, p: Math.round(q.confidence * 100) })}</span>}
                    <select aria-label={t("review.pii.choose", { col: key })} className="input h-9 w-auto py-0 text-sm"
                            value={types[key] ?? ""} onChange={(e) => setTypes((x) => ({ ...x, [key]: e.target.value }))}>
                      <option value="" disabled>{t("review.pii.pick")}</option>
                      {(review.pii_types ?? []).map((k) => <option key={k} value={k}>{t(`review.pii.types.${k}`)}</option>)}
                    </select>
                  </li>
                );
              })}
            </ul>
          ) : <p className="text-sm text-muted">{t("review.pii.none")}</p>
        )}
        {step === "etl" && (
          <>
            {review.schema_type && <span className="chip bg-accent text-accent-fg">{t("review.etl.schema", { s: review.schema_type })}</span>}
            <div className="grid gap-3 md:grid-cols-2">
              {review.tables?.map((x) => (
                <div key={x.source} className={cn("rounded-xl border p-3.5", x.role === "fact" ? "border-accent/50" : "border-line")}>
                  <div className="flex items-center gap-2">
                    <Database className="h-4 w-4 text-primary" />
                    <span className="min-w-0 flex-1 truncate font-mono text-[12px] font-semibold">{x.source}</span>
                    <span className={cn("chip text-[10px] uppercase tracking-wider", x.role === "fact" ? "bg-accent text-accent-fg" : "bg-primary-soft text-primary")}>{x.role}</span>
                  </div>
                  {(x.measures?.length || x.dates?.length) ? (
                    <p className="mt-1.5 text-xs text-muted">
                      {x.measures?.length ? t("review.etl.measures", { m: x.measures.join(", ") }) : ""}
                      {x.measures?.length && x.dates?.length ? " · " : ""}
                      {x.dates?.length ? t("review.etl.dates", { d: x.dates.join(", ") }) : ""}
                    </p>
                  ) : null}
                </div>
              ))}
            </div>
            {!!review.links?.length && (
              <div>
                <h3 className="text-sm font-semibold">{t("review.etl.links")}</h3>
                <ul className="mt-2 space-y-1 text-xs">
                  {review.links.map((l, i) => (
                    <li key={i} className={cn("flex items-center gap-2", !l.kept && "text-subtle line-through")}>
                      {l.kept ? <Check className="h-3.5 w-3.5 text-ok" /> : <X className="h-3.5 w-3.5" />}
                      <span className="font-mono">{l.child} → {l.parent}</span><span className="text-muted">({l.columns.join(", ")})</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
        {err && <p role="alert" className="text-sm text-bad">{t("review.error")}</p>}
        {step !== "other" && <div className="flex flex-wrap gap-2">
          {review.approvable && (
            <button type="button" className="btn-primary h-10" disabled={!!busy || missing} onClick={() => answer("approve")}>
              {busy === "approve" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}{t("review.approve")}
            </button>
          )}
          <button type="button" className="btn-outline h-10" disabled={!!busy} onClick={() => answer("reject")}>
            {busy === "reject" ? <Loader2 className="h-4 w-4 animate-spin" /> : <X className="h-4 w-4" />}{t("review.reject")}
          </button>
        </div>}
        {step !== "other" && <p className="text-xs text-muted">{t("review.journaled_named")}</p>}
      </div>
    </section>
  );
}
