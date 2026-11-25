"""Is Internet search working right now?  python -m scripts.search_health

Sends one exact-phrase query to the configured web search (SearXNG / Brave / Google) and
prints which engines answered and which refused (CAPTCHA, 403, rate limit)."""

from __future__ import annotations

import httpx

from api.config import get_settings

PHRASE = '"the quick brown fox jumps over the lazy dog"'


def main() -> int:
    s = get_settings()
    if s.searxng_url:
        r = httpx.get(f"{s.searxng_url.rstrip('/')}/search", params={"q": PHRASE, "format": "json"}, timeout=60)
        data = r.json() if r.status_code == 200 else {}
        print(f"SearXNG HTTP {r.status_code}: {len(data.get('results', []))} results")
        engines = sorted({x.get('engine') for x in data.get('results', [])})
        print("  answered:", ", ".join(engines) or "none")
        for name, reason in data.get("unresponsive_engines", []):
            print(f"  refused:  {name} ({reason})")
    if s.serper_api_key:
        r = httpx.post("https://google.serper.dev/search", json={"q": PHRASE, "num": 10},
                       headers={"X-API-KEY": s.serper_api_key, "Content-Type": "application/json"}, timeout=30)
        n = len(r.json().get("organic", [])) if r.status_code == 200 else 0
        hint = {401: " (wrong key)", 403: " (key not allowed or no credits left)", 429: " (too many requests)"}
        print(f"Serper (Google) HTTP {r.status_code}{hint.get(r.status_code, '')}: {n} results")
    if s.brave_api_key:
        r = httpx.get("https://api.search.brave.com/res/v1/web/search", params={"q": PHRASE},
                      headers={"X-Subscription-Token": s.brave_api_key}, timeout=30)
        print(f"Brave API HTTP {r.status_code}")
    if not (s.serper_api_key or s.searxng_url or s.brave_api_key or s.google_cse_key):
        print("No web search configured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
