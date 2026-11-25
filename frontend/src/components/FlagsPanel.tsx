"use client";

import { useState } from "react";
import type { Flag } from "@/lib/api";

const LABELS: Record<string, { title: string; unit: string; help: string }> = {
  lookalike_characters: {
    title: "Look-alike characters",
    unit: "characters",
    help: "Letters from other alphabets (e.g. Cyrillic) that look like English letters. They were replaced with the normal letters before checking.",
  },
  invisible_characters: {
    title: "Invisible characters",
    unit: "characters",
    help: "Zero-width and similar characters that cannot be seen. They were removed before checking.",
  },
  hidden_text_vanish: {
    title: "Hidden text",
    unit: "characters",
    help: "Text marked as hidden in Word. It was left out of the check.",
  },
  hidden_text_color: {
    title: "Text the same colour as the background",
    unit: "characters",
    help: "For example white text on a white page. It was left out of the check.",
  },
  hidden_text_tiny: {
    title: "Tiny text (under 4 pt)",
    unit: "characters",
    help: "Text too small to read. It was left out of the check.",
  },
  text_outside_page: {
    title: "Text outside the page",
    unit: "characters",
    help: "Text placed where it cannot be seen. It was left out of the check.",
  },
  image_only_pages: {
    title: "Image-only pages",
    unit: "pages",
    help: "Pages with no text layer (scans or pictures of text). They were read with OCR.",
  },
};

function labelFor(type: string) {
  return LABELS[type] ?? { title: type, unit: "items", help: "" };
}

export function FlagsPanel({ flags }: { flags: Flag[] }) {
  const [open, setOpen] = useState<string | null>(null);

  if (flags.length === 0) {
    return (
      <div className="card">
        <h2 className="text-lg font-semibold">Integrity flags</h2>
        <p className="mt-2 text-sm text-slate-600">No hidden text or character tricks were found.</p>
      </div>
    );
  }

  return (
    <div className="card">
      <h2 className="text-lg font-semibold">Integrity flags</h2>
      <p className="mb-4 mt-1 text-sm text-slate-600">
        These were found in the file and cleaned before checking. A flag needs a person to review it; it is not proof of
        cheating on its own.
      </p>
      <ul className="divide-y divide-slate-100">
        {flags.map((f) => {
          const l = labelFor(f.type);
          const isOpen = open === f.type;
          return (
            <li key={f.type} className="py-3">
              <button
                type="button"
                onClick={() => setOpen(isOpen ? null : f.type)}
                className="flex w-full items-center justify-between gap-4 text-left"
                aria-expanded={isOpen}
              >
                <span className="font-medium text-slate-800">{l.title}</span>
                <span className="shrink-0 rounded-full bg-accent/20 px-2.5 py-0.5 text-sm font-semibold text-amber-800">
                  {f.count.toLocaleString()} {l.unit}
                </span>
              </button>
              {isOpen && (
                <div className="mt-2 space-y-2">
                  <p className="text-xs text-slate-500">{l.help}</p>
                  <ul className="space-y-1 text-sm">
                    {f.locations.slice(0, 50).map((loc, i) => (
                      <li key={i} className="rounded-md bg-slate-50 px-3 py-1.5">
                        <span className="text-xs text-slate-500">Page {loc.page}</span>
                        {loc.text && (
                          <span dir="auto" className="ml-2 font-mono text-xs text-slate-800">
                            “{loc.text}”
                          </span>
                        )}
                        {loc.detail && <span className="ml-2 text-xs text-slate-500">→ {loc.detail}</span>}
                      </li>
                    ))}
                    {f.locations.length > 50 && (
                      <li className="text-xs text-slate-500">…and {f.locations.length - 50} more places</li>
                    )}
                  </ul>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
