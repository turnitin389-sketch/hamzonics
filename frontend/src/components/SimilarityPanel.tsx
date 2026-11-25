"use client";

import { useEffect, useMemo, useState } from "react";
import { api, ApiError, pctLabel, similarityQuery, type Similarity, type SimilarityFilters } from "@/lib/api";

// Same palettes as the PDF report (worker/report.py).
export const SOURCE_COLORS = ["#c2185b", "#1e63d6", "#0b7a4b", "#7b3fd6", "#d14900", "#00838f", "#ad1457", "#3949ab",
  "#2e7d32", "#6a1b9a", "#ef6c00", "#00695c"];
export const GROUPS: { key: string; label: string; bg: string; color: string; icon: string; help: string }[] = [
  { key: "not_cited_or_quoted", label: "Not Cited or Quoted", bg: "#f59a9a", color: "#e04848", icon: "■", help: "Neither in-text citation nor quotation marks" },
  { key: "missing_quotations", label: "Missing Quotations", bg: "#fbbd7c", color: "#ee7d1b", icon: "“", help: "Still very similar to the source material" },
  { key: "missing_citation", label: "Missing Citation", bg: "#f7e08a", color: "#d7a700", icon: "≡", help: "Quotation marks, but no in-text citation" },
  { key: "cited_and_quoted", label: "Cited and Quoted", bg: "#a9e2cf", color: "#2f9e7a", icon: "✓", help: "In-text citation present" },
];
const GROUP = Object.fromEntries(GROUPS.map((g) => [g.key, g]));
const TYPE_LABEL: Record<string, string> = { corpus: "Publication", web: "Internet", submission: "Submitted works" };
const TYPE_PILL: Record<string, string> = { corpus: "#ede7fb", web: "#fde4ee", submission: "#e3f2e9" };
const MATCH_LABEL: Record<string, string> = { exact: "Exact copy", near: "Near copy", paraphrase: "Paraphrase", crosslang: "Translation" };

function host(url: string | null): string | null {
  try {
    return url ? new URL(url).host : null;
  } catch {
    return null;
  }
}

