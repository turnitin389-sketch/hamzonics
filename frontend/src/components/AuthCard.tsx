export function Notice({ kind, children }: { kind: "error" | "ok"; children: React.ReactNode }) {
  const cls = kind === "error" ? "border-red-200 bg-red-50 text-red-700" : "border-brand-100 bg-brand-50 text-brand-700";
  return <p className={`mb-4 rounded-lg border px-3 py-2 text-sm ${cls}`}>{children}</p>;
}
