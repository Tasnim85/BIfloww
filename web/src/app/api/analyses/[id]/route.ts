import { NextResponse } from "next/server";
import { currentUserId } from "@/lib/auth";
import { getAnalysis, hideAnalysis } from "@/lib/db";

type Ctx = { params: Promise<{ id: string }> };

export async function GET(_: Request, { params }: Ctx) {
  const uid = await currentUserId();
  if (!uid) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const a = getAnalysis((await params).id, uid);
  return a ? NextResponse.json(a) : NextResponse.json({ error: "not_found" }, { status: 404 });
}

/** Removes the analysis from the HISTORY only. The audit journal is append-only: it keeps everything. */
export async function DELETE(_: Request, { params }: Ctx) {
  const uid = await currentUserId();
  if (!uid) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const id = (await params).id;
  if (!getAnalysis(id, uid)) return NextResponse.json({ error: "not_found" }, { status: 404 });
  hideAnalysis(id, uid);
  return NextResponse.json({ ok: true });
}
