"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AIPanel } from "@/components/AIPanel";
import { Notice } from "@/components/AuthCard";
import { FlagsPanel } from "@/components/FlagsPanel";
import { ScanningView } from "@/components/ScanningView";
import { SimilarityPanel } from "@/components/SimilarityPanel";
import { api, ApiError, deleteTokenFor, forgetMyCheck, formatBytes, pctLabel, type Flag, type Submission, type SubmissionText } from "@/lib/api";

type Tab = "similarity" | "ai" | "flags";

function Gauge({ value, label, color, sub, active, onClick }: {
  value: number | null; label: string; color: string; sub?: string; active: boolean; onClick: () => void;
}) {
  const r = 34;
  const c = 2 * Math.PI * r;
  const v = value == null ? 0 : Math.min(100, Math.max(0, value));
  return (
    <button type="button" onClick={onClick}
      className={`flex items-center gap-4 rounded-2xl border p-4 text-left transition hover:-translate-y-0.5 ${active ? "border-transparent bg-white shadow-glow ring-2" : "border-slate-200 bg-white"}`}
      style={active ? { ["--tw-ring-color" as string]: color } : undefined}>
      <svg viewBox="0 0 80 80" className="h-20 w-20 -rotate-90">
        <circle cx="40" cy="40" r={r} fill="none" stroke="#eef0f6" strokeWidth="8" />
        <circle cx="40" cy="40" r={r} fill="none" stroke={color} strokeWidth="8" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - v / 100)} style={{ transition: "stroke-dashoffset 1s ease" }} />
      </svg>
      <div>
        <div className="font-display text-3xl font-bold" style={{ color }}>{value == null ? "n/a" : pctLabel(value)}</div>
        <div className="text-sm font-medium text-slate-700">{label}</div>
        {sub && <div className="text-xs text-slate-500">{sub}</div>}
      </div>
    </button>
  );
}

export default function SubmissionPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [sub, setSub] = useState<Submission | null>(null);
  const [text, setText] = useState<SubmissionText | null>(null);
  const [flags, setFlags] = useState<Flag[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("similarity");
  const [canDelete, setCanDelete] = useState(false);

  useEffect(() => setCanDelete(Boolean(deleteTokenFor(id))), [id]);

  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let haveText = false;
    async function tick() {
      try {
        const s = await api<Submission>(`/submissions/${id}`);
        if (stop) return;
        setSub(s);
        // The text is available as soon as the document has been read: show it being scanned.
        if (!haveText && s.status !== "queued" && s.stage !== "extracting") {
          const t = await api<SubmissionText>(`/submissions/${id}/text`).catch(() => null);
          if (t && !stop) {
            setText(t);
            haveText = true;
          }
        }
        if (s.status === "done") {
          const f = await api<Flag[]>(`/submissions/${id}/flags`);
          if (!haveText) setText(await api<SubmissionText>(`/submissions/${id}/text`));
          if (!stop) setFlags(f);
        } else if (s.status !== "failed") timer = setTimeout(tick, s.status === "queued" ? 3000 : 1500);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not load this check");
      }
    }
    void tick();
    return () => {
      stop = true;
      if (timer) clearTimeout(timer);
    };
  }, [id]);

  async function remove() {
    if (!confirm("Delete this check, its text and its report? This cannot be undone.")) return;
    try {
      await api(`/submissions/${id}`, { method: "DELETE", headers: { "X-Delete-Token": deleteTokenFor(id) ?? "" } });
      forgetMyCheck(id);
      router.replace("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Delete failed");
    }
  }

  if (error) return <div className="mx-auto max-w-6xl px-4 py-10"><Notice kind="error">{error}</Notice></div>;
  if (!sub) {
    return (
      <div className="mx-auto max-w-6xl space-y-4 px-4 py-10">
        <div className="skeleton h-8 w-1/3" />
        <div className="skeleton h-64 w-full" />
      </div>
    );
  }

  const busy = sub.status === "queued" || sub.status === "running";

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-8">
      <Link href="/" className="text-sm font-medium text-brand-700 hover:underline">← New check</Link>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-4">
          <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-brand-50 to-brand-100 text-2xl">📄</div>
          <div className="min-w-0">
            <h1 className="break-words text-2xl font-bold">{sub.original_filename}</h1>
            <p className="text-sm text-slate-500">
              {sub.file_type.toUpperCase()} · {formatBytes(sub.file_size)}
              {sub.word_count != null && <> · {sub.word_count.toLocaleString()} words</>}
              {sub.page_count != null && <> · {sub.page_count} page{sub.page_count === 1 ? "" : "s"}</>}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {sub.status === "done" && <a href={`/api/submissions/${sub.id}/report.pdf`} className="btn">⬇ Full report (PDF)</a>}
          {sub.status === "done" && <a href={`/api/submissions/${sub.id}/report.pdf?part=similarity`} className="btn-ghost">⬇ Similarity report</a>}
          {sub.status === "done" && sub.ai_available !== false && <a href={`/api/submissions/${sub.id}/report.pdf?part=ai`} className="btn-ghost">⬇ AI report</a>}
          {sub.status === "done" && <Link href={`/verify/${sub.id}`} className="btn-ghost">Verify</Link>}
          {canDelete && sub.status !== "running" && <button onClick={remove} className="btn-ghost text-red-600">Delete</button>}
        </div>
      </div>

      {busy && <ScanningView sub={sub} text={text?.clean_text ?? null} />}

      {sub.status === "failed" && <Notice kind="error">{sub.error ?? "This check failed."}</Notice>}

      {sub.status === "done" && (
        <div className="grid animate-fadeUp gap-4 sm:grid-cols-3">
          <Gauge value={sub.similarity_percent} label="Overall Similarity" color="#e8590c" active={tab === "similarity"} onClick={() => setTab("similarity")} />
          <Gauge value={sub.ai_available === false ? null : sub.ai_percent} label="Detected as AI" color="#3b4bd8"
            sub={sub.ai_available === false ? "Not enough English text" : undefined} active={tab === "ai"} onClick={() => setTab("ai")} />
          <button type="button" onClick={() => setTab("flags")}
            className={`flex items-center gap-4 rounded-2xl border p-4 text-left transition hover:-translate-y-0.5 ${tab === "flags" ? "border-transparent bg-white shadow-glow ring-2 ring-amber-400" : "border-slate-200 bg-white"}`}>
            <div className="flex h-20 w-20 items-center justify-center rounded-full bg-amber-50 font-display text-3xl font-bold text-amber-600">{sub.flags.length}</div>
            <div>
              <div className="text-sm font-medium text-slate-700">Integrity flags</div>
              <div className="text-xs text-slate-500">{sub.flags.length ? "Hidden text or tricks found" : "No tricks found"}</div>
            </div>
          </button>
        </div>
      )}

      {sub.status === "done" && text && tab === "similarity" && <SimilarityPanel submissionId={sub.id} text={text.clean_text} />}
      {sub.status === "done" && text && tab === "ai" && <AIPanel submissionId={sub.id} text={text.clean_text} />}
      {sub.status === "done" && flags && tab === "flags" && <FlagsPanel flags={flags} />}
    </div>
  );
}
