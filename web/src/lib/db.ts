/**
 * SQLite storage of the web app: users and their analyses (the history).
 * The pipeline's own data and decisions stay in the Python side (runs/ + audit journal):
 * this database only remembers WHO asked WHAT, and which run answered.
 */
import "server-only";
import Database from "better-sqlite3";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

const FILE = process.env.DATABASE_PATH ?? "./data/askboard.db";

const SCHEMA = `
CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY,
  email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name          TEXT,
  password_hash TEXT,                       -- NULL for Google accounts
  provider      TEXT NOT NULL,              -- 'credentials' | 'google'
  image         TEXT,
  created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses (
  id            TEXT PRIMARY KEY,
  user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  question      TEXT NOT NULL,
  dataset       TEXT NOT NULL,              -- base run whose data answers (run_001, clinic_001...)
  file_name     TEXT,                       -- the CSV the user dropped (profiled in the browser)
  file_rows     INTEGER,
  file_columns  TEXT,                       -- JSON list
  run_id        TEXT,                       -- run created by the BO4-12 agent (custom_xxxx)
  metric        TEXT NOT NULL,
  dimensions    TEXT NOT NULL,              -- JSON list
  period_start  TEXT NOT NULL, period_end  TEXT NOT NULL,
  compare_start TEXT NOT NULL, compare_end TEXT NOT NULL,
  status        TEXT NOT NULL,              -- running | needs_review | completed | failed
  decision      TEXT,                       -- pending | accepted | rejected
  lang          TEXT NOT NULL DEFAULT 'en',
  hidden        INTEGER NOT NULL DEFAULT 0, -- removed from the history (the audit journal keeps it)
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS analyses_user ON analyses(user_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS analyses_run ON analyses(run_id);
CREATE TABLE IF NOT EXISTS notifications (
  id            TEXT PRIMARY KEY,
  user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  analysis_id   TEXT REFERENCES analyses(id) ON DELETE CASCADE,
  kind          TEXT NOT NULL,              -- completed | needs_review | failed
  created_at    TEXT NOT NULL,
  read_at       TEXT
);
CREATE INDEX IF NOT EXISTS notifications_user ON notifications(user_id, created_at DESC);
`;

const g = globalThis as unknown as { __askboardDb?: Database.Database };

export function db(): Database.Database {
  if (!g.__askboardDb) {
    fs.mkdirSync(path.dirname(path.resolve(FILE)), { recursive: true });
    const d = new Database(FILE);
    d.pragma("journal_mode = WAL");
    d.pragma("foreign_keys = ON");
    d.exec(SCHEMA);
    g.__askboardDb = d;
  }
  return g.__askboardDb;
}

const now = () => new Date().toISOString();
export const newId = () => crypto.randomUUID();

// ---- users -------------------------------------------------------------------------
export type User = {
  id: string; email: string; name: string | null; password_hash: string | null;
  provider: string; image: string | null; created_at: string;
};

export function userByEmail(email: string): User | undefined {
  return db().prepare("SELECT * FROM users WHERE email = ?").get(email.trim()) as User | undefined;
}

export function createUser(u: { email: string; name: string; passwordHash: string }): User {
  const id = newId();
  db().prepare(`INSERT INTO users (id, email, name, password_hash, provider, created_at)
                VALUES (?, ?, ?, ?, 'credentials', ?)`).run(id, u.email.trim(), u.name.trim(), u.passwordHash, now());
  return userByEmail(u.email)!;
}

/** Google sign-in: create the account on first visit, refresh name and picture after. */
export function upsertGoogleUser(u: { email: string; name?: string | null; image?: string | null }): User {
  const existing = userByEmail(u.email);
  if (existing) {
    db().prepare("UPDATE users SET name = COALESCE(?, name), image = COALESCE(?, image) WHERE id = ?")
      .run(u.name ?? null, u.image ?? null, existing.id);
    return userByEmail(u.email)!;
  }
  const id = newId();
  db().prepare(`INSERT INTO users (id, email, name, password_hash, provider, image, created_at)
                VALUES (?, ?, ?, NULL, 'google', ?, ?)`).run(id, u.email.trim(), u.name ?? null, u.image ?? null, now());
  return userByEmail(u.email)!;
}

// ---- analyses (the history) ---------------------------------------------------------------
export type AnalysisRow = {
  id: string; user_id: string; question: string; dataset: string; file_name: string | null;
  file_rows: number | null; file_columns: string | null; run_id: string | null; metric: string;
  dimensions: string; period_start: string; period_end: string; compare_start: string; compare_end: string;
  status: string; decision: string | null; lang: string; hidden: number; created_at: string; updated_at: string;
};

