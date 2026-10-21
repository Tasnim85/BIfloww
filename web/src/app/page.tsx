import {
  ArrowRight, BadgeCheck, BrainCircuit, Database, FileSpreadsheet, Gauge, Languages, LayoutDashboard,
  Link2, LockKeyhole, MessageSquareText, Scale, ScanSearch, ShieldCheck, Sparkles, Users, Workflow,
} from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { HeroDemo } from "@/components/landing/HeroDemo";
import { Navbar } from "@/components/landing/Navbar";
import { Reveal } from "@/components/landing/Reveal";
import { Logo } from "@/components/ui/Logo";
import { currentUserId } from "@/lib/auth";

const STEPS = [{ id: "drop", icon: FileSpreadsheet }, { id: "ask", icon: MessageSquareText }, { id: "trust", icon: BadgeCheck }];
const AGENTS = [
  { id: "quality", icon: ScanSearch }, { id: "etl", icon: Database }, { id: "semantic", icon: BrainCircuit },
  { id: "analyst", icon: Gauge }, { id: "dashboard", icon: LayoutDashboard }, { id: "auditor", icon: ShieldCheck },
];
const OBJECTIVES = [
  { id: "bo1", icon: Sparkles }, { id: "bo2", icon: Workflow }, { id: "bo3", icon: Scale }, { id: "bo4", icon: Users },
];

