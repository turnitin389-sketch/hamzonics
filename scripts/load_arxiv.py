"""Download arXiv abstracts (metadata is CC0) into a JSONL corpus file.

Usage:
  python -m scripts.load_arxiv --query "cat:cs.CL" --max 100
  python -m scripts.load_arxiv --query "all:climate AND all:agriculture" --max 200
Appends to corpus/arxiv/sample.jsonl (existing URLs skipped); then run scripts.index_corpus.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx

ATOM = "{http://www.w3.org/2005/Atom}"
USER_AGENT = "HamzonicsCorpusLoader/0.1 (self-hosted document similarity checker)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--query", default="cat:cs.CL")
    ap.add_argument("--max", type=int, default=100)
    ap.add_argument("--out", type=Path, default=Path("corpus/arxiv/sample.jsonl"))
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    if args.out.exists():
        seen = {json.loads(line)["url"] for line in args.out.read_text(encoding="utf-8").splitlines() if line}

    added = 0
    with httpx.Client(timeout=60, headers={"User-Agent": USER_AGENT}) as client, args.out.open("a", encoding="utf-8") as fh:
        for start in range(0, args.max, 100):
            r = client.get(
                "https://export.arxiv.org/api/query",
                params={"search_query": args.query, "start": start, "max_results": min(100, args.max - start),
                        "sortBy": "submittedDate", "sortOrder": "descending"},
            )
            r.raise_for_status()
            for entry in ET.fromstring(r.text).iter(f"{ATOM}entry"):
                url = (entry.findtext(f"{ATOM}id") or "").strip()
                title = " ".join((entry.findtext(f"{ATOM}title") or "").split())
                abstract = " ".join((entry.findtext(f"{ATOM}summary") or "").split())
                if not url or not abstract or url in seen:
                    continue
                fh.write(json.dumps({"corpus": "arxiv", "title": title, "url": url, "license": "CC0 (arXiv metadata)",
                                     "text": abstract}, ensure_ascii=False) + "\n")
                seen.add(url)
                added += 1
            time.sleep(3)  # arXiv asks for 3 s between calls
    print(f"added {added} abstracts to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
