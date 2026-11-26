"""Application settings, loaded from environment variables / `.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["dev", "prod", "test"] = "dev"
    app_name: str = "Turnitin"
    public_base_url: str = "http://localhost:3000"
    # Server secret: used to hash uploader IP addresses for rate limiting (never stored in clear).
    secret_key: str = Field(min_length=32)

    # Public site limits
    max_concurrent_checks: int = 3  # checks processed at the same time; the rest wait in the queue
    max_queue: int = 200  # new uploads are refused while this many checks are waiting
    checks_per_ip_per_hour: int = 20  # 0 = no limit
    retention_days: int = 30  # checks (file, text, report) are deleted after N days; 0 = keep
    trust_proxy_headers: bool = False  # true behind Nginx: take the client IP from X-Forwarded-For

    # Storage / queue
    database_url: str = "sqlite:///./data/hamzonics.db"
    redis_url: str = "redis://localhost:6379/0"
    job_runner: Literal["celery", "inline"] = "celery"
    inline_sync: bool = False  # tests: run the job inside the request
    job_time_limit_s: int = 1800

    # Uploads
    upload_dir: Path = Path("./data/uploads")
    report_dir: Path = Path("./data/reports")
    model_dir: Path = Path("./data/models")
    report_timezone: str = "Asia/Karachi"
    # Build the PDF as part of every check (False: build on first download).
    generate_pdf_in_pipeline: bool = True
    max_upload_mb: int = 25
    max_words: int = 50_000

    # Extraction / OCR
    ocr_languages: str = "eng+urd"
    ocr_min_chars_per_page: int = 25
    ocr_dpi: int = 300
    pdf_backend: Literal["pdfplumber", "pymupdf"] = "pdfplumber"
    enable_pymupdf: bool = False

    # Similarity
    enable_semantic: bool = True
    similarity_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    similarity_model_revision: str = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
    semantic_threshold: float = 0.85
    torch_threads: int = 1
    max_candidate_sources: int = 80
    # The report leaves these out of the score by default (like other checkers); the
    # online report can switch them back on.
    default_exclude_bibliography: bool = True
    default_exclude_quotes: bool = False
    # Shared runs shorter than this are common phrases ("such as the use of"), not copying.
    # Tested 2026-11-22: on two original essays, all matches under 8 words were stock phrases.
    default_min_words: int = 8

    # Live sources: FREE services (comma list; empty = off).
    #   wikipedia, arxiv, europepmc, openalex, crossref, semanticscholar, core, searxng
    # Internet search uses Serper (API keys) only. Optional free APIs can be added here
    # (wikipedia, arxiv, europepmc, openalex, crossref, semanticscholar, core); off by default.
    free_sources: str = ""
    wikipedia_langs: str = "en,ur"
    # Optional free keys: raise the free daily limits.
    openalex_api_key: str = ""
    semanticscholar_api_key: str = ""
    core_api_key: str = ""
    # Web search (Internet sources). SearXNG is free and self-hosted (docker-compose runs one);
    # Brave / Google are optional keyed APIs with free tiers.
    searxng_url: str = ""
    # serper.dev: Google results, ~$1 per 1,000 searches, 2,500 free at sign-up (recommended).
    serper_api_key: str = ""
    # Paid search: one phrase per PAID_SEARCH_WORDS_PER_QUERY words of the document, at least
    # PAID_SEARCH_MAX_QUERIES and at most PAID_SEARCH_QUERY_CAP (Serper: ~$0.001 per search).
    # Phrases already found in an indexed page are skipped, so copied text costs less.
    # 12 fixed phrases missed 6 of 10 copied pages in a 4,600-word document (2026-11-24).
    paid_search_max_queries: int = 12
    paid_search_words_per_query: int = 100
    paid_search_query_cap: int = 60
    search_cache_days: int = 30  # a phrase searched once is not searched (paid) again for N days
    # Admin portal (API keys, usage). Empty = admin portal disabled.
    admin_password: str = ""
    brave_api_key: str = ""
    google_cse_key: str = ""
    google_cse_cx: str = ""
    web_search_max_queries: int = 24
    web_results_per_query: int = 4
    web_max_pages: int = 100
    web_cache_days: int = 90
    web_fetch_pdfs: bool = True
    web_time_budget_s: int = 240  # max time spent searching/fetching sources per check
    web_embed_sources: bool = False  # paraphrase-index live pages too (slow: minutes per check)

    # AI-writing detection (numpy, no PyTorch)
    enable_ai: bool = True
    ai_model: str = "fakespot-ai/roberta-base-ai-text-detection-v1"
    ai_model_revision: str = "f9cdb14d1f8b105f597d80fa7b56f20c6ea0e9db"
    # Measured 2026-11-22 on 66 human texts written before ChatGPT (41 PubMed abstracts 2010-16,
    # 20 arXiv abstracts 2015-18, 5 Wikipedia articles as of 2015) and 15 AI texts:
    #   0.9   -> 7/66 human documents wrongly >= 20% AI (human windows scored 0.992-0.993)
    #   0.995 -> 0/66 wrongly flagged, still 12/12 plain AI texts detected (AI scored ~1.000)
    # Heavily "humanized" AI text (typos, slang) is NOT detected at any threshold (0/3).
    ai_threshold: float = 0.995
    ai_possible_threshold: float = 0.9
    ai_window_tokens: int = 400
    ai_overlap: bool = True
    ai_min_words: int = 300
    # Second detector (needs PyTorch; used on the server/Docker): DeBERTa-v3-large trained on RAID.
    ai2_enabled: bool = False
    ai2_model: str = "desklib/ai-text-detector-v1.01"
    ai2_model_revision: str = "5fdea974cd4287c61674951ec78803aa274e2fb7"
    ai2_rule: str = "max"  # how the two scores are combined: max | mean | min
    # int8 (dynamic quantization) for the second detector: ~1 GB less RAM, for small servers.
    ai2_quantize: bool = False
    # Confirming detector (needs PyTorch): a window is AI only if BOTH models say so.
    # Measured 2026-11-23 (scripts/eval_classifiers.py): the primary model alone wrongly flagged
    # 11/159 human texts (book summaries, news, finance answers) and 6/130 in a separate hold-out
    # set; with confirmation 0/159 and 0/130, while AI detection stayed the same (hold-out 40/40).
    ai_confirm_enabled: bool = True
    ai_confirm_model: str = "SuperAnnotate/ai-detector"
    ai_confirm_model_revision: str = "74b2b8580915c202607c09f64f8170eaa87a6a14"
    ai_confirm_threshold: float = 0.72  # human max among primary false alarms was 0.70
    # If the confirming model cannot load (e.g. no PyTorch), the primary model alone needs this
    # stricter threshold instead (hold-out: 0/130 human, 36/40 AI).
    ai_threshold_unconfirmed: float = 0.9997
    # Third detector: Binoculars (zero-shot, two small Qwen models; needs PyTorch).
    ai3_enabled: bool = False
    ai3_observer: str = "Qwen/Qwen2.5-0.5B"
    ai3_observer_revision: str = "060db6499f32faf8b98477b0a26969ef7d8b9987"
    ai3_performer: str = "Qwen/Qwen2.5-0.5B-Instruct"
    ai3_performer_revision: str = "7ae557604adf67be50417f59c2c2f167def9a775"
    ai3_threshold: float = 0.9  # Binoculars score below this = AI (calibrated on the test set)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @model_validator(mode="after")
    def _check(self) -> "Settings":
        if self.pdf_backend == "pymupdf" and not self.enable_pymupdf:
            raise ValueError("PDF_BACKEND=pymupdf requires ENABLE_PYMUPDF=true (AGPL licence, see THIRD_PARTY.md)")
        if self.env == "prod" and self.secret_key.startswith("CHANGE_ME"):
            raise ValueError("Set a real SECRET_KEY in production")
        if self.max_concurrent_checks < 1:
            raise ValueError("MAX_CONCURRENT_CHECKS must be at least 1")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
