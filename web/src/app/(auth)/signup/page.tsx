import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { AuthForm } from "@/components/auth/AuthForm";
import { currentUserId, googleEnabled } from "@/lib/auth";

export const metadata: Metadata = { title: "Sign up" };

/** Only a page of this site: never send the user to another website after sign-in (open redirect). */
function safeCallback(raw?: string): string {
  if (!raw) return "/app";
  try {
    const self = new URL(process.env.NEXTAUTH_URL ?? "http://localhost:3000");
    const u = new URL(raw, self);
    return u.origin === self.origin && u.pathname.startsWith("/app") ? u.pathname + u.search : "/app";
  } catch {
    return "/app";
  }
}

type Props = { searchParams: Promise<{ error?: string; callbackUrl?: string }> };

export default async function Page({ searchParams }: Props) {
  if (await currentUserId()) redirect("/app");
  const sp = await searchParams;
  const siteKey = process.env.NEXT_PUBLIC_RECAPTCHA_SITE_KEY || null;
  const callbackUrl = safeCallback(sp.callbackUrl);
  return <AuthForm mode="signup" google={googleEnabled()} siteKey={siteKey} captchaOff={!process.env.RECAPTCHA_SECRET_KEY}
                   initialError={sp.error ?? null} callbackUrl={callbackUrl} />;
}
