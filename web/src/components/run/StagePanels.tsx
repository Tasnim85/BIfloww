"use client";
/* What each agent produced, read from GET /api/runs/{id}/pipeline (contract files only).
   One small panel per stage; the BO3 / BO4-12 panels (AuditPanels, ComparisonPanel) are reused. */
import { ArrowRight, Check, ChevronDown, Code2, EyeOff, FileSpreadsheet, KeyRound, Lightbulb, ShieldCheck, TriangleAlert } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { Fragment, useMemo, useState } from "react";
import { fmtNum, fmtPct } from "@/components/ui/kit";
import type { Analysis, PipelineView, S } from "@/lib/client";
import { cn } from "@/lib/cn";

type V = PipelineView;
const int = (v: number, locale: string) => fmtNum(v, locale, 0);

// ---- small shared pieces -----------------------------------------------------------------------------
export function Tile({ label, value, hint, tone }: { label: string; value: React.ReactNode; hint?: string; tone?: "ok" | "warn" | "accent" }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className={cn("mt-1 font-display text-lg font-bold tabular-nums [overflow-wrap:anywhere] sm:text-2xl",
        tone === "ok" && "text-ok", tone === "warn" && "text-warn", tone === "accent" && "text-accent")}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-subtle">{hint}</div>}
    </div>
  );
}

function Bar({ value, className }: { value: number; className?: string }) {
  return (
    <span className="block h-1.5 w-full overflow-hidden rounded-full bg-surface-2" aria-hidden>
      <span className={cn("block h-full rounded-full bg-primary", className)} style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} />
    </span>
  );
}

const Mono = ({ children }: { children: React.ReactNode }) => <span className="font-mono text-[12px]">{children}</span>;

// ---- 0 · upload (Samar, demo) --------------------------------------------------------------------------
export function UploadPanel({ v, a }: { v: V | null; a: Analysis }) {
  const t = useTranslations("app.inspect.upload");
  const locale = useLocale();
  return (
    <div className="space-y-4">
      {a.file_name && a.file_rows != null && (
        <div className="flex items-start gap-3 rounded-xl border border-line p-4">
          <FileSpreadsheet className="mt-0.5 h-5 w-5 text-primary" />
          <div className="min-w-0">
            <div className="font-semibold [overflow-wrap:anywhere]">{a.file_name}</div>
            <p className="text-sm text-muted">{t("file", { rows: int(a.file_rows ?? 0, locale), cols: a.file_columns.length })}</p>
          </div>
        </div>
      )}
      {v?.tables && (
        <div>
          <h4 className="text-sm font-semibold">{t("tables", { n: Object.keys(v.tables).length })}</h4>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {Object.entries(v.tables).map(([name, file]) => <span key={name} className="chip border border-line bg-surface-2" title={file}><Mono>{name}</Mono></span>)}
          </div>
        </div>
      )}
    </div>
  );
}

