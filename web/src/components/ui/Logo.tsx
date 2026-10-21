/* The logo has a light and a dark version: CSS picks one, so there is no flash on load. */
import Image from "next/image";
import { cn } from "@/lib/cn";

export function Logo({ variant = "full", className, size = 36 }:
  { variant?: "full" | "mark" | "lockup"; className?: string; size?: number }) {
  if (variant === "full") {
    return (
      <span className={cn("relative inline-block", className)}>
        <Image src="/brand/logo-light.png" alt="Askboard" width={313} height={261} priority className="h-auto w-full dark:hidden" />
        <Image src="/brand/logo-dark.png" alt="Askboard" width={313} height={261} priority className="hidden h-auto w-full dark:block" />
      </span>
    );
  }
  const mark = (
    <span className="relative inline-block shrink-0" style={{ width: size, height: size }}>
      <Image src="/brand/mark-light.png" alt={variant === "mark" ? "Askboard" : ""} width={size} height={size} className="dark:hidden" />
      <Image src="/brand/mark-dark.png" alt={variant === "mark" ? "Askboard" : ""} width={size} height={size} className="hidden dark:block" />
    </span>
  );
  if (variant === "mark") return mark;
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      {mark}
      <span className="font-display text-xl font-bold tracking-tight text-ink">Askboard</span>
    </span>
  );
}