export type Analysis = Omit<AnalysisRow, "dimensions" | "file_columns" | "hidden"> & {
  dimensions: string[]; file_columns: string[];
};

const parse = (r: AnalysisRow): Analysis => {
  const { hidden: _hidden, ...rest } = r;
  return { ...rest, dimensions: JSON.parse(r.dimensions), file_columns: r.file_columns ? JSON.parse(r.file_columns) : [] };
};

export function listAnalyses(userId: string): Analysis[] {
  return (db().prepare("SELECT * FROM analyses WHERE user_id = ? AND hidden = 0 ORDER BY created_at DESC")
    .all(userId) as AnalysisRow[]).map(parse);
}

export function getAnalysis(id: string, userId: string): Analysis | undefined {
  const r = db().prepare("SELECT * FROM analyses WHERE id = ? AND user_id = ?").get(id, userId) as AnalysisRow | undefined;
  return r ? parse(r) : undefined;
}

export function analysisByRun(runId: string, userId: string): Analysis | undefined {
  const r = db().prepare("SELECT * FROM analyses WHERE run_id = ? AND user_id = ?").get(runId, userId) as AnalysisRow | undefined;
  return r ? parse(r) : undefined;
}

export function createAnalysis(a: {
  userId: string; question: string; dataset: string; fileName?: string | null; fileRows?: number | null;
  fileColumns?: string[]; metric: string; dimensions: string[]; period: { start: string; end: string };
  compareTo: { start: string; end: string }; lang: string;
}): Analysis {
  const id = newId();
  const t = now();
  db().prepare(`INSERT INTO analyses (id, user_id, question, dataset, file_name, file_rows, file_columns, metric,
                  dimensions, period_start, period_end, compare_start, compare_end, status, lang, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?)`)
    .run(id, a.userId, a.question, a.dataset, a.fileName ?? null, a.fileRows ?? null,
         JSON.stringify(a.fileColumns ?? []), a.metric, JSON.stringify(a.dimensions), a.period.start, a.period.end,
         a.compareTo.start, a.compareTo.end, a.lang, t, t);
  return getAnalysis(id, a.userId)!;
}

export function updateAnalysis(id: string, userId: string,
                               fields: Partial<Pick<AnalysisRow, "run_id" | "status" | "decision">>) {
  const keys = Object.keys(fields) as (keyof typeof fields)[];
  if (!keys.length) return;
  const set = keys.map((k) => `${k} = ?`).join(", ");
  db().prepare(`UPDATE analyses SET ${set}, updated_at = ? WHERE id = ? AND user_id = ?`)
    .run(...keys.map((k) => fields[k] ?? null), now(), id, userId);
}

export function hideAnalysis(id: string, userId: string) {
  db().prepare("UPDATE analyses SET hidden = 1, updated_at = ? WHERE id = ? AND user_id = ?").run(now(), id, userId);
}

// ---- Notifications: "your analysis is ready" -------------------------------------------------
export type NotificationKind = "completed" | "needs_review" | "failed";
export type Notification = { id: string; kind: NotificationKind; analysis_id: string | null; question: string | null;
                             created_at: string; read: boolean };

export function addNotification(userId: string, analysisId: string, kind: NotificationKind) {
  db().prepare("INSERT INTO notifications (id, user_id, analysis_id, kind, created_at) VALUES (?, ?, ?, ?, ?)")
    .run(newId(), userId, analysisId, kind, now());
}

export function listNotifications(userId: string, limit = 20): { unread: number; items: Notification[] } {
  const rows = db().prepare(`SELECT n.id, n.kind, n.analysis_id, a.question, n.created_at, n.read_at
                               FROM notifications n LEFT JOIN analyses a ON a.id = n.analysis_id
                              WHERE n.user_id = ? ORDER BY n.created_at DESC LIMIT ?`).all(userId, limit) as
    (Omit<Notification, "read"> & { read_at: string | null })[];
  const unread = (db().prepare("SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND read_at IS NULL")
    .get(userId) as { c: number }).c;
  return { unread, items: rows.map(({ read_at, ...r }) => ({ ...r, read: read_at !== null })) };
}

/** Marks some (ids) or all of the user's notifications as read. Only the user's own rows are touched. */
export function markNotificationsRead(userId: string, ids?: string[]) {
  if (ids && ids.length === 0) return;
  if (!ids) {
    db().prepare("UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL").run(now(), userId);
    return;
  }
  const mark = db().prepare("UPDATE notifications SET read_at = ? WHERE id = ? AND user_id = ? AND read_at IS NULL");
  db().transaction(() => ids.forEach((id) => mark.run(now(), id, userId)))();
}
