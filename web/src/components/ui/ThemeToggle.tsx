"use client";
import { Monitor, Moon, Sun } from "lucide-react";
import { useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";

const MODES = [
  { id: "light", icon: Sun },
  { id: "dark", icon: Moon },
  { id: "system", icon: Monitor },
] as const;

export function ThemeToggle({ className }: { className?: string }) {
  const t = useTranslations();
  const { theme, setTheme } = useTheme();
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);
  return (
    <div role="radiogroup" aria-label={t("common.theme")}
         className={cn("inline-flex items-center rounded-full border border-line bg-surface p-0.5", className)}>
      {MODES.map(({ id, icon: Icon }) => {
        const active = ready && theme === id;
        return (
          <button key={id} type="button" role="radio" aria-checked={active} aria-label={t(`common.theme_${id}`)}
                  title={t(`common.theme_${id}`)} onClick={() => setTheme(id)}
                  className={cn("grid h-8 w-8 place-items-center rounded-full transition",
                    active ? "bg-primary text-primary-fg" : "text-muted hover:text-ink")}>
            <Icon className="h-4 w-4" aria-hidden />
          </button>
        );
      })}
    </div>
  );
}
