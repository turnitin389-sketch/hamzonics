# Third-party components

Every library, repo and model used by Turnitin Reports, with its licence. Rule: anything
that forbids commercial use (or is "academic use only") stays behind an
`ENABLE_<NAME>=false` flag and is not shipped in production.

## Phase 1 (in use)

| Component | Version | Licence | Used for | Notes |
| --- | --- | --- | --- | --- |
| FastAPI | 0.115.6 | MIT | HTTP API | |
| Uvicorn | 0.34.0 | BSD-3-Clause | ASGI server | |
| SQLAlchemy | 2.0.36 | MIT | ORM | |
| Alembic | 1.14.0 | MIT | Migrations | |
| psycopg | 3.2.3 | LGPL-3.0 | PostgreSQL driver | Used unmodified as a library (allowed for commercial use). |
| pydantic / pydantic-settings | 2.10.4 / 2.7.0 | MIT | Validation, config | |
| argon2-cffi | 23.1.0 | MIT | Password hashing (argon2id) | |
| PyJWT | 2.10.1 | MIT | Session tokens | |
| Celery | 5.4.0 | BSD-3-Clause | Background jobs | |
| redis-py | 5.2.1 | MIT | Queue broker client | |
| pdfplumber (+ pdfminer.six, pypdfium2) | 0.11.4 | MIT (pdfminer MIT, pypdfium2 Apache-2.0/BSD-3) | PDF text + page rendering for OCR | **Default PDF backend.** |
| python-docx | 1.1.2 | MIT | DOCX files (test fixtures) | |
| lxml | 6.1.3 | BSD-3-Clause | DOCX XML parsing for hidden-text detection | |
| striprtf | 0.0.28 | BSD-3-Clause | RTF text | |
| pytesseract | 0.3.13 | Apache-2.0 | Tesseract wrapper | |
| Tesseract OCR + eng/urd data | Debian package | Apache-2.0 | OCR | Installed in the Docker image. |
| Pillow | 11.0.0 | MIT-CMU (HPND) | Images for OCR | |
| Next.js | 16.4.6 | MIT | Frontend | Spec says 14+. Upgraded from 14.2 because every 14.x release has open security advisories (npm audit: 0 vulnerabilities on 16.4.6). |
| React / React DOM | 19.2.9 | MIT | Frontend | |
| Tailwind CSS | 3.4.14 | MIT | Styling | |
| PostgreSQL + pgvector image | pg16 | PostgreSQL / PostgreSQL licence | Database | |
| Redis | 7.4 | RSALv2 / SSPLv1 (7.4+) | Queue broker | Self-hosting for our own app is allowed; we do not offer Redis as a service. Valkey (BSD) is a drop-in alternative if preferred. |
| Nginx | 1.27 | BSD-2-Clause | Reverse proxy | |
| fakespot-ai/roberta-base-ai-text-detection-v1 | f9cdb14 | Apache-2.0 | AI-writing detection (primary) | Run with numpy. |
| SuperAnnotate/ai-detector | 74b2b85 | SAIPL 1.0 (copyleft, AGPL-style; commercial use allowed) | Confirms AI windows (removes false alarms on human text) | Used **unmodified**. SAIPL requires attribution, a link to the licence, and that network users can get the model's source: the site footer links to the model and licence. If the model is ever modified, the modified model must be published under SAIPL. Get legal advice before charging money for the service. |
| FacebookAI/roberta-large (config only) | 722cf37 | MIT | Architecture config for the SuperAnnotate model | |

## Phase 3 (similarity)

| Component | Version | Licence | Used for | Notes |
| --- | --- | --- | --- | --- |
| PyTorch (CPU build) | 2.15.0 | BSD-3-Clause (+ bundled permissive licences) | Embedding inference | Installed from the official CPU wheel index. On Windows it needs Visual C++ runtime 14.40+. |
| sentence-transformers | 6.3.0 | Apache-2.0 | Sentence embeddings | |
| transformers / tokenizers / huggingface-hub | 5.23.0 / 0.23.3 / – | Apache-2.0 | Model loading | |
| **paraphrase-multilingual-MiniLM-L12-v2** | HF commit `e8f8c211226b894fcb81acc59f3b34ba3efd5f42` | Apache-2.0 (model card) | Paraphrase + cross-language (Urdu ↔ English) matching | Downloaded at Docker build time; offline at runtime. |
| spaCy | 3.8.18 | MIT | Sentence splitting (blank `xx` + sentencizer, no model download) | |
| NumPy | 2.5.5 | BSD-3-Clause | Vector maths | |
| pgvector (Python) | 0.5.1 | MIT | SQLAlchemy `vector` type | |
| trafilatura | 2.3.1 | Apache-2.0 | Main-text extraction from web pages | |
| httpx | 0.28.1 | BSD-3-Clause | Search APIs, page fetching | |

