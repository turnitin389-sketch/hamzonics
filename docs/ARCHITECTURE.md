# Architecture (public checker)

```
browser ──> nginx ──/api/*──> api (FastAPI) ──> postgres (pgvector)
              │                    │
              └──/*──> web (Next.js)│ send_task (queue "checks")
                                   ▼
                                redis ──> worker (Celery, --concurrency=3: one task = whole check)
                                              │        └── searxng (private web search)
                                              └── engine/ (pure Python, no web code)
```

## Public site (no accounts)

- Anyone can upload. A check is reached only by its random UUID; there is no listing endpoint.
  The browser keeps "my recent checks" in localStorage.
- `POST /api/submissions` returns a `delete_token` once; `DELETE` needs it in `X-Delete-Token`.
- Limits: `CHECKS_PER_IP_PER_HOUR` (by keyed hash of the IP; the IP itself is never stored),
  `MAX_QUEUE` waiting checks, 25 MB / 50,000 words.
- Queue: at most `MAX_CONCURRENT_CHECKS` (3) checks run at once (Celery concurrency, or 3 inline
  threads locally); the rest wait in arrival order and see `queue_position`. `GET /api/queue`.
- The upload is deleted when its check is done; whole checks are deleted after `RETENTION_DAYS`.
  Repository copies show to others only as "Submitted to Hamzonics on <date>", never a file name,
  and are removed when the uploader deletes the check.
- Same text = same result: frozen results (similarity AND AI) keyed by text hash + engine version.

## AI writing (engine/ai)

RoBERTa classifier (fakespot-ai/roberta-base-ai-text-detection-v1, pinned) run in numpy
(`engine/ai/roberta.py`, verified equal to ONNX Runtime to 5 decimals). Qualifying prose
sentences (no headings, tables, references) are packed into ~400-token windows, scored twice with
overlapping windows, averaged per sentence. >= 0.9 = AI-generated (counted), 0.7-0.9 = possibly AI
(shown, not counted). Under 300 qualifying words: not checked.

## Live sources (engine/similarity/web.py)

24 distinctive phrases per document, spread over the whole text, searched in Wikipedia, arXiv,
Europe PMC (full text of open-access papers), OpenAlex (abstract + open-access PDF/page), Crossref,
optionally Semantic Scholar, CORE, SearXNG, Brave, Google. Pages and PDFs are fetched safely
(public IPs only, robots.txt, 5 checked redirects, 15 MB, 25 s per page, 150 s budget per check).

## Packages

| Path | Role |
| --- | --- |
| `api/` | HTTP layer: auth, uploads, submissions. Never does heavy work in a request. |
| `engine/` | Checking engine. Phase 1: `engine/extract` (type detection, PDF/DOCX/ODT/RTF/TXT, OCR, normalisation, word count). Later: `flags`, `similarity`, `ai`, `citations`, `report`. |
| `worker/` | `pipeline.py` holds job logic (shared by Celery and the inline dev runner); `tasks.py` wraps it as Celery tasks. |
| `frontend/` | Next.js App Router, TypeScript strict, Tailwind. Talks to `/api` on the same origin. |
| `alembic/` | Database migrations. |

## Upload flow

1. `POST /api/submissions` (multipart: `file` or `text`, `idempotency_key`, `repository_opt_in`).
2. API checks session + CSRF + verified email, reads at most 25 MB, detects type by
   magic bytes, stores the file under `UPLOAD_DIR/<submission_id>/`, inserts a
   `queued` submission and returns **202** immediately.
   The same `idempotency_key` from the same user returns the existing submission (200).
3. A worker picks the job from the `extract` queue: `running` → extracts each page
   (pages with < 25 characters of text layer go to Tesseract `eng+urd`) → normalises
   → counts words → stores `documents_text` (clean text + page offsets) → `done`.
   Document problems (damaged, password-protected, no text, > 50,000 words) end as
   `failed` with a readable message.
4. The browser polls `GET /api/submissions/{id}` for `status`, `progress` and `queue_position`.

