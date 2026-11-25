"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Notice } from "@/components/AuthCard";
import { ProgressBar, StatusBadge } from "@/components/StatusBadge";
import {
  api,
  ApiError,
  formatBytes,
  loadMyChecks,
  newIdempotencyKey,
  pctLabel,
  saveMyCheck,
  type MyCheck,
  type QueueStatus,
  type Submission,
} from "@/lib/api";

const ACCEPT = ".pdf,.docx,.odt,.rtf,.txt";

const FEATURES = [
  { icon: "🔍", title: "Plagiarism with sources", text: "Every copied sentence is highlighted and linked to the web page or paper it came from, with numbered, colour-coded sources." },
  { icon: "🤖", title: "AI-writing detection", text: "Finds text written by ChatGPT, Gemini, Llama and other models, sentence by sentence, even in documents that are only partly AI." },
  { icon: "📄", title: "Professional PDF report", text: "Download a full report with match groups, top sources and highlighted pages. A QR code lets anyone confirm it is genuine." },
  { icon: "🕵️", title: "Hidden-trick detection", text: "Catches white text, tiny fonts, invisible characters and look-alike letters that students use to fool checkers." },
  { icon: "🌐", title: "Urdu & translation", text: "Recognises Urdu text that was translated from English sources." },
  { icon: "🔒", title: "Private by design", text: "No account needed. Only you get the link to your report, and checks are deleted after 30 days." },
];

const STEPS = [
  { n: "1", title: "Upload", text: "PDF, Word, ODT, RTF or plain text, up to 25 MB." },
  { n: "2", title: "We scan", text: "The text is compared with the web and checked for AI writing. You see it being scanned live." },
  { n: "3", title: "Get the report", text: "Read it online or download the PDF report in a few minutes." },
];

const FAQ = [
  { q: "How accurate is the AI detection?", a: "In our tests it detected 100% of plain ChatGPT, GPT-4 and Llama text and wrongly flagged about 1 in 100 human texts. Text that was heavily rewritten with paraphrasing tools is harder to detect. Always review the highlighted parts yourself." },
  { q: "Why can my score differ from other checkers?", a: "Every checker searches different sources and uses a different AI model. Use the highlights and sources to judge each match." },
  { q: "Is my document stored?", a: "Your file is deleted as soon as the check finishes; the report is deleted after 30 days. If you allow it, the text is kept in our comparison library so copies of it can be found later (others never see your file name)." },
];

