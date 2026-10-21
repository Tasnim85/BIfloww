"use client";
/**
 * reCAPTCHA v2 CHECKBOX ("I'm not a robot"). The widget is rendered in `container`; when the user
 * ticks it, `token` holds a one-time token to send with the form. After each use (or a failed
 * submit) call reset(): Google only verifies a token once.
 * Without a site key nothing is rendered and token stays null: the server then decides
 * (allowed in development, refused in production).
 */
import { useCallback, useEffect, useRef, useState } from "react";

type Grecaptcha = {
  ready: (cb: () => void) => void;
  render: (el: HTMLElement, o: Record<string, unknown>) => number;
  reset: (id: number) => void;
};
declare global {
  interface Window { grecaptcha?: Grecaptcha; __askboardCaptchaLoaded?: () => void }
}

const SCRIPT_ID = "recaptcha-v2-script";
const waiting: Array<() => void> = [];

function loadScript(onReady: () => void, lang: string) {
  if (window.grecaptcha?.render) { window.grecaptcha.ready(onReady); return; }
  waiting.push(onReady);
  if (document.getElementById(SCRIPT_ID)) return;
  window.__askboardCaptchaLoaded = () => waiting.splice(0).forEach((cb) => cb());
  const s = document.createElement("script");
  s.id = SCRIPT_ID;
  s.src = `https://www.google.com/recaptcha/api.js?onload=__askboardCaptchaLoaded&render=explicit&hl=${lang}`;
  s.async = true;
  s.defer = true;
  document.head.appendChild(s);
}

export function useRecaptcha(siteKey: string | null, theme: "light" | "dark", lang: string) {
  const container = useRef<HTMLDivElement>(null);
  const widget = useRef<number | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!siteKey) return;
    let alive = true;
    widget.current = null;                    // a new container (theme change) gets a new widget
    loadScript(() => {
      if (!alive || !container.current || widget.current !== null || !window.grecaptcha) return;
      widget.current = window.grecaptcha.render(container.current, {
        sitekey: siteKey,
        theme,
        callback: (t: string) => { setToken(t); setFailed(false); },
        "expired-callback": () => setToken(null),               // ticked more than 2 minutes ago
        // Google's widget itself failed: usually a wrong key type (must be v2 checkbox) or a domain
        // missing from the key's settings. Google writes the exact reason in the browser console (F12).
        "error-callback": () => {
          console.error("[recaptcha] widget error: check the key type (v2 checkbox) and the allowed domains");
          setToken(null);
          setFailed(true);
        },
      });
    }, lang);
    return () => { alive = false; setToken(null); };
  }, [siteKey, theme, lang]);

  /** Untick the box: needed after every submit, a token can only be verified once. */
  const reset = useCallback(() => {
    if (window.grecaptcha && widget.current !== null) window.grecaptcha.reset(widget.current);
    setToken(null);
  }, []);

  return { container, token, reset, failed, enabled: Boolean(siteKey) };
}
