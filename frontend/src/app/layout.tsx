import type { Metadata } from "next";
import { Inter, Lexend } from "next/font/google";
import Link from "next/link";
import { Logo } from "@/components/Logo";
import { BRAND_NAME } from "@/lib/brand";
import "./globals.css";

const sans = Inter({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const display = Lexend({ subsets: ["latin"], variable: "--font-display", display: "swap" });

export const metadata: Metadata = {
  title: `${BRAND_NAME} – Plagiarism & AI-writing checker`,
  description: "Check documents for plagiarism and AI writing. Highlighted sources, AI detection and a full PDF report.",
  icons: {
    icon: [
      { url: "/favicon.png?v=2", type: "image/png" },
      { url: "/favicon.ico?v=2", type: "image/x-icon" },
    ],
    shortcut: "/favicon.ico?v=2",
    apple: "/favicon.png?v=2",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${display.variable}`}>
      <body className="min-h-screen font-sans">
        <header className="sticky top-0 z-30 border-b border-slate-200/70 bg-white/80 backdrop-blur-lg">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
            <Link href="/" className="flex items-center gap-2 font-display text-xl font-bold tracking-tight text-ink-900">
              <Logo className="h-8 w-auto" />
            </Link>
            <nav className="hidden items-center gap-7 text-sm font-medium text-slate-600 md:flex">
              <Link href="/#features" className="hover:text-ink-900">Features</Link>
              <Link href="/#how" className="hover:text-ink-900">How it works</Link>
              <Link href="/#faq" className="hover:text-ink-900">FAQ</Link>
            </nav>
            <Link href="/#check" className="btn whitespace-nowrap px-3 py-2 sm:px-4">New check</Link>
          </div>
        </header>
        <main>{children}</main>
        <footer className="mt-20 border-t border-slate-200 bg-white">
          <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-3 px-4 py-8 text-sm text-slate-500 md:flex-row">
            <div className="flex items-center gap-2 font-display font-semibold text-ink-900"><Logo className="h-6 w-auto" /></div>
            <p className="text-center">Results are estimates and should be reviewed by a person. Checks are deleted automatically after 30 days.</p>
            <p className="text-center text-xs">
              © {new Date().getFullYear()} {BRAND_NAME} · AI detection uses open models by{" "}
              <a className="underline" href="https://huggingface.co/fakespot-ai/roberta-base-ai-text-detection-v1" rel="noopener" target="_blank">Fakespot</a> and{" "}
              <a className="underline" href="https://huggingface.co/SuperAnnotate/ai-detector" rel="noopener" target="_blank">SuperAnnotate</a>{" "}
              (<a className="underline" href="https://huggingface.co/SuperAnnotate/ai-detector/blob/main/LICENSE" rel="noopener" target="_blank">SAIPL licence</a>, unmodified)
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
