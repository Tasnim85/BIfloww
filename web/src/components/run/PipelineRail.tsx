"use client";
/* The pipeline as a flow of agent cards: the orchestrator + the 6 agents, in DAG order, each with the
   tasks it performs underneath. Click a task: the inspector below shows what that agent produced.
   On a NEW analysis the tasks light up one after the other, the active agent glows and the
   connector leading to it flows. */
import { motion } from "framer-motion";
import {
  AlertTriangle, BadgeCheck, BarChart3, BookOpenText, Check, Copy, Database, GitBranch, LayoutDashboard, Loader2,
  MessageSquare, Scale, ScanSearch, Shield, ShieldCheck, Sparkles, Tags, Upload, Workflow,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { Fragment, useEffect, useRef } from "react";
import { cn } from "@/lib/cn";
import { PHASES, STAGES, type Phase, type Stage, type StageState } from "@/lib/pipeline";

export const ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  upload: Upload, copy: Copy, tags: Tags, shield: Shield, scan: ScanSearch, sparkles: Sparkles, database: Database,
  message: MessageSquare, chart: BarChart3, scale: Scale, layout: LayoutDashboard, git: GitBranch, badge: BadgeCheck,
};

/** Each agent has its own icon and colour, so the flow reads at a glance (works in light and dark). */
const AGENTS: Record<Phase, { icon: React.ComponentType<{ className?: string }>; from: string; to: string }> = {
  orchestrator: { icon: Workflow, from: "#0F2A3D", to: "#335C7A" },
  profiler: { icon: ScanSearch, from: "#0E7490", to: "#22A6C3" },
  etl: { icon: Database, from: "#4F46E5", to: "#818CF8" },
  semantic: { icon: BookOpenText, from: "#7C3AED", to: "#C084FC" },
  analyst: { icon: BarChart3, from: "#DB2777", to: "#F472B6" },
  dashboard: { icon: LayoutDashboard, from: "#EA580C", to: "#FBBF24" },
  auditor: { icon: ShieldCheck, from: "#047857", to: "#34D399" },
};

export function StateDot({ state, className }: { state: StageState; className?: string }) {
  return <span aria-hidden className={cn("inline-block h-2 w-2 rounded-full",
    state === "live" ? "bg-accent" : state === "demo" ? "border border-muted" : "bg-line", className)} />;
}

type Status = "todo" | "doing" | "done";

