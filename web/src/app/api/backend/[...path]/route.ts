/**
 * The browser never talks to the Python API directly: it goes through this route, which
 *   1. requires a signed-in user,
 *   2. only forwards an ALLOWLIST of routes,
 *   3. checks ownership: a user reads showcase datasets and HIS analyses, and writes (decision,
 *      why?) only on his analyses,
 *   4. keeps the history in sync with the user's decision,
 *   5. writes the signed-in user's name as the reviewer of every approval / decision (audit journal),
 *   6. limits the question parser (POST parse: no run, read-only) to 20 calls a minute per user.
 */
import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { currentUser } from "@/lib/auth";
import { backend } from "@/lib/backend";
import { analysisByRun, updateAnalysis } from "@/lib/db";
import { allow } from "@/lib/rate-limit";
import { isShowcaseRun } from "@/lib/pipeline";
import { isUploadRun } from "@/lib/uploads";

const RUN = "([A-Za-z0-9_-]{1,64})";
const READ: RegExp[] = [
  /^datasets$/, /^drift$/, /^journals$/, /^journals\/(demo|drift|clinics|ui|real|integration)\/verify$/,
  new RegExp(`^runs/${RUN}(/(comparison|dashboard|journal|drift|explanations|pipeline|charts|progress))?$`),
  new RegExp(`^runs/${RUN}/explanations/[A-Za-z0-9_.:-]{1,128}$`),
];
const WRITE: RegExp[] = [new RegExp(`^runs/${RUN}/(comparison/decision|why|review)$`), /^parse$/];
const PASS_QUERY = ["limit", "offset", "anomalies_only", "include_llm"];

type Ctx = { params: Promise<{ path: string[] }> };

async function handle(req: Request, { params }: Ctx, method: "GET" | "POST") {
  const user = await currentUser();
  if (!user) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const uid = user.id;
  const path = (await params).path.join("/");
  const rules = method === "GET" ? READ : WRITE;
  if (!rules.some((r) => r.test(path))) return NextResponse.json({ error: "not_allowed" }, { status: 403 });

  if (path === "parse" && !allow(`parse:${uid}`, 20)) return NextResponse.json({ error: "too_many" }, { status: 429 });

  const runId = path.startsWith("runs/") ? path.split("/")[1] : null;
  const owned = runId ? analysisByRun(runId, uid) : undefined;
  if (runId && !owned && (method === "POST" || !isShowcaseRun(runId)))
    return NextResponse.json({ error: "not_found" }, { status: 404 });

  const url = new URL(req.url);
  const query: Record<string, string> = {};
  for (const k of PASS_QUERY) { const v = url.searchParams.get(k); if (v !== null) query[k] = v; }
  const lang = url.searchParams.get("lang") ?? (await cookies()).get("NEXT_LOCALE")?.value ?? "en";
  let body = method === "POST" ? await req.json().catch(() => ({})) : undefined;
  // WHO approves or decides is taken from the session, never from the browser: it goes to the audit journal
  if (method === "POST" && /\/(review|comparison\/decision)$/.test(path)) body = { ...(body ?? {}), reviewer: user.name };

  const res = await backend<Record<string, unknown>>(path, { method, body, lang, query });

  if (method === "POST" && owned && path.endsWith("comparison/decision") && res.status === 200) {
    const decision = String(res.data.user_decision ?? "");
    // an uploaded dataset goes on in the pipeline (dashboard, auditor): synced later in src/lib/uploads.ts
    updateAnalysis(owned.id, uid, { decision, status: decision === "pending" ? "needs_review" : isUploadRun(runId) ? "running" : "completed" });
  }
  if (method === "POST" && owned && path.endsWith("/review") && res.status === 200) updateAnalysis(owned.id, uid, { status: "running" });
  return NextResponse.json(res.data, { status: res.status });
}

export const GET = (req: Request, ctx: Ctx) => handle(req, ctx, "GET");
export const POST = (req: Request, ctx: Ctx) => handle(req, ctx, "POST");
