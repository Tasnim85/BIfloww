import {
  BookLock, FileSpreadsheet, MessageSquareText, ScanSearch, ShieldCheck, Sparkles, Wand2,
} from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { AskHero } from "@/components/landing/AskHero";
import { Navbar } from "@/components/landing/Navbar";
import { Logo } from "@/components/ui/Logo";
import { currentUserId } from "@/lib/auth";

// a real sequence: numbered on purpose
const STEPS = [
  { id: "drop", icon: FileSpreadsheet }, { id: "prepare", icon: Wand2 }, { id: "ask", icon: MessageSquareText },
  { id: "check", icon: ScanSearch }, { id: "explain", icon: Sparkles },
];
const GOALS = ["bo1", "bo2", "bo3", "bo4"] as const;

/** Thin orbit rings, the same motif as the presentation's section slides. */
function Orbits({ className }: { className?: string }) {
  return (
    <div aria-hidden className={`pointer-events-none absolute ${className ?? ""}`}>
      {[100, 72, 46].map((s) => (
        <span key={s} className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/[0.08]"
              style={{ width: `${s}%`, height: `${s}%` }} />
      ))}
      <span className="absolute left-[14%] top-[22%] h-2 w-2 rounded-full bg-accent" />
      <span className="absolute right-[18%] top-[30%] h-1.5 w-1.5 rounded-full bg-primary" />
      <span className="absolute bottom-[20%] left-[30%] h-1.5 w-1.5 rounded-full bg-primary" />
    </div>
  );
}

