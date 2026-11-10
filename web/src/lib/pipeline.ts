/**
 * THE PIPELINE, as the app shows it. One entry per agent of the DAG (contracts/pipeline.py).
 *
 * mode "live": the stage shows what the real agent wrote (GET /api/runs/{id}/pipeline).
 * mode "demo": a placeholder until its owner plugs the real agent in (every agent is plugged in today).
 * scope "dataset": computed ONCE when the dataset is prepared (similarity ... lineage), shown from
 *   the dataset's run; scope "question": computed for each question (request, analysis, comparisons, auditor).
 * Texts are in messages/en.json and fr.json under "app.stages.<id>"; panels in src/components/run/StagePanels.tsx.
 */
export type StageMode = "live" | "demo";
/** The 6 agents of BIFlow + the orchestrator. Each task (Stage) belongs to ONE agent; the rail shows
 *  the agents in pipeline order, each with its tasks underneath. */
export type Phase = "orchestrator" | "profiler" | "etl" | "semantic" | "analyst" | "dashboard" | "auditor";

export type Stage = {
  id: string;           // = the step name in contracts/pipeline.py
  step: string;         // number shown in the timeline
  owner: string;
  bo: string[];         // business objectives served
  mode: StageMode;
  scope: "dataset" | "question";
  phase: Phase;
  icon: string;         // lucide icon name (see ICONS in src/components/run/PipelineRail.tsx)
};

export const STAGES: Stage[] = [
  { id: "upload", step: "0", owner: "Samar", bo: ["BO1"], mode: "live", scope: "dataset", phase: "orchestrator", icon: "upload" },
  { id: "similarity", step: "0", owner: "Malek", bo: ["BO1"], mode: "live", scope: "dataset", phase: "orchestrator", icon: "copy" },
  { id: "column_types", step: "1a", owner: "Malek", bo: ["BO1"], mode: "live", scope: "dataset", phase: "profiler", icon: "tags" },
  { id: "pii", step: "1b", owner: "Ikbel", bo: ["BO2"], mode: "live", scope: "dataset", phase: "profiler", icon: "shield" },
  { id: "profiling", step: "2", owner: "Ahmed", bo: ["BO2"], mode: "live", scope: "dataset", phase: "profiler", icon: "scan" },
  { id: "cleaning", step: "2b", owner: "Ikbel", bo: ["BO1", "BO2"], mode: "live", scope: "dataset", phase: "profiler", icon: "sparkles" },
  { id: "etl", step: "3", owner: "Ahmed", bo: ["BO1"], mode: "live", scope: "dataset", phase: "etl", icon: "database" },
  { id: "lineage", step: "3b", owner: "Ahmed", bo: ["BO2"], mode: "live", scope: "dataset", phase: "etl", icon: "git" },
  { id: "request", step: "4", owner: "Malek", bo: ["BO3", "BO4"], mode: "live", scope: "question", phase: "semantic", icon: "message" },
  { id: "analysis", step: "5", owner: "Rabeb", bo: ["BO1"], mode: "live", scope: "question", phase: "analyst", icon: "chart" },
  { id: "comparisons", step: "6", owner: "Tasnim", bo: ["BO4"], mode: "live", scope: "question", phase: "dashboard", icon: "scale" },
  { id: "dashboard", step: "6b", owner: "Samar", bo: ["BO4"], mode: "live", scope: "question", phase: "dashboard", icon: "layout" },
  { id: "auditor", step: "7", owner: "Tasnim", bo: ["BO3"], mode: "live", scope: "question", phase: "auditor", icon: "badge" },
];

export const PHASES: Phase[] = ["orchestrator", "profiler", "etl", "semantic", "analyst", "dashboard", "auditor"];

/** What a stage really is FOR THIS RUN:
 *  live    the agent's own output is shown;
 *  demo    a placeholder (owner not plugged in yet, or a dataset prepared by a script, not by the agents);
 *  missing the agent did not run on this dataset. */
export type StageState = "live" | "demo" | "missing";
export function stageState(stage: Stage, dataset: string, available: boolean | undefined): StageState {
  if (stage.mode === "demo") return "demo";
  if (!available) return "missing";
  // a dataset the user uploaded went through the real agents too
  if (stage.scope === "dataset" && !(DATASET_INFO[dataset]?.agents ?? /^up_/.test(dataset))) return "demo";
  return "live";
}

/** The datasets the demo can answer questions on (runs prepared on the Python side), with the
 *  example question the form starts with (a known trap the comparison agent catches). */
type Example = { metric: string; dimension: string; period: { start: string; end: string }; compareTo: { start: string; end: string } };
//  agents: true = the dataset was prepared by the team's real agents (tools/integration/run_with_reviews.py),
//  false = by a script (demo data): its data stages are then shown as DEMO even if files exist.
export const DATASET_INFO: Record<string, { flag: string; key: string; agents: boolean; example?: Example }> = {
  olist_live: { flag: "BR", key: "olist_live", agents: true, example: { metric: "Revenue", dimension: "customer_state",
    period: { start: "2018-08-01", end: "2018-08-31" }, compareTo: { start: "2018-07-01", end: "2018-07-31" } } },
  run_001: { flag: "BR", key: "olist", agents: false, example: { metric: "Revenue", dimension: "customer_state",
    period: { start: "2018-08-01", end: "2018-08-31" }, compareTo: { start: "2018-07-01", end: "2018-07-31" } } },
  clinic_001: { flag: "TN", key: "clinics", agents: false, example: { metric: "Consultation revenue", dimension: "region",
    period: { start: "2024-03-01", end: "2024-03-31" }, compareTo: { start: "2024-02-01", end: "2024-02-29" } } },
};

/** Runs anyone signed in may READ (showcase data). Every other run must belong to the user. */
export const isShowcaseRun = (runId: string) => !/^(custom|up)_/.test(runId);

/** A dataset the user uploaded: the whole DAG runs on it in the Python API (Samar's orchestrator). */
export const isUploadRunId = (runId: string | null | undefined) => Boolean(runId && /^up_[0-9a-f]{12}$/.test(runId));
