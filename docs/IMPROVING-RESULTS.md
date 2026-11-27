# Getting closer to Turnitin

Measured 2026-11-22 on one 5,000-word pharmacy paper that Turnitin scored at 7% similarity:
Hamzonics found 2% on a Windows PC **without** web search (open-access papers + Wikipedia only).
Most of Turnitin's sources for that paper were web pages and PDFs (researchsquare, frontiersin,
university repositories), which only a web search engine finds.

Later the same day, with SearXNG web search on (run locally without Docker, see README):

| Test | Before web search | With web search |
| --- | --- | --- |
| Text copied from a business website (transdontics.com) | 0% | **87%** (81% from the right page) |
| The 5,000-word pharmacy paper (Turnitin 7%) | 2% | 2% (0.33% with the default 8-word filter) |

Copied passages are found well. What a search-based checker cannot reproduce is Turnitin's
many tiny matches (25 sources, each under 1%) scattered through an original paper: those come
from Turnitin's own full index of the web, not from searching.

## Similarity, from biggest gain to smallest

| Step | Cost | Why |
| --- | --- | --- |
| **Serper.dev key (`SERPER_API_KEY`)** | 2,500 free searches, then ~$1 per 1,000 (12 per check = ~$0.012) | Google results that do not get blocked. Free engines (SearXNG) blocked this PC after a few hundred searches in testing (CAPTCHA, 429), giving 0% on fully copied text. |
| Run on the VPS with docker-compose (SearXNG included) | free | Adds Internet sources (Google/Bing/DuckDuckGo results via your own SearXNG). Largest single gain. |
| Brave Search API key (`BRAVE_API_KEY`) | free tier, then paid | Reliable web results; SearXNG can be rate-limited by search engines. |
| Free OpenAlex key (`OPENALEX_API_KEY`) | free | Own daily budget instead of sharing one per IP address. |
| Free CORE key (`CORE_API_KEY`, add `core` to `FREE_SOURCES`) | free | Full text of 30M+ open-access papers. |
| Semantic Scholar key + add `semanticscholar` | free | More abstracts and open-access PDFs. |
| Enable paraphrase matching (`ENABLE_SEMANTIC=true`, works on the VPS) | free | Finds reworded copying, not only copied wording. |
| More search phrases (`WEB_SEARCH_MAX_QUERIES` 24 -> 40) | slower checks | Covers more of each document. |
| Grow the local corpus (`scripts/load_wikipedia --random 5000`, `scripts/load_arxiv`) | disk space | Matches without any live search. |
| Keep the repository on (users opt in) | free | Finds copying between students, like Turnitin's "Submitted works". Grows with use. |

Not possible for any new service: Turnitin's private database of paywalled journals (publisher
agreements) and its 1.9 billion student papers.

## AI writing

Measured 2026-11-22 on 81 labelled texts (threshold 0.995, the default):

| Texts | Result |
| --- | --- |
| 66 human texts written before ChatGPT (41 PubMed abstracts 2010-16, 20 arXiv 2015-18, 5 Wikipedia 2015) | **0 wrongly flagged** (at threshold 0.9 it was 7) |
| 12 plain AI texts (essay, report, blog, story, cover letter, ...) | **12 detected, 100% AI each** |
| 3 AI texts rewritten to look human (typos, slang, short sentences) | **0 detected** |
| Urdu / other languages | not scored; the report says AI detection is English-only |

- Model: Mozilla Fakespot RoBERTa (Apache-2.0).
- **Known weakness:** encyclopedic text (e.g. Wikipedia) scores high. Treat AI results as a
  pointer for review, never as proof.
- Better accuracy: build a labelled test set (100+ human texts from before 2022 in your users'
  subjects, 100+ AI texts from current models), measure, and tune `AI_THRESHOLD`; or switch to a
  stronger model (e.g. a DeBERTa-large detector, needs PyTorch on the VPS); or use a paid API
  (GPTZero, Originality.ai, Copyleaks, Pangram) for the highest accuracy.
