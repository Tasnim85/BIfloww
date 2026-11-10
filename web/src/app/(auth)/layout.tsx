import { BadgeCheck } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { Aurora } from "@/components/ui/Aurora";
import { Logo } from "@/components/ui/Logo";
import { LocaleSwitch } from "@/components/ui/LocaleSwitch";
import { ThemeToggle } from "@/components/ui/ThemeToggle";

export default async function AuthLayout({ children }: { children: React.ReactNode }) {
  const t = await getTranslations("auth");
  return (
    <div className="grid min-h-dvh lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <Aurora />
      <aside className="relative m-3 hidden overflow-hidden rounded-[2rem] bg-navy p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div aria-hidden className="aurora !absolute"><span className="a1" /><span className="a2" /><span className="a3" /></div>
        <div aria-hidden className="absolute -right-24 -top-24 h-96 w-96 rounded-full bg-primary/40 blur-3xl" />
        <div aria-hidden className="absolute -bottom-32 -left-16 h-96 w-96 rounded-full bg-accent/20 blur-3xl" />
        <Link href="/" className="relative inline-flex items-center gap-3">
          <img src="/brand/mark-dark.png" alt="" width={40} height={40} />
          <span className="font-display text-2xl font-bold">Askboard</span>
        </Link>
        <div className="relative">
          <h2 className="max-w-md bg-gradient-to-r from-white via-white to-[#C4B5FD] bg-clip-text text-5xl font-extrabold leading-tight text-transparent">{t("panel_title")}</h2>
          <ul className="mt-8 space-y-3">
            {["p1", "p2", "p3"].map((k) => (
              <li key={k} className="flex items-start gap-3 rounded-2xl border border-white/10 bg-white/[0.06] p-3.5 text-white/90 backdrop-blur"><BadgeCheck className="mt-0.5 h-5 w-5 shrink-0 text-accent" />{t(`panel_points.${k}`)}</li>
            ))}
          </ul>
        </div>
        <p className="relative text-sm text-white/50">Drop a CSV. Ask a question. Get your dashboard.</p>
      </aside>
      <main className="flex flex-col">
        <div className="flex items-center justify-between p-4 sm:p-6">
          <Link href="/" className="lg:invisible"><Logo variant="lockup" size={32} /></Link>
          <div className="flex items-center gap-2"><LocaleSwitch /><ThemeToggle /></div>
        </div>
        <div className="flex flex-1 items-center justify-center px-4 pb-16 sm:px-6">
          <div className="card w-full max-w-md rounded-3xl p-6 shadow-glow sm:p-8">{children}</div>
        </div>
      </main>
    </div>
  );
}