## Phase 4 (reports)

| Component | Licence | Used for | Notes |
| --- | --- | --- | --- |
| Playwright (Python) + Chromium | Apache-2.0 (Chromium: BSD-3-Clause and others) | HTML → PDF | Replaces WeasyPrint from the spec (needs GTK/Pango, unavailable on the Windows dev PC). JS disabled and network blocked while printing. |
| Jinja2 | BSD-3-Clause | Report templates | |
| qrcode | BSD-3-Clause | Verify QR code | |
| pypdfium2 | Apache-2.0 / BSD-3-Clause | Counting PDF pages | |
| Noto fonts (`fonts-noto-core`, Docker) | SIL OFL 1.1 | Latin + Arabic-script (Urdu) text in PDFs | |

### Data

| Data | Licence | Notes |
| --- | --- | --- |
| Wikipedia articles (`corpus/wikipedia/*.jsonl`) | CC BY-SA 4.0 | Source URL stored with every article and shown in reports as the match source. |
| arXiv abstracts (`corpus/arxiv/*.jsonl`, via script) | CC0 (arXiv metadata) | |

### Live sources (free, no API keys, no paid plans)

| Service | Content licence | Notes |
| --- | --- | --- |
| Wikipedia API (en, ur) | CC BY-SA 4.0 | Search + plain-text extracts; polite rate (retry on 429). |
| arXiv API | CC0 metadata | Abstract phrase search. |
| Europe PMC REST API | Abstract rights vary by publisher; used only to compare and show short excerpts with a link | Abstract phrase search. |
| SearXNG (optional, your own instance) | n/a | **Off by default.** It scrapes Google/Bing etc., which may break their terms. |

Evaluated and not used: Brave / Bright Data (paid keys), OpenAlex (API key required
since Feb 2026), DOAJ (API returned 403 to our requests on 2026-11-21).

## Reference repos (Phase 3, read for ideas only, no code copied)

| Repo | Notes |
| --- | --- |
| FurkanBaran/PlagCheck-Web-App | Not cloned; our flow is already more complete. |
| TristanPerry/plagiarism-detection-software | Not cloned. |
| cobel1024/minima | Not cloned. Its two-stage design (cheap candidate retrieval, then detailed comparison) is the same approach used here (fingerprint lookup → alignment). |

## Disabled by default

| Component | Licence | Why it is off | Flag |
| --- | --- | --- | --- |
| PyMuPDF 1.25.1 | **AGPL-3.0** (or paid commercial licence) | The spec lists PyMuPDF, but AGPL requires publishing the full source of a network service that uses it. pdfplumber covers the same needs (text, char colours and font sizes for Phase 2, page rendering for OCR). Used in tests only, to build PDF fixtures. | `ENABLE_PYMUPDF=false`, `PDF_BACKEND=pdfplumber` |

## Later phases (not cloned yet)

Each repo will be cloned into `third_party/` at a pinned commit, and its LICENSE
checked before use. Commit hashes will be recorded here.

| Repo | Phase | Licence to verify |
| --- | --- | --- |
| baoguangsheng/fast-detect-gpt | 5 | Check LICENSE |
| ahans30/Binoculars | 5 | README says academic use: expected `ENABLE_BINOCULARS=false` |
| frostming/Aletheia | 5 | Check LICENSE |
| xuzhenpeng263/ai-text-detector | 5 | Check LICENSE |
| superannotateai/generated_text_detector | 5 | Check LICENSE and model card |
| dodona-edu/dolos | 7 | MIT |
| jplag/JPlag | 7 | GPL-3.0: separate CLI process only, `ENABLE_JPLAG=false` |
