/** The signed-in user's notifications (GET) and "mark as read" (POST {ids} or {all: true}). */
import { NextResponse } from "next/server";
import { z } from "zod";
import { currentUserId } from "@/lib/auth";
import { listNotifications, markNotificationsRead } from "@/lib/db";

export async function GET() {
  const uid = await currentUserId();
  if (!uid) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  return NextResponse.json(listNotifications(uid), { headers: { "Cache-Control": "no-store" } });
}

const Body = z.union([z.object({ ids: z.array(z.string().uuid()).max(100) }), z.object({ all: z.literal(true) })]);

export async function POST(req: Request) {
  const uid = await currentUserId();
  if (!uid) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const parsed = Body.safeParse(await req.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: "invalid_form" }, { status: 400 });
  markNotificationsRead(uid, "ids" in parsed.data ? parsed.data.ids : undefined);
  return NextResponse.json(listNotifications(uid));
}
