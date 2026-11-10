"use client";
/* Samar's dashboard agent (dashboard_ai), live: the charts IT chose for this question, drawn here, each
   with the reason of the choice, the options it refused (and why), and the visual warnings it raised. */
import { AlertTriangle, ChevronDown, Info, LayoutDashboard, ShieldAlert } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Skeleton, fmtNum } from "@/components/ui/kit";
import { type ChartView, type DashboardView, useApi } from "@/lib/client";
import { cn } from "@/lib/cn";

const SERIES = ["rgb(var(--primary))", "rgb(var(--accent))", "rgb(var(--muted) / 0.55)", "rgb(var(--ok))", "rgb(var(--warn))", "rgb(var(--navy))"];
const tip = { background: "rgb(var(--glass) / 0.85)", backdropFilter: "blur(12px)", boxShadow: "0 12px 30px -12px rgb(15 42 61 / 0.3)", border: "1px solid rgb(var(--line))", borderRadius: 12, color: "rgb(var(--ink))" };
const axis = { fill: "rgb(var(--muted))", fontSize: 12 };

export function DashboardCharts({ runId, version, unit, onEmpty }:
  { runId: string; version: number; unit: string; onEmpty?: React.ReactNode }) {
  const t = useTranslations("app.dash");
  const { data, error, loading } = useApi<DashboardView>(`runs/${runId}/charts`, { v: version });
  if (loading && !data) return <Skeleton className="h-96" />;
  if (error || !data) return <>{onEmpty ?? <p className="text-sm text-muted">{t("none")}</p>}</>;
  const kpi = data.charts.find((c) => c.chart_type === "kpi_card");
  const others = data.charts.filter((c) => c !== kpi);
  return (
    <section className="space-y-4" aria-label={t("label")}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 font-semibold"><LayoutDashboard className="h-5 w-5 text-primary" />{t("title")}</h2>
        <span className="text-[11px] text-subtle">Samar · BO4 · {data.rules_version ?? ""}</span>
      </div>
      {data.warnings.length > 0 && <Warnings items={data.warnings} />}
      {kpi && <KpiCard c={kpi} unit={unit} />}
      {others.map((c) => <ChartCard key={c.chart_id} c={c} unit={unit} />)}
    </section>
  );
}

function Warnings({ items }: { items: string[] }) {
  const t = useTranslations("app.dash");
  const [open, setOpen] = useState(false);
  const blocking = items.filter((w) => w.startsWith("[BLOCKING]"));
  const shown = open ? items : items.slice(0, 2);
  return (
    <div className="rounded-xl border border-warn/30 bg-warn-soft/50 p-3.5">
      <ul className="space-y-1.5 text-sm">
        {shown.map((w) => {
          const block = w.startsWith("[BLOCKING]");
          return (
            <li key={w} className="flex gap-2">
              {block ? <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-bad" /> : <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warn" />}
              <span className={cn(!open && "line-clamp-2", block && "text-bad")}>{w.replace("[BLOCKING] ", "")}</span>
            </li>
          );
        })}
      </ul>
      {(items.length > 2 || items.some((w) => w.length > 160)) && (
        <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="mt-1.5 text-xs font-semibold text-primary hover:underline">
          {open ? t("less") : t("more", { n: items.length, b: blocking.length })}
        </button>
      )}
    </div>
  );
}

function KpiCard({ c, unit }: { c: ChartView; unit: string }) {
  const locale = useLocale();
  const v = Number((c.rows[0] as { value?: number } | undefined)?.value ?? NaN);
  return (
    <div className="rounded-2xl border border-line bg-surface p-5">
      <div className="text-sm font-medium text-muted">{c.title}</div>
      <div className="mt-1 font-display text-3xl font-bold tabular-nums">{Number.isFinite(v) ? fmtNum(v, locale) : "—"} <span className="text-base font-normal text-muted">{unit}</span></div>
    </div>
  );
}

