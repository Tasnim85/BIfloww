/** reCAPTCHA v2 (checkbox), verified on the server. Without a secret key: skipped in development
 *  (with a warning), REFUSED in production — a missing key never silently opens the door. */
import "server-only";

export type CaptchaResult = { ok: boolean; skipped?: boolean; reason?: string };

export async function verifyRecaptcha(token: string | undefined | null): Promise<CaptchaResult> {
  const secret = process.env.RECAPTCHA_SECRET_KEY;
  if (!secret) {
    if (process.env.NODE_ENV === "production") return { ok: false, reason: "captcha_not_configured" };
    console.warn("[recaptcha] RECAPTCHA_SECRET_KEY missing: check skipped (development only)");
    return { ok: true, skipped: true };
  }
  if (!token) return { ok: false, reason: "captcha_missing" };
  try {
    // RECAPTCHA_VERIFY_URL: only for automated tests (a local fake Google). Leave it unset.
    const res = await fetch(process.env.RECAPTCHA_VERIFY_URL || "https://www.google.com/recaptcha/api/siteverify", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ secret, response: token }),
      cache: "no-store",
    });
    const data = (await res.json()) as { success: boolean; hostname?: string; "error-codes"?: string[] };
    if (!data.success) {
      // invalid-input-secret: wrong secret key · invalid-input-response: token from another key or expired
      console.warn("[recaptcha] refused by Google:", data["error-codes"]);
      return { ok: false, reason: "captcha_invalid" };
    }
    // the token must have been solved on THIS site (not copied from another one)
    const expected = new URL(process.env.NEXTAUTH_URL ?? "http://localhost:3000").hostname;
    if (data.hostname && data.hostname !== expected) {
      console.warn(`[recaptcha] token solved on ${data.hostname}, expected ${expected}`);
      return { ok: false, reason: "captcha_invalid" };
    }
    return { ok: true };
  } catch (e) {
    // the SERVER could not talk to Google (no internet, firewall, antivirus or proxy inspecting HTTPS)
    const err = e as Error & { cause?: { code?: string; message?: string } };
    console.error("[recaptcha] the server cannot reach Google:", err.cause?.code ?? "", err.cause?.message ?? err.message);
    return { ok: false, reason: "captcha_unreachable" };
  }
}
