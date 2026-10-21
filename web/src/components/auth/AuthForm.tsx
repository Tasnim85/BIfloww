"use client";
import { AlertCircle, Eye, EyeOff, Loader2, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { signIn } from "next-auth/react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useState } from "react";
import { useRecaptcha } from "@/components/auth/useRecaptcha";

type Props = { mode: "signin" | "signup"; google: boolean; siteKey: string | null; captchaOff: boolean;
               initialError?: string | null; callbackUrl: string };

function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" aria-hidden>
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.1z" />
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z" />
      <path fill="#FBBC05" d="M5.84 14.1A6.6 6.6 0 0 1 5.5 12c0-.73.13-1.44.34-2.1V7.06H2.18A11 11 0 0 0 1 12c0 1.77.42 3.45 1.18 4.94l3.66-2.84z" />
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1A11 11 0 0 0 2.18 7.06l3.66 2.84C6.71 7.31 9.14 5.38 12 5.38z" />
    </svg>
  );
}

export function AuthForm({ mode, google, siteKey, captchaOff, initialError, callbackUrl }: Props) {
  const t = useTranslations("auth");
  const router = useRouter();
  const { resolvedTheme } = useTheme();
  const locale = useLocale();
  const captchaTheme = resolvedTheme === "dark" ? "dark" : "light";
  const captcha = useRecaptcha(siteKey, captchaTheme, locale);
  const [busy, setBusy] = useState(false);
  const [show, setShow] = useState(false);
  const [error, setError] = useState<string | null>(initialError ?? null);
  const errText = (code: string) => (t.has(`errors.${code}`) ? t(`errors.${code}`) : t("errors.default"));

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const email = String(f.get("email") ?? "");
    const password = String(f.get("password") ?? "");
    if (captcha.enabled && !captcha.token) { setError("captcha_missing"); return; }
    setBusy(true);
    setError(null);
    const token = captcha.token;
    let ok = false;
    try {
      let ticket: string | undefined;
      if (mode === "signup") {
        const res = await fetch("/api/signup", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: f.get("name"), email, password, captcha: token }) });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) { setError(body.error ?? "default"); return; }
        ticket = body.ticket;
      }
      const r = await signIn("credentials", { email, password, redirect: false,
        ...(ticket ? { ticket } : { captcha: token ?? "" }) });
      if (!r || r.error) { setError(r?.error ?? "default"); return; }
      ok = true;
      router.push(callbackUrl);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "default");
    } finally {
      setBusy(false);
      if (!ok) captcha.reset();                      // the token was used: the box must be ticked again
    }
  }

  return (
    <div>
      <h1 className="text-3xl font-bold">{t(mode === "signin" ? "signin_title" : "signup_title")}</h1>
      <p className="mt-2 text-muted">{t(mode === "signin" ? "signin_subtitle" : "signup_subtitle")}</p>

      <button type="button" disabled={!google || busy} onClick={() => signIn("google", { callbackUrl })}
              className="btn-outline mt-8 h-12 w-full" title={google ? undefined : t("google_off")}>
        <GoogleIcon />{t("google")}
      </button>
      {!google && <p className="mt-2 text-xs text-subtle">{t("google_off")}</p>}

      <div className="my-6 flex items-center gap-3 text-xs uppercase tracking-wider text-subtle">
        <span className="h-px flex-1 bg-line" />{t("email")}<span className="h-px flex-1 bg-line" />
      </div>

      <form onSubmit={onSubmit} className="space-y-4" noValidate={false}>
        {mode === "signup" && (
          <div>
            <label htmlFor="name" className="label">{t("name")}</label>
            <input id="name" name="name" required minLength={2} maxLength={80} autoComplete="name" className="input" />
          </div>
        )}
        <div>
          <label htmlFor="email" className="label">{t("email")}</label>
          <input id="email" name="email" type="email" required autoComplete="email" className="input" />
        </div>
        <div>
          <label htmlFor="password" className="label">{t("password")}</label>
          <div className="relative">
            <input id="password" name="password" type={show ? "text" : "password"} required minLength={8} maxLength={128}
                   autoComplete={mode === "signin" ? "current-password" : "new-password"} className="input pr-11"
                   pattern={mode === "signup" ? "(?=.*[A-Za-z])(?=.*\\d).{8,}" : undefined}
                   aria-describedby={mode === "signup" ? "pw-hint" : undefined} />
            <button type="button" onClick={() => setShow((v) => !v)} aria-label={t("password")}
                    className="absolute inset-y-0 right-0 grid w-11 place-items-center text-muted hover:text-ink">
              {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
          {mode === "signup" && <p id="pw-hint" className="mt-1.5 text-xs text-muted">{t("password_hint")}</p>}
        </div>

        {error && (
          <div role="alert" className="flex items-start gap-2 rounded-xl border border-bad/30 bg-bad-soft p-3 text-sm text-bad">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />{errText(error)}
          </div>
        )}

        {captcha.enabled && (
          <div className="flex min-h-[78px] justify-center">
            <div key={`${captchaTheme}-${locale}`} ref={captcha.container} />
          </div>
        )}
        {captcha.failed && !error && (
          <p role="alert" className="text-sm text-bad">{errText("captcha_widget_error")}</p>
        )}

        <button type="submit" disabled={busy} className="btn-primary h-12 w-full text-base">
          {busy && <Loader2 className="h-4 w-4 animate-spin" />}
          {t(mode === "signin" ? "submit_signin" : "submit_signup")}
        </button>
      </form>

      <p className="mt-4 flex items-start gap-2 text-xs text-subtle">
        <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />{captchaOff ? t("captcha_off") : t("captcha_notice")}
      </p>
      <p className="mt-8 text-center text-sm text-muted">
        {t(mode === "signin" ? "no_account" : "have_account")}{" "}
        <Link href={mode === "signin" ? "/signup" : "/signin"} className="font-semibold text-primary hover:underline">
          {t(mode === "signin" ? "create_one" : "signin_link")}
        </Link>
      </p>
    </div>
  );
}
