"""Index JSONL corpus files into the database (fingerprints + sentence embeddings).

Usage:
  python -m scripts.index_corpus corpus/wikipedia/sample.jsonl corpus/arxiv/sample.jsonl
  python -m scripts.index_corpus --force corpus/wikipedia/sample.jsonl   # rebuild (e.g. after enabling embeddings)
Re-running is safe: unchanged documents (same URL and text) are skipped unless --force.
Changing the corpus changes results, so bump ENGINE_VERSION after a corpus update.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from api.config import get_settings
from api.db import get_sessionmaker
from api.models import SourceType
from engine.similarity.index import build_entry
from worker.pipeline import get_encoder
from worker.sql_index import store_entry, upsert_source


def main() -> int:
    args = sys.argv[1:]
    force = "--force" in args
    paths = [Path(a) for a in args if a != "--force"]
    if not paths:
        print(__doc__)
        return 2
    encoder = get_encoder(get_settings())
    print("sentence embeddings:", "ON" if encoder is not None else "OFF (ENABLE_SEMANTIC=false)")
    total = indexed = 0
    with get_sessionmaker()() as db:
        for path in paths:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                total += 1
                corpus = item.get("corpus") or ""
                # Wikipedia is an Internet source in reports; papers/abstracts are Publications.
                kind = SourceType.WEB if corpus.startswith("wikipedia") else SourceType.CORPUS
                row, changed = upsert_source(
                    db, type=kind, corpus=corpus or None, title=item["title"],
                    text=item["text"], url=item["url"],
                )
                if changed or force:
                    store_entry(db, row, build_entry(item["text"], encoder))
                    indexed += 1
                db.commit()
                if total % 10 == 0:
                    print(f"{total} documents read, {indexed} indexed")
    print(f"done: {total} documents read, {indexed} (re)indexed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
