# Turnitin Reports

Free public document checker: **similarity (plagiarism) with highlighted, numbered sources**,
**AI-writing detection**, hidden-text checks, and a full **PDF report**. No accounts: anyone opens
the site, uploads a file or pastes text, and gets a report. **3 checks run at the same time**;
everyone else waits in a first-come, first-served queue and sees their position.

See `docs/ARCHITECTURE.md` for how it works and `docs/IMPROVING-RESULTS.md` for how to get closer
to commercial checkers.

## Run locally on Windows (no Docker)

Uses SQLite and runs checks inside the API process (`JOB_RUNNER=inline`, 3 worker threads).

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m playwright install chromium
copy .env.example .env    # then edit: ENV=dev, DATABASE_URL=sqlite:///./data/hamzonics.db,
                          # JOB_RUNNER=inline, UPLOAD_DIR=./data/uploads, a real SECRET_KEY
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m scripts.index_corpus corpus/wikipedia/sample.jsonl
.\.venv\Scripts\python.exe -m uvicorn api.main:app --port 8000
```

In a second terminal:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Open http://localhost:3000. The AI model (~500 MB) is downloaded on the first check and cached in
`data/models`. It runs with numpy, so it works even where PyTorch does not.

- **OCR for scanned PDFs** needs Tesseract (UB Mannheim build, with Urdu data).
- **Paraphrase matching** needs PyTorch, which on Windows needs the Microsoft Visual C++
  Redistributable 14.40+ (`winget install --id Microsoft.VCRedist.2015+.x64 -e`), then
  `ENABLE_SEMANTIC=true` in `.env`.
- **Web (Internet) sources** need a search engine. Without one, only Wikipedia, open-access
  papers (OpenAlex, Europe PMC, arXiv) and earlier submissions are searched. Locally without
  Docker, run SearXNG from `../searxng-app` (official source, pinned commit cd6d28091, own venv;
  `pwd.py` there is a small Windows stand-in) with the settings in `deploy/searxng/settings.yml`,
  on port 8888 (launch config `searxng`), and set `SEARXNG_URL=http://127.0.0.1:8888`.
  On the server, docker-compose runs it for you.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=engine --cov=api --cov=worker
cd frontend; npm.cmd run build
```

## Test the server setup on this PC (Docker Desktop)

`.env.docker` holds local test settings (random passwords, `PUBLIC_BASE_URL=http://localhost:8080`).

```powershell
$env:HZ_ENV_FILE=".env.docker"; docker compose --env-file .env.docker up -d --build
```

Open http://localhost:8080. Stop with `docker compose --env-file .env.docker down`
(add `-v` only if you also want to delete the test database).

Run only ONE worker container: on start it re-queues checks a killed worker left running.

## Put it online (VPS with Docker)

Recommended: 2+ vCPU, 8 GB RAM (3 checks at once, each loads the AI model), a domain name.

```bash
cp .env.example .env        # fill in every CHANGE_ME (SECRET_KEY, POSTGRES_PASSWORD, SEARXNG_SECRET)
docker compose up -d --build
```

The sample Wikipedia corpus is indexed automatically in the background on the first start
(about 15 minutes; see `/data/index-corpus.log` in the worker).
The stack listens on `127.0.0.1:8080`. Make it public with HTTPS using the host Nginx file
`deploy/host-nginx.conf` (instructions inside: copy, set your domain, `certbot --nginx`).
docker-compose also runs a private SearXNG search engine (free) so Internet sources are found.

## Configuration

All settings are environment variables; see `.env.example`. Most useful:
`MAX_CONCURRENT_CHECKS` (3), `CHECKS_PER_IP_PER_HOUR` (20), `RETENTION_DAYS` (30),
`AI_THRESHOLD` (0.9), `FREE_SOURCES`, `OPENALEX_API_KEY`, `CORE_API_KEY`.
