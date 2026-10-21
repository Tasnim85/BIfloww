// Diagnostic: does this computer reach Google, and is the reCAPTCHA SECRET key valid?
//   npm run check:recaptcha
// It sends a fake token: Google then answers "invalid-input-response" if the secret is RIGHT,
// "invalid-input-secret" if the secret is WRONG. Nothing is stored, nothing is printed in full.
import fs from "node:fs";

const env = {};
for (const file of [".env.local", ".env"]) {
  if (!fs.existsSync(file)) continue;
  for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
    if (m && !(m[1] in env)) env[m[1]] = m[2].replace(/^["']|["']$/g, "");
  }
}
const site = env.NEXT_PUBLIC_RECAPTCHA_SITE_KEY ?? "";
const secret = env.RECAPTCHA_SECRET_KEY ?? "";
const mask = (s) => (s ? `${s.slice(0, 6)}…${s.slice(-4)} (${s.length} characters)` : "MISSING");
console.log("Site key  :", mask(site));
console.log("Secret key:", mask(secret));
if (!site || !secret) { console.log("\n-> Put both keys in web\\.env.local, then restart npm run dev."); process.exit(1); }
if (site === secret) console.log("!! The two keys are identical: the site key and the secret key are different values.");

try {
  const res = await fetch("https://www.google.com/recaptcha/api/siteverify", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ secret, response: "diagnostic-token" }),
  });
  const data = await res.json();
  const codes = data["error-codes"] ?? [];
  console.log("\nGoogle reached: yes. Answer:", JSON.stringify(data));
  if (codes.includes("invalid-input-secret")) console.log("-> The SECRET key is wrong (copy it again from the reCAPTCHA admin page).");
  else if (codes.includes("invalid-input-response")) console.log("-> The secret key is VALID. If the app still fails, check in the browser (F12, Console):\n   the site key must be of type 'v2 checkbox (I'm not a robot)' and 'localhost' must be in its domains.");
  else console.log("-> Unexpected answer: send it to Tasnim / the team.");
} catch (e) {
  console.log("\nGoogle reached: NO ->", e.cause?.code ?? "", e.cause?.message ?? e.message);
  console.log("-> This computer cannot reach www.google.com from Node (no internet, firewall, antivirus or proxy).");
  if (String(e.cause?.code ?? "").includes("CERT") || /certificate/i.test(String(e.cause?.message)))
    console.log("   A certificate problem usually means an antivirus or a proxy inspects HTTPS: try another network.");
}
