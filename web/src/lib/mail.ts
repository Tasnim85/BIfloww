/**
 * Emails sent by Askboard. Today: the welcome email at account creation.
 *
 * Configuration (web/.env.local), any SMTP server works:
 *   SMTP_HOST=smtp.gmail.com  SMTP_PORT=465  SMTP_USER=you@gmail.com  SMTP_PASS=<app password>
 *   MAIL_FROM="Askboard <you@gmail.com>"
 * SMTP_CA_FILE (optional): a certificate to trust for SMTP only, e.g. the root certificate of an antivirus
 *   that scans outgoing emails ("self-signed certificate in certificate chain"). Diagnostic: npm run check:mail
 * Without SMTP_HOST: in development the email is written to data/outbox/ (open it in a browser);
 * in production it is skipped with a warning. Sending never blocks or breaks the sign-up.
 */
import "server-only";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { createTranslator } from "next-intl";
import nodemailer from "nodemailer";
import en from "../../messages/en.json";
import fr from "../../messages/fr.json";

const MESSAGES = { en, fr } as const;
type Lang = keyof typeof MESSAGES;
const LOGO_FILE = path.join(process.cwd(), "public", "brand", "logo-light.png");
const LOGO_CID = "logo@askboard";

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

/** The welcome email: table layout + inline styles, so it renders the same in Gmail, Outlook and phones. */
export function welcomeEmail(name: string, lang: string, appUrl: string, logoSrc = `cid:${LOGO_CID}`) {
  const l: Lang = lang === "fr" ? "fr" : "en";
  const t = createTranslator({ locale: l, messages: MESSAGES[l], namespace: "email.welcome" });
  const first = esc(name.trim().split(/\s+/)[0] || name);
  const steps = (["drop", "ask", "trust"] as const).map((k, i) => `
      <tr>
        <td width="44" valign="top" style="padding:0 0 18px 0;">
          <div style="width:32px;height:32px;border-radius:16px;background:#E0F2F6;color:#0E7490;font:700 14px/32px Arial,sans-serif;text-align:center;">${i + 1}</div>
        </td>
        <td valign="top" style="padding:0 0 18px 0;font:400 15px/22px Arial,sans-serif;color:#4A6272;">
          <strong style="color:#0F2A3D;">${esc(t(`steps.${k}.title`))}</strong><br>${esc(t(`steps.${k}.text`))}
        </td>
      </tr>`).join("");
  const html = `<!doctype html>
<html lang="${l}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(t("subject"))}</title></head>
<body style="margin:0;padding:0;background:#EEF4F7;">
  <div style="display:none;max-height:0;overflow:hidden;">${esc(t("preheader"))}</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#EEF4F7;padding:32px 12px;">
    <tr><td align="center">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;background:#FFFFFF;border-radius:20px;overflow:hidden;">
        <tr><td style="background:#0F2A3D;padding:28px 36px;">
          <table role="presentation" cellpadding="0" cellspacing="0"><tr>
            <td style="background:#FFFFFF;border-radius:14px;padding:8px 10px;"><img src="${logoSrc}" width="72" alt="Askboard" style="display:block;width:72px;height:auto;border:0;"></td>
            <td style="padding-left:16px;font:700 22px/28px Arial,sans-serif;color:#FFFFFF;">Askboard<br>
              <span style="font:400 13px/18px Arial,sans-serif;color:#B5DCE5;">Drop a CSV. Ask a question. Get your dashboard.</span></td>
          </tr></table>
        </td></tr>
        <tr><td style="padding:36px 36px 8px 36px;">
          <h1 style="margin:0;font:700 26px/34px Arial,sans-serif;color:#0F2A3D;">${esc(t("title", { name: first }))}</h1>
          <p style="margin:14px 0 28px 0;font:400 16px/24px Arial,sans-serif;color:#4A6272;">${esc(t("intro"))}</p>
          <table role="presentation" cellpadding="0" cellspacing="0" width="100%">${steps}</table>
        </td></tr>
        <tr><td align="left" style="padding:8px 36px 36px 36px;">
          <a href="${esc(appUrl)}" style="display:inline-block;background:#F59E0B;color:#0F2A3D;font:700 16px/20px Arial,sans-serif;text-decoration:none;padding:14px 26px;border-radius:12px;">${esc(t("cta"))}</a>
        </td></tr>
        <tr><td style="padding:20px 36px;border-top:1px solid #DCE6EA;font:400 12px/18px Arial,sans-serif;color:#788C98;">
          ${esc(t("footer"))}
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>`;
  const text = [t("title", { name: first }), "", t("intro"), "",
    ...(["drop", "ask", "trust"] as const).map((k, i) => `${i + 1}. ${t(`steps.${k}.title`)}: ${t(`steps.${k}.text`)}`),
    "", `${t("cta")}: ${appUrl}`, "", t("footer")].join("\n");
  return { subject: t("subject"), html, text };
}

let transport: nodemailer.Transporter | null = null;
function smtp() {
  if (!process.env.SMTP_HOST) return null;
  const port = Number(process.env.SMTP_PORT || 465);
  const ca = process.env.SMTP_CA_FILE ? [fs.readFileSync(process.env.SMTP_CA_FILE)] : undefined;
  transport ??= nodemailer.createTransport({
    host: process.env.SMTP_HOST, port, secure: port === 465, tls: ca ? { ca } : undefined,
    auth: process.env.SMTP_USER ? { user: process.env.SMTP_USER, pass: process.env.SMTP_PASS } : undefined,
  });
  return transport;
}

/** Sends the welcome email. Never throws: a mail problem must not break the sign-up. */
export async function sendWelcomeEmail(to: string, name: string, lang: string): Promise<void> {
  const appUrl = `${(process.env.NEXTAUTH_URL ?? "http://localhost:3000").replace(/\/$/, "")}/app`;
  try {
    const tr = smtp();
    if (!tr) {
      if (process.env.NODE_ENV === "production") { console.warn("[mail] SMTP_HOST missing: welcome email not sent"); return; }
      // development: keep a copy you can open in a browser (logo inlined)
      const logo = `data:image/png;base64,${fs.readFileSync(LOGO_FILE).toString("base64")}`;
      const { html } = welcomeEmail(name, lang, appUrl, logo);
      const dir = path.join(process.cwd(), "data", "outbox");
      fs.mkdirSync(dir, { recursive: true });
      const file = path.join(dir, `${Date.now()}-welcome-${crypto.createHash("sha256").update(to).digest("hex").slice(0, 8)}.html`);
      fs.writeFileSync(file, html);
      console.info(`[mail] SMTP not configured: welcome email saved to ${file}`);
      return;
    }
    const { subject, html, text } = welcomeEmail(name, lang, appUrl);
    await tr.sendMail({
      from: process.env.MAIL_FROM || process.env.SMTP_USER, to, subject, html, text,
      attachments: [{ filename: "askboard.png", path: LOGO_FILE, cid: LOGO_CID }],
    });
  } catch (e) {
    const err = e as Error & { code?: string };
    console.error("[mail] welcome email failed:", err.message);
    if (/certificate/i.test(err.message) || err.code === "SELF_SIGNED_CERT_IN_CHAIN")
      console.error("[mail] something on this computer (often an antivirus scanning emails) replaces the server's certificate. Run: npm run check:mail");
  }
}
