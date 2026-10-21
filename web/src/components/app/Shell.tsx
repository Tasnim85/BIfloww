"use client";
import { History, LayoutGrid, LogOut, Menu, PlusCircle, ShieldCheck, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut } from "next-auth/react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { Logo } from "@/components/ui/Logo";
import { LocaleSwitch } from "@/components/ui/LocaleSwitch";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { cn } from "@/lib/cn";

const NAV = [
  { href: "/app", key: "overview", icon: LayoutGrid },
  { href: "/app/new", key: "new", icon: PlusCircle },
  { href: "/app/history", key: "history", icon: History },
  { href: "/app/monitoring", key: "monitoring", icon: ShieldCheck },
];

type User = { name?: string | null; email?: string | null; image?: string | null };
type Health = { ok: boolean; llm?: { provider: string; model: string; ready: boolean } };

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const t = useTranslations("app.nav");
  const path = usePathname();
  return (
    <nav className="flex flex-col gap-1" aria-label={t("label")}>
      {NAV.map(({ href, key, icon: Icon }) => {
        const active = href === "/app" ? path === "/app" : path.startsWith(href);
        return (
          <Link key={href} href={href} onClick={onNavigate} aria-current={active ? "page" : undefined}
                className={cn("flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition",
                  active ? "bg-primary text-primary-fg shadow-card" : "text-muted hover:bg-surface-2 hover:text-ink")}>
            <Icon className="h-[18px] w-[18px]" aria-hidden />{t(key)}
          </Link>
        );
      })}
    </nav>
  );
}

function Status({ health }: { health: Health }) {
  const t = useTranslations("app.status");
  return (
    <div className="rounded-xl border border-line bg-surface-2/60 p-3 text-xs">
      <div className="flex items-center gap-2 font-semibold">
        <span className={cn("h-2 w-2 rounded-full", health.ok ? "bg-ok" : "bg-bad")} />
        {health.ok ? t("api_ok") : t("api_down")}
      </div>
      {health.ok && health.llm && (
        <div className="mt-1.5 flex items-center gap-2 text-muted">
          <span className={cn("h-2 w-2 rounded-full", health.llm.ready ? "bg-ok" : "bg-warn")} />
          <span className="truncate">{health.llm.ready ? t("llm_ok", { model: health.llm.model }) : t("llm_off")}</span>
        </div>
      )}
    </div>
  );
}

function UserMenu({ user }: { user: User }) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, []);
  const initials = (user.name ?? user.email ?? "?").split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  return (
    <div ref={ref} className="relative">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-haspopup="menu"
              className="flex items-center gap-2 rounded-full border border-line bg-surface p-1 pr-3 transition hover:bg-surface-2">
        {user.image ? <img src={user.image} alt="" className="h-8 w-8 rounded-full" referrerPolicy="no-referrer" />
          : <span className="grid h-8 w-8 place-items-center rounded-full bg-accent text-xs font-bold text-accent-fg">{initials}</span>}
        <span className="hidden max-w-[140px] truncate text-sm font-medium sm:block">{user.name ?? user.email}</span>
      </button>
      {open && (
        <div role="menu" className="card absolute right-0 top-12 z-50 w-64 p-2">
          <div className="border-b border-line px-3 pb-3 pt-2">
            <div className="truncate text-sm font-semibold">{user.name}</div>
            <div className="truncate text-xs text-muted">{user.email}</div>
          </div>
          <button role="menuitem" type="button" onClick={() => signOut({ callbackUrl: "/" })}
                  className="mt-1 flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-sm text-bad hover:bg-bad-soft">
            <LogOut className="h-4 w-4" />{t("auth.signout")}
          </button>
        </div>
      )}
    </div>
  );
}

export function Shell({ user, health, children }: { user: User; health: Health; children: React.ReactNode }) {
  const t = useTranslations("app");
  const [drawer, setDrawer] = useState(false);
  const path = usePathname();
  useEffect(() => setDrawer(false), [path]);
  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[260px_minmax(0,1fr)]">
      <aside className="sticky top-0 hidden h-dvh flex-col gap-6 border-r border-line bg-surface p-5 lg:flex">
        <Link href="/" aria-label="Askboard"><Logo variant="lockup" size={34} /></Link>
        <NavLinks />
        <div className="mt-auto space-y-3">
          <div className="rounded-xl bg-navy p-4 text-white">
            <div className="text-sm font-semibold">{t("side.title")}</div>
            <p className="mt-1 text-xs text-white/70">{t("side.text")}</p>
          </div>
          <Status health={health} />
        </div>
      </aside>

      {drawer && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true">
          <button type="button" aria-label={t("nav.close")} className="absolute inset-0 bg-navy/50" onClick={() => setDrawer(false)} />
          <div className="absolute inset-y-0 left-0 flex w-72 flex-col gap-6 bg-surface p-5 shadow-lift">
            <div className="flex items-center justify-between">
              <Logo variant="lockup" size={30} />
              <button type="button" className="btn-ghost h-9 w-9 p-0" onClick={() => setDrawer(false)} aria-label={t("nav.close")}><X className="h-5 w-5" /></button>
            </div>
            <NavLinks onNavigate={() => setDrawer(false)} />
            <div className="mt-auto"><Status health={health} /></div>
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-col">
        <header className="sticky top-0 z-40 flex h-16 items-center justify-between gap-3 border-b border-line bg-bg/80 px-4 backdrop-blur-xl sm:px-6">
          <button type="button" className="btn-ghost h-10 w-10 p-0 lg:hidden" onClick={() => setDrawer(true)} aria-label={t("nav.open")}>
            <Menu className="h-5 w-5" />
          </button>
          <div className="lg:hidden"><Logo variant="mark" size={30} /></div>
          <div className="ml-auto flex items-center gap-2">
            <div className="hidden sm:flex sm:items-center sm:gap-2"><LocaleSwitch /><ThemeToggle /></div>
            <UserMenu user={user} />
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 lg:py-8">{children}</main>
        <div className="flex items-center justify-center gap-2 pb-6 sm:hidden"><LocaleSwitch /><ThemeToggle /></div>
      </div>
    </div>
  );
}
