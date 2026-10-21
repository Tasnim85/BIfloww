"use client";
import { Loader2, Lock, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { DriftPanel } from "@/components/run/AuditPanels";
import { Skeleton } from "@/components/ui/kit";
import { api, type IntegrityReport, useApi } from "@/lib/client";
import { cn } from "@/lib/cn";

type JournalInfo = { id: string; label: string; entries: number; runs: string[]; intact: boolean };

export function Monitoring() {
  const t = useTranslations("app.monitoring");
  const { data, loading } = useApi<JournalInfo[]>("journals");
  const [checks, setChecks] = useState<Record<string, IntegrityReport>>({});
  const [busy, setBusy] = useState<string | null>(null);
  async function verify(id: string) {
    setBusy(id);
    try { const r = await api<IntegrityReport>(`journals/${id}/verify`); setChecks((c) => ({ ...c, [id]: r })); }
    finally { setBusy(null); }
  }
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold sm:text-3xl">{t("title")}</h1>
        <p className="mt-1 max-w-3xl text-muted">{t("subtitle")}</p>
      </div>
      <section>
        <h2 className="mb-3 text-lg font-semibold">{t("journals")}</h2>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {loading && !data && [0, 1, 2].map((i) => <Skeleton key={i} className="h-36" />)}
          {data?.map((j) => {
            const c = checks[j.id];
            const ok = c ? c.ok : j.intact;
            return (
              <div key={j.id} className="card p-5">
                <div className="flex items-center gap-3">
                  <div className={cn("grid h-10 w-10 place-items-center rounded-xl", ok ? "bg-ok-soft text-ok" : "bg-bad-soft text-bad")}><Lock className="h-5 w-5" /></div>
                  <div className="min-w-0"><div className="truncate font-semibold">{t(`names.${j.id}`)}</div>
                    <div className="text-xs text-muted">{t("meta", { n: j.entries, runs: j.runs.length })}</div></div>
                </div>
                <p className={cn("mt-3 text-sm", ok ? "text-ok" : "text-bad")}>{c ? (c.ok ? t("intact_now", { n: c.entries_checked }) : c.problem) : ok ? t("intact") : t("broken")}</p>
                <button type="button" className="btn-outline mt-4 h-9 w-full" disabled={busy === j.id} onClick={() => verify(j.id)}>
                  {busy === j.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}{t("verify")}
                </button>
              </div>
            );
          })}
        </div>
      </section>
      <section>
        <h2 className="mb-3 text-lg font-semibold">{t("drift")}</h2>
        <DriftPanel datasetRun="run_001" />
      </section>
    </div>
  );
}
