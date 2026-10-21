"use client";
import { Menu, X } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { Logo } from "@/components/ui/Logo";
import { LocaleSwitch } from "@/components/ui/LocaleSwitch";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { cn } from "@/lib/cn";

const LINKS = ["how", "agents", "trust", "objectives"] as const;

export function Navbar({ signedIn }: { signedIn: boolean }) {
  const t = useTranslations();
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 8);
    on();
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);
  return (
    <header className={cn("sticky top-0 z-50 transition", scrolled ? "border-b border-line bg-bg/80 backdrop-blur-xl" : "bg-transparent")}>
      <nav className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-4 px-4 sm:px-6">
        <Link href="/" aria-label="Askboard"><Logo variant="lockup" size={34} /></Link>
        <div className="hidden items-center gap-1 lg:flex">
          {LINKS.map((l) => (
            <a key={l} href={`#${l}`} className="rounded-lg px-3 py-2 text-sm font-medium text-muted transition hover:text-ink">{t(`landing.nav.${l}`)}</a>
          ))}
        </div>
        <div className="hidden items-center gap-2 md:flex">
          <LocaleSwitch />
          <ThemeToggle />
          {signedIn ? (
            <Link href="/app" className="btn-primary">{t("landing.nav.open_app")}</Link>
          ) : (
            <>
              <Link href="/signin" className="btn-ghost">{t("auth.signin")}</Link>
              <Link href="/signup" className="btn-primary">{t("landing.nav.get_started")}</Link>
            </>
          )}
        </div>
        <button type="button" className="btn-ghost h-10 w-10 p-0 md:hidden" aria-label={t("common.menu")} aria-expanded={open}
                onClick={() => setOpen((v) => !v)}>
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </nav>
      {open && (
        <div className="border-t border-line bg-bg px-4 pb-4 md:hidden">
          <div className="flex flex-col py-2">
            {LINKS.map((l) => (
              <a key={l} href={`#${l}`} onClick={() => setOpen(false)} className="py-2.5 text-sm font-medium text-muted">{t(`landing.nav.${l}`)}</a>
            ))}
          </div>
          <div className="flex items-center gap-2"><LocaleSwitch /><ThemeToggle /></div>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <Link href={signedIn ? "/app" : "/signin"} className="btn-outline">{signedIn ? t("landing.nav.open_app") : t("auth.signin")}</Link>
            {!signedIn && <Link href="/signup" className="btn-primary">{t("landing.nav.get_started")}</Link>}
          </div>
        </div>
      )}
    </header>
  );
}