export default async function Landing() {
  const t = await getTranslations("landing");
  const signedIn = Boolean(await currentUserId());
  const cta = signedIn ? "/app" : "/signup";

  return (
    <div className="relative overflow-x-clip">
      <Navbar signedIn={signedIn} />

      {/* ---- Hero ---- */}
      <section className="relative">
        <div className="grid-bg pointer-events-none absolute inset-0 -z-10" aria-hidden />
        <div aria-hidden className="pointer-events-none absolute -top-24 right-[-10%] -z-10 h-[420px] w-[420px] rounded-full bg-primary/15 blur-3xl" />
        <div aria-hidden className="pointer-events-none absolute top-40 left-[-10%] -z-10 h-[320px] w-[320px] rounded-full bg-accent/15 blur-3xl" />
        <div className="mx-auto grid max-w-7xl items-center gap-12 px-4 pb-20 pt-12 sm:px-6 lg:grid-cols-[1.05fr_1fr] lg:pt-20">
          <Reveal>
            <span className="chip border border-primary/25 bg-primary-soft text-primary">
              <Sparkles className="h-3.5 w-3.5" />{t("hero.eyebrow")}
            </span>
            <h1 className="mt-5 text-4xl font-bold leading-[1.08] sm:text-5xl lg:text-6xl">
              {t("hero.title_1")} <span className="text-primary">{t("hero.title_2")}</span>{" "}
              <span className="relative whitespace-nowrap">
                <span className="relative z-10">{t("hero.title_3")}</span>
                <span aria-hidden className="absolute inset-x-0 bottom-1 -z-0 h-3 rounded bg-accent/40 sm:h-4" />
              </span>
            </h1>
            <p className="mt-6 max-w-xl text-lg leading-relaxed text-muted">{t("hero.subtitle")}</p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href={cta} className="btn-primary h-12 px-6 text-base">{t("hero.cta")}<ArrowRight className="h-4 w-4" /></Link>
              <a href="#how" className="btn-outline h-12 px-6 text-base">{t("hero.secondary")}</a>
            </div>
            <ul className="mt-8 flex flex-wrap gap-x-6 gap-y-2 text-sm text-muted">
              {["no_engineer", "languages", "proof"].map((k) => (
                <li key={k} className="flex items-center gap-2"><BadgeCheck className="h-4 w-4 text-ok" />{t(`hero.points.${k}`)}</li>
              ))}
            </ul>
          </Reveal>
          <Reveal delay={0.15}><HeroDemo /></Reveal>
        </div>
      </section>

      {/* ---- Stats ---- */}
      <section className="border-y border-line bg-surface">
        <div className="mx-auto grid max-w-7xl grid-cols-2 gap-6 px-4 py-10 sm:px-6 md:grid-cols-4">
          {["agents", "checks", "journal", "languages"].map((k, i) => (
            <Reveal key={k} delay={i * 0.05} className="text-center">
              <div className="font-display text-3xl font-bold text-primary sm:text-4xl">{t(`stats.${k}.value`)}</div>
              <div className="mt-1 text-sm text-muted">{t(`stats.${k}.label`)}</div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ---- How it works ---- */}
      <section id="how" className="mx-auto max-w-7xl scroll-mt-20 px-4 py-24 sm:px-6">
        <Reveal className="max-w-2xl">
          <p className="eyebrow">{t("how.eyebrow")}</p>
          <h2 className="mt-3 text-3xl font-bold sm:text-4xl">{t("how.title")}</h2>
          <p className="mt-4 text-muted">{t("how.subtitle")}</p>
        </Reveal>
        <div className="mt-12 grid gap-5 md:grid-cols-3">
          {STEPS.map(({ id, icon: Icon }, i) => (
            <Reveal key={id} delay={i * 0.1}>
              <div className="card group relative h-full p-6 transition hover:-translate-y-1 hover:shadow-lift">
                <div className="flex items-center justify-between">
                  <div className="grid h-12 w-12 place-items-center rounded-xl bg-primary text-primary-fg"><Icon className="h-6 w-6" /></div>
                  <span className="font-display text-5xl font-bold text-line">0{i + 1}</span>
                </div>
                <h3 className="mt-5 text-xl font-semibold">{t(`how.steps.${id}.title`)}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">{t(`how.steps.${id}.text`)}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ---- Agents ---- */}
      <section id="agents" className="scroll-mt-20 bg-navy py-24 text-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <Reveal className="max-w-2xl">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-accent">{t("agents.eyebrow")}</p>
            <h2 className="mt-3 text-3xl font-bold sm:text-4xl">{t("agents.title")}</h2>
            <p className="mt-4 text-white/70">{t("agents.subtitle")}</p>
          </Reveal>
          <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {AGENTS.map(({ id, icon: Icon }, i) => (
              <Reveal key={id} delay={i * 0.06}>
                <div className="h-full rounded-2xl border border-white/10 bg-white/[0.04] p-6 transition hover:border-accent/50 hover:bg-white/[0.07]">
                  <div className="flex items-center gap-3">
                    <div className="grid h-10 w-10 place-items-center rounded-lg bg-accent/15 text-accent"><Icon className="h-5 w-5" /></div>
                    <h3 className="text-lg font-semibold">{t(`agents.list.${id}.title`)}</h3>
                  </div>
                  <p className="mt-3 text-sm leading-relaxed text-white/70">{t(`agents.list.${id}.text`)}</p>
                </div>
              </Reveal>
            ))}
          </div>
          <Reveal delay={0.2}>
            <div className="mt-6 flex items-center gap-3 rounded-2xl border border-accent/30 bg-accent/10 p-5">
              <Workflow className="h-6 w-6 shrink-0 text-accent" />
              <p className="text-sm text-white/85"><span className="font-semibold text-white">{t("agents.orchestrator_title")}</span> {t("agents.orchestrator_text")}</p>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ---- Trust ---- */}
      <section id="trust" className="mx-auto max-w-7xl scroll-mt-20 px-4 py-24 sm:px-6">
        <Reveal className="max-w-2xl">
          <p className="eyebrow">{t("trust.eyebrow")}</p>
          <h2 className="mt-3 text-3xl font-bold sm:text-4xl">{t("trust.title")}</h2>
          <p className="mt-4 text-muted">{t("trust.subtitle")}</p>
        </Reveal>
        <div className="mt-12 grid gap-5 lg:grid-cols-3">
          <Reveal>
            <div className="card h-full p-6">
              <Scale className="h-6 w-6 text-accent" />
              <h3 className="mt-4 text-lg font-semibold">{t("trust.compare.title")}</h3>
              <p className="mt-2 text-sm text-muted">{t("trust.compare.text")}</p>
              <div className="mt-5 rounded-xl bg-surface-2 p-4 text-sm">
                <div className="flex items-center justify-between"><span className="text-muted">{t("trust.compare.asked")}</span><span className="font-mono font-semibold text-bad line-through">−4.1%</span></div>
                <div className="mt-2 flex items-center justify-between"><span className="text-muted">{t("trust.compare.fixed")}</span><span className="font-mono font-semibold text-ok">+34.6%</span></div>
              </div>
            </div>
          </Reveal>
          <Reveal delay={0.1}>
            <div className="card h-full p-6">
              <BrainCircuit className="h-6 w-6 text-accent" />
              <h3 className="mt-4 text-lg font-semibold">{t("trust.explain.title")}</h3>
              <p className="mt-2 text-sm text-muted">{t("trust.explain.text")}</p>
              <div className="mt-5 space-y-2.5">
                {[{ k: "trust.explain.f1", v: 67 }, { k: "trust.explain.f2", v: 33 }].map((f) => (
                  <div key={f.k}>
                    <div className="flex justify-between text-xs font-medium"><span>{t(f.k)}</span><span className="font-mono">{f.v}%</span></div>
                    <div className="mt-1 h-2 rounded-full bg-surface-2"><div className="h-2 rounded-full bg-primary" style={{ width: `${f.v}%` }} /></div>
                  </div>
                ))}
              </div>
            </div>
          </Reveal>
          <Reveal delay={0.2}>
            <div className="card h-full p-6">
              <LockKeyhole className="h-6 w-6 text-accent" />
              <h3 className="mt-4 text-lg font-semibold">{t("trust.journal.title")}</h3>
              <p className="mt-2 text-sm text-muted">{t("trust.journal.text")}</p>
              <div className="mt-5 space-y-2 font-mono text-[11px]">
                {["profiling · anomalies", "comparisons · coverage", "user · same_days"].map((row, i) => (
                  <div key={row} className="flex items-center gap-2 rounded-lg bg-surface-2 px-3 py-2">
                    <span className="text-muted">#{i + 4}</span><span className="flex-1 truncate">{row}</span>
                    <Link2 className="h-3.5 w-3.5 text-primary" aria-hidden /><span className="text-muted">a3f{i}…</span>
                  </div>
                ))}
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ---- Business objectives ---- */}
      <section id="objectives" className="scroll-mt-20 border-t border-line bg-surface py-24">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <Reveal className="max-w-2xl">
            <p className="eyebrow">{t("objectives.eyebrow")}</p>
            <h2 className="mt-3 text-3xl font-bold sm:text-4xl">{t("objectives.title")}</h2>
          </Reveal>
          <div className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {OBJECTIVES.map(({ id, icon: Icon }, i) => (
              <Reveal key={id} delay={i * 0.07}>
                <div className="h-full rounded-2xl border border-line bg-bg p-6">
                  <div className="flex items-center justify-between">
                    <Icon className="h-6 w-6 text-primary" />
                    <span className="chip bg-accent-soft text-ink">{id.toUpperCase()}</span>
                  </div>
                  <h3 className="mt-4 font-semibold">{t(`objectives.${id}.title`)}</h3>
                  <p className="mt-2 text-sm text-muted">{t(`objectives.${id}.text`)}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ---- CTA ---- */}
      <section className="mx-auto max-w-7xl px-4 py-24 sm:px-6">
        <Reveal>
          <div className="relative overflow-hidden rounded-3xl bg-primary px-6 py-14 text-center text-primary-fg sm:px-12">
            <div aria-hidden className="absolute -right-16 -top-16 h-64 w-64 rounded-full bg-accent/30 blur-2xl" />
            <h2 className="relative text-3xl font-bold sm:text-4xl">{t("cta.title")}</h2>
            <p className="relative mx-auto mt-4 max-w-xl opacity-90">{t("cta.text")}</p>
            <Link href={cta} className="btn-accent relative mt-8 h-12 px-7 text-base">{t("cta.button")}<ArrowRight className="h-4 w-4" /></Link>
          </div>
        </Reveal>
      </section>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-4 px-4 py-8 text-sm text-muted sm:flex-row sm:px-6">
          <Logo variant="lockup" size={28} />
          <p className="flex items-center gap-2"><Languages className="h-4 w-4" />{t("footer.text")}</p>
        </div>
      </footer>
    </div>
  );
}