export function PipelineRail({ states, selected, onSelect, progress, alerts, real }:
  { states: Record<string, StageState>; selected: string; onSelect: (id: string) => void;
    progress: number;              // number of tasks already "done" (13 = all)
    alerts: string[];              // tasks to flag (e.g. a blocked comparison)
    real?: Record<string, string> }) {   // an uploaded dataset: the REAL status of each step (orchestrator)
  const t = useTranslations("app");
  const box = useRef<HTMLDivElement>(null);
  const running = !real && progress < STAGES.length;
  const statusOf = (s: Stage): Status => {
    if (real) {
      const st = real[s.id];
      return st === "RUNNING" ? "doing" : st === "SUCCESS" || st === "NEEDS_REVIEW" || st === "FAILED" ? "done" : "todo";
    }
    return running ? (STAGES.indexOf(s) < progress ? "done" : STAGES.indexOf(s) === progress ? "doing" : "todo") : "done";
  };
  const doneCount = STAGES.filter((s) => statusOf(s) === "done").length;

  // keep the task being worked on (or the selected one) visible on small screens
  useEffect(() => {
    const id = running ? STAGES[Math.min(progress, STAGES.length - 1)].id : selected;
    const el = box.current?.querySelector<HTMLElement>(`[data-stage="${id}"]`);
    const parent = box.current;
    if (!el || !parent || parent.scrollWidth <= parent.clientWidth) return;
    const dx = el.getBoundingClientRect().left - parent.getBoundingClientRect().left;
    parent.scrollTo({ left: parent.scrollLeft + dx - parent.clientWidth / 2 + el.clientWidth / 2, behavior: "smooth" });
  }, [progress, selected, running]);

  return (
    <div>
      {/* overall progress */}
      <div className="mb-4 flex items-center gap-3 px-1">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2">
          <motion.div className="h-full rounded-full bg-gradient-to-r from-[#0E7490] via-[#7C3AED] to-[#F59E0B]"
                      initial={false} animate={{ width: `${(doneCount / STAGES.length) * 100}%` }}
                      transition={{ type: "spring", stiffness: 80, damping: 20 }} />
        </div>
        <span className="shrink-0 font-mono text-[11px] tabular-nums text-muted">
          {t("rail.progress", { done: doneCount, total: STAGES.length })}
        </span>
      </div>

      <div ref={box} className="-mx-1 overflow-x-auto px-1 pb-3 [scrollbar-width:thin]">
        <div role="tablist" aria-label={t("rail.label")} className="flex min-w-[1040px] items-stretch">
          {PHASES.map((phase, i) => {
            const stages = STAGES.filter((s) => s.phase === phase);
            const statuses = stages.map(statusOf);
            const agentStatus: Status = statuses.includes("doing") ? "doing"
              : statuses.every((s) => s === "done") ? "done" : statuses.some((s) => s === "done") ? "doing" : "todo";
            const prevDone = i === 0 || STAGES.filter((s) => s.phase === PHASES[i - 1]).every((s) => statusOf(s) === "done");
            return (
              <Fragment key={phase}>
                {i > 0 && <Connector active={prevDone} flowing={prevDone && agentStatus !== "done"} />}
                <AgentCard phase={phase} index={i} status={agentStatus}
                           hasAlert={stages.some((s) => alerts.includes(s.id) && statusOf(s) === "done")}
                           live={stages.filter((s) => states[s.id] === "live").length} total={stages.length}>
                  {stages.map((s, k) => (
                    <TaskChip key={s.id} stage={s} state={states[s.id] ?? "missing"} selected={!running && selected === s.id}
                              alert={alerts.includes(s.id)} onSelect={onSelect} status={statuses[k]} delay={i * 0.06 + k * 0.04} />
                  ))}
                </AgentCard>
              </Fragment>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function Connector({ active, flowing }: { active: boolean; flowing: boolean }) {
  return (
    <div aria-hidden className="relative flex w-7 shrink-0 items-center">
      <svg viewBox="0 0 28 12" className="h-3 w-full overflow-visible">
        <line x1="0" y1="6" x2="22" y2="6" strokeWidth="2" strokeLinecap="round" strokeDasharray={flowing ? "4 4" : undefined}
              className={cn(active ? "stroke-primary" : "stroke-line", flowing && "animate-flow")} />
        <path d="M20 2 L26 6 L20 10" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
              className={active ? "stroke-primary" : "stroke-line"} />
      </svg>
    </div>
  );
}

function AgentCard({ phase, index, status, hasAlert, live, total, children }:
  { phase: Phase; index: number; status: Status; hasAlert: boolean; live: number; total: number; children: React.ReactNode }) {
  const t = useTranslations("app");
  const a = AGENTS[phase];
  const Icon = a.icon;
  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.05, duration: 0.35 }}
                className={cn("group/agent relative flex min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border bg-surface transition-all duration-300",
                  status === "doing" ? "border-transparent shadow-lift" : "border-line hover:-translate-y-0.5 hover:shadow-card",
                  status === "todo" && "opacity-50 saturate-50")}>
      {/* colour band of the agent */}
      <div className="h-1 w-full" style={{ background: `linear-gradient(90deg, ${a.from}, ${a.to})` }} />
      {status === "doing" && (
        <motion.span aria-hidden className="pointer-events-none absolute inset-0 rounded-2xl"
                     style={{ boxShadow: `inset 0 0 0 2px ${a.to}` }}
                     animate={{ opacity: [0.35, 1, 0.35] }} transition={{ duration: 1.6, repeat: Infinity }} />
      )}
      <div className="flex items-start gap-2 px-2.5 pb-2 pt-3">
        <span className="relative grid h-8 w-8 shrink-0 place-items-center rounded-xl text-white shadow-sm"
              style={{ background: `linear-gradient(135deg, ${a.from}, ${a.to})` }}>
          <Icon className="h-[18px] w-[18px]" />
          {status === "done" && !hasAlert && (
            <span className="absolute -bottom-1 -right-1 grid h-4 w-4 place-items-center rounded-full border-2 border-surface bg-ok text-white">
              <Check className="h-2.5 w-2.5" strokeWidth={3} />
            </span>
          )}
          {hasAlert && (
            <span className="absolute -bottom-1 -right-1 grid h-4 w-4 place-items-center rounded-full border-2 border-surface bg-warn text-white">
              <span className="text-[9px] font-bold leading-none">!</span>
            </span>
          )}
        </span>
        <div className="min-w-0">
          <div className="font-mono text-[9px] font-semibold uppercase tracking-[0.16em] text-subtle">
            {index === 0 ? t("rail.coordinator") : t("rail.agent_n", { n: index })}
          </div>
          <div className="text-[12px] font-semibold leading-tight text-ink [overflow-wrap:break-word] hyphens-auto">{t(`rail.phases.${phase}`)}</div>
        </div>
      </div>
      <div className="flex flex-1 flex-col gap-1 px-2 pb-2">{children}</div>
      <div className="flex items-center justify-between border-t border-line/70 px-3 py-1.5 text-[10px] text-subtle">
        <span>{t("rail.tasks", { count: total })}</span>
        <span className="inline-flex items-center gap-1"><StateDot state="live" className="h-1.5 w-1.5" />{live}/{total}</span>
      </div>
    </motion.div>
  );
}

function TaskChip({ stage, state, selected, alert, status, onSelect, delay }:
  { stage: Stage; state: StageState; selected: boolean; alert: boolean; status: Status;
    onSelect: (id: string) => void; delay: number }) {
  const t = useTranslations("app");
  const Icon = ICONS[stage.icon] ?? Sparkles;
  const flagged = alert && status === "done";
  return (
    <motion.button type="button" role="tab" aria-selected={selected} aria-controls="stage-inspector" data-stage={stage.id}
                   disabled={status !== "done"} onClick={() => onSelect(stage.id)}
                   initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay, duration: 0.25 }}
                   whileTap={status === "done" ? { scale: 0.97 } : undefined}
                   title={`${t(`stages.${stage.id}.name`)} · ${t(`state.${state}`)}`}
                   className={cn("relative flex w-full items-center gap-1.5 rounded-lg px-1.5 py-1.5 text-left transition-colors",
                     "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
                     selected ? "text-primary-fg shadow-sm"
                       : flagged ? "bg-warn-soft text-ink ring-1 ring-warn/40 hover:ring-warn"
                       : "text-muted hover:bg-surface-2 hover:text-ink",
                     status === "todo" && "cursor-default opacity-50")}>
      {selected && <motion.span layoutId="rail-selected" aria-hidden className="absolute inset-0 -z-0 rounded-lg bg-primary"
                                transition={{ type: "spring", stiffness: 400, damping: 32 }} />}
      <span className={cn("relative z-10 grid h-6 w-6 shrink-0 place-items-center rounded-md",
        selected ? "bg-white/15" : status === "doing" ? "bg-primary text-primary-fg"
          : state === "live" ? "bg-accent-soft text-warn" : "bg-surface-2 text-subtle")}>
        {status === "doing" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Icon className="h-3.5 w-3.5" />}
      </span>
      <span className="relative z-10 min-w-0 flex-1">
        <span className={cn("block text-[12px] leading-tight [overflow-wrap:break-word] hyphens-auto", selected ? "font-semibold" : "font-medium")}>
          {t(`stages.${stage.id}.short`)}
        </span>
        {flagged && (
          <span className={cn("mt-0.5 flex items-center gap-1 text-[10px] font-semibold", selected ? "text-primary-fg/90" : "text-warn")}>
            <AlertTriangle className="h-3 w-3" />{t("rail.alert")}
          </span>
        )}
      </span>
    </motion.button>
  );
}
