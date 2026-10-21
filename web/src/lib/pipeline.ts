/**
 * THE PIPELINE, as the app shows it. One entry per agent of the DAG (contracts/pipeline.py).
 *
 * mode "live": the stage really runs through the Python API (Tasnim's agents today).
 * mode "demo": a placeholder until its owner plugs the real agent in. To go live, an owner:
 *   1. exposes the agent's output through the API (a route in their own FastAPI router),
 *   2. sets mode: "live" here and writes what the stage shows in useOutput() (src/components/run/Pipeline.tsx),
 *      and, for a full panel, a tab in src/components/run/RunView.tsx.
 * Texts (name, demo output) are in messages/en.json and fr.json under "stages.<id>".
 */
export type StageMode = "live" | "demo";

export type Stage = {
  id: string;           // = the step name in contracts/pipeline.py
  step: string;         // number shown in the timeline
  owner: string;
  bo: string[];         // business objectives served
  mode: StageMode;
  icon: string;         // lucide icon name (see src/components/run/StageIcon.tsx)
};

export const STAGES: Stage[] = [
  { id: "upload", step: "0", owner: "Samar", bo: ["BO1"], mode: "live", icon: "upload" },
  { id: "similarity", step: "0", owner: "Malek", bo: ["BO1"], mode: "demo", icon: "copy" },
  { id: "column_types", step: "1a", owner: "Malek", bo: ["BO1"], mode: "demo", icon: "tags" },
  { id: "pii", step: "1b", owner: "Ikbel", bo: ["BO2"], mode: "demo", icon: "shield" },
  { id: "profiling", step: "2", owner: "Ahmed", bo: ["BO2"], mode: "demo", icon: "scan" },
  { id: "cleaning", step: "2b", owner: "Ikbel", bo: ["BO1", "BO2"], mode: "demo", icon: "sparkles" },
  { id: "etl", step: "3", owner: "Ahmed", bo: ["BO1"], mode: "demo", icon: "database" },
  { id: "request", step: "4", owner: "Malek", bo: ["BO3", "BO4"], mode: "demo", icon: "message" },
  { id: "analysis", step: "5", owner: "Rabeb", bo: ["BO1"], mode: "demo", icon: "chart" },
  { id: "comparisons", step: "6", owner: "Tasnim", bo: ["BO4"], mode: "live", icon: "scale" },
  { id: "dashboard", step: "6", owner: "Samar", bo: ["BO4"], mode: "demo", icon: "layout" },
  { id: "lineage", step: "—", owner: "Ahmed", bo: ["BO2"], mode: "demo", icon: "git" },
  { id: "auditor", step: "7", owner: "Tasnim", bo: ["BO3"], mode: "live", icon: "badge" },
];

/** The datasets the demo can answer questions on (runs prepared on the Python side), with the
 *  example question the form starts with (a known trap the comparison agent catches). */
type Example = { metric: string; dimension: string; period: { start: string; end: string }; compareTo: { start: string; end: string } };
export const DATASET_INFO: Record<string, { flag: string; key: string; example?: Example }> = {
  run_001: { flag: "BR", key: "olist", example: { metric: "Revenue", dimension: "customer_state",
    period: { start: "2018-08-01", end: "2018-08-31" }, compareTo: { start: "2018-07-01", end: "2018-07-31" } } },
  clinic_001: { flag: "TN", key: "clinics", example: { metric: "Consultation revenue", dimension: "region",
    period: { start: "2024-03-01", end: "2024-03-31" }, compareTo: { start: "2024-02-01", end: "2024-02-29" } } },
};

/** Runs anyone signed in may READ (showcase data). Every other run must belong to the user. */
export const isShowcaseRun = (runId: string) => !runId.startsWith("custom_");
