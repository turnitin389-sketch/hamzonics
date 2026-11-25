// Thin fetch wrapper for the Hamzonics API (same origin, no accounts).

export type Submission = {
  id: string;
  status: "queued" | "running" | "done" | "failed";
  progress: number;
  stage: string;
  error: string | null;
  queue_position: number | null;
  original_filename: string;
  file_type: string;
  file_size: number;
  word_count: number | null;
  page_count: number | null;
  ocr_pages: number | null;
  repository_opt_in: boolean;
  engine_version: string;
  flags: { type: string; count: number }[];
  similarity_percent: number | null;
  ai_percent: number | null;
  ai_available: boolean | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  delete_token?: string | null;
};

export type QueueStatus = { running: number; queued: number; max_concurrent: number };

export type SubmissionText = {
  id: string;
  word_count: number;
  clean_text: string;
  pages: { page: number; start: number; end: number; ocr: boolean }[];
};

export type FlagLocation = {
  count: number;
  page: number;
  text?: string;
  start?: number;
  end?: number;
  detail?: string;
};

export type Flag = { type: string; count: number; locations: FlagLocation[] };

export type SimilaritySource = {
  source_key: string;
  type: "corpus" | "web" | "submission" | string;
  title: string;
  url: string | null;
  words: number;
  percent: number;
};

export type SimilarityRun = {
  start: number;
  end: number;
  words: number;
  source_key: string;
  match_type: "exact" | "near" | "paraphrase" | "crosslang" | string;
  group: string;
  score: number;
  source_excerpt: string;
};

export type Similarity = {
  percent: number;
  matched_words: number;
  total_words: number;
  sources: SimilaritySource[];
  runs: SimilarityRun[];
  groups: Record<string, number>;
  by_type: Record<string, number>;
  exclude_bibliography: boolean;
  exclude_quotes: boolean;
  min_words: number;
  web_search: "off" | "ok" | "partial" | "unavailable" | string;
  web_search_message: string;
};

export type SimilarityFilters = {
  exclude_quotes: boolean;
  exclude_bibliography: boolean;
  min_words: number;
  exclude_source: string[];
};

export type AISegment = { start: number; end: number; word_start: number; word_end: number; level: "ai" | "possible"; score: number };

export type AIResult = {
  available: boolean;
  percent: number | null;
  qualifying_words: number;
  ai_words: number;
  model: string;
  message: string;
  segments: AISegment[];
};

export function similarityQuery(f: SimilarityFilters): string {
  const p = new URLSearchParams();
  p.set("exclude_quotes", String(f.exclude_quotes));
  p.set("exclude_bibliography", String(f.exclude_bibliography));
  p.set("min_words", String(f.min_words));
  f.exclude_source.forEach((s) => p.append("exclude_source", s));
  return `?${p.toString()}`;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(`/api${path}`, { ...init, headers, credentials: "omit", cache: "no-store" });
  const data: unknown = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) {
    throw new ApiError(res.status, errorMessage(data) ?? `Request failed (${res.status})`);
  }
  return data as T;
}

function errorMessage(data: unknown): string | null {
  if (data && typeof data === "object" && "detail" in data) {
    const detail = (data as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0] && typeof detail[0] === "object" && "msg" in detail[0]) {
      return String((detail[0] as { msg: unknown }).msg);
    }
  }
  return null;
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID().replace(/-/g, "");
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/** Whole percent like the PDF report; "<1%" for small non-zero values. */
export function pctLabel(p: number | null | undefined): string {
  if (p == null) return "–";
  if (p <= 0) return "0%";
  if (p < 1) return "<1%";
  return `${Math.round(p)}%`;
}

export function fmtDate(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "–";
}

// ---------------------------------------------------------------- "my checks" (this browser only)

export type MyCheck = { id: string; filename: string; created_at: string; delete_token?: string | null };
const KEY = "hz-my-checks";

export function loadMyChecks(): MyCheck[] {
  try {
    const raw = localStorage.getItem(KEY);
    const list = raw ? (JSON.parse(raw) as MyCheck[]) : [];
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

export function saveMyCheck(c: MyCheck): void {
  try {
    const list = loadMyChecks().filter((x) => x.id !== c.id);
    localStorage.setItem(KEY, JSON.stringify([c, ...list].slice(0, 50)));
  } catch {
    /* private mode: the check still works, it is just not remembered */
  }
}

export function forgetMyCheck(id: string): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(loadMyChecks().filter((x) => x.id !== id)));
  } catch {
    /* ignore */
  }
}

export function deleteTokenFor(id: string): string | null {
  return loadMyChecks().find((x) => x.id === id)?.delete_token ?? null;
}