// ---- 0 · similarity (Malek) ----------------------------------------------------------------------------
export function SimilarityPanel({ v }: { v: V }) {
  const t = useTranslations("app.inspect.similarity");
  const s = v.similarity!;
  const best = s.best_match;
  return (
    <div className="grid gap-4 md:grid-cols-[240px_minmax(0,1fr)]">
      <div className="rounded-xl border border-line bg-surface p-5 text-center">
        <div className="font-display text-5xl font-bold text-primary tabular-nums">{best ? Math.round(best.score * 100) : 0}<span className="text-2xl">%</span></div>
        <p className="mt-1 text-sm text-muted">{best ? t("close_to", { name: best.name }) : t("none")}</p>
        {best?.playbook && <span className="chip mt-3 bg-accent-soft text-ink"><KeyRound className="h-3.5 w-3.5 text-accent" />{t("playbook", { p: best.playbook })}</span>}
      </div>
      <div>
        <p className="text-sm text-muted">{t("text")}</p>
        <ul className="mt-3 space-y-2.5">
          {s.matches.map((m) => (
            <li key={m.name} className="text-sm">
              <div className="flex justify-between"><Mono>{m.name}</Mono><span className="tabular-nums text-muted">{Math.round(m.score * 100)} %</span></div>
              <div className="relative mt-1">
                <Bar value={m.score} className={m.score >= s.threshold ? "bg-accent" : "bg-muted"} />
                <span className="absolute -top-1 h-3.5 w-px bg-ink/60" style={{ left: `${s.threshold * 100}%` }} title={t("threshold")} />
              </div>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-subtle">{t("method", { m: s.method, th: Math.round(s.threshold * 100) })}</p>
      </div>
    </div>
  );
}

// ---- 1a · column types (Malek) -------------------------------------------------------------------------
export function ColumnTypesPanel({ v }: { v: V }) {
  const t = useTranslations("app.inspect.column_types");
  const cols = v.column_types!.columns;
  const tables = useMemo(() => [...new Set(cols.map((c) => c.table))], [cols]);
  const [table, setTable] = useState<string>("");
  const counts = useMemo(() => {
    const m = new Map<string, number>();
    cols.forEach((c) => m.set(c.semantic_type, (m.get(c.semantic_type) ?? 0) + 1));
    return [...m.entries()].sort((x, y) => y[1] - x[1]);
  }, [cols]);
  const shown = table ? cols.filter((c) => c.table === table) : cols;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-1.5">
        {counts.map(([k, n]) => <span key={k} className="chip border border-line bg-surface"><b className="tabular-nums">{n}</b>{k}</span>)}
        <span className="chip bg-warn-soft text-warn"><EyeOff className="h-3.5 w-3.5" />{t("pii_candidates", { n: cols.filter((c) => c.pii_candidate).length })}</span>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted">{t("text", { n: cols.length, model: v.column_types!.model })}</p>
        <select aria-label={t("filter")} className="input h-9 w-auto py-0 text-sm" value={table} onChange={(e) => setTable(e.target.value)}>
          <option value="">{t("all_tables", { n: tables.length })}</option>
          {tables.map((x) => <option key={x} value={x}>{x}</option>)}
        </select>
      </div>
      <div className="max-h-[420px] overflow-auto rounded-xl border border-line">
        <table className="w-full text-left text-sm">
          <thead className="sticky top-0 bg-surface-2 text-xs text-muted">
            <tr><th className="px-3 py-2 font-semibold">{t("column")}</th><th className="px-3 py-2 font-semibold">{t("type")}</th>
              <th className="w-32 px-3 py-2 font-semibold">{t("confidence")}</th><th className="px-3 py-2 font-semibold">PII</th></tr>
          </thead>
          <tbody>
            {shown.map((c) => (
              <tr key={`${c.table}.${c.column}`} className="border-t border-line">
                <td className="px-3 py-1.5"><Mono>{c.column}</Mono>{!table && <span className="ml-2 text-xs text-subtle">{c.table}</span>}</td>
                <td className="px-3 py-1.5"><span className="chip bg-primary-soft text-primary">{c.semantic_type}</span></td>
                <td className="px-3 py-1.5"><div className="flex items-center gap-2"><Bar value={c.confidence} /><span className="w-9 text-right text-xs tabular-nums text-muted">{Math.round(c.confidence * 100)}%</span></div></td>
                <td className="px-3 py-1.5">{c.pii_candidate && <EyeOff className="h-4 w-4 text-warn" aria-label={t("pii_flag")} />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---- 1b · PII (Ikbel) -----------------------------------------------------------------------------------
const ACTION_STYLE: Record<string, string> = {
  kept: "bg-line", pseudonymized: "bg-primary", generalized: "bg-accent", dropped: "bg-bad",
};
export function PiiPanel({ v }: { v: V }) {
  const t = useTranslations("app.inspect.pii");
  const locale = useLocale();
  const p = v.pii!;
  const total = p.columns.length || 1;
  const touched = p.columns.filter((c) => c.action !== "kept");
  const order = ["pseudonymized", "generalized", "dropped", "kept"].filter((k) => p.actions[k]);
  return (
    <div className="space-y-5">
      <div>
        <div className="flex h-3 overflow-hidden rounded-full" role="img" aria-label={order.map((k) => `${p.actions[k]} ${t(`actions.${k}`)}`).join(", ")}>
          {order.map((k) => <span key={k} className={ACTION_STYLE[k]} style={{ width: `${(p.actions[k] / total) * 100}%` }} />)}
        </div>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
          {order.map((k) => <span key={k} className="inline-flex items-center gap-1.5"><span className={cn("h-2.5 w-2.5 rounded-sm", ACTION_STYLE[k])} /><b className="text-ink">{p.actions[k]}</b>{t(`actions.${k}`)}</span>)}
        </div>
      </div>
      <ul className="divide-y divide-line rounded-xl border border-line">
        {touched.map((c) => (
          <li key={`${c.table}.${c.column}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-sm">
            <span className="min-w-0 flex-1"><Mono>{c.table}.{c.column}</Mono></span>
            <span className="chip bg-surface-2 text-muted">{c.pii_kind}</span>
            <span className={cn("chip", c.action === "pseudonymized" ? "bg-primary-soft text-primary" : c.action === "dropped" ? "bg-bad-soft text-bad" : "bg-accent-soft text-ink")}>{t(`actions.${c.action}`)}</span>
            <span className="w-28 text-right text-xs text-muted">{t("rows", { n: int(c.rows_affected, locale) })}</span>
          </li>
        ))}
      </ul>
      <p className="flex items-start gap-2 rounded-xl bg-surface-2 p-3 text-xs text-muted"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" />{t("note", { policy: p.policy_version })}</p>
    </div>
  );
}

// ---- 2 · profiling (Ahmed) -------------------------------------------------------------------------------
export function ProfilingPanel({ v, onAudit }: { v: V; onAudit: () => void }) {
  const t = useTranslations("app.inspect.profiling");
  const locale = useLocale();
  const p = v.profiling!;
  const an = p.anomalies;
  return (
    <div className="space-y-5">
      {an && (
        <div className="flex flex-wrap items-center gap-4 rounded-xl border border-accent/40 bg-accent-soft/50 p-4">
          <div className="font-display text-3xl font-bold tabular-nums">{int(an.n_anomalies, locale)}</div>
          <div className="min-w-0 flex-1 text-sm">
            <div className="font-semibold">{t("anomalies", { table: an.table, n: int(an.n_rows, locale) })}</div>
            <div className="text-muted">{t("model", { m: an.model, v: an.model_version, c: fmtPct(an.contamination ?? null, locale).replace("+", "") })} · <Mono>{an.features.join(", ")}</Mono></div>
          </div>
          <button type="button" onClick={onAudit} className="btn-outline h-9 text-xs">{t("see_shap")}<ArrowRight className="h-3.5 w-3.5" /></button>
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {p.tables.map((x) => (
          <div key={x.table} className="rounded-xl border border-line p-3.5">
            <div className="flex items-baseline justify-between gap-2"><Mono>{x.table}</Mono><span className="text-xs text-subtle">{t("cols", { n: x.columns })}</span></div>
            <div className="mt-1 font-display text-xl font-bold tabular-nums">{int(x.rows, locale)}</div>
            <div className="mt-1 flex flex-wrap gap-1.5 text-[11px]">
              <span className={cn("chip", x.duplicate_rows ? "bg-warn-soft text-warn" : "bg-ok-soft text-ok")}>{t("dupes", { n: int(x.duplicate_rows, locale) })}</span>
              <span className={cn("chip", x.missing_cells_pct ? "bg-warn-soft text-warn" : "bg-ok-soft text-ok")}>{t("missing", { p: fmtNum(x.missing_cells_pct, locale, 1) })}</span>
            </div>
            {x.most_missing.length > 0 && (
              <ul className="mt-2 space-y-1">
                {x.most_missing.map((m) => (
                  <li key={m.name} className="text-[11px] text-muted"><div className="flex justify-between gap-2"><span className="truncate font-mono">{m.name}</span><span className="tabular-nums">{fmtNum(m.missing_pct, locale, 1)} %</span></div>
                    <Bar value={m.missing_pct / 100} className="bg-warn" /></li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
      {p.coverage.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold">{t("coverage")}</h4>
          <ul className="mt-2 flex flex-wrap gap-2 text-xs">
            {p.coverage.map((c) => <li key={c.table} className="chip border border-line bg-surface"><Mono>{c.table}.{c.date_column}</Mono>{c.first_day} → {c.last_day} · {t("days", { n: c.days })}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

// ---- 2b · cleaning (Ikbel) ---------------------------------------------------------------------------------
export function CleaningPanel({ v }: { v: V }) {
  const t = useTranslations("app.inspect.cleaning");
  const locale = useLocale();
  const c = v.cleaning!;
  const [all, setAll] = useState(false);
  const rules = all ? c.applied : c.applied.filter((r) => r.rows_affected > 0);
  const changed = Object.keys(c.rows_before).filter((k) => c.rows_before[k] !== c.rows_after[k]);
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile label={t("playbook")} value={<span className="text-lg">{c.playbook}</span>} hint={t("versioned")} />
        <Tile label={t("rules")} value={c.rules} />
        <Tile label={t("with_effect")} value={c.rules_with_effect} tone="accent" />
        <Tile label={t("cells")} value={int(c.rows_changed, locale)} />
      </div>
      <ul className="divide-y divide-line rounded-xl border border-line">
        {rules.map((r) => (
          <li key={r.rule_id} className="flex items-center gap-3 px-4 py-2 text-sm">
            <span className="min-w-0 flex-1 truncate"><Mono>{r.rule_id}</Mono></span>
            <span className={cn("w-32 text-right text-xs tabular-nums", r.rows_affected ? "font-semibold text-ink" : "text-subtle")}>{t("rows", { n: int(r.rows_affected, locale) })}</span>
          </li>
        ))}
      </ul>
      {c.applied.length > c.rules_with_effect && (
        <button type="button" className="btn-ghost h-8 text-xs" onClick={() => setAll((x) => !x)} aria-expanded={all}>
          <ChevronDown className={cn("h-3.5 w-3.5 transition", all && "rotate-180")} />{all ? t("only_effect") : t("show_all", { n: c.applied.length - c.rules_with_effect })}
        </button>
      )}
      <p className="text-xs text-muted">{changed.length ? t("rows_changed_tables", { tables: changed.join(", ") }) : t("no_row_lost", { n: Object.keys(c.rows_before).length })}</p>
    </div>
  );
}

// ---- 3 · ETL (Ahmed) -------------------------------------------------------------------------------------------
export function EtlPanel({ v }: { v: V }) {
  const t = useTranslations("app.inspect.etl");
  const locale = useLocale();
  const { manifest, receipts } = v.etl!;
  const rec = new Map((receipts?.receipts ?? []).map((r) => [r.output_table, r]));
  const tables = [...manifest.tables].sort((x, y) => (x.kind === y.kind ? x.name.localeCompare(y.name) : x.kind === "fact" ? -1 : 1));
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">{t("text", { facts: tables.filter((x) => x.kind === "fact").length, dims: tables.filter((x) => x.kind === "dimension").length })}</p>
      <div className="grid gap-3 md:grid-cols-2">
        {tables.map((x) => {
          const r = rec.get(x.name);
          const kept = r ? r.rows_before === r.rows_after : null;
          return (
            <div key={x.name} className={cn("rounded-xl border p-4", x.kind === "fact" ? "border-accent/50" : "border-line")}>
              <div className="flex items-center gap-2">
                <span className={cn("chip text-[10px] uppercase tracking-wider", x.kind === "fact" ? "bg-accent text-accent-fg" : "bg-primary-soft text-primary")}>{t(`kind.${x.kind}`)}</span>
                <span className="min-w-0 flex-1 truncate font-semibold"><Mono>{x.name}</Mono></span>
                <span className="text-sm tabular-nums text-muted">{int(x.row_count, locale)}</span>
              </div>
              <div className="mt-2 text-xs text-muted">{t("grain", { g: x.grain })} · {t("key", { k: x.primary_key.join(", ") || "—" })} · {t("cols", { n: x.columns.length })}</div>
              {r && (
                <div className={cn("mt-2 flex flex-wrap items-center gap-1.5 text-xs", kept ? "text-ok" : "text-warn")}>
                  {kept ? <Check className="h-3.5 w-3.5" /> : <TriangleAlert className="h-3.5 w-3.5" />}
                  <span className="text-muted">{r.source_tables.join(" + ")}</span>
                  <span className="tabular-nums">{int(r.rows_before, locale)} → {int(r.rows_after, locale)}</span>
                  <span>{kept ? t("no_fanout") : t("changed")}</span>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---- lineage (Ahmed) ------------------------------------------------------------------------------------------
const LAYERS = ["raw", "pii", "clean", "physical", "warehouse", "kpi"] as const;
export function LineagePanel({ v }: { v: V }) {
  const t = useTranslations("app.inspect.lineage");
  const locale = useLocale();
  const l = v.lineage!;
  const chains = useMemo(() => {
    const next = new Map<string, S["LineageEdge"]>();
    l.edges.forEach((e) => { if (!next.has(e.source)) next.set(e.source, e); });
    return l.nodes.filter((n) => n.id.startsWith("raw:")).map((n) => {
      const steps: { id: string; relation?: string }[] = [{ id: n.id }];
      let cur = n.id;
      for (let i = 0; i < 12 && next.has(cur); i++) { const e = next.get(cur)!; steps.push({ id: e.target, relation: e.relation }); cur = e.target; }
      return steps;
    });
  }, [l]);
  const layers = LAYERS.filter((k) => chains.some((c) => c.some((s) => s.id.startsWith(`${k}:`))));
  const label = (id: string) => id.slice(id.indexOf(":") + 1);
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">{t("text", { kpi: l.kpi })}</p>
      <div className="overflow-x-auto">
        <div className="grid min-w-[760px] gap-y-2" style={{ gridTemplateColumns: `repeat(${layers.length}, minmax(0, 1fr))` }}>
          {layers.map((k) => <div key={k} className="px-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-subtle">{t(`layers.${k}`)}</div>)}
          {chains.map((c) => (
            <Fragment key={c[0].id}>
              {layers.map((k, i) => {
                const s = c.find((x) => x.id.startsWith(`${k}:`));
                return (
                  <div key={k} className="flex items-center">
                    {i > 0 && <ArrowRight className="mx-1 h-3.5 w-3.5 shrink-0 text-subtle" aria-hidden />}
                    {s ? (
                      <span title={s.relation ? `${s.relation} → ${s.id}` : s.id}
                            className={cn("min-w-0 truncate rounded-lg border px-2 py-1 font-mono text-[11px]",
                              k === "kpi" ? "border-accent bg-accent text-accent-fg font-semibold" : k === "raw" ? "border-line bg-surface-2" : "border-primary/25 bg-primary-soft text-ink")}>
                        {label(s.id)}
                      </span>
                    ) : <span className="text-subtle">·</span>}
                  </div>
                );
              })}
            </Fragment>
          ))}
        </div>
      </div>
      <p className="text-xs text-subtle">{t("size", { n: int(l.total_nodes, locale), e: int(l.total_edges, locale), shown: l.nodes.length })}</p>
    </div>
  );
}

// ---- 4 · request (Malek) ------------------------------------------------------------------------------------------
function Highlight({ text, terms }: { text: string; terms: string[] }) {
  if (!terms.length) return <>{text}</>;
  const esc = terms.map((x) => x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).sort((a, b) => b.length - a.length);
  const parts = text.split(new RegExp(`(${esc.join("|")})`, "gi"));
  return <>{parts.map((p, i) => terms.some((x) => x.toLowerCase() === p.toLowerCase())
    ? <mark key={i} className="rounded bg-accent-soft px-1 text-ink">{p}</mark> : <Fragment key={i}>{p}</Fragment>)}</>;
}
export function RequestPanel({ v }: { v: V }) {
  const t = useTranslations("app.inspect.request");
  const r = v.request!;
  const terms = Object.entries(r.matched_terms ?? {});
  return (
    <div className="space-y-5">
      <blockquote className="rounded-xl border-l-4 border-accent bg-surface-2 px-4 py-3 text-lg [overflow-wrap:anywhere]">
        <Highlight text={r.question} terms={terms.map(([w]) => w)} />
      </blockquote>
      {terms.length > 0 ? (
        <ul className="flex flex-wrap gap-2">
          {terms.map(([w, g]) => <li key={w} className="chip border border-line bg-surface">“{w}” <ArrowRight className="h-3 w-3 text-subtle" /> <b className="font-mono text-[12px]">{g}</b></li>)}
        </ul>
      ) : <p className="text-sm text-muted">{t("from_form")}</p>}
      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label={t("metric")} value={r.metric} />
        <Field label={t("dimensions")} value={r.dimensions.map((d) => d.replace(/_/g, " ")).join(", ") || t("overall")} />
        <Field label={t("period")} value={`${r.period.start} → ${r.period.end}`} />
        <Field label={t("compare_to")} value={r.compare_to ? `${r.compare_to.start} → ${r.compare_to.end}` : "—"} />
      </dl>
      {terms.length > 0 && (
        <div className="max-w-sm">
          <div className="flex justify-between text-xs text-muted"><span>{t("confidence")}</span><span className="tabular-nums">{Math.round((r.confidence ?? 1) * 100)} %</span></div>
          <div className="mt-1"><Bar value={r.confidence ?? 1} className="bg-accent" /></div>
        </div>
      )}
    </div>
  );
}
function Field({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border border-line p-3"><dt className="text-xs text-muted">{label}</dt><dd className="mt-0.5 font-semibold [overflow-wrap:anywhere]">{value}</dd></div>;
}

// ---- 5 · analysis (Rabeb) ------------------------------------------------------------------------------------------
export function AnalysisPanel({ v }: { v: V }) {
  const t = useTranslations("app.inspect.analysis");
  const locale = useLocale();
  const a = v.analysis!;
  const passed = a.validations.filter((x) => x.passed).length;
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile label={t("current")} value={fmtNum(a.value_current, locale)} hint={a.unit} />
        <Tile label={t("previous")} value={fmtNum(a.value_previous, locale)} hint={a.unit} />
        <Tile label={t("change")} value={fmtPct(a.change_pct, locale)} tone={(a.change_pct ?? 0) >= 0 ? "ok" : "warn"} hint={t("as_asked")} />
        <Tile label={t("kpi")} value={<span className="text-lg">{a.kpi}</span>} hint={t("rows", { n: a.rows })} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <section>
          <h4 className="text-sm font-semibold">{t("checks", { ok: passed, n: a.validations.length })}</h4>
          <ul className="mt-2 space-y-2">
            {a.validations.map((c) => (
              <li key={c.name} className="flex gap-2.5 rounded-xl border border-line p-3 text-sm">
                {c.passed ? <Check className="mt-0.5 h-4 w-4 shrink-0 text-ok" /> : <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-bad" />}
                <div className="min-w-0"><Mono>{c.name}</Mono><p className="mt-0.5 text-xs text-muted [overflow-wrap:anywhere]">{c.detail}</p></div>
              </li>
            ))}
          </ul>
        </section>
        <section>
          <h4 className="text-sm font-semibold">{t("insights")}</h4>
          <Insights items={a.insights} />
        </section>
      </div>
      <details className="group rounded-xl border border-line">
        <summary className="flex cursor-pointer items-center gap-2 px-4 py-2.5 text-sm font-medium"><Code2 className="h-4 w-4 text-primary" />{t("sql")}<ChevronDown className="ml-auto h-4 w-4 transition group-open:rotate-180" /></summary>
        <pre className="overflow-x-auto border-t border-line bg-surface-2 p-4 font-mono text-[12px] leading-relaxed">{a.sql}</pre>
      </details>
    </div>
  );
}

export function Insights({ items }: { items: S["Insight"][] }) {
  const t = useTranslations("app.inspect.analysis");
  if (!items.length) return <p className="mt-2 text-sm text-muted">{t("no_insight")}</p>;
  return (
    <ul className="mt-2 space-y-2">
      {items.map((x, i) => (
        <li key={i} className="flex gap-2.5 rounded-xl bg-accent-soft/50 p-3 text-sm">
          <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-accent" /><span>{x.text}</span>
        </li>
      ))}
    </ul>
  );
}
