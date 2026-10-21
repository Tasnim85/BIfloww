/** Server-side calls to the Python API (FastAPI, Tasnim's router mounted under /api). */
import "server-only";

const BASE = (process.env.BACKEND_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export type BackendResponse<T = unknown> = { status: number; data: T };

export async function backend<T = unknown>(path: string, init: { method?: "GET" | "POST"; body?: unknown;
  lang?: string; query?: Record<string, string> } = {}): Promise<BackendResponse<T>> {
  const q = new URLSearchParams(init.query ?? {});
  if (init.lang) q.set("lang", init.lang);
  const url = `${BASE}/api/${path.replace(/^\//, "")}${q.size ? `?${q}` : ""}`;
  try {
    const res = await fetch(url, {
      method: init.method ?? "GET",
      headers: init.body ? { "Content-Type": "application/json" } : undefined,
      body: init.body ? JSON.stringify(init.body) : undefined,
      cache: "no-store",
      signal: AbortSignal.timeout(init.method === "POST" ? 180_000 : 30_000),   // the why? agent can take a while
    });
    const text = await res.text();
    let data: unknown = text;
    try { data = JSON.parse(text); } catch { /* keep the text */ }
    return { status: res.status, data: data as T };
  } catch {
    return { status: 503, data: { detail: "backend_unreachable" } as T };
  }
}

export async function backendHealth(): Promise<{ ok: boolean; llm?: { provider: string; model: string; ready: boolean } }> {
  try {
    const res = await fetch(`${BASE}/health`, { cache: "no-store", signal: AbortSignal.timeout(4000) });
    if (!res.ok) return { ok: false };
    const h = await res.json();
    return { ok: true, llm: h.llm };
  } catch {
    return { ok: false };
  }
}
