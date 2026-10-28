/**
 * Uploaded datasets (Samar's intake): the whole DAG runs in the Python API, in the background.
 * The history is kept in sync HERE, server-side: each time the user's history or notifications are read,
 * the analyses still in the pipeline ask the API for their progress, and a notification is added
 * when one needs the user (a review) or finishes.
 */
import "server-only";
import { backend } from "@/lib/backend";
import { addNotification, pendingUploads, updateAnalysis } from "@/lib/db";

type Progress = { state: "running" | "needs_review" | "done" | "failed" | "stopped" };
type Summary = {
  request?: { metric: string; dimensions: string[]; period: { start: string; end: string };
              compare_to?: { start: string; end: string } | null } | null;
  comparison?: { user_decision: string } | null;
};

export const isUploadRun = (runId: string | null | undefined) => Boolean(runId && /^up_[0-9a-f]{12}$/.test(runId));

export async function syncUploads(uid: string): Promise<void> {
  for (const a of pendingUploads(uid)) {
    const p = await backend<Progress>(`runs/${a.run_id}/progress`);
    if (p.status !== 200) continue;
    const state = p.data.state;
    const s = await backend<Summary>(`runs/${a.run_id}`);
    const r = s.status === 200 ? s.data.request : null;
    const fields = r ? { metric: r.metric, dimensions: JSON.stringify(r.dimensions), period_start: r.period.start,
                         period_end: r.period.end, compare_start: r.compare_to?.start ?? "", compare_end: r.compare_to?.end ?? "" } : {};
    const decision = s.status === 200 ? s.data.comparison?.user_decision ?? null : null;
    if (state === "running") {
      if (a.status !== "running" || (r && !a.metric)) updateAnalysis(a.id, uid, { status: "running", ...fields });
    } else if (state === "needs_review") {
      if (a.status !== "needs_review") { updateAnalysis(a.id, uid, { status: "needs_review", decision, ...fields }); addNotification(uid, a.id, "needs_review"); }
    } else if (state === "done") {
      updateAnalysis(a.id, uid, { status: "completed", decision, ...fields }); addNotification(uid, a.id, "completed");
    } else {
      updateAnalysis(a.id, uid, { status: "failed", ...fields }); addNotification(uid, a.id, "failed");
    }
  }
}
