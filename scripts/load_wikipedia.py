"""Download Wikipedia articles as plain text into a JSONL corpus file.

Usage:
  python -m scripts.load_wikipedia                       # default sample list (English)
  python -m scripts.load_wikipedia --lang ur --titles پاکستان لاہور
  python -m scripts.load_wikipedia --random 200 --out corpus/wikipedia/random.jsonl

Wikipedia text is CC BY-SA 4.0: the source URL is kept with every article and shown
in reports. Grow the corpus by running this again with more titles or --random N
(appends; existing URLs are skipped), then run scripts.index_corpus.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.parse import quote

import httpx

USER_AGENT = "HamzonicsCorpusLoader/0.1 (self-hosted document similarity checker)"

DEFAULT_TITLES = [
    "Pakistan", "Climate change in Pakistan", "Indus River", "Lahore", "Karachi", "Islamabad",
    "Agriculture in Pakistan", "Economy of Pakistan", "Education in Pakistan", "Muhammad Ali Jinnah",
    "Muhammad Iqbal", "Urdu", "Photosynthesis", "Global warming", "Renewable energy", "Deforestation",
    "Plastic pollution", "Artificial intelligence", "Machine learning", "Internet", "Social media",
    "Computer science", "Industrial Revolution", "French Revolution", "World War II", "Democracy",
    "Human rights", "Diabetes", "COVID-19 pandemic", "Cricket",
]


def _get(client: httpx.Client, url: str, params: dict) -> httpx.Response:
    """GET with polite retries on 429/503 (honours Retry-After)."""
    for attempt in range(6):
        r = client.get(url, params=params)
        if r.status_code not in (429, 503):
            r.raise_for_status()
            return r
        wait = float(r.headers.get("Retry-After", "") or 0) or min(60, 5 * 2**attempt)
        print(f"  rate limited, waiting {wait:.0f} s")
        time.sleep(wait)
    r.raise_for_status()
    return r


def fetch_article(client: httpx.Client, lang: str, title: str) -> dict | None:
    r = _get(
        client,
        f"https://{lang}.wikipedia.org/w/api.php",
        {
            "action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1,
            "titles": title, "format": "json", "formatversion": 2,
        },
    )
    pages = r.json().get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing") or not pages[0].get("extract"):
        return None
    page = pages[0]
    real_title = page["title"]
    return {
        "corpus": f"wikipedia-{lang}",
        "title": real_title,
        "url": f"https://{lang}.wikipedia.org/wiki/{quote(real_title.replace(' ', '_'))}",
        "license": "CC BY-SA 4.0",
        "text": page["extract"],
    }


def random_titles(client: httpx.Client, lang: str, n: int) -> list[str]:
    titles: list[str] = []
    while len(titles) < n:
        r = _get(
            client,
            f"https://{lang}.wikipedia.org/w/api.php",
            {"action": "query", "list": "random", "rnnamespace": 0, "rnlimit": min(50, n - len(titles)),
             "format": "json", "formatversion": 2},
        )
        titles.extend(p["title"] for p in r.json()["query"]["random"])
    return titles


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", default="en")
    ap.add_argument("--titles", nargs="*")
    ap.add_argument("--random", type=int, default=0)
    ap.add_argument("--out", type=Path, default=Path("corpus/wikipedia/sample.jsonl"))
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    if args.out.exists():
        seen = {json.loads(line)["url"] for line in args.out.read_text(encoding="utf-8").splitlines() if line}

    with httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT}) as client:
        titles = args.titles or ([] if args.random else DEFAULT_TITLES)
        if args.random:
            titles += random_titles(client, args.lang, args.random)
        added = 0
        with args.out.open("a", encoding="utf-8") as fh:
            for title in titles:
                art = fetch_article(client, args.lang, title)
                time.sleep(1.5)  # be polite to the API
                if art is None or art["url"] in seen:
                    continue
                fh.write(json.dumps(art, ensure_ascii=False) + "\n")
                seen.add(art["url"])
                added += 1
                print(f"+ {art['title']} ({len(art['text'].split())} words)")
    print(f"added {added} articles to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
