import { ArrowRight, BadgeCheck, Clock3, FileSearch, History, PlusCircle, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { getServerSession } from "next-auth";
import { getLocale, getTranslations } from "next-intl/server";
import { Empty, ModeBadge, StatusBadge, fmtDate } from "@/components/ui/kit";
import { authOptions } from "@/lib/auth";
import { listAnalyses } from "@/lib/db";
import { STAGES } from "@/lib/pipeline";

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
      <section className="relative overflow-hidden rounded-3xl bg-navy p-6 text-white sm:p-10">
        <div aria-hidden className="absolute -right-20 -top-20 h-72 w-72 rounded-full bg-primary/50 blur-3xl" />
        <div aria-hidden className="absolute bottom-0 right-40 h-40 w-40 rounded-full bg-accent/30 blur-3xl" />
        <div className="relative max-w-2xl">
          <p className="text-sm font-medium text-accent">{t("overview.hello", { name: first || "👋" })}</p>
          <h1 className="mt-2 text-3xl font-bold sm:text-4xl">{t("overview.title")}</h1>
          <p className="mt-3 text-white/75">{t("overview.subtitle")}</p>
          <Link href="/app/new" className="btn-accent mt-6 h-12 px-6 text-base"><PlusCircle className="h-5 w-5" />{t("overview.cta")}</Link>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {[
          { label: t("overview.stats.total"), value: items.length, icon: History, cls: "text-primary bg-primary-soft" },
          { label: t("overview.stats.review"), value: review, icon: Clock3, cls: "text-warn bg-warn-soft" },
          { label: t("overview.stats.done"), value: done, icon: BadgeCheck, cls: "text-ok bg-ok-soft" },
        ].map((s) => (
          <div key={s.label} className="card flex items-center gap-4 p-5">
            <div className={`grid h-12 w-12 place-items-center rounded-xl ${s.cls}`}><s.icon className="h-6 w-6" /></div>
            <div><div className="font-display text-3xl font-bold">{s.value}</div><div className="text-sm text-muted">{s.label}</div></div>
          </div>
        ))}
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <section className="card min-w-0 p-5 sm:p-6">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">{t("overview.recent")}</h2>
            {items.length > 0 && <Link href="/app/history" className="text-sm font-semibold text-primary hover:underline">{t("overview.see_all")}</Link>}
          </div>
          <div className="mt-4">
            {items.length === 0 ? (
              <Empty icon={FileSearch} title={t("overview.empty_title")} text={t("overview.empty_text")}
                     action={<Link href="/app/new" className="btn-primary">{t("overview.cta")}</Link>} />
            ) : (
              <ul className="divide-y divide-line">
                {items.slice(0, 5).map((a) => (
                  <li key={a.id}>
                    <Link href={`/app/runs/${a.id}`} className="group flex items-center gap-4 rounded-xl px-2 py-3 transition hover:bg-surface-2">
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

        <section className="card min-w-0 p-5 sm:p-6">
          <div className="flex items-center gap-2"><ShieldCheck className="h-5 w-5 text-primary" /><h2 className="text-lg font-semibold">{t("overview.pipeline")}</h2></div>
          <p className="mt-1 text-sm text-muted">{t("overview.pipeline_text")}</p>
          <ol className="mt-4 space-y-2">
            {STAGES.map((s) => (
              <li key={s.id} className="flex items-center gap-3 rounded-lg px-2 py-1.5 text-sm">
                <span className="w-7 shrink-0 font-mono text-xs text-subtle">{s.step}</span>
                <span className="min-w-0 flex-1 truncate">{t(`stages.${s.id}.name`)}</span>
                <span className="hidden text-xs text-muted sm:inline">{s.owner}</span>
                <ModeBadge mode={s.mode} label={t(`mode.${s.mode}`)} />
              </li>
            ))}
          </ol>
        </section>
      </div>
    </div>
  );
}
