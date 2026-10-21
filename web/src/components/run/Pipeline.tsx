"use client";
/* The pipeline of one analysis. On a NEW analysis the stages light up one after the other;
   LIVE stages show what the real agents returned, DEMO stages a placeholder from their owners. */
import { motion } from "framer-motion";
import {
  BadgeCheck, BarChart3, Check, Copy, Database, GitBranch, LayoutDashboard, Loader2, MessageSquare,
  Scale, ScanSearch, Shield, Sparkles, Tags, Upload,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { ModeBadge } from "@/components/ui/kit";
import type { Analysis, RunSummary } from "@/lib/client";
import { cn } from "@/lib/cn";
import { STAGES, type Stage } from "@/lib/pipeline";

const ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  upload: Upload, copy: Copy, tags: Tags, shield: Shield, scan: ScanSearch, sparkles: Sparkles, database: Database,
  message: MessageSquare, chart: BarChart3, scale: Scale, layout: LayoutDashboard, git: GitBranch, badge: BadgeCheck,
};

function useOutput(stage: Stage, a: Analysis, s: RunSummary | null, datasetName: string) {
  const t = useTranslations("app.stages");
  const tApp = useTranslations("app");
  const cmp = s?.comparison;
  const blocking = cmp?.checks.filter((c) => c.status === "blocking").map((c) => c.kind) ?? [];
  const warnings = cmp?.checks.filter((c) => c.status === "warning").map((c) => c.kind) ?? [];
  switch (stage.id) {
    case "upload":
      return a.file_name ? t("upload.file", { name: a.file_name, rows: a.file_rows ?? 0, cols: a.file_columns.length })
                         : t("upload.dataset", { name: datasetName });
    case "column_types":
      return a.file_columns.length ? t("column_types.file", { n: a.file_columns.length }) : t("column_types.out");
    case "profiling":
      return s?.anomalies != null ? t("profiling.real", { n: s.anomalies }) : t("profiling.out");
    case "request":
      return t("request.real", { kpi: a.metric, dim: a.dimensions[0]?.replace(/_/g, " ") ?? "—" });
    case "comparisons":
      if (!cmp) return t("comparisons.out");
      if (blocking.length) return t("comparisons.blocked", { kinds: blocking.join(", ") });
      if (warnings.length) return t("comparisons.warning", { kinds: warnings.join(", ") });
      return t("comparisons.valid");
    case "auditor":
      return t("auditor.real", { n: s?.anomalies ?? 0, entries: s?.integrity?.entries_checked ?? 0,
                                 drift: tApp(`drift.status.${s?.drift_status ?? "not_available"}`),
                                 intact: s?.integrity?.ok ? "ok" : "ko" });
    default:
      return t(`${stage.id}.out`);
  }
}

