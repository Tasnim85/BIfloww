"use client";
import { AnimatePresence, motion } from "framer-motion";
import { AlertCircle, CalendarRange, Check, Database, FileSpreadsheet, Loader2, Sparkles, UploadCloud, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { Skeleton } from "@/components/ui/kit";
import { api, ApiError, type Dataset, useApi } from "@/lib/client";
import { cn } from "@/lib/cn";
import { DATASET_INFO } from "@/lib/pipeline";

type Parsed = { name: string; size: number; rows: number; columns: string[]; types: string[]; preview: string[][] };
type Period = { start: string; end: string };

const MAX_BYTES = 50 * 1024 * 1024;

/** Minimal CSV line splitter (quotes and escaped quotes). Enough for a preview in the browser. */
function splitLine(line: string, sep: string): string[] {
  const out: string[] = [];
  let cur = "", q = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (q) {
      if (c === '"' && line[i + 1] === '"') { cur += '"'; i++; } else if (c === '"') q = false; else cur += c;
    } else if (c === '"') q = true;
    else if (c === sep) { out.push(cur); cur = ""; } else cur += c;
  }
  out.push(cur);
  return out.map((s) => s.trim());
}

function guessType(values: string[]): string {
  const v = values.filter((x) => x !== "");
  if (!v.length) return "empty";
  if (v.every((x) => /^-?\d+([.,]\d+)?$/.test(x))) return "number";
  if (v.every((x) => /^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$/.test(x) || /^\d{2}\/\d{2}\/\d{4}/.test(x))) return "date";
  return "text";
}

async function parseCsv(file: File): Promise<Parsed> {
  const text = await file.slice(0, Math.min(file.size, MAX_BYTES)).text();
  const lines = text.split(/\r?\n/).filter((l) => l.length > 0);
  const head = lines[0] ?? "";
  const sep = [",", ";", "\t"].sort((a, b) => head.split(b).length - head.split(a).length)[0];
  const columns = splitLine(head, sep);
  const sample = lines.slice(1, 201).map((l) => splitLine(l, sep));
  const types = columns.map((_, i) => guessType(sample.map((r) => r[i] ?? "")));
  return { name: file.name, size: file.size, rows: Math.max(0, lines.length - 1), columns, types, preview: sample.slice(0, 5) };
}

function monthPeriods(lastDay: string): { cur: Period; prev: Period } {
  const last = new Date(`${lastDay}T00:00:00Z`);
  const curStart = new Date(Date.UTC(last.getUTCFullYear(), last.getUTCMonth(), 1));
  const prevEnd = new Date(curStart.getTime() - 86400000);
  const prevStart = new Date(Date.UTC(prevEnd.getUTCFullYear(), prevEnd.getUTCMonth(), 1));
  const d = (x: Date) => x.toISOString().slice(0, 10);
  return { cur: { start: d(curStart), end: lastDay }, prev: { start: d(prevStart), end: d(prevEnd) } };
}

