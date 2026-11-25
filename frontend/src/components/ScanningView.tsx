"use client";

import { useEffect, useMemo, useState } from "react";
import type { Submission } from "@/lib/api";

const STEPS = [
  { key: "upload", label: "Document received" },
  { key: "read", label: "Reading the document" },
  { key: "search", label: "Searching the web for sources" },
  { key: "compare", label: "Comparing with sources" },
  { key: "ai", label: "Detecting AI writing" },
  { key: "report", label: "Building your report" },
] as const;

const MESSAGES: Record<string, string[]> = {
  queued: ["Waiting for a free checking slot…", "Up to 3 documents are checked at the same time…", "Your check starts automatically…"],
  read: ["Extracting the text from your file…", "Looking for hidden text and invisible characters…", "Counting words and pages…"],
  search: ["Picking the most distinctive sentences…", "Searching Google for matching pages…", "Downloading possible sources…"],
  compare: ["Comparing your sentences with every source…", "Grouping matches: quoted, cited, not cited…", "Calculating the similarity score…"],
  ai: ["Reading paragraph by paragraph…", "Scoring each passage for AI-writing patterns…", "Combining the paragraph scores…"],
  report: ["Highlighting the matches…", "Building the PDF report…", "Almost done…"],
};

function currentStep(sub: Submission): number {
  if (sub.status === "queued") return 0;
  if (sub.status === "done") return STEPS.length;
  if (sub.stage === "extracting") return 1;
  if (sub.stage === "extracted") return 2;
  if (sub.stage === "similarity") return sub.progress < 62 ? 2 : 3;
  if (sub.stage === "ai") return sub.progress >= 94 ? 5 : 4;
  return 1;
}

function fmtTime(s: number): string {
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

function Ring({ value }: { value: number }) {
  const r = 52;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative h-36 w-36">
      <svg viewBox="0 0 120 120" className="h-full w-full -rotate-90">
        <defs>
          <linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#4f63f0" />
            <stop offset="100%" stopColor="#f26b1d" />
          </linearGradient>
        </defs>
        <circle cx="60" cy="60" r={r} fill="none" stroke="#e8ebf5" strokeWidth="10" />
        <circle cx="60" cy="60" r={r} fill="none" stroke="url(#ringGrad)" strokeWidth="10" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - value / 100)} style={{ transition: "stroke-dashoffset .8s ease" }} />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-display text-3xl font-bold text-ink-900">{value}%</span>
        <span className="text-[11px] font-medium uppercase tracking-wider text-slate-500">complete</span>
      </div>
    </div>
  );
}

