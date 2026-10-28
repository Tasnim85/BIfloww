/**
 * The user's own CSV files + question -> the WHOLE pipeline (Samar's intake, then the 12 other agents)
 * in the Python API. Checked here first (signed in, rate limit, CSV only, size), then again by the API.
 */
import { NextResponse } from "next/server";
import { currentUserId } from "@/lib/auth";
import { backend } from "@/lib/backend";
import { createAnalysis, updateAnalysis } from "@/lib/db";
import { allow } from "@/lib/rate-limit";

const MAX_FILES = 20;
const MAX_TOTAL = 300 * 1024 * 1024;

export async function POST(req: Request) {
  const uid = await currentUserId();
  if (!uid) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  if (!allow(`upload:${uid}`, 5, 10 * 60_000)) return NextResponse.json({ error: "too_many" }, { status: 429 });

  const form = await req.formData().catch(() => null);
  if (!form) return NextResponse.json({ error: "invalid_form" }, { status: 400 });
  const question = String(form.get("question") ?? "").trim();
  const lang = form.get("lang") === "fr" ? "fr" : "en";
  const files = form.getAll("files").filter((f): f is File => f instanceof File);
  if (question.length < 3 || question.length > 500) return NextResponse.json({ error: "invalid_question" }, { status: 400 });
  if (!files.length || files.length > MAX_FILES) return NextResponse.json({ error: "invalid_files" }, { status: 400 });
  if (files.some((f) => !/\.csv$/i.test(f.name))) return NextResponse.json({ error: "not_csv" }, { status: 400 });
  if (files.reduce((n, f) => n + f.size, 0) > MAX_TOTAL) return NextResponse.json({ error: "too_big" }, { status: 413 });

  const out = new FormData();
  for (const f of files) out.append("files", f, f.name);
  out.append("question", question);
  out.append("lang", lang);
  out.append("uploaded_by", uid);                     // an id, never the email
  const res = await backend<{ run_id: string; tables: string[]; detail?: string }>("uploads", { method: "POST", form: out });
  if (res.status !== 200) {
    return NextResponse.json({ error: "pipeline_unavailable", detail: res.data?.detail ?? null }, { status: res.status === 413 ? 413 : 502 });
  }
  // KPI, dimensions and periods are not known yet: the question agent finds them (synced in src/lib/uploads.ts)
  const a = createAnalysis({ userId: uid, question, dataset: res.data.run_id, fileName: files.map((f) => f.name).join(", ").slice(0, 200),
    fileColumns: res.data.tables, metric: "", dimensions: [], period: { start: "", end: "" }, compareTo: { start: "", end: "" }, lang });
  updateAnalysis(a.id, uid, { run_id: res.data.run_id, status: "running" });
  return NextResponse.json({ id: a.id, run_id: res.data.run_id }, { status: 201 });
}
