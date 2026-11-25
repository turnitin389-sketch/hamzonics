"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Notice } from "@/components/AuthCard";
import { api, ApiError, pctLabel } from "@/lib/api";

type Info = {
  submission_id: string;
  submitted_at: string;
  report_created_at: string;
  word_count: number | null;
  similarity_percent: number | null;
  ai_percent: number | null;
  engine_version: string;
  pages: number;
  sha256: string;
};

type Result = { authentic: boolean; message: string };

export default function VerifyPage() {
  const { id } = useParams<{ id: string }>();
  const [info, setInfo] = useState<Info | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<Info>(`/verify/${id}`)
      .then(setInfo)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load this report"));
  }, [id]);

  async function check(file: File) {
    setBusy(true);
    setResult(null);
    const form = new FormData();
    form.set("file", file);
    try {
      // Public endpoint: plain fetch (no session, no CSRF token needed).
      const res = await fetch(`/api/verify/${id}`, { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new ApiError(res.status, data?.detail ?? "Check failed");
      setResult(data as Result);
    } catch (err) {
      setResult({ authentic: false, message: err instanceof ApiError ? err.message : "Check failed" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6 px-4 py-10">
      <div className="card space-y-4">
        <h1 className="text-xl font-semibold">Verify a report</h1>
        {error && <Notice kind="error">{error}</Notice>}
        {info && (
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <dt className="text-slate-500">Submission ID</dt>
            <dd className="break-all font-mono text-xs">{info.submission_id}</dd>
            <dt className="text-slate-500">Submitted</dt>
            <dd>{new Date(info.submitted_at).toLocaleString()}</dd>
            <dt className="text-slate-500">Report created</dt>
            <dd>{new Date(info.report_created_at).toLocaleString()}</dd>
            <dt className="text-slate-500">Words</dt>
            <dd>{info.word_count?.toLocaleString() ?? "–"}</dd>
            <dt className="text-slate-500">Similarity</dt>
            <dd className="font-semibold">{info.similarity_percent != null ? `${info.similarity_percent}%` : "–"}</dd>
            <dt className="text-slate-500">AI writing</dt>
            <dd className="font-semibold">{pctLabel(info.ai_percent)}</dd>
            <dt className="text-slate-500">Pages</dt>
            <dd>{info.pages}</dd>
            <dt className="text-slate-500">Engine</dt>
            <dd className="font-mono text-xs">{info.engine_version}</dd>
          </dl>
        )}
      </div>

      {info && (
        <div className="card space-y-3">
          <h2 className="font-semibold">Is my PDF genuine?</h2>
          <p className="text-sm text-slate-600">
            Choose the PDF report you received. It is compared byte by byte with the report we issued; nothing is stored.
          </p>
          <input
            type="file"
            accept="application/pdf,.pdf"
            className="input"
            disabled={busy}
            onChange={(e) => e.target.files?.[0] && check(e.target.files[0])}
          />
          {busy && <p className="text-sm text-slate-500">Checking…</p>}
          {result && <Notice kind={result.authentic ? "ok" : "error"}>{result.message}</Notice>}
        </div>
      )}
    </div>
  );
}
