# Open corpus samples

Small starting corpora that submissions are compared against. Each line of a
`.jsonl` file is one document: `{"corpus", "title", "url", "license", "text"}`.

| File | Content | Licence |
| --- | --- | --- |
| `wikipedia/sample.jsonl` | 30 English Wikipedia articles (Pakistan, agriculture, climate, science, history, ...) | CC BY-SA 4.0 |

## Grow the corpus

```bash
python -m scripts.load_wikipedia --random 500                  # 500 random English articles
python -m scripts.load_wikipedia --lang ur --titles پاکستان لاہور  # Urdu Wikipedia
python -m scripts.load_arxiv --query "cat:cs.CL" --max 500      # arXiv abstracts (CC0)
python -m scripts.index_corpus corpus/wikipedia/sample.jsonl corpus/arxiv/sample.jsonl
```

Every corpus change can change results: bump `ENGINE_VERSION` (engine/version.py)
after indexing a new snapshot.

Measured locally (Windows dev PC, fingerprints only, no embeddings): indexing the 30
sample articles (~290,000 words) took about 22 seconds. Indexing with embeddings and
database size have not been measured yet; measure them on the VPS before loading a
large corpus.
