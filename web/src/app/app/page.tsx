import { ArrowRight, BadgeCheck, Clock3, FileSearch, History, PlusCircle, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { getServerSession } from "next-auth";
import { getLocale, getTranslations } from "next-intl/server";
import { CountUp } from "@/components/ui/CountUp";
import { Empty, StatusBadge, fmtDate } from "@/components/ui/kit";
import { authOptions } from "@/lib/auth";
import { listAnalyses } from "@/lib/db";
import { PHASES, STAGES } from "@/lib/pipeline";

export default async function Overview() {
  const t = await getTranslations("app");
  const locale = await getLocale();
  const session = await getServerSession(authOptions);
  const items = listAnalyses(session!.user.id);
  const review = items.filter((a) => a.status === "needs_review").length;
  const done = items.filter((a) => a.status === "completed").length;
  const first = (session?.user.name ?? "").split(" ")[0];

  return (
    <div className="space-y-8">
      <section className="rise relative isolate overflow-hidden rounded-[2rem] bg-navy p-6 text-white shadow-lift sm:p-10">
        <div aria-hidden className="aurora !absolute"><span className="a1" /><span className="a2" /><span className="a3" /></div>
        <div aria-hidden className="absolute inset-0 -z-10 bg-[linear-gradient(rgb(255_255_255/0.05)_1px,transparent_1px),linear-gradient(90deg,rgb(255_255_255/0.05)_1px,transparent_1px)] bg-[size:40px_40px] [mask-image:radial-gradient(ellipse_at_70%_30%,black,transparent_70%)]" />
        <div className="relative max-w-2xl">
          <p className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/10 px-3 py-1 text-sm font-medium text-accent backdrop-blur">{t("overview.hello", { name: first || "👋" })}</p>
          <h1 className="mt-4 bg-gradient-to-r from-white via-white to-[#C4B5FD] bg-clip-text text-4xl font-extrabold leading-[1.05] text-transparent sm:text-5xl">{t("overview.title")}</h1>
          <p className="mt-3 text-white/75">{t("overview.subtitle")}</p>
          <Link href="/app/new" className="btn-accent mt-6 h-12 px-6 text-base"><PlusCircle className="h-5 w-5" />{t("overview.cta")}</Link>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {[
          { label: t("overview.stats.total"), value: items.length, icon: History, g: "from-[#0E7490] to-[#7C3AED]" },
          { label: t("overview.stats.review"), value: review, icon: Clock3, g: "from-[#F59E0B] to-[#EA580C]" },
          { label: t("overview.stats.done"), value: done, icon: BadgeCheck, g: "from-[#059669] to-[#22D3EE]" },
        ].map((s, i) => (
          <div key={s.label} className="card card-hover glow-ring rise relative flex items-center gap-4 overflow-hidden p-5" style={{ ["--d" as string]: `${80 + i * 80}ms` }}>
            <span aria-hidden className={`absolute -right-10 -top-10 h-28 w-28 rounded-full bg-gradient-to-br ${s.g} opacity-20 blur-2xl`} />
            <div className={`grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br ${s.g} text-white shadow-lg`}><s.icon className="h-6 w-6" /></div>
            <div><div className="font-display text-4xl font-extrabold leading-none"><CountUp value={s.value} /></div><div className="mt-1 text-sm text-muted">{s.label}</div></div>
          </div>
        ))}
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <section className="card rise min-w-0 p-5 sm:p-6" style={{ ["--d" as string]: "200ms" }}>
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">{t("overview.recent")}</h2>
            {items.length > 0 && <Link href="/app/history" className="text-sm font-semibold text-primary hover:underline">{t("overview.see_all")}</Link>}
          </div>
          <div className="mt-4">
            {items.length === 0 ? (
              <Empty icon={FileSearch} title={t("overview.empty_title")} text={t("overview.empty_text")}
                     action={<Link href="/app/new" className="btn-primary">{t("overview.cta")}</Link>} />
            ) : (
              <ul className="divide-y divide-line/60">
                {items.slice(0, 5).map((a) => (
                  <li key={a.id}>
                    <Link href={`/app/runs/${a.id}`} className="group flex items-center gap-4 rounded-xl px-2 py-3 transition hover:translate-x-0.5 hover:bg-surface-2/70">
                      <span aria-hidden className="h-9 w-1 shrink-0 rounded-full bg-gradient-to-b from-primary to-violet opacity-40 transition group-hover:opacity-100" />
                      <div className="min-w-0 flex-1">
                        <div className="line-clamp-2 break-words font-medium [overflow-wrap:anywhere]" title={a.question}>{a.question}</div>
                        <div className="mt-0.5 text-xs text-muted">{a.metric} · {fmtDate(a.created_at, locale)}</div>
                      </div>
                      <span className="shrink-0"><StatusBadge status={a.status} label={t(`status.${a.status}`)} /></span>
                      <ArrowRight className="h-4 w-4 shrink-0 text-subtle transition group-hover:translate-x-0.5 group-hover:text-ink" />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        <section className="card rise min-w-0 p-5 sm:p-6" style={{ ["--d" as string]: "280ms" }}>
          <div className="flex items-center gap-2"><ShieldCheck className="h-5 w-5 text-primary" /><h2 className="text-lg font-semibold">{t("overview.pipeline")}</h2></div>
          <p className="mt-1 text-sm text-muted">{t("overview.pipeline_text")}</p>
          <ol className="relative mt-5 space-y-3 pl-6">
            <span aria-hidden className="absolute bottom-3 left-[9px] top-3 w-0.5 rounded-full bg-gradient-to-b from-primary via-violet to-accent opacity-50" />
            {PHASES.map((p, i) => (
              <li key={p} className="relative">
                <span aria-hidden className="absolute -left-6 top-1 grid h-5 w-5 place-items-center rounded-full bg-gradient-to-br from-primary to-violet text-[9px] font-bold text-white ring-4 ring-surface">{i}</span>
                <div className="text-sm font-semibold">{t(`rail.phases.${p}`)}</div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {STAGES.filter((s) => s.phase === p).map((s) => (
                    <span key={s.id} className="chip border border-line/70 bg-surface-2/60 font-medium text-muted">{t(`stages.${s.id}.short`)}</span>
                  ))}
                </div>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </div>
  );
}
