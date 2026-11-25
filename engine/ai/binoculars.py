"""Binoculars: zero-shot AI-text detection with two small language models (no training on
any particular chatbot, so it also works on text from new models).

Hans et al., "Spotting LLMs With Binoculars: Zero-Shot Detection of Machine-Generated Text"
(2024). score = log-perplexity of the text under the PERFORMER model / cross-perplexity
between the OBSERVER's and the PERFORMER's next-token predictions. Machine text is
unusually predictable relative to how surprising the models expect it to be, so its score
is LOW; human text scores higher. Here with Qwen2.5-0.5B (observer) and Qwen2.5-0.5B-Instruct
(performer), which run on a CPU. Needs PyTorch (server/Docker).
"""

from __future__ import annotations

import math
import threading
from pathlib import Path

MAX_TOKENS = 512

_lock = threading.Lock()
_cache: dict[tuple[str, str, str, str], "BinocularsScorer"] = {}


class BinocularsScorer:
    def __init__(self, observer_dir: Path, performer_dir: Path, name: str, threshold: float, threads: int = 1) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        torch.set_num_threads(max(1, threads))
        self.torch = torch
        self.name = name
        self.threshold = threshold
        self.tokenizer = AutoTokenizer.from_pretrained(str(observer_dir))
        self.observer = AutoModelForCausalLM.from_pretrained(str(observer_dir), torch_dtype=torch.float32).eval()
        self.performer = AutoModelForCausalLM.from_pretrained(str(performer_dir), torch_dtype=torch.float32).eval()

    def count_tokens(self, text: str) -> int:
        return len(self.tokenizer(text, add_special_tokens=False)["input_ids"])

    def raw(self, text: str) -> float:
        """The Binoculars score itself (lower = more machine-like)."""
        torch = self.torch
        ids = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=MAX_TOKENS)["input_ids"]
        if ids.shape[1] < 8:
            return float("inf")
        with torch.inference_mode():
            obs = self.observer(ids).logits[:, :-1].float()
            perf = self.performer(ids).logits[:, :-1].float()
            targets = ids[:, 1:]
            log_ppl = torch.nn.functional.cross_entropy(perf.transpose(1, 2), targets).item()
            x_ppl = -(torch.softmax(obs, -1) * torch.log_softmax(perf, -1)).sum(-1).mean().item()
        return log_ppl / x_ppl if x_ppl > 0 else float("inf")

    def score(self, text: str) -> float:
        """Probability-like value in 0..1 (0.5 at the calibrated threshold, higher = more AI)."""
        b = self.raw(text)
        if math.isinf(b):
            return 0.0
        return 1.0 / (1.0 + math.exp((b - self.threshold) * 40.0))


def download(repo: str, revision: str, cache_dir: Path) -> Path:
    from huggingface_hub import snapshot_download

    return Path(snapshot_download(repo, revision=revision, cache_dir=str(cache_dir),
                                  allow_patterns=["*.json", "*.safetensors", "*.txt", "merges.txt", "vocab.json"]))


def get_binoculars(observer: str, observer_rev: str, performer: str, performer_rev: str, cache_dir: Path,
                   threshold: float, threads: int = 1) -> BinocularsScorer:
    key = (observer, observer_rev, performer, performer_rev)
    with _lock:
        if key not in _cache:
            _cache[key] = BinocularsScorer(download(observer, observer_rev, cache_dir),
                                           download(performer, performer_rev, cache_dir),
                                           f"binoculars({observer.split('/')[-1]})", threshold, threads)
        return _cache[key]
