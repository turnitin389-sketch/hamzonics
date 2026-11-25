# Shared image for the API and the Celery worker.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

# Tesseract OCR with English + Urdu language data.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-urd \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.lock requirements.lock
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.lock

# Download the pinned embedding model at build time; at runtime the Hub is never contacted.
ENV HF_HOME=/opt/hf
ARG SIMILARITY_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
ARG SIMILARITY_MODEL_REVISION=e8f8c211226b894fcb81acc59f3b34ba3efd5f42
RUN python -c "from sentence_transformers import SentenceTransformer as S; S('${SIMILARITY_MODEL}', revision='${SIMILARITY_MODEL_REVISION}', device='cpu')" \
 && chmod -R a+rX /opt/hf

# AI-writing detector (pinned revision, ~500 MB), run with numpy (engine/ai/roberta.py).
ENV MODEL_DIR=/opt/models
ARG AI_MODEL=fakespot-ai/roberta-base-ai-text-detection-v1
ARG AI_MODEL_REVISION=f9cdb14d1f8b105f597d80fa7b56f20c6ea0e9db
RUN python -c "from huggingface_hub import hf_hub_download as d; [d('${AI_MODEL}', f, revision='${AI_MODEL_REVISION}', cache_dir='/opt/models') for f in ('config.json','tokenizer.json','model.safetensors')]" \
 && chmod -R a+rX /opt/models
# Confirming AI detector (SuperAnnotate, RoBERTa-large, ~1.4 GB; PyTorch).
ARG AI_CONFIRM_MODEL=SuperAnnotate/ai-detector
ARG AI_CONFIRM_MODEL_REVISION=74b2b8580915c202607c09f64f8170eaa87a6a14
RUN python -c "from huggingface_hub import hf_hub_download as d; [d('${AI_CONFIRM_MODEL}', f, revision='${AI_CONFIRM_MODEL_REVISION}', cache_dir='/opt/models') for f in ('model.safetensors','tokenizer.json','tokenizer_config.json','special_tokens_map.json','vocab.json','merges.txt','config.json')]; d('FacebookAI/roberta-large', 'config.json', revision='722cf37b1afa9454edce342e7895e588b6ff1d59', cache_dir='/opt/models')" \
 && chmod -R a+rX /opt/models
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

# Headless Chromium for PDF reports, plus Noto fonts (Latin + Arabic script for Urdu).
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-noto-core \
 && python -m playwright install --with-deps chromium \
 && chmod -R a+rX /opt/ms-playwright \
 && rm -rf /var/lib/apt/lists/*

COPY alembic.ini ./
COPY alembic ./alembic
COPY api ./api
COPY engine ./engine
COPY worker ./worker
COPY scripts ./scripts
COPY corpus ./corpus

RUN useradd --system --uid 10001 hamzonics && mkdir -p /data/uploads /data/reports && chown -R hamzonics /data
USER hamzonics

EXPOSE 8000
