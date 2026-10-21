"use client";
/* The hero's live story, looping: a question -> the agents work -> a misleading comparison is caught
   -> the honest answer with its proof. The numbers are the real Olist ones (August vs July 2018). */
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, BadgeCheck, MessageSquare } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";

const AGENTS = ["profile", "clean", "model", "kpi", "analyze", "check", "audit"] as const;
const BARS = [{ k: "SP", a: 244, b: 412 }, { k: "RJ", a: 92, b: 121 }, { k: "MG", a: 81, b: 110 }, { k: "RS", a: 38, b: 52 }, { k: "PR", a: 33, b: 47 }];

export function HeroDemo() {
  const t = useTranslations("landing.demo");
  const [phase, setPhase] = useState(0);                 // 0 ask, 1 agents, 2 caught, 3 answer
  const [agent, setAgent] = useState(-1);
  useEffect(() => {
    const id = setInterval(() => setPhase((p) => (p + 1) % 4), 2600);
    return () => clearInterval(id);
  }, []);
  useEffect(() => {
    if (phase !== 1) { setAgent(phase === 0 ? -1 : AGENTS.length); return; }
    setAgent(0);
    const id = setInterval(() => setAgent((a) => Math.min(a + 1, AGENTS.length)), 330);
    return () => clearInterval(id);
  }, [phase]);

  return (
    <div className="card relative overflow-hidden p-5 shadow-lift sm:p-6" aria-label={t("aria")} role="img">
      <div className="flex items-start gap-3">
        <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-primary-soft text-primary"><MessageSquare className="h-4 w-4" /></div>
        <div className="rounded-2xl rounded-tl-sm bg-surface-2 px-4 py-2.5 text-sm font-medium">{t("question")}</div>
      </div>

      <div className="mt-5">
        <div className="mb-2 flex items-center justify-between text-xs font-semibold text-muted">
          <span>{t("agents_at_work")}</span>
          <span className="font-mono">{Math.max(0, Math.min(agent, AGENTS.length))}/{AGENTS.length}</span>
        </div>
        <div className="grid grid-cols-7 gap-1.5">
          {AGENTS.map((a, i) => (
            <div key={a} className="flex flex-col items-center gap-1.5">
              <motion.div className={cn("h-2 w-full rounded-full", i < agent ? (a === "check" || a === "audit" ? "bg-accent" : "bg-primary") : "bg-line")}
                          animate={{ opacity: i === agent ? [0.5, 1, 0.5] : 1 }} transition={{ duration: 0.6, repeat: i === agent ? Infinity : 0 }} />
              <span className="truncate text-[10px] font-medium text-muted">{t(`agent_${a}`)}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-5 min-h-[208px]">
        <AnimatePresence mode="wait">
          {phase >= 2 && (
            <motion.div key={phase === 2 ? "caught" : "answer"} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -10 }} transition={{ duration: 0.35 }}>
              {phase === 2 ? (
                <div className="rounded-xl border border-warn/30 bg-warn-soft p-4">
                  <div className="flex items-center gap-2 text-sm font-bold text-warn"><AlertTriangle className="h-4 w-4" />{t("caught_title")}</div>
                  <p className="mt-1.5 text-sm text-ink">{t("caught_text")}</p>
                  <div className="mt-3 flex items-baseline gap-3 font-display">
                    <span className="text-2xl font-bold text-ink line-through decoration-bad/70">−4.1%</span>
                    <span className="text-sm text-muted">{t("as_asked")}</span>
                  </div>
                </div>
              ) : (
                <div>
                  <div className="flex items-end justify-between">
                    <div>
                      <div className="text-xs font-semibold text-muted">{t("answer_label")}</div>
                      <div className="font-display text-3xl font-bold text-ok">+34.6%</div>
                    </div>
                    <span className="chip bg-ok-soft text-ok"><BadgeCheck className="h-3.5 w-3.5" />{t("verified")}</span>
                  </div>
                  <div className="mt-3 flex h-28 items-end gap-3" aria-hidden>
                    {BARS.map((b, i) => (
                      <div key={b.k} className="flex flex-1 flex-col items-center gap-1">
                        <div className="flex h-24 w-full items-end gap-1">
                          <motion.div className="flex-1 rounded-t-md bg-primary/35" initial={{ height: 0 }} animate={{ height: `${(b.a / 412) * 100}%` }} transition={{ delay: i * 0.06, duration: 0.5 }} />
                          <motion.div className="flex-1 rounded-t-md bg-primary" initial={{ height: 0 }} animate={{ height: `${(b.b / 412) * 100}%` }} transition={{ delay: 0.1 + i * 0.06, duration: 0.5 }} />
                        </div>
                        <span className="text-[10px] font-semibold text-muted">{b.k}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </motion.div>
          )}
          {phase < 2 && (
            <motion.div key="wait" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                        className="grid h-[208px] place-items-center rounded-xl border border-dashed border-line text-sm text-muted">
              {phase === 0 ? t("waiting") : t("working")}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      <div className="mt-4 flex items-center gap-2 border-t border-line pt-3 text-xs text-muted">
        <span className="h-2 w-2 rounded-full bg-ok" />{t("footer")}
      </div>
    </div>
  );
}