function ChartCard({ c, unit }: { c: ChartView; unit: string }) {
  const t = useTranslations("app.dash");
  const locale = useLocale();
  const [why, setWhy] = useState(false);
  const fmt = (v: number) => `${fmtNum(v, locale)} ${unit}`;
  const compact = (v: number) => new Intl.NumberFormat(locale, { notation: "compact" }).format(v);
  const x = c.x ?? "label";
  // two periods -> one series per period (color), aligned on x
  const { rows, series } = useMemo(() => {
    if (!c.color) return { rows: c.rows, series: ["value"] };
    const by = new Map<string, Record<string, unknown>>();
    const keys = new Set<string>();
    for (const r of c.rows as Record<string, unknown>[]) {
      const k = String(r[x]); const s = String(r[c.color]);
      keys.add(s);
      by.set(k, { ...(by.get(k) ?? { [x]: k }), [s]: r[c.y] });
    }
    return { rows: [...by.values()], series: [...keys] };
  }, [c, x]);

  let chart: React.ReactNode;
  if (c.chart_type === "bar" || c.chart_type === "line") {
    const Chart = c.chart_type === "bar" ? BarChart : LineChart;
    chart = (
      <ResponsiveContainer width="100%" height="100%">
        <Chart data={rows} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
          <defs>
            {/* Aurora: gradient fills for the first two series (same ids in every chart = same definition) */}
            <linearGradient id="aurora-bar-0" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="rgb(var(--violet))" /><stop offset="100%" stopColor="rgb(var(--primary))" />
            </linearGradient>
            <linearGradient id="aurora-bar-1" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#FB923C" /><stop offset="100%" stopColor="rgb(var(--accent))" />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" vertical={false} />
          <XAxis dataKey={x} tick={axis} axisLine={false} tickLine={false} interval={rows.length > 8 ? 0 : "preserveStartEnd"}
                 angle={rows.length > 8 ? -35 : 0} textAnchor={rows.length > 8 ? "end" : "middle"} height={rows.length > 8 ? 70 : 30} />
          <YAxis tick={axis} axisLine={false} tickLine={false} width={64} tickFormatter={compact} domain={[0, "auto"]} />
          <Tooltip contentStyle={tip} itemStyle={{ color: "rgb(var(--ink))" }} cursor={{ fill: "rgb(var(--surface-2))" }} formatter={(v: number) => fmt(v)} />
          {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
          {series.map((s, i) => c.chart_type === "bar"
            ? <Bar key={s} dataKey={s} name={s === "value" ? c.title : s} fill={i < 2 ? `url(#aurora-bar-${i})` : SERIES[i % SERIES.length]} radius={[10, 10, 2, 2]} animationDuration={900} />
            : <Line key={s} dataKey={s} name={s === "value" ? c.title : s} stroke={SERIES[i % SERIES.length]} strokeWidth={2.5} dot={false} type="monotone" />)}
        </Chart>
      </ResponsiveContainer>
    );
  } else if (c.chart_type === "pie") {
    chart = (
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={c.rows} dataKey={c.y} nameKey={x} innerRadius="45%" outerRadius="80%" paddingAngle={2}>
            {c.rows.map((_, i) => <Cell key={i} fill={SERIES[i % SERIES.length]} />)}
          </Pie>
          <Tooltip contentStyle={tip} formatter={(v: number) => fmt(v)} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
        </PieChart>
      </ResponsiveContainer>
    );
  } else {
    const cols = Object.keys(c.rows[0] ?? {});
    chart = (
      <div className="h-full overflow-auto">
        <table className="w-full text-left text-sm">
          <thead className="sticky top-0 bg-surface-2 text-xs text-muted"><tr>{cols.map((k) => <th key={k} className="px-3 py-2 font-semibold">{k}</th>)}</tr></thead>
          <tbody>{(c.rows as Record<string, unknown>[]).map((r, i) => (
            <tr key={i} className="border-t border-line">{cols.map((k) => <td key={k} className="px-3 py-1.5 tabular-nums">{typeof r[k] === "number" ? fmtNum(r[k] as number, locale) : String(r[k] ?? "")}</td>)}</tr>
          ))}</tbody>
        </table>
      </div>
    );
  }

  const refused = (c.alternatives ?? []).filter((a) => a.chart_type !== c.chart_type);
  return (
    <div className="rounded-2xl border border-line bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-4">
        <h3 className="font-semibold">{c.title}</h3>
        <span className="chip bg-primary-soft text-primary">{t(`types.${c.chart_type}`)}</span>
      </div>
      <div className="h-80 p-3">{chart}</div>
      <div className="border-t border-line px-4 py-3 text-sm">
        <p className="flex items-start gap-2 text-muted"><Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" /><span><b className="text-ink">{t("why")}</b> {c.reason}</span></p>
        {refused.length > 0 && (
          <>
            <button type="button" onClick={() => setWhy((v) => !v)} aria-expanded={why} className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline">
              <ChevronDown className={cn("h-3.5 w-3.5 transition", why && "rotate-180")} />{t("options", { n: refused.length })}
            </button>
            {why && (
              <ul className="mt-2 space-y-1.5">
                {refused.map((a) => (
                  <li key={a.chart_type} className="flex gap-3 rounded-lg bg-surface-2 px-3 py-2 text-xs">
                    <span className="w-20 shrink-0 font-semibold">{t(`types.${a.chart_type}`)}</span>
                    <span className={cn("w-14 shrink-0 tabular-nums", a.eligible ? "text-ok" : "text-bad")}>{a.eligible ? `${Math.round(a.score)} / 100` : t("refused")}</span>
                    <span className="text-muted">{a.reason}</span>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/** The inspector of the Dashboard step: for each chart, every type the agent considered, its score and why. */
export function DashboardDecisions({ runId, version }: { runId: string; version: number }) {
  const t = useTranslations("app.dash");
  const { data, error, loading } = useApi<DashboardView>(`runs/${runId}/charts`, { v: version });
  if (loading && !data) return <Skeleton className="h-48" />;
  if (error || !data) return <div className="rounded-xl border border-dashed border-line p-8 text-center text-sm text-muted">{t("none")}</div>;
  return (
    <div className="space-y-5">
      <p className="text-sm text-muted">{t("decisions_text", { rules: data.rules_version ?? "" })}</p>
      {data.charts.map((c) => (
        <div key={c.chart_id} className="rounded-xl border border-line p-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold">{c.title}</span>
            <span className="chip bg-accent text-accent-fg">{t(`types.${c.chart_type}`)}</span>
          </div>
          <ul className="mt-3 space-y-2">
            {(c.alternatives ?? []).map((o) => (
              <li key={o.chart_type} className="grid grid-cols-[80px_120px_minmax(0,1fr)] items-start gap-3 text-xs">
                <span className={cn("font-semibold", o.chart_type === c.chart_type && "text-accent")}>{t(`types.${o.chart_type}`)}</span>
                <span className="flex items-center gap-2">
                  <span className="block h-1.5 w-16 overflow-hidden rounded-full bg-surface-2"><span className={cn("block h-full rounded-full", o.eligible ? "bg-primary" : "bg-bad/50")} style={{ width: `${Math.max(4, o.score)}%` }} /></span>
                  <span className={cn("tabular-nums", o.eligible ? "text-muted" : "text-bad")}>{o.eligible ? Math.round(o.score) : t("refused")}</span>
                </span>
                <span className="text-muted">{o.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
      {data.warnings.length > 0 && <Warnings items={data.warnings} />}
    </div>
  );
}