export default function HomePage() {
  const router = useRouter();
  const [mode, setMode] = useState<"file" | "text">("file");
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [optIn, setOptIn] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [queue, setQueue] = useState<QueueStatus | null>(null);
  const [mine, setMine] = useState<MyCheck[]>([]);
  const [status, setStatus] = useState<Record<string, Submission | "gone">>({});
  const keyRef = useRef(newIdempotencyKey());

  const refresh = useCallback(async () => {
    setQueue(await api<QueueStatus>("/queue").catch(() => null));
    const list = loadMyChecks();
    setMine(list);
    const entries = await Promise.all(
      list.slice(0, 15).map(async (c) => {
        try {
          return [c.id, await api<Submission>(`/submissions/${c.id}`)] as const;
        } catch (err) {
          return [c.id, err instanceof ApiError && err.status === 404 ? ("gone" as const) : null] as const;
        }
      }),
    );
    setStatus(Object.fromEntries(entries.filter(([, v]) => v != null)) as Record<string, Submission | "gone">);
  }, []);

  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), 5000);
    return () => clearInterval(t);
  }, [refresh]);

  const words = text.trim() ? text.trim().split(/\s+/).length : 0;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const form = new FormData();
    form.set("idempotency_key", keyRef.current);
    form.set("repository_opt_in", String(optIn));
    if (mode === "file") {
      if (!file) return setError("Choose a file first.");
      if (file.size > 25 * 1024 * 1024) return setError("The file is larger than 25 MB.");
      form.set("file", file);
    } else {
      if (words < 20) return setError("Paste at least 20 words.");
      form.set("text", text);
    }
    setBusy(true);
    try {
      const sub = await api<Submission>("/submissions", { method: "POST", body: form });
      saveMyCheck({ id: sub.id, filename: sub.original_filename, created_at: sub.created_at, delete_token: sub.delete_token });
      keyRef.current = newIdempotencyKey();
      router.push(`/submissions/${sub.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files?.[0];
    if (f) {
      setMode("file");
      setFile(f);
    }
  }

  return (
    <div>
      {/* Hero */}
      <section className="relative overflow-hidden bg-ink-900">
        <div className="absolute inset-0 animate-gradient bg-[length:200%_200%] bg-gradient-to-br from-ink-900 via-brand-900 to-[#012a32] opacity-95" />
        <div className="absolute -left-24 top-10 h-72 w-72 rounded-full bg-brand-500/30 blur-3xl" />
        <div className="absolute -right-16 bottom-0 h-72 w-72 rounded-full bg-accent-500/25 blur-3xl" />
        <div className="relative mx-auto max-w-6xl px-4 pb-40 pt-16 text-center text-white md:pt-24">
          <div className="mb-5 flex flex-wrap justify-center gap-2">
            <span className="chip">✓ No sign-up</span>
            <span className="chip">✓ Plagiarism + AI in one report</span>
            <span className="chip">✓ Results in minutes</span>
          </div>
          <h1 className="mx-auto max-w-3xl text-4xl font-bold leading-tight md:text-6xl">
            Check for <span className="bg-gradient-to-r from-accent-400 to-[#66d4ff] bg-clip-text text-transparent">plagiarism</span> and{" "}
            <span className="bg-gradient-to-r from-[#5ecfff] to-[#a8e8ff] bg-clip-text text-transparent">AI writing</span>
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-lg text-slate-300">
            Upload a paper, thesis or essay. Get a detailed report with highlighted sources, AI-written passages and a downloadable PDF.
          </p>
        </div>
      </section>

      {/* Upload card */}
      <section id="check" className="relative z-10 mx-auto -mt-32 max-w-3xl px-4">
        <form onSubmit={submit} className="card space-y-5 p-6 shadow-2xl md:p-8">
          {error && <Notice kind="error">{error}</Notice>}
          <div className="grid grid-cols-2 rounded-xl bg-slate-100 p-1 text-sm font-semibold">
            {(["file", "text"] as const).map((m) => (
              <button key={m} type="button" onClick={() => setMode(m)}
                className={`rounded-lg py-2 transition ${mode === m ? "bg-white text-ink-900 shadow" : "text-slate-500 hover:text-slate-700"}`}>
                {m === "file" ? "Upload a file" : "Paste text"}
              </button>
            ))}
          </div>

          {mode === "file" ? (
            <label
              htmlFor="file"
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              className={`group flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-4 py-12 text-center transition ${
                dragging ? "border-brand-500 bg-brand-50" : file ? "border-green-400 bg-green-50/50" : "border-slate-300 hover:border-brand-500 hover:bg-brand-50/40"
              }`}
            >
              <div className={`mb-3 flex h-14 w-14 items-center justify-center rounded-2xl text-2xl transition ${file ? "bg-green-100" : "bg-brand-100 group-hover:scale-110"}`}>
                {file ? "📄" : "⬆️"}
              </div>
              <span className="text-base font-semibold text-ink-900">{file ? file.name : "Drop your document here, or click to browse"}</span>
              <span className="mt-1 text-xs text-slate-500">
                {file ? `${formatBytes(file.size)} · ready to check` : "PDF, DOCX, ODT, RTF or TXT · up to 25 MB · up to 50,000 words"}
              </span>
              <input id="file" type="file" accept={ACCEPT} className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </label>
          ) : (
            <div>
              <textarea rows={10} className="input resize-y leading-relaxed" value={text} onChange={(e) => setText(e.target.value)}
                placeholder="Paste the text you want to check…" />
              <div className="mt-1 text-right text-xs text-slate-500">{words.toLocaleString()} words</div>
            </div>
          )}

          <label className="flex items-start gap-3 text-sm text-slate-700">
            <input type="checkbox" className="mt-0.5 h-4 w-4 accent-brand-600" checked={optIn} onChange={(e) => setOptIn(e.target.checked)} />
            <span>
              Add my document to the comparison library
              <span className="block text-xs text-slate-500">So later copies of it are found. Others only see matching sentences, never your file name.</span>
            </span>
          </label>

          <div className="flex flex-col items-center gap-3 sm:flex-row sm:justify-between">
            <button className="btn w-full px-8 py-3 text-base sm:w-auto" disabled={busy}>
              {busy ? (
                <><span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" /> Uploading…</>
              ) : (
                <>Check document <span aria-hidden>→</span></>
              )}
            </button>
            {queue && (
              <span className="flex items-center gap-2 text-sm text-slate-500">
                <span className="relative flex h-2.5 w-2.5">
                  <span className="absolute inline-flex h-full w-full animate-ping2 rounded-full bg-green-400" />
                  <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-green-500" />
                </span>
                {queue.running} of {queue.max_concurrent} checking now · {queue.queued} waiting
              </span>
            )}
          </div>
        </form>
      </section>

      {mine.length > 0 && (
        <section className="mx-auto mt-10 max-w-3xl px-4">
          <h2 className="mb-3 text-lg font-semibold">Your recent checks <span className="text-xs font-normal text-slate-500">(this browser only)</span></h2>
          <div className="card divide-y divide-slate-100 p-0">
            {mine.map((c) => {
              const s = status[c.id];
              if (s === "gone") return null;
              return (
                <Link key={c.id} href={`/submissions/${c.id}`} className="flex items-center gap-4 px-5 py-3 transition hover:bg-slate-50">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-lg">📄</div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium text-ink-900">{c.filename}</div>
                    <div className="text-xs text-slate-500">{new Date(c.created_at).toLocaleString()}</div>
                  </div>
                  {s && s.status === "done" ? (
                    <div className="flex gap-4 text-right text-sm">
                      <div><div className="font-bold text-accent-600">{pctLabel(s.similarity_percent)}</div><div className="text-[11px] text-slate-500">similarity</div></div>
                      <div><div className="font-bold text-brand-600">{s.ai_available === false ? "n/a" : pctLabel(s.ai_percent)}</div><div className="text-[11px] text-slate-500">AI</div></div>
                    </div>
                  ) : s ? (
                    <div className="w-28"><StatusBadge status={s.status} />{(s.status === "running" || s.status === "queued") && <div className="mt-1"><ProgressBar value={s.progress} /></div>}</div>
                  ) : null}
                </Link>
              );
            })}
          </div>
        </section>
      )}

      {/* Features */}
      <section id="features" className="mx-auto mt-20 max-w-6xl px-4">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-bold md:text-4xl">Everything in one report</h2>
          <p className="mt-3 text-slate-600">Built for teachers, students and journals that need a clear answer, not just a number.</p>
        </div>
        <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f, i) => (
            <div key={f.title} className="card animate-fadeUp transition hover:-translate-y-1 hover:shadow-glow" style={{ animationDelay: `${i * 60}ms` }}>
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-brand-50 to-brand-100 text-2xl">{f.icon}</div>
              <h3 className="text-lg font-semibold">{f.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">{f.text}</p>
            </div>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section id="how" className="mx-auto mt-20 max-w-6xl px-4">
        <div className="rounded-3xl bg-gradient-to-br from-ink-900 to-brand-900 px-6 py-12 text-white md:px-12">
          <h2 className="text-center text-3xl font-bold">How it works</h2>
          <div className="mt-10 grid gap-8 md:grid-cols-3">
            {STEPS.map((s) => (
              <div key={s.n} className="text-center">
                <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br from-accent-400 to-accent-600 font-display text-lg font-bold shadow-lg">{s.n}</div>
                <h3 className="text-lg font-semibold">{s.title}</h3>
                <p className="mt-2 text-sm text-slate-300">{s.text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section id="faq" className="mx-auto mt-20 max-w-3xl px-4">
        <h2 className="text-center text-3xl font-bold">Questions</h2>
        <div className="mt-8 space-y-3">
          {FAQ.map((f) => (
            <details key={f.q} className="card group p-5 open:shadow-glow">
              <summary className="flex cursor-pointer list-none items-center justify-between font-semibold">
                {f.q}<span className="ml-4 text-brand-600 transition group-open:rotate-45">+</span>
              </summary>
              <p className="mt-3 text-sm leading-relaxed text-slate-600">{f.a}</p>
            </details>
          ))}
        </div>
      </section>
    </div>
  );
}
