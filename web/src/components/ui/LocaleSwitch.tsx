"use client";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useTransition } from "react";
import { cn } from "@/lib/cn";

const LOCALES = [{ id: "en", label: "EN" }, { id: "fr", label: "FR" }];

export function LocaleSwitch({ className }: { className?: string }) {
  const t = useTranslations();
  const locale = useLocale();
  const router = useRouter();
  const [pending, start] = useTransition();
  const choose = (id: string) => {
    document.cookie = `NEXT_LOCALE=${id}; path=/; max-age=31536000; samesite=lax`;
    start(() => router.refresh());
  };
  return (
    <div role="radiogroup" aria-label={t("common.language")}
         className={cn("inline-flex items-center rounded-full border border-line bg-surface p-0.5", pending && "opacity-60", className)}>
      {LOCALES.map(({ id, label }) => (
        <button key={id} type="button" role="radio" aria-checked={locale === id} onClick={() => choose(id)}
                aria-label={t(`common.lang_${id}`)}
                className={cn("h-8 min-w-9 rounded-full px-2 text-xs font-bold transition",
                  locale === id ? "bg-primary text-primary-fg" : "text-muted hover:text-ink")}>
          {label}
        </button>
      ))}
    </div>
  );
}
