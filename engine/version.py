"""ENGINE_VERSION changes whenever any model, threshold, corpus snapshot or algorithm
changes. It is part of every result_key, so old frozen results are not reused.

CODE_FINGERPRINT is computed from the source of everything that shapes a result (engine/,
the pipeline and live-source code). It is added to the result key automatically, so a code
change can never silently reuse results computed by older code (this happened once in
testing when ENGINE_VERSION was not bumped by hand)."""

from __future__ import annotations

import hashlib
from pathlib import Path

ENGINE_VERSION = "2026.11-public5"

_ROOT = Path(__file__).resolve().parents[1]
_RESULT_CODE = ["engine", "worker/pipeline.py", "worker/web_sources.py", "worker/frozen.py", "worker/sql_index.py"]


def _fingerprint() -> str:
    h = hashlib.sha256()
    for entry in _RESULT_CODE:
        p = _ROOT / entry
        files = sorted(p.rglob("*")) if p.is_dir() else [p]
        for f in files:
            if f.is_file() and f.suffix in (".py", ".html") and "__pycache__" not in f.parts:
                h.update(f.relative_to(_ROOT).as_posix().encode())
                h.update(f.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


CODE_FINGERPRINT = _fingerprint()
