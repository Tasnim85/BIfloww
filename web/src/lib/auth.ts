/** Authentication: email + password (reCAPTCHA v2 checkbox) and Google. Sessions are signed JWT cookies. */
import "server-only";
import bcrypt from "bcryptjs";
import crypto from "node:crypto";
import type { NextAuthOptions } from "next-auth";
import { getServerSession } from "next-auth";
import { cookies } from "next/headers";
import CredentialsProvider from "next-auth/providers/credentials";
import GoogleProvider from "next-auth/providers/google";
import { upsertGoogleUser, userByEmail } from "@/lib/db";
import { sendWelcomeEmail } from "@/lib/mail";
import { verifyRecaptcha } from "@/lib/recaptcha";
import { allow } from "@/lib/rate-limit";
import { consumeTicket } from "@/lib/signup-ticket";

export const googleEnabled = () => Boolean(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET);

// A real hash of nothing: a wrong email takes as long as a wrong password (no account enumeration by timing).
let dummyHash: string | null = null;
const dummy = () => (dummyHash ??= bcrypt.hashSync(crypto.randomUUID(), 12));

export const authOptions: NextAuthOptions = {
  session: { strategy: "jwt", maxAge: 7 * 24 * 3600 },
  pages: { signIn: "/signin" },
  providers: [
    CredentialsProvider({
      name: "Email",
      credentials: { email: {}, password: {}, captcha: {}, ticket: {} },
      async authorize(credentials, req) {
        const email = String(credentials?.email ?? "").trim().toLowerCase();
        const password = String(credentials?.password ?? "");
        const ip = String((req?.headers as Record<string, string> | undefined)?.["x-forwarded-for"] ?? "local");
        if (!allow(`signin:${ip}:${email}`)) throw new Error("too_many_attempts");
        // right after sign-up: the one-time ticket replaces a second reCAPTCHA challenge
        if (!consumeTicket(email, credentials?.ticket)) {
          const captcha = await verifyRecaptcha(credentials?.captcha);
          if (!captcha.ok) throw new Error(captcha.reason ?? "captcha_invalid");
        }
        const user = email ? userByEmail(email) : undefined;
        const valid = await bcrypt.compare(password, user?.password_hash ?? dummy());
        if (!user || !user.password_hash || !valid) throw new Error("invalid_credentials");
        return { id: user.id, email: user.email, name: user.name, image: user.image };
      },
    }),
    ...(googleEnabled()
      ? [GoogleProvider({ clientId: process.env.GOOGLE_CLIENT_ID!, clientSecret: process.env.GOOGLE_CLIENT_SECRET! })]
      : []),
  ],
  callbacks: {
    async signIn({ account, profile, user }) {
      if (account?.provider === "google") {
        const p = profile as { email?: string; email_verified?: boolean; name?: string; picture?: string } | undefined;
        if (!p?.email || p.email_verified === false) return false;            // only verified Google emails
        const isNew = !userByEmail(p.email);
        const u = upsertGoogleUser({ email: p.email, name: p.name ?? user.name, image: p.picture ?? user.image });
        user.id = u.id;
        if (isNew) void sendWelcomeEmail(u.email, u.name ?? u.email, (await cookies()).get("NEXT_LOCALE")?.value ?? "en");
      }
      return true;
    },
    async jwt({ token, user }) {
      if (user?.id) token.uid = user.id;
      return token;
    },
    async session({ session, token }) {
      if (session.user && token.uid) session.user.id = token.uid;
      return session;
    },
  },
};

/** The signed-in user's id, or null. Use it in every server route and page. */
export async function currentUserId(): Promise<string | null> {
  const s = await getServerSession(authOptions);
  return s?.user?.id ?? null;
}
