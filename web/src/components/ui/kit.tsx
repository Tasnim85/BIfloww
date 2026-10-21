/* Small building blocks shared by every screen. */
import { AlertTriangle, CheckCircle2, CircleDashed, Clock3, XCircle } from "lucide-react";
import { cn } from "@/lib/cn";

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-xl bg-surface-2", className)} aria-hidden />;
}

export function Empty({ icon: Icon, title, text, action }:
  { icon: React.ComponentType<{ className?: string }>; title: string; text?: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-line px-6 py-14 text-center">
      <div className="grid h-12 w-12 place-items-center rounded-full bg-primary-soft text-primary"><Icon className="h-6 w-6" /></div>
      <h3 className="mt-4 font-semibold">{title}</h3>
      {text && <p className="mt-1 max-w-sm text-sm text-muted">{text}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

const STATUS = {
  completed: { cls: "bg-ok-soft text-ok", icon: CheckCircle2 },
  needs_review: { cls: "bg-warn-soft text-warn", icon: AlertTriangle },
  running: { cls: "bg-primary-soft text-primary", icon: Clock3 },
  failed: { cls: "bg-bad-soft text-bad", icon: XCircle },
} as const;

export function StatusBadge({ status, label }: { status: string; label: string }) {
  const s = STATUS[status as keyof typeof STATUS] ?? { cls: "bg-surface-2 text-muted", icon: CircleDashed };
  const Icon = s.icon;
  return <span className={cn("chip", s.cls)}><Icon className="h-3.5 w-3.5" aria-hidden />{label}</span>;
}

export function ModeBadge({ mode, label }: { mode: "live" | "demo"; label: string }) {
  return (
    <span className={cn("chip text-[10px] uppercase tracking-wider",
      mode === "live" ? "bg-accent text-accent-fg" : "border border-line bg-surface-2 text-muted")}>
      {mode === "live" && <span className="relative flex h-1.5 w-1.5"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent-fg/60" /><span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-accent-fg" /></span>}
      {label}
    </span>
  );
}

export function SectionTitle({ title, subtitle, action }: { title: string; subtitle?: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 className="text-lg font-semibold">{title}</h2>
        {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

export function fmtDate(iso: string, locale: string, withTime = true) {
  return new Intl.DateTimeFormat(locale === "fr" ? "fr-FR" : "en-GB", withTime
    ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium" }).format(new Date(iso));
}

export function fmtNum(v: number | null | undefined, locale: string, digits = 2) {
  if (v === null || v === undefined) return "—";
  return new Intl.NumberFormat(locale === "fr" ? "fr-FR" : "en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(v);
}

export function fmtPct(v: number | null | undefined, locale: string) {
  if (v === null || v === undefined) return "—";
  return new Intl.NumberFormat(locale === "fr" ? "fr-FR" : "en-US", { style: "percent", maximumFractionDigits: 1, minimumFractionDigits: 1, signDisplay: "always" }).format(v);
}