export function ScanningView({ sub, text }: { sub: Submission; text: string | null }) {
  const step = currentStep(sub);
  const stepKey = sub.status === "queued" ? "queued" : STEPS[Math.min(step, STEPS.length - 1)]!.key;
  const [tick, setTick] = useState(0);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const t = setInterval(() => setTick((x) => x + 1), 140);
    const e = setInterval(() => {
      const start = sub.started_at ?? sub.created_at;
      setElapsed(Math.max(0, Math.round((Date.now() - new Date(start).getTime()) / 1000)));
    }, 1000);
    return () => {
      clearInterval(t);
      clearInterval(e);
    };
  }, [sub.started_at, sub.created_at]);

  // The document as short lines (like a page), for the scanning animation.
  const lines = useMemo(() => {
    if (!text) return [];
    const out: string[] = [];
    // Blank lines separate paragraphs; single line breaks (text copied from a PDF) are joined.
    for (const para of text.split(/\n\s*\n/).map((p) => p.replace(/\s*\n\s*/g, " "))) {
      const words = para.trim().split(/\s+/).filter(Boolean);
      for (let i = 0; i < words.length; i += 11) out.push(words.slice(i, i + 11).join(" "));
      if (words.length) out.push("");
    }
    return out.slice(0, 400);
  }, [text]);

  // The "reading position" moves forward continuously inside the current stage.
  const span = Math.max(lines.length, 1);
  const stageStart = { read: 0, search: 0, compare: 0.15, ai: 0, report: 0.85 }[stepKey as string] ?? 0;
  const pos = lines.length ? Math.floor((stageStart * span + tick * 0.35) % span) : 0;
  const LINE_H = 26;
  const messages = MESSAGES[stepKey] ?? MESSAGES.read!;
  const message = messages[Math.floor(tick / 18) % messages.length];

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
      {/* The paper being scanned */}
      <div className="card relative overflow-hidden p-0">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-ink-900">
            <span className="relative flex h-2.5 w-2.5">
              <span className="absolute inline-flex h-full w-full animate-ping2 rounded-full bg-accent-400" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-accent-500" />
            </span>
            {sub.status === "queued" ? "Waiting to start" : "Live scan"}
          </div>
          <span className="font-mono text-xs text-slate-500">{fmtTime(elapsed)}</span>
        </div>
        <div className="relative h-[440px] overflow-hidden bg-gradient-to-b from-white to-slate-50">
          {lines.length ? (
            <div className="absolute inset-x-0 px-8 font-serif text-[14.5px] text-slate-700"
              style={{ top: 180 - pos * LINE_H, transition: "top .14s linear" }}>
              {lines.map((line, i) => {
                const done = i < pos;
                const current = i === pos;
                return (
                  <div key={i} style={{ height: LINE_H, lineHeight: `${LINE_H}px` }}
                    className={`truncate rounded px-1 transition-colors duration-300 ${
                      current ? "bg-accent-400/25 text-ink-900" : done ? (i % 7 === 3 ? "bg-rose-100/70" : "bg-emerald-50") : ""
                    }`}>
                    {line || " "}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="space-y-4 p-8">
              <div className="skeleton h-5 w-2/3" />
              {Array.from({ length: 14 }).map((_, i) => (
                <div key={i} className="skeleton h-3" style={{ width: `${70 + ((i * 37) % 30)}%` }} />
              ))}
            </div>
          )}
          {sub.status !== "queued" && <div className="scan-beam" />}
          <div className="pointer-events-none absolute inset-x-0 top-0 h-16 bg-gradient-to-b from-white to-transparent" />
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-slate-50 to-transparent" />
        </div>
        <div className="flex items-center gap-4 border-t border-slate-100 px-5 py-3 text-xs text-slate-500">
          <span className="flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm bg-emerald-100" /> checked</span>
          <span className="flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm bg-accent-400/40" /> reading now</span>
          {sub.word_count != null && <span className="ml-auto">{sub.word_count.toLocaleString()} words</span>}
        </div>
      </div>

      {/* Progress panel */}
      <div className="card flex flex-col items-center gap-5">
        {sub.status === "queued" ? (
          <div className="flex flex-col items-center py-4 text-center">
            <div className="relative mb-4 flex h-28 w-28 items-center justify-center">
              <span className="absolute h-20 w-20 animate-ping2 rounded-full bg-brand-200" />
              <span className="relative flex h-24 w-24 items-center justify-center rounded-full bg-gradient-to-br from-brand-600 to-brand-500 font-display text-4xl font-bold text-white shadow-glow">
                {sub.queue_position ?? "…"}
              </span>
            </div>
            <div className="font-semibold text-ink-900">Your place in the queue</div>
            <p className="mt-1 text-sm text-slate-500">Up to 3 documents are checked at the same time. Yours starts automatically.</p>
          </div>
        ) : (
          <Ring value={sub.progress} />
        )}

        <div key={message} className="min-h-[20px] animate-fadeUp text-center text-sm font-medium text-brand-700">{message}</div>

        <ol className="w-full space-y-1">
          {STEPS.map((s, i) => {
            const state = i < step ? "done" : i === step && sub.status !== "queued" ? "active" : "todo";
            return (
              <li key={s.key} className={`flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition ${state === "active" ? "bg-brand-50" : ""}`}>
                <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                  state === "done" ? "bg-emerald-500 text-white" : state === "active" ? "bg-white ring-2 ring-brand-500" : "bg-slate-100 text-slate-400"}`}>
                  {state === "done" ? "✓" : state === "active" ? <span className="h-3 w-3 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" /> : i + 1}
                </span>
                <span className={state === "todo" ? "text-slate-400" : state === "active" ? "font-semibold text-ink-900" : "text-slate-700"}>{s.label}</span>
              </li>
            );
          })}
        </ol>
        <p className="text-center text-xs text-slate-500">You can leave this page: the check keeps running. Bookmark it to come back.</p>
      </div>
    </div>
  );
}
