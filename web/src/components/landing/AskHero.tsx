"use client";
/* The hero's single moment: the question is typed, the data is prepared, the misleading
   comparison is caught, then the honest answer appears with its proof. Real Olist figures
   (August vs July 2018). With reduced motion, the final answer is shown directly. */
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { AlertTriangle, BookLock, Check, ListChecks } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";

const STAGES = ["profile", "clean", "model", "analyse", "check"] as const;
type Phase = "typing" | "preparing" | "caught" | "answer";

export function AskHero() {
  const t = useTranslations("landing.hero");
  const reduced = useReducedMotion();
  const question = t("question");
  const [typed, setTyped] = useState(reduced ? question.length : 0);
  const [phase, setPhase] = useState<Phase>(reduced ? "answer" : "typing");
  const [stage, setStage] = useState(0);

  useEffect(() => {
    if (reduced) { setTyped(question.length); setPhase("answer"); return; }
    let cancelled = false;
    const timers: ReturnType<typeof setTimeout>[] = [];
    const at = (ms: number, fn: () => void) => timers.push(setTimeout(() => { if (!cancelled) fn(); }, ms));
    const run = () => {
      setPhase("typing"); setTyped(0); setStage(0);
      let ms = 400;
      for (let i = 1; i <= question.length; i++) { at(ms, () => setTyped(i)); ms += 45; }
      ms += 450; at(ms, () => setPhase("preparing"));
      STAGES.forEach((_, i) => { ms += 380; at(ms, () => setStage(i + 1)); });
      ms += 500; at(ms, () => setPhase("caught"));
      ms += 2600; at(ms, () => setPhase("answer"));
      ms += 6500; at(ms, run);
    };
    run();
    return () => { cancelled = true; timers.forEach(clearTimeout); };
  }, [question, reduced]);

  const shown = question.slice(0, typed);
  const cut = shown.lastIndexOf(" ") + 1;
  const head = shown.slice(0, cut), tail = shown.slice(cut);
  return (
    <div role="img" aria-label={t("aria")}>
      <h1 className="font-display text-[2.15rem] font-bold leading-[1.1] tracking-tight text-ink sm:text-5xl lg:text-[4rem]">
        <span className="text-accent" aria-hidden>“</span>
        {head}
        {/* the last word, the caret and the closing quote never wrap apart */}
        <span className="whitespace-nowrap">
          {tail}
          <span className={cn("ml-1 inline-block h-[0.9em] w-[3px] translate-y-[0.1em] rounded bg-accent",
                              phase === "typing" ? "animate-pulse" : "hidden")} aria-hidden />
          <span className={cn("text-accent transition-opacity", typed === question.length ? "opacity-100" : "opacity-0")} aria-hidden>”</span>
        </span>
      </h1>

      <div className="mt-8 min-h-[176px] max-w-2xl">
        <AnimatePresence mode="wait">
          {phase === "preparing" && (
            <motion.div key="prep" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                        className="rounded-2xl border border-white/10 bg-white/[0.04] p-5">
              <p className="text-sm text-muted">{t("preparing")}</p>
              <ol className="mt-4 grid grid-cols-5 gap-2">
                {STAGES.map((s, i) => (
                  <li key={s} className="flex flex-col gap-2">
                    <span className={cn("h-1.5 rounded-full transition-colors duration-300", i < stage ? "bg-primary" : "bg-white/10")} />
                    <span className={cn("flex items-center gap-1 text-xs", i < stage ? "text-ink" : "text-subtle")}>
                      {i < stage && <Check className="h-3 w-3 text-primary" />}{t(`stages.${s}`)}
                    </span>
                  </li>
                ))}
              </ol>
            </motion.div>
          )}
          {phase === "caught" && (
            <motion.div key="caught" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                        className="rounded-2xl border border-accent/40 bg-accent/10 p-5">
              <div className="flex items-center gap-2 font-semibold text-accent"><AlertTriangle className="h-4 w-4" />{t("caught_title")}</div>
              <div className="mt-3 flex flex-wrap items-baseline gap-x-4 gap-y-1">
                <span className="font-display text-4xl font-bold text-ink line-through decoration-accent decoration-2">−4.1%</span>
                <span className="text-sm text-muted">{t("as_asked")}</span>
              </div>
              <p className="mt-2 text-sm text-ink/80">{t("caught_text")}</p>
            </motion.div>
          )}
          {phase === "answer" && (
            <motion.div key="answer" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                        className="rounded-2xl border border-white/10 bg-white/[0.06] p-5">
              <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                <span className="font-display text-5xl font-bold text-ok">+34.6%</span>
                <span className="font-semibold text-ink">{t("answer_title")}</span>
                <span className="text-sm text-subtle line-through">−4.1% {t("as_asked")}</span>
              </div>
              <p className="mt-2 text-sm text-muted">{t("answer_text")}</p>
              <div className="mt-4 flex flex-wrap gap-2 text-xs">
                <span className="chip bg-white/10 text-ink"><ListChecks className="h-3.5 w-3.5 text-primary" />{t("proof_checks")}</span>
                <span className="chip bg-white/10 text-ink"><BookLock className="h-3.5 w-3.5 text-primary" />{t("proof_journal")}</span>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
