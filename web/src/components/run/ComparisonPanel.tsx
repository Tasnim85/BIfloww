"use client";
/* BO4-12 (live): the verdict on the comparison, the user's decision, then the dashboard drawn for the
   periods that decision fixes. The dashboard route answers 409 while a blocked comparison waits. */
import { AlertTriangle, CheckCircle2, Info, Loader2, RotateCcw, ShieldAlert, Sparkles } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Skeleton, fmtNum, fmtPct } from "@/components/ui/kit";
import { api, type ComparisonReport, type KpiBreakdown, type ProposedFix, useApi } from "@/lib/client";
import { cn } from "@/lib/cn";

export function ComparisonBanner({ runId, report, canDecide, onChanged }:
  { runId: string; report: ComparisonReport; canDecide: boolean; onChanged: () => void }) {
  const t = useTranslations("app.cmp");
  const locale = useLocale();
  const [busy, setBusy] = useState<string | null>(null);
  const [more, setMore] = useState(false);
  const fixes = [report.proposed_fix, ...report.alternatives].filter(Boolean) as ProposedFix[];
  const blocking = report.checks.filter((c) => c.status === "blocking");
  const warnings = report.checks.filter((c) => c.status === "warning");

  async function decide(decision: "accepted" | "rejected" | "pending", fix?: string) {
    setBusy(fix ?? decision);
    try {
      await api(`runs/${runId}/comparison/decision`, { method: "POST", lang: locale,
        body: { decision, chosen_fix: fix ?? null } });
      onChanged();
    } finally { setBusy(null); }
  }

  if (!report.has_comparison) return null;
  const source = report.summary_source.startsWith("llm:") ? t("source_llm") : t("source_template");

  if (report.user_decision === "accepted" && report.chosen_fix) {
    const f = fixes.find((x) => x.method === report.chosen_fix)!;
    return (
      <div className="rounded-2xl border border-ok/30 bg-ok-soft p-5">
        <div className="flex flex-wrap items-start gap-3">
          <CheckCircle2 className="mt-0.5 h-5 w-5 text-ok" />
          <div className="min-w-0 flex-1">
            <div className="font-semibold text-ok">{t("adjusted")}</div>
            <p className="mt-1 text-sm">{f.description}</p>
          </div>
          {canDecide && <button type="button" className="btn-outline h-9 text-xs" disabled={!!busy} onClick={() => decide("pending")}>
            <RotateCcw className="h-3.5 w-3.5" />{t("review")}</button>}
        </div>
      </div>
    );
  }
  if (report.user_decision === "rejected") {
    return (
      <div className="rounded-2xl border border-warn/30 bg-warn-soft p-5">
        <div className="flex flex-wrap items-start gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 text-warn" />
          <div className="min-w-0 flex-1">
            <div className="font-semibold text-warn">{t("kept")}</div>
            {blocking[0] && <p className="mt-1 text-sm">{blocking[0].message}</p>}
          </div>
          {canDecide && <button type="button" className="btn-outline h-9 text-xs" disabled={!!busy} onClick={() => decide("pending")}>
            <RotateCcw className="h-3.5 w-3.5" />{t("review")}</button>}
        </div>
      </div>
    );
  }
  if (!blocking.length && !fixes.length) {
    return (
      <div className={cn("rounded-2xl border p-5", warnings.length ? "border-primary/25 bg-primary-soft" : "border-ok/30 bg-ok-soft")}>
        <div className="flex items-start gap-3">
          {warnings.length ? <Info className="mt-0.5 h-5 w-5 text-primary" /> : <CheckCircle2 className="mt-0.5 h-5 w-5 text-ok" />}
          <div>
            <div className="font-semibold">{t("valid")}</div>
            {warnings.map((w) => <p key={w.kind} className="mt-1 text-sm text-muted">{w.message}</p>)}
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className={cn("overflow-hidden rounded-2xl border", blocking.length ? "border-bad/30" : "border-primary/25")}>
      <div className={cn("flex items-start gap-3 p-5", blocking.length ? "bg-bad-soft" : "bg-primary-soft")}>
        {blocking.length ? <ShieldAlert className="mt-0.5 h-6 w-6 shrink-0 text-bad" /> : <Info className="mt-0.5 h-6 w-6 shrink-0 text-primary" />}
        <div className="min-w-0">
          <div className={cn("font-display text-lg font-bold", blocking.length ? "text-bad" : "text-primary")}>
            {blocking.length ? t("misleading") : t("adjustable")}
          </div>
          <p className={cn("mt-1.5 text-sm leading-relaxed", !more && "line-clamp-3")}>{report.summary}</p>
          <button type="button" onClick={() => setMore((v) => !v)} aria-expanded={more}
                  className="mt-1 text-xs font-semibold text-primary hover:underline">{more ? t("less") : t("more")}</button>
          <p className="mt-2 text-xs text-muted">{source} · {report.rules_version}</p>
        </div>
      </div>
      <div className="grid grid-cols-1 gap-3 bg-surface p-5 md:grid-cols-[repeat(auto-fit,minmax(220px,1fr))]">
        {fixes.map((f, i) => (
          <div key={f.method} className={cn("flex flex-col rounded-xl border p-4", i === 0 ? "border-primary ring-4 ring-primary/10" : "border-line")}>
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted">
              {i === 0 && <Sparkles className="h-3.5 w-3.5 text-accent" />}{i === 0 ? t("recommended") : t("alternative")}
            </div>
            <div className="mt-2 font-semibold">{f.description.split(":")[0]}</div>
            <div className="mt-3 flex items-baseline gap-2">
              <span className={cn("font-display text-2xl font-bold", (f.change_pct ?? 0) >= 0 ? "text-ok" : "text-bad")}>{fmtPct(f.change_pct, locale)}</span>
              <span className="text-xs text-muted">{fmtNum(f.value_current, locale)} / {fmtNum(f.value_previous, locale)} {f.unit}</span>
            </div>
            <p className="mt-2 flex-1 text-xs text-muted">{f.justification}</p>
            {canDecide && (
              <button type="button" disabled={!!busy} onClick={() => decide("accepted", f.method)}
                      className={cn("mt-4 h-10", i === 0 ? "btn-primary" : "btn-outline")}>
                {busy === f.method && <Loader2 className="h-4 w-4 animate-spin" />}{t("accept")}
              </button>
            )}
          </div>
        ))}
        {canDecide && (
          <div className="flex flex-col justify-between rounded-xl border border-dashed border-line p-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider text-muted">{t("as_asked")}</div>
              <p className="mt-2 text-sm text-muted">{t("as_asked_text")}</p>
            </div>
            <button type="button" disabled={!!busy} onClick={() => decide("rejected")} className="btn-ghost mt-4 h-10 border border-line">
              {busy === "rejected" && <Loader2 className="h-4 w-4 animate-spin" />}{t("keep")}
            </button>
          </div>
        )}
      </div>
      {canDecide && <p className="border-t border-line bg-surface px-5 py-3 text-xs text-muted">{t("journaled")}</p>}
    </div>
  );
}

export function KpiChart({ runId, version }: { runId: string; version: number }) {
  const t = useTranslations("app.cmp");
  const locale = useLocale();
  const { data, error, loading } = useApi<KpiBreakdown>(`runs/${runId}/dashboard`, { limit: 10, v: version });
  if (loading && !data) return <Skeleton className="h-80" />;
  if (error?.status === 409) {
    return (
      <div className="grid h-72 place-items-center rounded-2xl border border-dashed border-line bg-surface-2/40 p-6 text-center">
        <div><ShieldAlert className="mx-auto h-8 w-8 text-warn" /><p className="mt-3 font-semibold">{t("waiting_title")}</p>
          <p className="mt-1 max-w-sm text-sm text-muted">{t("waiting_text")}</p></div>
      </div>
    );
  }
  if (error || !data) return <p className="text-sm text-bad">{t("chart_error")}</p>;
  const rows = data.rows.map((r) => ({ label: r.label, current: r.current, previous: r.previous ?? 0 }));
  const up = (data.change_pct ?? 0) >= 0;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Metric label={`${data.period.start} → ${data.period.end}`} value={`${fmtNum(data.total_current, locale, 0)} ${data.unit}`} />
        {data.compare_to && <Metric label={`${data.compare_to.start} → ${data.compare_to.end}`} value={`${fmtNum(data.total_previous, locale, 0)} ${data.unit}`} muted />}
        <Metric label={t("change")} value={fmtPct(data.change_pct, locale)} tone={up ? "ok" : "bad"} />
      </div>
      <div className="h-80 rounded-2xl border border-line bg-surface p-3">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" vertical={false} />
            <XAxis dataKey="label" tick={{ fill: "rgb(var(--muted))", fontSize: 12 }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fill: "rgb(var(--muted))", fontSize: 12 }} axisLine={false} tickLine={false} width={70}
                   tickFormatter={(v: number) => new Intl.NumberFormat(locale, { notation: "compact" }).format(v)} />
            <Tooltip cursor={{ fill: "rgb(var(--surface-2))" }}
                     contentStyle={{ background: "rgb(var(--surface))", border: "1px solid rgb(var(--line))", borderRadius: 12, color: "rgb(var(--ink))" }}
                     itemStyle={{ color: "rgb(var(--ink))" }}
                     formatter={(v: number) => `${fmtNum(v, locale)} ${data.unit}`} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar dataKey="previous" name={t("previous")} fill="rgb(var(--muted) / 0.45)" radius={[6, 6, 0, 0]} />
            <Bar dataKey="current" name={t("current")} fill="rgb(var(--primary))" radius={[6, 6, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="text-xs text-muted">{t("chart_note", { kpi: data.kpi, dim: data.dimension ?? "—", source: data.periods_source })}</p>
    </div>
  );
}

function Metric({ label, value, muted, tone }: { label: string; value: string; muted?: boolean; tone?: "ok" | "bad" }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <div className="truncate text-xs font-medium text-muted">{label}</div>
      <div className={cn("mt-1 font-display text-2xl font-bold", muted && "text-muted", tone === "ok" && "text-ok", tone === "bad" && "text-bad")}>{value}</div>
    </div>
  );
}
