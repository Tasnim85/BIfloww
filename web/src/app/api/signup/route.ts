import bcrypt from "bcryptjs";
import { NextResponse } from "next/server";
import { z } from "zod";
import { createUser, userByEmail } from "@/lib/db";
import { verifyRecaptcha } from "@/lib/recaptcha";
import { allow } from "@/lib/rate-limit";
import { issueTicket } from "@/lib/signup-ticket";

const Body = z.object({
  name: z.string().trim().min(2).max(80),
  email: z.string().trim().toLowerCase().email().max(200),
  // at least 8 characters, one letter and one digit
  password: z.string().min(8).max(128).regex(/[A-Za-z]/).regex(/\d/),
  captcha: z.string().optional().nullable(),
});

export async function POST(req: Request) {
  const ip = req.headers.get("x-forwarded-for") ?? "local";
  if (!allow(`signup:${ip}`, 5, 10 * 60_000)) return NextResponse.json({ error: "too_many_attempts" }, { status: 429 });
  const parsed = Body.safeParse(await req.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: "invalid_form" }, { status: 400 });
  const captcha = await verifyRecaptcha(parsed.data.captcha);
  if (!captcha.ok) return NextResponse.json({ error: captcha.reason }, { status: 400 });
  if (userByEmail(parsed.data.email)) return NextResponse.json({ error: "email_taken" }, { status: 409 });
  const passwordHash = await bcrypt.hash(parsed.data.password, 12);
  createUser({ email: parsed.data.email, name: parsed.data.name, passwordHash });
  // lets the browser sign in at once without a second reCAPTCHA (see lib/signup-ticket.ts)
  return NextResponse.json({ ok: true, ticket: issueTicket(parsed.data.email) }, { status: 201 });
}
