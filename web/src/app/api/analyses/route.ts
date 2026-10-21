/** The user's history (GET) and a new analysis (POST): runs the REAL BO4-12 agent via the Python API. */
import { NextResponse } from "next/server";
import { z } from "zod";
import { currentUserId } from "@/lib/auth";
import { backend } from "@/lib/backend";
import { createAnalysis, listAnalyses, updateAnalysis } from "@/lib/db";

const day = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const Body = z.object({
  question: z.string().trim().min(3).max(500),
  dataset: z.string().regex(/^[A-Za-z0-9_-]{1,64}$/),
  metric: z.string().min(1).max(100),
  dimensions: z.array(z.string().max(100)).max(3),
  period: z.object({ start: day, end: day }),
  compareTo: z.object({ start: day, end: day }),
  file: z.object({ name: z.string().max(200), rows: z.number().int().nonnegative(),
                   columns: z.array(z.string().max(200)).max(500) }).nullable().optional(),
  llm: z.boolean().optional(),
  lang: z.enum(["en", "fr"]),
});

type ComparisonReport = { checks: { status: string }[]; user_decision: string };

export async function GET() {
  const uid = await currentUserId();
  if (!uid) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  return NextResponse.json(listAnalyses(uid));
}

export async function POST(req: Request) {
  const uid = await currentUserId();
  if (!uid) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const parsed = Body.safeParse(await req.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: "invalid_form", issues: parsed.error.issues }, { status: 400 });
  const b = parsed.data;
  if (b.period.start > b.period.end || b.compareTo.start > b.compareTo.end)
    return NextResponse.json({ error: "invalid_periods" }, { status: 400 });

  const a = createAnalysis({ userId: uid, question: b.question, dataset: b.dataset, fileName: b.file?.name,
    fileRows: b.file?.rows, fileColumns: b.file?.columns, metric: b.metric, dimensions: b.dimensions,
    period: b.period, compareTo: b.compareTo, lang: b.lang });

  const res = await backend<{ run_id: string; report: ComparisonReport; detail?: string }>("comparisons", {
    method: "POST", lang: b.lang,
    body: { base_run: b.dataset, metric: b.metric, dimensions: b.dimensions, period: b.period,
            compare_to: b.compareTo, question: b.question, llm: Boolean(b.llm), lang: b.lang },
  });
  if (res.status !== 200) {
    updateAnalysis(a.id, uid, { status: "failed" });
    return NextResponse.json({ error: "pipeline_failed", detail: res.data, id: a.id }, { status: 502 });
  }
  const blocking = res.data.report.checks.some((c) => c.status === "blocking");
  updateAnalysis(a.id, uid, { run_id: res.data.run_id, status: blocking ? "needs_review" : "completed",
                              decision: res.data.report.user_decision });
  return NextResponse.json({ id: a.id, run_id: res.data.run_id }, { status: 201 });
}
