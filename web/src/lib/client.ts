"use client";
/** Browser-side access to the pipeline: always through /api/backend (auth + allowlist + ownership). */
import { useLocale } from "next-intl";
import { useCallback, useEffect, useState } from "react";
import type { components } from "@/lib/api-types";

export type S = components["schemas"];
export type ComparisonReport = S["ComparisonReport"];
export type ComparisonCheck = S["ComparisonCheck"];
export type ProposedFix = S["ProposedFix"];
export type RunSummary = S["RunSummary"];
export type KpiBreakdown = S["KpiBreakdown"];
export type Dataset = S["Dataset"];
export type ExplanationPage = S["ExplanationPage"];
export type AnomalyExplanation = S["AnomalyExplanation"];
export type JournalEntry = S["JournalEntry"];
export type DriftReport = S["DriftReport"];
export type WhyAnswer = S["WhyAnswer"];
export type IntegrityReport = S["IntegrityReport"];

export type Analysis = {
  id: string; question: string; dataset: string; file_name: string | null; file_rows: number | null;
  file_columns: string[]; run_id: string | null; metric: string; dimensions: string[];
  period_start: string; period_end: string; compare_start: string; compare_end: string;
  status: "running" | "needs_review" | "completed" | "failed"; decision: string | null; lang: string;
  created_at: string; updated_at: string;
};

export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) { super(`HTTP ${status}`); }
}

export async function api<T>(path: string, init: { method?: "GET" | "POST" | "DELETE"; body?: unknown;
  lang?: string; query?: Record<string, string | number | boolean> } = {}): Promise<T> {
  const q = new URLSearchParams(Object.entries(init.query ?? {}).map(([k, v]) => [k, String(v)]));
  if (init.lang) q.set("lang", init.lang);
  const url = path.startsWith("/api/") ? path : `/api/backend/${path}`;
  const res = await fetch(`${url}${q.size ? `?${q}` : ""}`, {
    method: init.method ?? "GET",
    headers: init.body ? { "Content-Type": "application/json" } : undefined,
    body: init.body ? JSON.stringify(init.body) : undefined,
    cache: "no-store",
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data);
  return data as T;
}

/** GET with loading / error state, re-fetched when the language changes. */
export function useApi<T>(path: string | null, query?: Record<string, string | number | boolean>) {
  const lang = useLocale();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const key = JSON.stringify(query ?? {});
  const load = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try {
      setData(await api<T>(path, { lang, query: JSON.parse(key) }));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, null));
    } finally {
      setLoading(false);
    }
  }, [path, lang, key]);
  useEffect(() => { void load(); }, [load]);
  return { data, error, loading, reload: load, setData };
}