## Integrity flags (Phase 2)

`engine/flags/` finds and cleans tricks before any other check, inside extraction:

| Flag | Detected in | How it is cleaned |
| --- | --- | --- |
| `lookalike_characters` | all formats | Cyrillic/Greek twins, fullwidth and math letters → Latin. Only inside mixed-script words, or whole look-alike words in mostly-Latin text, so real Russian/Greek text is untouched. |
| `invisible_characters` | all formats | Zero-width, bidi-control, tag characters, soft hyphen removed. ZWNJ/ZWJ/LRM/RLM next to Urdu/Arabic letters are kept (they are normal there). |
| `hidden_text_vanish` | DOCX | Runs with Word's "hidden" attribute are left out. |
| `hidden_text_color` | DOCX, PDF | Text with WCAG contrast < 1.5 against its background (run shading/highlight, paragraph or cell shading, page background; for PDF the filled shape under the glyph, else white). Text over images is not judged. |
| `hidden_text_tiny` | DOCX, PDF | Font < 4 pt left out. |
| `text_outside_page` | PDF | Glyphs entirely outside the page box left out. |
| `image_only_pages` | PDF | Pages without a text layer, read with OCR. |

Counts are characters (whitespace excluded), except `image_only_pages` (pages).
DOCX formatting is resolved through direct formatting → character style → paragraph
style → document defaults. Flags are stored in the `flags` table (one row per type,
with locations) and returned by `GET /api/submissions/{id}/flags`.

