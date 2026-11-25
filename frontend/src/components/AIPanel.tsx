"use client";

import { useEffect, useMemo, useState } from "react";
import { api, ApiError, pctLabel, type AIResult } from "@/lib/api";

const COLORS = { ai: "#8fe3f0", possible: "#d9c8f7" };

export function AIPanel({ submissionId, text }: { submissionId: string; text: string }) {
  const [data, setData] = useState<AIResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<AIResult>(`/submissions/${submissionId}/ai`)
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load the AI result"));
  }, [submissionId]);

  const segments = useMemo(() => {
    if (!data) return [];
    const out: { text: string; level?: "ai" | "possible"; score?: number }[] = [];
    let pos = 0;
    for (const s of data.segments) {
      if (s.start < pos) continue;
      if (s.start > pos) out.push({ text: text.slice(pos, s.start) });
      out.push({ text: text.slice(s.start, s.end), level: s.level, score: s.score });
      pos = s.end;
    }
    if (pos < text.length) out.push({ text: text.slice(pos) });
    return out;
  }, [data, text]);

  if (error) return <div className="card text-sm text-red-700">{error}</div>;
  if (!data) return <div className="card text-sm text-slate-500">Loading AI result…</div>;
  if (!data.available) {
    return (
      <div className="card space-y-2">
        <div className="text-3xl font-bold text-slate-400">Not checked</div>
        <p className="text-sm text-slate-600">{data.message}</p>
      </div>
    );
  }

  const ai = data.segments.filter((s) => s.level === "ai");
  const possible = data.segments.filter((s) => s.level === "possible");
  const low = data.percent != null && data.percent > 0 && data.percent < 20;

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
      <div className="card order-2 p-0 lg:order-1">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-5 py-3">
          <h2 className="font-semibold">Document</h2>
          <div className="flex gap-3 text-xs text-slate-600">
            <span className="flex items-center gap-1"><i className="inline-block h-3 w-3 rounded-sm" style={{ background: COLORS.ai }} />AI-generated</span>
            <span className="flex items-center gap-1"><i className="inline-block h-3 w-3 rounded-sm" style={{ background: COLORS.possible }} />Possibly AI (not counted)</span>
          </div>
        </div>
        <div dir="auto" className="max-h-[75vh] overflow-auto whitespace-pre-wrap px-5 py-4 font-serif text-[15px] leading-8 text-slate-900">
          {segments.map((seg, i) =>
            seg.level ? (
              <mark key={i} style={{ background: COLORS[seg.level], color: "inherit" }} className="rounded-sm" title={`AI score ${Math.round((seg.score ?? 0) * 100)}%`}>
                {seg.text}
              </mark>
            ) : (
              <span key={i}>{seg.text}</span>
            ),
          )}
        </div>
      </div>
      <aside className="order-1 space-y-4 lg:order-2">
        <div className="card space-y-4 p-5">
          <div>
            <div className="text-4xl font-bold text-cyan-700">{pctLabel(data.percent)}{low ? "*" : ""}</div>
            <div className="text-sm font-medium text-slate-700">detected as AI</div>
            <div className="text-xs text-slate-500">{data.ai_words.toLocaleString()} of {data.qualifying_words.toLocaleString()} qualifying words</div>
          </div>
          {low && <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">* Scores under 20% are less reliable and more likely to be false positives.</p>}
          {data.message && <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">{data.message}</p>}
          <div className="space-y-2 text-sm">
            <div className="flex items-start gap-2"><span className="mt-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-cyan-600 text-[10px] font-bold text-white">AI</span><div><b>{ai.length}</b> AI-generated <div className="text-xs text-slate-500">Likely written by an AI model. Counted.</div></div></div>
            <div className="flex items-start gap-2"><span className="mt-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-violet-600 text-[10px] font-bold text-white">?</span><div><b>{possible.length}</b> Possibly AI-generated <div className="text-xs text-slate-500">Borderline score. Shown for review, not counted.</div></div></div>
          </div>
          <p className="border-t border-slate-100 pt-3 text-xs text-slate-500">
            AI detection can be wrong, especially on formal or non-native English. Never use it as the only reason for a decision.
          </p>
        </div>
      </aside>
    </div>
  );
}
