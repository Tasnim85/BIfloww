/** Small in-memory limiter against password guessing (per process; enough for one server). */
import "server-only";

const hits = new Map<string, number[]>();

export function allow(key: string, max = 5, windowMs = 60_000): boolean {
  const t = Date.now();
  const recent = (hits.get(key) ?? []).filter((x) => t - x < windowMs);
  recent.push(t);
  hits.set(key, recent);
  if (hits.size > 10_000) hits.clear();
  return recent.length <= max;
}