export function NewAnalysis() {
  const t = useTranslations("app.new");
  const tc = useTranslations("app");
  const locale = useLocale();
  const router = useRouter();
  const raw = useApi<Dataset[]>("datasets");
  const { loading, error } = raw;
  const order = Object.keys(DATASET_INFO);
  const datasets = useMemo(() => raw.data && [...raw.data].sort((x, y) =>
    (order.indexOf(x.run_id) + 1 || 99) - (order.indexOf(y.run_id) + 1 || 99)), [raw.data]);  // eslint-disable-line react-hooks/exhaustive-deps
  const [file, setFile] = useState<Parsed | null>(null);
  const [fileErr, setFileErr] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const [datasetId, setDatasetId] = useState<string | null>(null);
  const [metric, setMetric] = useState("");
  const [dimension, setDimension] = useState("");
  const [period, setPeriod] = useState<Period>({ start: "", end: "" });
  const [compare, setCompare] = useState<Period>({ start: "", end: "" });
  const [question, setQuestion] = useState("");
  const [llm, setLlm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [submitErr, setSubmitErr] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const ds = useMemo(() => datasets?.find((d) => d.run_id === datasetId) ?? null, [datasets, datasetId]);
  const kpi = ds?.kpis.find((k) => k.name === metric) ?? null;

  useEffect(() => { if (datasets?.length && !datasetId) setDatasetId(datasets[0].run_id); }, [datasets, datasetId]);
  useEffect(() => {
    if (!ds) return;
    const ex = DATASET_INFO[ds.run_id]?.example;
    const k = ds.kpis.find((x) => x.name === ex?.metric) ?? ds.kpis[0];
    setMetric(k?.name ?? "");
    setDimension(ex && k?.allowed_dimensions.includes(ex.dimension) ? ex.dimension : k?.allowed_dimensions[0] ?? "");
    const p = ex ? { cur: ex.period, prev: ex.compareTo } : monthPeriods(ds.last_day);
    setPeriod(p.cur); setCompare(p.prev);
  }, [ds]);

  const autoQuestion = kpi ? t("auto_question", { kpi: kpi.name, dim: dimension || t("overall"),
    p1: `${period.start} → ${period.end}`, p2: `${compare.start} → ${compare.end}` }) : "";

  async function onFile(f: File | undefined) {
    setFileErr(null);
    if (!f) return;
    if (!/\.(csv|tsv|txt)$/i.test(f.name)) { setFileErr(t("file_type")); return; }
    if (f.size > MAX_BYTES) setFileErr(t("file_big"));
    setFile(await parseCsv(f));
  }

  const dsLabel = (id: string) => (DATASET_INFO[id] ? tc(`datasets.${DATASET_INFO[id].key}.name`) : id);
  const valid = Boolean(ds && kpi && period.start && period.end && compare.start && compare.end
    && period.start <= period.end && compare.start <= compare.end);

  async function submit() {
    if (!ds || !kpi) return;
    setBusy(true); setSubmitErr(null);
    try {
      const r = await api<{ id: string }>("/api/analyses", { method: "POST", body: {
        question: question.trim() || autoQuestion, dataset: ds.run_id, metric: kpi.name,
        dimensions: dimension ? [dimension] : [], period, compareTo: compare, llm, lang: locale,
        file: file ? { name: file.name, rows: file.rows, columns: file.columns } : null } });
      router.push(`/app/runs/${r.id}?new=1`);
    } catch (e) {
      setSubmitErr(e instanceof ApiError && e.status === 502 ? t("err_pipeline") : t("err_generic"));
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold sm:text-3xl">{t("title")}</h1>
        <p className="mt-1 text-muted">{t("subtitle")}</p>
      </div>

      {/* 1. The file */}
      <section className="card p-5 sm:p-6">
        <StepTitle n={1} title={t("s1_title")} text={t("s1_text")} />
        <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
             onDrop={(e) => { e.preventDefault(); setDrag(false); void onFile(e.dataTransfer.files[0]); }}
             className={cn("mt-4 rounded-2xl border-2 border-dashed p-6 text-center transition",
               drag ? "border-primary bg-primary-soft" : "border-line hover:border-primary/50")}>
          {!file ? (
            <div className="flex flex-col items-center">
              <div className="grid h-12 w-12 place-items-center rounded-full bg-primary-soft text-primary"><UploadCloud className="h-6 w-6" /></div>
              <p className="mt-3 font-medium">{t("drop")}</p>
              <p className="mt-1 text-sm text-muted">{t("drop_hint")}</p>
              <button type="button" className="btn-outline mt-4" onClick={() => inputRef.current?.click()}>{t("browse")}</button>
              <input ref={inputRef} type="file" accept=".csv,.tsv,.txt,text/csv" className="sr-only" aria-label={t("browse")}
                     onChange={(e) => void onFile(e.target.files?.[0])} />
            </div>
          ) : (
            <div className="text-left">
              <div className="flex flex-wrap items-center gap-3">
                <FileSpreadsheet className="h-8 w-8 text-primary" />
                <div className="min-w-0 flex-1">
                  <div className="truncate font-semibold">{file.name}</div>
                  <div className="text-sm text-muted">{t("file_meta", { rows: file.rows.toLocaleString(locale), cols: file.columns.length, kb: Math.round(file.size / 1024).toLocaleString(locale) })}</div>
                </div>
                <button type="button" className="btn-ghost h-9 w-9 p-0" onClick={() => setFile(null)} aria-label={t("remove_file")}><X className="h-4 w-4" /></button>
              </div>
              <div className="mt-4 flex flex-wrap gap-1.5">
                {file.columns.slice(0, 24).map((c, i) => (
                  <span key={c + i} className="chip border border-line bg-surface-2 font-mono text-[11px] font-medium text-ink">
                    {c}<span className="text-subtle">· {t(`types.${file.types[i]}`)}</span>
                  </span>
                ))}
                {file.columns.length > 24 && <span className="chip text-muted">+{file.columns.length - 24}</span>}
              </div>
              <div className="mt-4 overflow-x-auto rounded-xl border border-line">
                <table className="w-full text-left text-xs">
                  <thead className="bg-surface-2"><tr>{file.columns.slice(0, 8).map((c, i) => <th key={c + i} className="whitespace-nowrap px-3 py-2 font-semibold">{c}</th>)}</tr></thead>
                  <tbody>{file.preview.map((r, i) => (
                    <tr key={i} className="border-t border-line">{file.columns.slice(0, 8).map((_, j) => <td key={j} className="max-w-[180px] truncate whitespace-nowrap px-3 py-1.5 text-muted">{r[j]}</td>)}</tr>
                  ))}</tbody>
                </table>
              </div>
            </div>
          )}
        </div>
        {fileErr && <p className="mt-2 flex items-center gap-1.5 text-sm text-warn"><AlertCircle className="h-4 w-4" />{fileErr}</p>}
        <p className="mt-3 rounded-xl bg-surface-2 p-3 text-xs text-muted">{t("file_note")}</p>
      </section>

      {/* 2. The prepared data */}
      <section className="card p-5 sm:p-6">
        <StepTitle n={2} title={t("s2_title")} text={t("s2_text")} />
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {loading && [0, 1].map((i) => <Skeleton key={i} className="h-28" />)}
          {error && <p className="text-sm text-bad">{t("err_datasets")}</p>}
          {datasets?.map((d) => {
            const active = d.run_id === datasetId;
            const info = DATASET_INFO[d.run_id];
            return (
              <button key={d.run_id} type="button" onClick={() => setDatasetId(d.run_id)} aria-pressed={active}
                      className={cn("relative rounded-2xl border p-4 text-left transition",
                        active ? "border-primary bg-primary-soft ring-4 ring-primary/10" : "border-line hover:border-primary/40")}>
                {active && <span className="absolute right-3 top-3 grid h-6 w-6 place-items-center rounded-full bg-primary text-primary-fg"><Check className="h-3.5 w-3.5" /></span>}
                <div className="flex items-center gap-2 font-semibold"><Database className="h-4 w-4 text-primary" />{dsLabel(d.run_id)}</div>
                <p className="mt-1 text-sm text-muted">{info ? tc(`datasets.${info.key}.text`) : d.run_id}</p>
                <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted">
                  <span className="chip bg-surface-2"><CalendarRange className="h-3 w-3" />{d.first_day} → {d.last_day}</span>
                  <span className="chip bg-surface-2">{d.kpis.map((k) => k.name).join(", ")}</span>
                </div>
              </button>
            );
          })}
        </div>
      </section>

      {/* 3. The question */}
      <section className="card p-5 sm:p-6">
        <StepTitle n={3} title={t("s3_title")} text={t("s3_text")} />
        <div className="mt-4 space-y-4">
          <div>
            <label htmlFor="q" className="label">{t("question")}</label>
            <textarea id="q" rows={2} maxLength={500} value={question} onChange={(e) => setQuestion(e.target.value)}
                      placeholder={autoQuestion} className="input h-auto py-3" />
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="kpi" className="label">{t("kpi")}</label>
              <select id="kpi" className="input" value={metric} onChange={(e) => { setMetric(e.target.value);
                setDimension(ds?.kpis.find((k) => k.name === e.target.value)?.allowed_dimensions[0] ?? ""); }}>
                {ds?.kpis.map((k) => <option key={k.name} value={k.name}>{k.name} ({k.unit})</option>)}
              </select>
              {kpi && <p className="mt-1.5 text-xs text-muted">{kpi.description}</p>}
            </div>
            <div>
              <label htmlFor="dim" className="label">{t("dimension")}</label>
              <select id="dim" className="input" value={dimension} onChange={(e) => setDimension(e.target.value)}>
                <option value="">{t("overall")}</option>
                {kpi?.allowed_dimensions.map((d) => <option key={d} value={d}>{d.replace(/_/g, " ")}</option>)}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <PeriodInput id="p1" label={t("period")} value={period} onChange={setPeriod} min={ds?.first_day} max={ds?.last_day} />
            <PeriodInput id="p2" label={t("compare_to")} value={compare} onChange={setCompare} min={ds?.first_day} max={ds?.last_day} />
          </div>
          <p className="text-xs text-muted">{t("period_hint")}</p>
          <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-line p-3">
            <input type="checkbox" checked={llm} onChange={(e) => setLlm(e.target.checked)} className="mt-0.5 h-4 w-4 accent-[rgb(var(--primary))]" />
            <span>
              <span className="flex items-center gap-1.5 text-sm font-medium"><Sparkles className="h-4 w-4 text-accent" />{t("llm")}</span>
              <span className="mt-0.5 block text-xs text-muted">{t("llm_hint")}</span>
            </span>
          </label>
        </div>
      </section>

      {submitErr && <div role="alert" className="flex items-center gap-2 rounded-xl border border-bad/30 bg-bad-soft p-3 text-sm text-bad"><AlertCircle className="h-4 w-4" />{submitErr}</div>}
      <div className="flex justify-end">
        <button type="button" disabled={!valid || busy} onClick={submit} className="btn-primary h-12 px-7 text-base">
          {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <Sparkles className="h-5 w-5" />}{t("run")}
        </button>
      </div>

      <AnimatePresence>
        {busy && (
          <motion.div className="fixed inset-0 z-[60] grid place-items-center bg-navy/60 p-4 backdrop-blur-sm"
                      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} role="status" aria-live="polite">
            <motion.div className="card w-full max-w-sm p-8 text-center" initial={{ scale: 0.95 }} animate={{ scale: 1 }}>
              <div className="relative mx-auto h-16 w-16">
                <span className="absolute inset-0 animate-pulseRing rounded-full bg-primary/40" />
                <span className="relative grid h-16 w-16 place-items-center rounded-full bg-primary text-primary-fg"><Sparkles className="h-7 w-7" /></span>
              </div>
              <h2 className="mt-5 text-lg font-semibold">{t("working_title")}</h2>
              <p className="mt-1 text-sm text-muted">{t("working_text")}</p>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function StepTitle({ n, title, text }: { n: number; title: string; text: string }) {
  return (
    <div className="flex items-start gap-3">
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-navy font-display text-sm font-bold text-white dark:bg-primary dark:text-primary-fg">{n}</span>
      <div><h2 className="font-semibold">{title}</h2><p className="text-sm text-muted">{text}</p></div>
    </div>
  );
}

function PeriodInput({ id, label, value, onChange, min, max }:
  { id: string; label: string; value: Period; onChange: (p: Period) => void; min?: string; max?: string }) {
  return (
    <fieldset>
      <legend className="label">{label}</legend>
      <div className="flex items-center gap-2">
        <input id={`${id}-s`} aria-label={`${label} (start)`} type="date" className="input" value={value.start} min={min} max={max}
               onChange={(e) => onChange({ ...value, start: e.target.value })} />
        <span className="text-muted">→</span>
        <input id={`${id}-e`} aria-label={`${label} (end)`} type="date" className="input" value={value.end} min={min} max={max}
               onChange={(e) => onChange({ ...value, end: e.target.value })} />
      </div>
    </fieldset>
  );
}
