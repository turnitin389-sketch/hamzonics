"use client";

import { useCallback, useEffect, useState } from "react";
import { Notice } from "@/components/AuthCard";

type Key = {
  id: string;
  provider: string;
  label: string;
  masked: string;
  status: "in use" | "waiting" | "used up" | "disabled" | "cannot decrypt" | string;
  last_error: string | null;
  searches_used: number;
  last_used_at: string | null;
  created_at: string;
};
type Stats = {
  checks_total: number;
  checks_last_24h: number;
  running: number;
  queued: number;
  failed: number;
  searches_used_total: number;
  searches_cached: number;
  usable_keys: number;
  env_key_configured: boolean;
};

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("X-Requested-With", "hamzonics");
  if (init.body) headers.set("Content-Type", "application/json");
  const res = await fetch(`/api/admin${path}`, { ...init, headers, credentials: "same-origin", cache: "no-store" });
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) throw Object.assign(new Error(data?.detail ?? `Request failed (${res.status})`), { status: res.status });
  return data as T;
}

const BADGE: Record<string, string> = {
  "in use": "bg-green-100 text-green-800",
  waiting: "bg-slate-100 text-slate-700",
  "used up": "bg-red-100 text-red-700",
  disabled: "bg-slate-200 text-slate-500",
  "cannot decrypt": "bg-amber-100 text-amber-800",
};

