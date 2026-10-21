// Diagnostic for the welcome email:  npm run check:mail  [your@address to receive a test]
// 1. shows WHO signed the certificate this computer receives from the SMTP server
//    (if it is your antivirus instead of Google, the antivirus is intercepting the email);
// 2. checks the login with the normal, secure verification;
// 3. optionally sends a test email.
import fs from "node:fs";
import net from "node:net";
import tls from "node:tls";
import nodemailer from "nodemailer";

const env = { ...process.env };
for (const file of [".env.local", ".env"]) {
  if (!fs.existsSync(file)) continue;
  for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
    if (m && !(m[1] in env)) env[m[1]] = m[2].replace(/^["']|["']$/g, "");
  }
}
const host = env.SMTP_HOST, port = Number(env.SMTP_PORT || 465);
if (!host) { console.log("SMTP_HOST is empty in web\\.env.local: emails go to web\\data\\outbox\\ instead."); process.exit(1); }
console.log(`Server: ${host}:${port}   user: ${env.SMTP_USER || "(none)"}   password: ${env.SMTP_PASS ? `${env.SMTP_PASS.length} characters` : "MISSING"}`);
if (env.SMTP_PASS && /\s/.test(env.SMTP_PASS)) console.log("!! SMTP_PASS contains spaces: write the 16-letter app password without spaces.");

const ca = env.SMTP_CA_FILE ? [fs.readFileSync(env.SMTP_CA_FILE)] : undefined;
if (ca) console.log(`Trusting for SMTP only: ${env.SMTP_CA_FILE}`);

// 1. Inspection only (nothing is sent on this connection): who issued the certificate we receive?
if (port === 465) {
  await new Promise((done) => {
    const s = tls.connect({ host, port, servername: net.isIP(host) ? undefined : host, ca, rejectUnauthorized: false }, () => {
      let c = s.getPeerCertificate(true); const chain = [];
      while (c && !chain.includes(c)) { chain.push(c); if (c.issuerCertificate === c) break; c = c.issuerCertificate; }
      const root = chain[chain.length - 1];
      console.log(`Certificate received: ${chain[0]?.subject?.CN}  ->  signed by: ${root?.issuer?.O || root?.issuer?.CN}`);
      if (s.authorized) console.log("Certificate: trusted by Node.js. OK");
      else console.log(`Certificate: NOT trusted (${s.authorizationError}). If "signed by" above names your antivirus
  (Avast, AVG, Kaspersky, ESET, Bitdefender...), it is scanning outgoing emails. Fix: turn off its
  email / SMTP scanning, or export its root certificate and set SMTP_CA_FILE (see README).`);
      s.end(); done();
    });
    s.on("error", (e) => { console.log("Cannot reach the server:", e.code || e.message); done(); });
    s.setTimeout(10000, () => { console.log("Timeout: port blocked by a firewall or the network?"); s.destroy(); done(); });
  });
}

// 2. Real check, with full verification (exactly what the app does)
const tr = nodemailer.createTransport({ host, port, secure: port === 465, tls: ca ? { ca } : undefined,
  auth: env.SMTP_USER ? { user: env.SMTP_USER, pass: env.SMTP_PASS } : undefined });
try {
  await tr.verify();
  console.log("Login: OK");
} catch (e) {
  console.log("Login: FAILED ->", e.code || "", e.message);
  if (/535|Username and Password not accepted/i.test(e.message)) console.log("-> Gmail refuses the password: use an APP password, not your normal password.");
  process.exit(1);
}

// 3. Optional test email
const to = process.argv[2];
if (to) {
  await tr.sendMail({ from: env.MAIL_FROM || env.SMTP_USER, to, subject: "Askboard test email", text: "If you read this, the email settings work." });
  console.log(`Test email sent to ${to}.`);
}