export function SimilarityPanel({ submissionId, text }: { submissionId: string; text: string }) {
  const [filters, setFilters] = useState<SimilarityFilters | null>(null);
  const [data, setData] = useState<Similarity | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [numbering, setNumbering] = useState<Record<string, number>>({});

  useEffect(() => {
    let stop = false;
    // First load: the report defaults (bibliography excluded); then the user's filters.
    api<Similarity>(`/submissions/${submissionId}/similarity${filters ? similarityQuery(filters) : ""}`)
      .then((d) => {
        if (stop) return;
        setData(d);
        if (!filters) {
          setFilters({ exclude_quotes: d.exclude_quotes, exclude_bibliography: d.exclude_bibliography, min_words: d.min_words, exclude_source: [] });
          setNumbering(Object.fromEntries(d.sources.map((s, i) => [s.source_key, i + 1])));
        }
      })
      .catch((err) => !stop && setError(err instanceof ApiError ? err.message : "Could not load similarity"));
    return () => {
      stop = true;
    };
  }, [submissionId, filters]);

  const colorOf = (key: string) => SOURCE_COLORS[((numbering[key] ?? 1) - 1) % SOURCE_COLORS.length]!;

  const segments = useMemo(() => {
    if (!data) return [];
    const out: { text: string; run?: Similarity["runs"][number]; badge?: boolean }[] = [];
    let pos = 0;
    let last: string | null = null;
    for (const run of [...data.runs].sort((a, b) => a.start - b.start)) {
      if (run.start < pos) continue;
      if (run.start > pos) out.push({ text: text.slice(pos, run.start) });
      out.push({ text: text.slice(run.start, run.end), run, badge: run.source_key !== last });
      last = run.source_key;
      pos = run.end;
    }
    if (pos < text.length) out.push({ text: text.slice(pos) });
    return out;
  }, [data, text]);

  if (error) return <div className="card text-sm text-red-700">{error}</div>;
  if (!data || !filters) return <div className="card text-sm text-slate-500">Loading similarity…</div>;

  const total = Math.max(data.total_words, 1);
  const counts: Record<string, number> = {};
  {
    let prev = "";
    for (const r of [...data.runs].sort((a, b) => a.start - b.start)) {
      const k = `${r.source_key}|${r.group}`;
      if (k !== prev) counts[r.group] = (counts[r.group] ?? 0) + 1;
      prev = k;
    }
  }

  const jumpTo = (key: string) => {
    const marks = Array.from(document.querySelectorAll<HTMLElement>(`mark[data-source="${CSS.escape(key)}"]`));
    if (marks.length === 0) return;
    const current = marks.findIndex((m) => m.dataset.active === "1");
    marks.forEach((m) => {
      delete m.dataset.active;
      m.style.outline = "";
    });
    const next = marks[(current + 1) % marks.length]!;
    next.dataset.active = "1";
    next.style.outline = `2px solid ${colorOf(key)}`;
    next.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const toggleSource = (key: string) =>
    setFilters((f) => f && ({
      ...f,
      exclude_source: f.exclude_source.includes(key) ? f.exclude_source.filter((k) => k !== key) : [...f.exclude_source, key],
    }));

  return (
    <>
    {data.web_search_message && (
      <div className="mb-4 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
        <b>Incomplete check.</b> {data.web_search_message}
      </div>
    )}
    <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
      <div className="card order-2 p-0 lg:order-1">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-5 py-3">
          <h2 className="font-semibold">Document</h2>
          <div className="flex flex-wrap gap-3 text-xs text-slate-600">
            {GROUPS.filter((g) => data.groups[g.key]).map((g) => (
              <span key={g.key} className="flex items-center gap-1"><i className="inline-block h-3 w-3 rounded-sm" style={{ background: g.bg }} />{g.label}</span>
            ))}
          </div>
        </div>
        <div dir="auto" className="max-h-[75vh] overflow-auto whitespace-pre-wrap px-5 py-4 font-serif text-[15px] leading-8 text-slate-900">
          {segments.map((seg, i) => {
            if (!seg.run) return <span key={i}>{seg.text}</span>;
            const g = GROUP[seg.run.group];
            const n = numbering[seg.run.source_key];
            return (
              <mark
                key={i}
                data-source={seg.run.source_key}
                title={`Source ${n ?? ""} · ${MATCH_LABEL[seg.run.match_type] ?? seg.run.match_type} · ${g?.label ?? "Bibliography"}\n\n${seg.run.source_excerpt}`}
                className="cursor-help rounded-sm"
                style={{ background: g?.bg ?? "#d9dee6", color: "inherit" }}
                onClick={() => jumpTo(seg.run!.source_key)}
              >
                {seg.badge && n && (
                  <sup className="mr-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full px-1 align-top font-sans text-[10px] font-bold leading-none text-white" style={{ background: colorOf(seg.run.source_key) }}>
                    {n}
                  </sup>
                )}
                {seg.text}
              </mark>
            );
          })}
        </div>
      </div>

      <aside className="order-1 space-y-4 lg:order-2">
        <div className="card space-y-4 p-5">
          <div>
            <div className="text-4xl font-bold text-orange-600">{pctLabel(data.percent)}</div>
            <div className="text-sm font-medium text-slate-700">Overall Similarity</div>
            <div className="text-xs text-slate-500">{data.matched_words.toLocaleString()} of {data.total_words.toLocaleString()} words match</div>
          </div>
          <div className="space-y-2">
            {GROUPS.map((g) => (
              <div key={g.key} className="flex items-start gap-2 text-sm">
                <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white" style={{ background: g.color }}>{g.icon}</span>
                <div>
                  <b>{counts[g.key] ?? 0}</b> {g.label} <b className="ml-1">{pctLabel((100 * (data.groups[g.key] ?? 0)) / total)}</b>
                  <div className="text-xs text-slate-500">{g.help}</div>
                </div>
              </div>
            ))}
          </div>
          <div className="space-y-1 border-t border-slate-100 pt-3 text-sm">
            {(["web", "corpus", "submission"] as const).map((t) => (
              <div key={t} className="flex gap-3"><span className="w-10 font-semibold">{pctLabel(data.by_type[t] ?? 0)}</span>{t === "web" ? "Internet sources" : t === "corpus" ? "Publications" : "Submitted works"}</div>
            ))}
          </div>
          <fieldset className="space-y-2 border-t border-slate-100 pt-3 text-sm text-slate-700">
            <legend className="sr-only">Filters</legend>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={filters.exclude_bibliography} onChange={(e) => setFilters({ ...filters, exclude_bibliography: e.target.checked })} />
              Exclude bibliography
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={filters.exclude_quotes} onChange={(e) => setFilters({ ...filters, exclude_quotes: e.target.checked })} />
              Exclude quoted text
            </label>
            <label className="flex items-center gap-2">
              Exclude matches under
              <input type="number" min={0} max={1000} className="input w-16 py-0.5" value={filters.min_words}
                onChange={(e) => setFilters({ ...filters, min_words: Math.max(0, Number(e.target.value) || 0) })} />
              words
            </label>
          </fieldset>
        </div>

        <div className="card p-0">
          <div className="border-b border-slate-200 px-5 py-3 font-semibold">Top Sources</div>
          <ol className="max-h-[50vh] divide-y divide-slate-100 overflow-auto">
            {data.sources.map((s) => (
              <li key={s.source_key} className="flex items-start gap-3 px-5 py-3">
                <span className="mt-0.5 inline-flex h-6 min-w-8 items-center justify-center rounded-full px-2 text-xs font-bold text-white" style={{ background: colorOf(s.source_key) }}>
                  {numbering[s.source_key] ?? "•"}
                </span>
                <div className="min-w-0 flex-1">
                  <span className="mb-1 inline-block rounded-full px-3 py-0.5 text-[11px] font-semibold text-slate-700" style={{ background: TYPE_PILL[s.type] ?? "#eef2f6" }}>{TYPE_LABEL[s.type] ?? s.type}</span>
                  <div className="cursor-pointer break-words text-sm font-medium text-slate-800 hover:underline" onClick={() => jumpTo(s.source_key)} title="Jump to the next match from this source">
                    {s.type === "web" ? host(s.url) ?? s.title : s.title}
                  </div>
                  <div className="flex gap-3 text-xs">
                    {s.url && <a href={s.url} target="_blank" rel="noopener noreferrer" className="text-brand-700 hover:underline">Open source</a>}
                    <button type="button" onClick={() => toggleSource(s.source_key)} className="text-slate-500 hover:text-red-600">Exclude</button>
                  </div>
                </div>
                <span className="text-sm font-semibold">{pctLabel(s.percent)}</span>
              </li>
            ))}
            {data.sources.length === 0 && <li className="px-5 py-3 text-sm text-slate-500">No matching sources found.</li>}
          </ol>
          {filters.exclude_source.length > 0 && (
            <button type="button" onClick={() => setFilters({ ...filters, exclude_source: [] })} className="px-5 py-2 text-xs text-brand-700 hover:underline">
              Restore {filters.exclude_source.length} excluded source(s)
            </button>
          )}
        </div>
      </aside>
    </div>
    </>
  );
}