function StageRow({ stage, state, a, s, datasetName, last, compact }:
  { stage: Stage; state: "todo" | "doing" | "done"; a: Analysis; s: RunSummary | null; datasetName: string;
    last: boolean; compact: boolean }) {
  const t = useTranslations("app");
  const out = useOutput(stage, a, s, datasetName);
  const Icon = ICONS[stage.icon] ?? Sparkles;
  const live = stage.mode === "live";
  const alert = stage.id === "comparisons" && s?.comparison?.checks.some((c) => c.status === "blocking");
  if (compact) {
    return (
      <li className="flex items-center gap-3 py-1.5" title={out}>
        <span className={cn("grid h-7 w-7 shrink-0 place-items-center rounded-lg",
          live ? "bg-accent text-accent-fg" : "bg-primary-soft text-primary")}><Icon className="h-3.5 w-3.5" /></span>
        <span className="min-w-0 flex-1 truncate text-sm">{t(`stages.${stage.id}.name`)}</span>
        <ModeBadge mode={stage.mode} label={t(`mode.${stage.mode}`)} />
        <Check className={cn("h-4 w-4 shrink-0", alert ? "text-warn" : "text-ok")} aria-label={out} />
      </li>
    );
  }
  return (
    <li className="relative flex gap-4 pb-5">
      {!last && <span aria-hidden className={cn("absolute left-5 top-11 -bottom-0 w-px", state === "done" ? "bg-primary/40" : "bg-line")} />}
      <div className={cn("relative z-10 grid h-10 w-10 shrink-0 place-items-center rounded-xl border transition",
        state === "todo" && "border-line bg-surface text-subtle",
        state === "doing" && "border-primary bg-primary-soft text-primary",
        state === "done" && (live ? "border-accent bg-accent text-accent-fg" : "border-primary/30 bg-primary-soft text-primary"))}>
        {state === "doing" ? <Loader2 className="h-5 w-5 animate-spin" /> : <Icon className="h-5 w-5" />}
      </div>
      <div className={cn("min-w-0 flex-1 rounded-xl border p-3.5 transition",
        state === "todo" ? "border-transparent opacity-50" : "border-line bg-surface",
        live && state === "done" && "border-accent/40 shadow-card", alert && state === "done" && "border-warn/50 bg-warn-soft/40")}>
        <div className="flex items-start justify-between gap-2">
          <span className="font-semibold leading-snug">{t(`stages.${stage.id}.name`)}</span>
          <ModeBadge mode={stage.mode} label={t(`mode.${stage.mode}`)} />
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
          <span className="font-mono">{t("pipeline.step", { n: stage.step })}</span><span>·</span><span>{stage.owner}</span>
          {stage.bo.map((b) => <span key={b} className="rounded bg-surface-2 px-1.5 py-0.5 font-semibold">{b}</span>)}
        </div>
        {state !== "todo" && (
          <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-1.5 flex items-start gap-1.5 text-sm text-muted">
            {state === "done" && <Check className={cn("mt-0.5 h-4 w-4 shrink-0", alert ? "text-warn" : "text-ok")} />}
            <span>{state === "doing" ? t("pipeline.running") : out}</span>
          </motion.p>
        )}
      </div>
    </li>
  );
}

export function Pipeline({ a, summary, animate, datasetName, onDone }:
  { a: Analysis; summary: RunSummary | null; animate: boolean; datasetName: string; onDone?: () => void }) {
  const t = useTranslations("app.pipeline");
  const [step, setStep] = useState(animate ? 0 : STAGES.length);
  const [doing, setDoing] = useState(animate);
  const [compact, setCompact] = useState(!animate);
  useEffect(() => {
    if (!animate) return;
    if (step >= STAGES.length) { setDoing(false); setCompact(true); onDone?.(); return; }
    setDoing(true);
    const live = STAGES[step].mode === "live";
    const id = setTimeout(() => setStep((x) => x + 1), live ? 1100 : 420);
    return () => clearTimeout(id);
  }, [animate, step, onDone]);
  const doneCount = Math.min(step, STAGES.length);
  const live = STAGES.filter((s) => s.mode === "live").length;

  return (
    <section className="card p-5 sm:p-6" aria-labelledby="pipeline-title">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="pipeline-title" className="text-lg font-semibold">{t("title")}</h2>
          <p className="text-sm text-muted">{t("subtitle", { live, total: STAGES.length })}</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="h-2 w-40 overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-valuemin={0}
               aria-valuemax={STAGES.length} aria-valuenow={doneCount} aria-label={t("title")}>
            <motion.div className="h-full rounded-full bg-primary" animate={{ width: `${(doneCount / STAGES.length) * 100}%` }} />
          </div>
          <span className="font-mono text-xs text-muted">{doneCount}/{STAGES.length}</span>
        </div>
      </div>
      <ol className={compact ? "mt-4" : "mt-6"}>
        {STAGES.map((s, i) => (
          <StageRow key={s.id} stage={s} a={a} s={summary} datasetName={datasetName} last={i === STAGES.length - 1}
                    compact={compact} state={i < step ? "done" : i === step && doing ? "doing" : "todo"} />
        ))}
      </ol>
      {!doing && (
        <button type="button" onClick={() => setCompact((v) => !v)} aria-expanded={!compact}
                className="btn-outline mt-3 h-9 w-full text-xs">{compact ? t("details") : t("compact")}</button>
      )}
    </section>
  );
}