export default async function Landing() {
  const t = await getTranslations("landing");
  const signedIn = Boolean(await currentUserId());
  const cta = signedIn ? "/app" : "/signup";

  return (
    <div className="relative overflow-x-clip">
      {/* ---- Hero: always dark, the question is the headline ---- */}
      <Navbar signedIn={signedIn} overDark />
      <section className="dark relative isolate overflow-hidden bg-bg text-ink">
        <div aria-hidden className="absolute inset-0 -z-10 bg-[radial-gradient(60%_70%_at_75%_40%,rgb(14_116_144/0.35),transparent_70%),radial-gradient(40%_40%_at_85%_80%,rgb(245_158_11/0.12),transparent_70%)]" />
        <Orbits className="-right-[18%] top-[6%] -z-10 aspect-square w-[95%] sm:w-[70%] lg:w-[58%]" />
        <div className="mx-auto max-w-6xl px-4 pb-20 pt-10 sm:px-6 lg:pb-28 lg:pt-16">
          <p className="max-w-xl text-lg text-muted">{t("hero.lead")}</p>
          <div className="mt-8"><AskHero /></div>
          <div className="mt-4 flex flex-wrap gap-3">
            <Link href={cta} className="btn-accent h-12 px-6 text-base">{t("hero.cta")}</Link>
            <a href="#how" className="btn h-12 border border-white/15 px-6 text-base text-ink hover:bg-white/5">{t("hero.secondary")}</a>
          </div>
        </div>
      </section>

      {/* ---- How it works: a five-step rail ---- */}
      <section id="how" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-24 sm:px-6">
        <div className="max-w-2xl">
          <h2 className="text-3xl font-bold sm:text-4xl">{t("how.title")}</h2>
          <p className="mt-4 text-lg text-muted">{t("how.text")}</p>
        </div>
        <ol className="relative mt-14 grid gap-10 md:grid-cols-5 md:gap-6">
          <span aria-hidden className="absolute left-6 top-6 hidden h-px w-[calc(100%-3rem)] bg-line md:block" />
          {STEPS.map(({ id, icon: Icon }, i) => (
            <li key={id} className="relative flex gap-4 md:block">
              <div className="relative z-10 grid h-12 w-12 shrink-0 place-items-center rounded-full border border-line bg-surface text-primary shadow-card">
                <Icon className="h-5 w-5" />
              </div>
              <div className="md:mt-5">
                <p className="font-display text-sm font-semibold text-accent">{i + 1}</p>
                <h3 className="mt-1 text-lg font-semibold">{t(`how.steps.${id}.title`)}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-muted">{t(`how.steps.${id}.text`)}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* ---- Proof: real fragments of the product, not feature cards ---- */}
      <section id="proof" className="scroll-mt-20 border-y border-line bg-surface py-24">
        <div className="mx-auto max-w-6xl px-4 sm:px-6">
          <div className="max-w-2xl">
            <h2 className="text-3xl font-bold sm:text-4xl">{t("proof.title")}</h2>
            <p className="mt-4 text-lg text-muted">{t("proof.text")}</p>
          </div>

          <div className="mt-12 grid gap-6 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
            {/* the comparison fix, as Sarra sees it */}
            <div className="rounded-3xl bg-bg p-6 sm:p-8">
              <h3 className="text-xl font-semibold">{t("proof.compare.title")}</h3>
              <div className="mt-6 flex items-baseline justify-between gap-4 rounded-2xl border border-line bg-surface px-5 py-4">
                <span className="text-sm text-muted">{t("proof.compare.asked")}</span>
                <span className="font-display text-2xl font-bold text-bad line-through decoration-2">−4.1%</span>
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <div className="rounded-2xl border-2 border-primary bg-surface px-5 py-4">
                  <span className="text-xs font-semibold text-primary">{t("proof.compare.recommended")}</span>
                  <p className="mt-1 text-sm font-medium">{t("proof.compare.fixed")}</p>
                  <p className="mt-2 font-display text-3xl font-bold text-ok">+34.6%</p>
                </div>
                <div className="rounded-2xl border border-line bg-surface px-5 py-4">
                  <span className="text-xs font-semibold text-muted">&nbsp;</span>
                  <p className="mt-1 text-sm font-medium">{t("proof.compare.per_day")}</p>
                  <p className="mt-2 font-display text-3xl font-bold text-ok">+23.4%</p>
                </div>
              </div>
              <p className="mt-5 flex items-center gap-2 text-sm text-muted"><ShieldCheck className="h-4 w-4 text-primary" />{t("proof.compare.choose")}</p>
            </div>

            <div className="grid gap-6">
              {/* an anomaly, explained */}
              <div className="rounded-3xl border border-line p-6">
                <h3 className="text-lg font-semibold">{t("proof.explain.title")}</h3>
                <p className="mt-3 text-sm leading-relaxed">{t("proof.explain.sentence")}</p>
                <div className="mt-4 space-y-2">
                  {[{ k: "f1", v: 67 }, { k: "f2", v: 33 }].map((f) => (
                    <div key={f.k} className="grid grid-cols-[8.5rem_1fr_2.5rem] items-center gap-3 text-xs">
                      <span className="truncate text-muted">{t(`proof.explain.${f.k}`)}</span>
                      <span className="h-2 rounded-full bg-surface-2"><span className="block h-2 rounded-full bg-accent" style={{ width: `${f.v}%` }} /></span>
                      <span className="text-right font-semibold">{f.v}%</span>
                    </div>
                  ))}
                </div>
              </div>
              {/* the journal: entries linked to each other */}
              <div className="rounded-3xl border border-line p-6">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-lg font-semibold">{t("proof.journal.title")}</h3>
                  <span className="chip shrink-0 bg-ok-soft text-ok"><BookLock className="h-3.5 w-3.5" />{t("proof.journal.intact")}</span>
                </div>
                <p className="mt-2 text-sm text-muted">{t("proof.journal.text")}</p>
                <ol className="relative mt-4 space-y-2 pl-5">
                  <span aria-hidden className="absolute bottom-3 left-[5px] top-3 w-px bg-primary/40" />
                  {(["r1", "r2", "r3"] as const).map((r) => (
                    <li key={r} className="relative text-sm">
                      <span aria-hidden className="absolute -left-5 top-1.5 h-2.5 w-2.5 rounded-full border-2 border-primary bg-surface" />
                      {t(`proof.journal.rows.${r}`)}
                    </li>
                  ))}
                </ol>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ---- Goals ---- */}
      <section id="goals" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-24 sm:px-6">
        <h2 className="text-3xl font-bold sm:text-4xl">{t("goals.title")}</h2>
        <dl className="mt-12 grid gap-x-8 gap-y-10 sm:grid-cols-2 lg:grid-cols-4">
          {GOALS.map((g) => (
            <div key={g} className="border-t-2 border-ink pt-5">
              <dt>
                <span className="font-display text-sm font-semibold text-primary">{g.toUpperCase()}</span>
                <span className="mt-2 block text-lg font-semibold">{t(`goals.${g}.title`)}</span>
              </dt>
              <dd className="mt-2 text-sm leading-relaxed text-muted">{t(`goals.${g}.text`)}</dd>
            </div>
          ))}
        </dl>
      </section>

      {/* ---- Closing call to action (dark again) ---- */}
      <section className="dark relative isolate overflow-hidden bg-bg text-ink">
        <Orbits className="left-1/2 top-1/2 -z-10 aspect-square w-[120%] -translate-x-1/2 -translate-y-1/2 sm:w-[70%]" />
        <div className="mx-auto max-w-3xl px-4 py-24 text-center sm:px-6">
          <h2 className="text-3xl font-bold sm:text-5xl">{t("cta.title")}</h2>
          <p className="mx-auto mt-4 max-w-xl text-lg text-muted">{t("cta.text")}</p>
          <Link href={cta} className="btn-accent mt-8 h-12 px-7 text-base">{t("cta.button")}</Link>
        </div>
      </section>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-4 py-8 text-sm text-muted sm:flex-row sm:px-6">
          <Logo variant="lockup" size={28} />
          <p>{t("footer.text")}</p>
        </div>
      </footer>
    </div>
  );
}
