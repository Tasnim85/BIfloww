/**
 * After a successful sign-up (reCAPTCHA already solved), the browser signs in right away. A reCAPTCHA
 * token can only be verified once, so instead of a second challenge the sign-up returns a one-time
 * ticket, valid 2 minutes, for that email only. The password is still checked at sign-in.
 * (Kept in memory: enough for one server process.)
 */
import "server-only";
import crypto from "node:crypto";

const TTL_MS = 2 * 60_000;
const tickets = new Map<string, { hash: Buffer; exp: number }>();
const sha = (s: string) => crypto.createHash("sha256").update(s).digest();

export function issueTicket(email: string): string {
  const ticket = crypto.randomBytes(32).toString("base64url");
  tickets.set(email.toLowerCase(), { hash: sha(ticket), exp: Date.now() + TTL_MS });
  return ticket;
}

export function consumeTicket(email: string, ticket: string | undefined | null): boolean {
  const key = email.toLowerCase();
  const t = tickets.get(key);
  tickets.delete(key);                                   // one use, valid or not
  if (!t || !ticket || Date.now() > t.exp) return false;
  return crypto.timingSafeEqual(t.hash, sha(ticket));
}
