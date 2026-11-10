"use client";
/* The pipeline as a horizontal rail: the orchestrator + the 6 agents, in DAG order, each with the
   tasks it performs underneath. Click a task: the inspector below shows what that agent produced. On a NEW analysis the stages light up one after the other. */
import { motion } from "framer-motion";
import {
  BadgeCheck, BarChart3, ChevronRight, Copy, Database, GitBranch, LayoutDashboard, Loader2, MessageSquare,
  Scale, ScanSearch, Shield, Sparkles, Tags, Upload,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { Fragment, useEffect, useRef } from "react";
import { cn } from "@/lib/cn";
import { PHASES, STAGES, type Stage, type StageState } from "@/lib/pipeline";

export const ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  upload: Upload, copy: Copy, tags: Tags, shield: Shield, scan: ScanSearch, sparkles: Sparkles, database: Database,
  message: MessageSquare, chart: BarChart3, scale: Scale, layout: LayoutDashboard, git: GitBranch, badge: BadgeCheck,
};

export function StateDot({ state, className }: { state: StageState; className?: string }) {
  return <span aria-hidden className={cn("inline-block h-2 w-2 rounded-full",
    state === "live" ? "bg-accent" : state === "demo" ? "border border-muted" : "bg-line", className)} />;
}

export function PipelineRail({ states, selected, onSelect, progress, alerts, real }:
  { states: Record<string, StageState>; selected: string; onSelect: (id: string) => void;
    progress: number;              // number of stages already "done" (13 = all)
    alerts: string[];              // stages to flag (e.g. a blocked comparison)
    real?: Record<string, string> }) {   // an uploaded dataset: the REAL status of each step (orchestrator)
  const t = useTranslations("app");
  const box = useRef<HTMLDivElement>(null);
  const running = !real && progress < STAGES.length;
  const statusOf = (s: (typeof STAGES)[number]): "todo" | "doing" | "done" => {
    if (real) {
      const st = real[s.id];
      return st === "RUNNING" ? "doing" : st === "SUCCESS" || st === "NEEDS_REVIEW" || st === "FAILED" ? "done" : "todo";
    }
    return running ? (STAGES.indexOf(s) < progress ? "done" : STAGES.indexOf(s) === progress ? "doing" : "todo") : "done";
  };

  // keep the stage being worked on (or the selected one) visible on small screens
  useEffect(() => {
    const id = running ? STAGES[Math.min(progress, STAGES.length - 1)].id : selected;
    const el = box.current?.querySelector<HTMLElement>(`[data-stage="${id}"]`);
    const parent = box.current;
    if (!el || !parent || parent.scrollWidth <= parent.clientWidth) return;
    const dx = el.getBoundingClientRect().left - parent.getBoundingClientRect().left;
    parent.scrollTo({ left: parent.scrollLeft + dx - parent.clientWidth / 2 + el.clientWidth / 2, behavior: "smooth" });
  }, [progress, selected, running]);

  return (
    <div ref={box} className="-mx-1 overflow-x-auto px-1 pb-2 [scrollbar-width:thin]">
      <div role="tablist" aria-label={t("rail.label")} className="flex min-w-[1180px] items-stretch gap-1">
        {PHASES.map((phase, i) => {
          const stages = STAGES.filter((s) => s.phase === phase);
          return (
            <Fragment key={phase}>
              {i > 0 && <ChevronRight aria-hidden className="h-4 w-4 shrink-0 self-center text-subtle" />}
              <div style={{ flexGrow: Math.max(stages.length, 1.4), flexBasis: 0 }}
                   className="flex min-w-0 flex-col rounded-2xl border border-line bg-surface-2/60 px-1.5 pb-2 pt-2.5">
                <div className="flex min-h-[2.5em] items-start gap-1.5 px-1.5">
                  <span className="mt-px grid h-4 w-4 shrink-0 place-items-center rounded-full bg-primary/10 text-[9px] font-bold text-primary">{i}</span>
                  <span className="line-clamp-2 text-[10px] font-semibold uppercase leading-tight tracking-[0.08em] text-ink/80">{t(`rail.phases.${phase}`)}</span>
                </div>
                <div className="relative mt-2 flex">
                  {stages.length > 1 && <span aria-hidden className="absolute left-[12%] right-[12%] top-5 h-px bg-line" />}
                  {stages.map((s) => (
                    <Node key={s.id} stage={s} state={states[s.id] ?? "missing"} selected={!running && selected === s.id}
                          alert={alerts.includes(s.id)} onSelect={onSelect}
                          status={statusOf(s)} />
                  ))}
                </div>
              </div>
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}

function Node({ stage, state, selected, alert, status, onSelect }:
  { stage: Stage; state: StageState; selected: boolean; alert: boolean; status: "todo" | "doing" | "done";
    onSelect: (id: string) => void }) {
  const t = useTranslations("app");
  const Icon = ICONS[stage.icon] ?? Sparkles;
  return (
    <button type="button" role="tab" aria-selected={selected} aria-controls="stage-inspector" data-stage={stage.id}
            disabled={status !== "done"} onClick={() => onSelect(stage.id)}
            title={`${t(`stages.${stage.id}.name`)} · ${stage.owner} · ${t(`state.${state}`)}`}
            className={cn("group relative flex min-w-0 flex-1 flex-col items-center rounded-xl px-1 pb-1.5 pt-0 text-center transition",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
              selected ? "bg-surface shadow-card" : "hover:bg-surface/70", status === "todo" && "opacity-35")}>
      <span className={cn("relative z-10 grid h-10 w-10 place-items-center rounded-full transition",
        status === "doing" ? "bg-primary text-primary-fg"
          : state === "live" ? "bg-accent text-accent-fg"
          : state === "demo" ? "border border-dashed border-muted/60 bg-surface text-muted"
          : "bg-surface-2 text-subtle",
        selected && "ring-4 ring-primary/25")}>
        {status === "doing" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Icon className="h-[18px] w-[18px]" />}
        {status === "done" && alert && <span className="absolute -right-0.5 -top-0.5 h-3 w-3 rounded-full border-2 border-surface bg-warn" />}
        {status === "done" && state === "live" && !selected && (
          <motion.span aria-hidden initial={{ scale: 0.6, opacity: 0.8 }} animate={{ scale: 1.5, opacity: 0 }}
                       transition={{ duration: 0.9 }} className="absolute inset-0 rounded-full bg-accent" />)}
      </span>
      <span className={cn("mt-1.5 line-clamp-2 min-h-[2.4em] text-[11px] leading-tight", selected ? "font-semibold text-ink" : "text-muted")}>
        {t(`stages.${stage.id}.short`)}
      </span>
      <span className="text-[10px] text-subtle">{stage.owner}</span>
      {selected && <motion.span layoutId="rail-pointer" aria-hidden className="absolute -bottom-2 left-1/2 h-1 w-8 -translate-x-1/2 rounded-full bg-primary" />}
    </button>
  );
}