Not covered yet: hidden text in ODT/RTF, PDF text-render-mode 3 (invisible text is
also how OCR'd PDFs store their text layer, so it is not flagged), text hidden behind
images.

## Similarity (Phase 3)

Job stages: `extract` queue (text + flags) → `similarity` queue → done.

1. **Sources** (`sources` table): `corpus` (Wikipedia/arXiv loaded by scripts),
   `web` / live `corpus` (documents found by searching the submission's most distinctive
   phrases on free key-less APIs: Wikipedia en+ur, arXiv, Europe PMC; cached 90 days),
   `submission` (own repository: finished submissions that did not opt out).
2. **Candidates**: word 5-grams → 64-bit BLAKE2b hashes → winnowing (window 4) →
   lookup in `fingerprints` (btree on `hash`). Any shared run of ≥ 8 words is found.
3. **Alignment** (`engine/similarity/align.py`): exact runs of shared 5-grams on the
   same diagonal; runs separated by ≤ 3 changed words are merged into `near` matches.
4. **Paraphrase / translation**: sentences not already ≥ 50 % covered are embedded
   (MiniLM multilingual, 384-d) and compared with stored source sentences
   (pgvector HNSW; numpy on SQLite). Cosine ≥ 0.85 → `paraphrase`, or `crosslang`
   when the scripts differ (e.g. Urdu vs English).
5. **Groups**: quotes (“…”, "…", «…»), in-text citations ((Author, 2020), Author (2020),
   [3]) and the reference list (heading such as References / Bibliography / حوالہ جات)
   put each match in Not cited or quoted / Missing quotations / Missing citation /
   Cited and quoted / Bibliography.
6. **Scoring** (`merge.py`): each word goes to one match (exact > near > paraphrase,
   then the source with more matched words, then source id). Similarity % =
   matched words / total words, rounded half-up to 2 decimals. Raw matches are stored,
   so filters (exclude quotes, bibliography, matches under N words, a source) are
   recomputed instantly by `GET /api/submissions/{id}/similarity`.
7. **No self-match**: the submission itself and earlier uploads of the same text by
   the same user are excluded; the same text from another user is reported (collusion).
   A submission joins the repository only after its own matching finishes.

Not done yet: block-quote detection (needs paragraph indentation from DOCX/PDF),
GROBID bibliography parsing, DOI checks with Crossref.

## Reports (Phase 4)

- Online: submission page shows similarity %, sources (click a source to jump through
  its highlights), filters, coloured highlights with source excerpts, integrity flags.
- PDF: `worker/report.py` builds the context from the SAME read model as the API
  (`api/services.similarity_view`), Jinja2 renders `engine/report/templates/report.html`,
  headless Chromium (Playwright) prints it. JavaScript is off and all network requests
  are blocked while printing. Pages: cover (ID, dates, words, Similarity %, AI status,
  flags), integrity flags, similarity overview (groups bar + sources), full text with
  numbered highlights, AI writing, how to read this report. Footer on every page:
  submission ID, page X of Y, QR code to `/verify/<id>`.
- The PDF's SHA-256 is stored in `reports`. `GET /api/verify/{id}` shows key facts
  (no text, no file name); `POST /api/verify/{id}` with a PDF says whether it is the
  exact file issued. The PDF is rebuilt on download if missing or changed on disk.
- Chromium replaces WeasyPrint from the spec: WeasyPrint needs GTK/Pango, which the
  Windows dev PC does not have, and Playwright is already needed for end-to-end tests,
  so one renderer is used everywhere.

## (Removed) Clients, credits and identical results (Phase 8)

Accounts, clients, credits and payments were removed on 2026-11-22 for the public site; the
code is archived in `../hamzonics-removed-accounts/`. The notes below are historical.

- **Roles:** `super_admin` creates clients (with a password, or an invite link valid 72 h).
  Logins belong to a client (`users.client_id`); every submission query is filtered by
  the caller's client in SQL, so another client's check is a 404. The admin can read any
  check ("view as client") but cannot delete it.
- **Credits:** `credit_ledger` is append-only (PostgreSQL trigger refuses UPDATE/DELETE
  except the cascade when a client is deleted). `clients.credit_balance` is the cached
  ledger sum, changed in the same transaction by one conditional
  `UPDATE … WHERE credit_balance >= 1 RETURNING`, plus a CHECK (balance >= 0). A failed
  check is refunded exactly once. Expiring credit batches are used first; leftovers
  expire through `worker.maintenance` (Celery beat every 5 min).
- **Idempotency:** `(user_id, idempotency_key)` is unique; a double submit returns the
  same submission and charges once, also when both requests arrive together.
- **Identical results:** `text_sha256` is a hash of the folded word sequence, so the
  same essay as DOCX or PDF is one document. `result_key = sha256(text_sha256 + check
  settings + ENGINE_VERSION + owner scope)`. The first result is stored in
  `frozen_results` (by word index) and copied for every later check; an advisory lock
  (PostgreSQL) / in-process lock (SQLite) stops two identical uploads computing at once.
  The owner scope is the client: the spec asks both "same result for any client" and
  "same text from another client is collusion"; collusion was chosen across clients.
- **Many users:** separate Celery queues; at most `MAX_RUNNING_PER_CLIENT` running checks
  per client (extra jobs wait); one automatic retry, then failed + refunded;
  `acks_late` + `reject_on_worker_lost`; stuck checks are re-queued once by maintenance.
  Locally (no Redis) an in-process queue with one worker thread does the same, and
  interrupted checks are re-queued when the API starts.
- **Payments:** plans (credits + PKR price); the client uploads a JazzCash / Easypaisa /
  bank receipt (PNG/JPG/PDF checked by magic bytes); the admin approves (credits added
  with the receipt reference in the ledger reason) or rejects. Admin actions go to `audit_log`.

## Security (public site)

- No cookies or sessions, so no CSRF surface. Check ids are UUID4 (unguessable); ids are validated
  before any query.
- Delete tokens: 24 random bytes, only the SHA-256 is stored, compared in constant time.
- File type by magic bytes, size limit while reading, per-IP hourly limit, queue cap.
- Outgoing fetches: SSRF guard on every hop, robots.txt, size and time limits.
- PDF rendering: Chromium with JavaScript off and all network requests blocked.

## Not yet built

ClamAV scan of uploads, encryption at rest, CAPTCHA against automated abuse, a labelled AI test
set for threshold tuning (see docs/IMPROVING-RESULTS.md).
