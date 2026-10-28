"use client";
import { AnimatePresence, motion } from "framer-motion";
import { AlertCircle, ArrowRight, CalendarRange, Check, Database, FileSpreadsheet, Loader2, ScanText, Sparkles, UploadCloud, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { NOTIFY_EVENT } from "@/components/app/Notifications";
import { Skeleton } from "@/components/ui/kit";
import { api, ApiError, type Dataset, type ParsedQuestion, useApi } from "@/lib/client";
import { cn } from "@/lib/cn";
import { DATASET_INFO } from "@/lib/pipeline";

type Parsed = { name: string; size: number; rows: number; columns: string[]; types: string[]; preview: string[][] };
type Period = { start: string; end: string };

const MAX_BYTES = 50 * 1024 * 1024;               // read in the browser for the preview
const MAX_UPLOAD = 150 * 1024 * 1024;             // per file, checked again by the server

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
  const [files, setFiles] = useState<{ parsed: Parsed; raw: File }[]>([]);
  const [shown, setShown] = useState(0);
  const upload = files.length > 0;                  // the user's own files: the whole pipeline runs on them
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
  // Malek's parser (live): what it proposed, and the form fields as it filled them
  const [parsed, setParsed] = useState<{ res: ParsedQuestion; fields: string } | null>(null);
  const [parsing, setParsing] = useState(false);
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

  const fields = JSON.stringify([metric, dimension, period, compare]);
  const parsedKept = parsed?.res.request != null && parsed.fields === fields;   // the user did not change the proposal

  async function readQuestion() {
    if (!ds || question.trim().length < 3) return;
    setParsing(true);
    try {
      const res = await api<ParsedQuestion>("parse", { method: "POST", body: { question: question.trim(), base_run: ds.run_id } });
      const r = res.request;
      let next = fields;
      if (r) {
        const k = ds.kpis.find((x) => x.name === r.metric);
        if (k) {
          const dim = r.dimensions.find((d) => k.allowed_dimensions.includes(d)) ?? "";
          const cmp = r.compare_to ?? compare;
          setMetric(k.name); setDimension(dim); setPeriod(r.period); setCompare(cmp);
          next = JSON.stringify([k.name, dim, r.period, cmp]);
        }
      }
      setParsed({ res, fields: next });
    } catch {
      setParsed({ res: { status: "failed", message: t("parse_error"), request: null }, fields: "" });
    } finally { setParsing(false); }
  }

  const autoQuestion = kpi ? t("auto_question", { kpi: kpi.name, dim: dimension || t("overall"),
    p1: `${period.start} → ${period.end}`, p2: `${compare.start} → ${compare.end}` }) : "";

  async function onFiles(list: FileList | null) {
    setFileErr(null);
    const added: { parsed: Parsed; raw: File }[] = [];
    for (const f of Array.from(list ?? [])) {
      if (!/\.csv$/i.test(f.name)) { setFileErr(t("file_type")); continue; }
      if (f.size > MAX_UPLOAD) { setFileErr(t("file_big")); continue; }
      added.push({ parsed: await parseCsv(f), raw: f });
    }
    setFiles((cur) => [...cur.filter((x) => !added.some((y) => y.raw.name.toLowerCase() === x.raw.name.toLowerCase())), ...added].slice(0, 20));
  }
  function removeFile(i: number) { setFiles((cur) => cur.filter((_, k) => k !== i)); setShown(0); }

  const dsLabel = (id: string) => (DATASET_INFO[id] ? tc(`datasets.${DATASET_INFO[id].key}.name`) : id);
  const valid = upload ? question.trim().length >= 3 : Boolean(ds && kpi && period.start && period.end && compare.start && compare.end
    && period.start <= period.end && compare.start <= compare.end);

  async function submitUpload() {
    setBusy(true); setSubmitErr(null);
    const form = new FormData();
    files.forEach((f) => form.append("files", f.raw, f.raw.name));
    form.append("question", question.trim());
    form.append("lang", locale);
    try {
      const res = await fetch("/api/uploads", { method: "POST", body: form });
      const data = await res.json().catch(() => ({}));
      if (res.status !== 201) {
        const detail = String(data?.detail ?? "");
        setSubmitErr(res.status === 429 ? t("err_too_many") : res.status === 413 ? t("file_big")
          : /BO2_PII_SECRET/.test(detail) ? t("err_secret") : /local LLM/i.test(detail) ? t("err_llm") : t("err_pipeline"));
        setBusy(false);
        return;
      }
      window.dispatchEvent(new Event(NOTIFY_EVENT));
      router.push(`/app/runs/${data.id}`);
    } catch {
      setSubmitErr(t("err_generic")); setBusy(false);
    }
  }

  async function submit() {
    if (upload) return submitUpload();
    if (!ds || !kpi) return;
    setBusy(true); setSubmitErr(null);
    try {
      const r = await api<{ id: string }>("/api/analyses", { method: "POST", body: {
        question: question.trim() || autoQuestion, dataset: ds.run_id, metric: kpi.name,
        dimensions: dimension ? [dimension] : [], period, compareTo: compare, llm, lang: locale,
        ...(parsedKept && parsed.res.request ? { confidence: parsed.res.request.confidence, matchedTerms: parsed.res.request.matched_terms } : {}) } });
      window.dispatchEvent(new Event(NOTIFY_EVENT));                 // the bell refreshes at once
      // if the user went elsewhere meanwhile, leave them there: the notification brings them back
      if (window.location.pathname === "/app/new") router.push(`/app/runs/${r.id}?new=1`);
    } catch (e) {
      window.dispatchEvent(new Event(NOTIFY_EVENT));
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

      {/* 1. The files (Samar's intake: they go through the WHOLE pipeline) */}
      <section className="card p-5 sm:p-6">
        <StepTitle n={1} title={t("s1_title")} text={t("s1_text")} />
        <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
             onDrop={(e) => { e.preventDefault(); setDrag(false); void onFiles(e.dataTransfer.files); }}
             className={cn("mt-4 rounded-2xl border-2 border-dashed p-6 text-center transition",
               drag ? "border-primary bg-primary-soft" : "border-line hover:border-primary/50")}>
          <div className="flex flex-col items-center">
            <div className="grid h-12 w-12 place-items-center rounded-full bg-primary-soft text-primary"><UploadCloud className="h-6 w-6" /></div>
            <p className="mt-3 font-medium">{t("drop")}</p>
            <p className="mt-1 text-sm text-muted">{t("drop_hint")}</p>
            <button type="button" className="btn-outline mt-4" onClick={() => inputRef.current?.click()}>{t("browse")}</button>
            <input ref={inputRef} type="file" multiple accept=".csv,text/csv" className="sr-only" aria-label={t("browse")}
                   onChange={(e) => { void onFiles(e.target.files); e.target.value = ""; }} />
          </div>
        </div>
        {files.length > 0 && (
          <div className="mt-4 space-y-3">
            <ul className="grid gap-2 sm:grid-cols-2">
              {files.map((f, i) => (
                <li key={f.parsed.name}>
                  <button type="button" onClick={() => setShown(i)} aria-pressed={shown === i}
                          className={cn("flex w-full items-center gap-3 rounded-xl border p-3 text-left transition",
                            shown === i ? "border-primary bg-primary-soft" : "border-line hover:border-primary/40")}>
                    <FileSpreadsheet className="h-6 w-6 shrink-0 text-primary" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-semibold">{f.parsed.name}</span>
                      <span className="block text-xs text-muted">{t("file_meta", { rows: f.parsed.rows.toLocaleString(locale), cols: f.parsed.columns.length, kb: Math.round(f.parsed.size / 1024).toLocaleString(locale) })}</span>
                    </span>
                    <span role="button" tabIndex={0} aria-label={t("remove_file")} className="grid h-8 w-8 shrink-0 place-items-center rounded-lg hover:bg-surface-2"
                          onClick={(e) => { e.stopPropagation(); removeFile(i); }}
                          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); removeFile(i); } }}>
                      <X className="h-4 w-4" />
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            {files[shown] && <Preview file={files[shown].parsed} />}
          </div>
        )}
        {fileErr && <p className="mt-2 flex items-center gap-1.5 text-sm text-warn"><AlertCircle className="h-4 w-4" />{fileErr}</p>}
        <p className="mt-3 rounded-xl bg-surface-2 p-3 text-xs text-muted">{upload ? t("file_note_upload") : t("file_note")}</p>
      </section>

      {/* 2. The prepared data */}
      <section className="card p-5 sm:p-6">
        <StepTitle n={2} title={t("s2_title")} text={upload ? t("s2_upload") : t("s2_text")} />
        {upload ? (
          <div className="mt-4 flex items-start gap-3 rounded-2xl border border-accent/40 bg-accent-soft/40 p-4 text-sm">
            <Sparkles className="mt-0.5 h-5 w-5 shrink-0 text-accent" />
            <div><p className="font-semibold">{t("upload_title", { n: files.length })}</p><p className="mt-1 text-muted">{t("upload_text")}</p></div>
          </div>
        ) : (
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
        )}
      </section>

      {/* 3. The question */}
      <section className="card p-5 sm:p-6">
        <StepTitle n={3} title={t("s3_title")} text={upload ? t("s3_upload") : t("s3_text")} />
        <div className="mt-4 space-y-4">
          <div>
            <label htmlFor="q" className="label">{t("question")}</label>
            <div className="relative">
              <textarea id="q" rows={2} maxLength={500} value={question} onChange={(e) => setQuestion(e.target.value)}
                        onKeyDown={(e) => { if (!upload && e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void readQuestion(); } }}
                        placeholder={t("question_placeholder")} className={cn("input h-auto py-3 pr-4", !upload && "sm:pr-44")} />
              {!upload && (
                <button type="button" onClick={readQuestion} disabled={parsing || !ds || question.trim().length < 3}
                        className="btn-primary mt-2 h-10 w-full sm:absolute sm:bottom-2 sm:right-2 sm:mt-0 sm:w-auto">
                  {parsing ? <Loader2 className="h-4 w-4 animate-spin" /> : <ScanText className="h-4 w-4" />}{t("parse")}
                </button>
              )}
            </div>
            <p className="mt-1.5 text-xs text-muted">{upload ? t("question_upload_hint") : t("parse_hint")}</p>
            {!upload && parsed && <ParseResult res={parsed.res} kept={parsedKept} />}
          </div>
          {!upload && (<>
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
          </>)}
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
              <h2 className="mt-5 text-lg font-semibold">{upload ? t("sending_title") : t("working_title")}</h2>
              <p className="mt-1 text-sm text-muted">{upload ? t("sending_text") : t("working_text")}</p>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function ParseResult({ res, kept }: { res: ParsedQuestion; kept: boolean }) {
  const t = useTranslations("app.new");
  const r = res.request;
  if (!r) {
    return <p role="status" className="mt-3 flex items-start gap-2 rounded-xl border border-warn/30 bg-warn-soft p-3 text-sm text-warn">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />{res.status === "failed" ? t("parse_error") : t("parse_unclear")}</p>;
  }
  const terms = Object.entries(r.matched_terms ?? {});
  return (
    <motion.div role="status" initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }}
                className="mt-3 rounded-xl border border-accent/40 bg-accent-soft/40 p-3.5">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Check className="h-4 w-4 text-ok" /><span className="font-semibold">{t("parsed_title")}</span>
        <span className="text-xs text-muted">{t("parsed_by", { p: Math.round(r.confidence * 100) })}</span>
        {!kept && <span className="chip bg-surface text-muted">{t("parsed_edited")}</span>}
      </div>
      {terms.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {terms.map(([w, g]) => <li key={w} className="chip border border-line bg-surface text-xs">“{w}”<ArrowRight className="h-3 w-3 text-subtle" /><b className="font-mono">{g}</b></li>)}
        </ul>
      )}
    </motion.div>
  );
}

function Preview({ file }: { file: Parsed }) {
  const t = useTranslations("app.new");
  return (
    <div>
      <div className="flex flex-wrap gap-1.5">
        {file.columns.slice(0, 24).map((c, i) => (
          <span key={c + i} className="chip border border-line bg-surface-2 font-mono text-[11px] font-medium text-ink">
            {c}<span className="text-subtle">· {t(`types.${file.types[i]}`)}</span>
          </span>
        ))}
        {file.columns.length > 24 && <span className="chip text-muted">+{file.columns.length - 24}</span>}
      </div>
      <div className="mt-3 overflow-x-auto rounded-xl border border-line">
        <table className="w-full text-left text-xs">
          <thead className="bg-surface-2"><tr>{file.columns.slice(0, 8).map((c, i) => <th key={c + i} className="whitespace-nowrap px-3 py-2 font-semibold">{c}</th>)}</tr></thead>
          <tbody>{file.preview.map((r, i) => (
            <tr key={i} className="border-t border-line">{file.columns.slice(0, 8).map((_, j) => <td key={j} className="max-w-[180px] truncate whitespace-nowrap px-3 py-1.5 text-muted">{r[j]}</td>)}</tr>
          ))}</tbody>
        </table>
      </div>
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
