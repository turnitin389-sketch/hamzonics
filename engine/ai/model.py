"""Load the AI-writing classifier (downloaded once from Hugging Face, pinned revision).

Default model: fakespot-ai/roberta-base-ai-text-detection-v1 (Mozilla Fakespot,
Apache-2.0), a RoBERTa-base fine-tuned to tell human from LLM text. It runs on the
CPU with numpy (engine/ai/roberta.py), so PyTorch is not needed.
"""

from __future__ import annotations

import threading
from pathlib import Path

from engine.ai.roberta import RobertaClassifier

FILES = ("config.json", "tokenizer.json", "model.safetensors")

_lock = threading.Lock()
_cache: dict[tuple[str, str], "RobertaScorer"] = {}


class RobertaScorer:
    def __init__(self, model_dir: Path, name: str) -> None:
        from tokenizers import Tokenizer

        self.name = name
        self.model = RobertaClassifier(model_dir)
        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        ai = [i for i, label in self.model.labels.items() if label.lower() in ("ai", "fake", "machine", "generated", "label_1")]
        self.ai_index = ai[0] if ai else 1

    def count_tokens(self, text: str) -> int:
        return len(self.tokenizer.encode(text, add_special_tokens=False).ids)

    def score(self, text: str) -> float:
        ids = self.tokenizer.encode(text, add_special_tokens=True).ids
        limit = self.model.max_positions
        if len(ids) > limit:  # keep <s> ... </s>
            ids = ids[: limit - 1] + ids[-1:]
        return float(self.model.probabilities(ids)[self.ai_index])


def download(repo: str, revision: str, cache_dir: Path) -> Path:
    from huggingface_hub import hf_hub_download

    path = None
    for f in FILES:
        path = Path(hf_hub_download(repo, f, revision=revision, cache_dir=str(cache_dir)))
    assert path is not None
    return path.parent


def get_scorer(repo: str, revision: str, cache_dir: Path) -> RobertaScorer:
    key = (repo, revision)
    with _lock:
        if key not in _cache:
            _cache[key] = RobertaScorer(download(repo, revision, cache_dir), f"{repo}@{revision[:7]}")
        return _cache[key]