export default function AdminPage() {
  const [state, setState] = useState<"loading" | "login" | "ready" | "disabled">("loading");
  const [password, setPassword] = useState("");
  const [keys, setKeys] = useState<Key[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [newKeys, setNewKeys] = useState("");
  const [label, setLabel] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [k, s] = await Promise.all([call<Key[]>("/keys"), call<Stats>("/stats")]);
      setKeys(k);
      setStats(s);
      setState("ready");
    } catch (e) {
      const status = (e as { status?: number }).status;
      setState(status === 404 ? "disabled" : "login");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(fn: () => Promise<Key[] | unknown>) {
    setError(null);
    setBusy(true);
    try {
      const r = await fn();
      if (Array.isArray(r)) setKeys(r as Key[]);
      setStats(await call<Stats>("/stats"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function login(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await call("/login", { method: "POST", body: JSON.stringify({ password }) });
      setPassword("");
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (state === "loading") return <p className="mx-auto max-w-6xl px-4 py-10 text-sm text-slate-500">Loading…</p>;
  if (state === "disabled")
    return <div className="mx-auto max-w-6xl px-4 py-10"><Notice kind="error">The admin portal is switched off. Set ADMIN_PASSWORD in the server settings to use it.</Notice></div>;
  if (state === "login")
    return (
      <form onSubmit={login} className="card mx-auto my-16 max-w-sm space-y-4">
        <h1 className="text-xl font-semibold">Admin login</h1>
        {error && <Notice kind="error">{error}</Notice>}
        <input type="password" className="input" placeholder="Admin password" value={password}
          onChange={(e) => setPassword(e.target.value)} autoFocus />
        <button className="btn w-full">Log in</button>
      </form>
    );

  const live = keys.filter((k) => k.status === "in use" || k.status === "waiting").length;

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Admin</h1>
        <button className="btn-ghost" onClick={() => run(async () => { await call("/logout", { method: "POST" }); setState("login"); })}>Log out</button>
      </div>
      {error && <Notice kind="error">{error}</Notice>}

      {stats && (
        <div className="grid gap-3 sm:grid-cols-4">
          {[
            ["Checks (24 h)", stats.checks_last_24h],
            ["Running / waiting", `${stats.running} / ${stats.queued}`],
            ["Searches used (all keys)", stats.searches_used_total],
            ["Searches saved by cache", stats.searches_cached],
          ].map(([t, v]) => (
            <div key={String(t)} className="card p-4">
              <div className="text-2xl font-bold">{v}</div>
              <div className="text-xs text-slate-500">{t}</div>
            </div>
          ))}
        </div>
      )}

      {live === 0 && !stats?.env_key_configured && (
        <Notice kind="error">No working search key: Internet sources are not searched until you add a key below.</Notice>
      )}

      <div className="card space-y-3">
        <h2 className="font-semibold">Add Serper API keys</h2>
        <p className="text-sm text-slate-600">
          Paste one or more keys (one per line). They are used in the order shown below; when a key runs out of credits
          the next one is used automatically. Keys are stored encrypted and never shown again in full.
        </p>
        <textarea rows={4} className="input font-mono" placeholder={"key 1\nkey 2\n..."} value={newKeys}
          onChange={(e) => setNewKeys(e.target.value)} />
        <div className="flex flex-wrap gap-2">
          <input className="input max-w-xs" placeholder="Label (optional), e.g. Account 3" value={label}
            onChange={(e) => setLabel(e.target.value)} />
          <button className="btn" disabled={busy || !newKeys.trim()}
            onClick={() => run(async () => { const r = await call<Key[]>("/keys", { method: "POST", body: JSON.stringify({ keys: newKeys, label }) }); setNewKeys(""); setLabel(""); return r; })}>
            Add keys
          </button>
        </div>
      </div>

      <div className="card overflow-x-auto p-0">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-slate-600">
            <tr>
              <th className="px-4 py-2 font-medium">#</th>
              <th className="px-4 py-2 font-medium">Key</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium">Searches used</th>
              <th className="px-4 py-2 font-medium">Last used</th>
              <th className="px-4 py-2 font-medium"></th>
            </tr>
          </thead>
          <tbody>
            {keys.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-4 text-slate-500">No keys yet.{stats?.env_key_configured ? " (The key in the server settings is used.)" : ""}</td></tr>
            )}
            {keys.map((k, i) => (
              <tr key={k.id} className="border-b border-slate-100 align-top last:border-0">
                <td className="px-4 py-2">{i + 1}</td>
                <td className="px-4 py-2">
                  <div className="font-medium">{k.label}</div>
                  <div className="font-mono text-xs text-slate-500">{k.masked}</div>
                  {k.last_error && <div className="text-xs text-red-600">{k.last_error}</div>}
                </td>
                <td className="px-4 py-2"><span className={`rounded-full px-2 py-0.5 text-xs font-medium ${BADGE[k.status] ?? ""}`}>{k.status}</span></td>
                <td className="px-4 py-2">{k.searches_used.toLocaleString()}</td>
                <td className="px-4 py-2 text-xs text-slate-500">{k.last_used_at ? new Date(k.last_used_at).toLocaleString() : "–"}</td>
                <td className="whitespace-nowrap px-4 py-2 text-xs">
                  <button className="mr-2 hover:underline" disabled={busy || i === 0} onClick={() => run(() => call(`/keys/${k.id}`, { method: "PATCH", body: JSON.stringify({ move: "up" }) }))}>↑</button>
                  <button className="mr-3 hover:underline" disabled={busy || i === keys.length - 1} onClick={() => run(() => call(`/keys/${k.id}`, { method: "PATCH", body: JSON.stringify({ move: "down" }) }))}>↓</button>
                  {k.status === "used up" && (
                    <button className="mr-3 text-brand-700 hover:underline" onClick={() => run(() => call(`/keys/${k.id}`, { method: "PATCH", body: JSON.stringify({ reset: true }) }))}>Reset</button>
                  )}
                  <button className="mr-3 hover:underline" onClick={() => run(() => call(`/keys/${k.id}`, { method: "PATCH", body: JSON.stringify({ active: k.status === "disabled" }) }))}>
                    {k.status === "disabled" ? "Enable" : "Disable"}
                  </button>
                  <button className="text-red-600 hover:underline" onClick={() => confirm("Delete this key?") && run(() => call(`/keys/${k.id}`, { method: "DELETE" }))}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-slate-500">
        Each check uses at most 12 searches, and none for text that is already found or was searched in the last 30 days.
      </p>
    </div>
  );
}
