"""Second AI-writing detector: desklib/ai-text-detector-v1.01 (MIT licence).

A DeBERTa-v3-large encoder + mean pooling + one linear output (sigmoid = probability of AI),
trained on the RAID benchmark, which includes "humanized" text (paraphrasing, synonym swaps,
misspellings). It needs PyTorch (available in the Docker/server image, not on every Windows PC).
"""

from __future__ import annotations

import threading
from pathlib import Path

FILES = ("config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
         "spm.model", "added_tokens.json")
MAX_TOKENS = 768

_lock = threading.Lock()
_cache: dict[tuple[str, str], "DesklibScorer"] = {}


class DesklibScorer:
    def __init__(self, model_dir: Path, name: str, threads: int = 1) -> None:
        import torch
        from safetensors.torch import load_file
        from transformers import AutoConfig, AutoModel, AutoTokenizer

        torch.set_num_threads(max(1, threads))
        self.torch = torch
        self.name = name
        config = AutoConfig.from_pretrained(str(model_dir))
        self.encoder = AutoModel.from_config(config)
        self.head = torch.nn.Linear(config.hidden_size, 1)
        state = load_file(str(model_dir / "model.safetensors"))
        enc_state = {k[len("model."):]: state.pop(k) for k in list(state) if k.startswith("model.")}
        missing, _ = self.encoder.load_state_dict(enc_state, strict=False)
        del enc_state
        self.head.load_state_dict({k[len("classifier."):]: v for k, v in state.items() if k.startswith("classifier.")})
        del state
        if [m for m in missing if "position_ids" not in m]:
            raise RuntimeError(f"Desklib weights incomplete: {missing[:5]}")
        self.encoder.eval()
        self.head.eval()
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_dir))

    def count_tokens(self, text: str) -> int:
        return len(self.tokenizer(text, add_special_tokens=False)["input_ids"])

    def score(self, text: str) -> float:
        torch = self.torch
        enc = self.tokenizer(text, truncation=True, max_length=MAX_TOKENS, return_tensors="pt")
        with torch.inference_mode():
            hidden = self.encoder(input_ids=enc["input_ids"], attention_mask=enc["attention_mask"]).last_hidden_state
            mask = enc["attention_mask"].unsqueeze(-1).float()
            pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            return float(torch.sigmoid(self.head(pooled)).item())


def download(repo: str, revision: str, cache_dir: Path) -> Path:
    from huggingface_hub import hf_hub_download

    path = None
    for f in FILES:
        try:
            path = Path(hf_hub_download(repo, f, revision=revision, cache_dir=str(cache_dir)))
        except Exception:
            if f in ("config.json", "model.safetensors", "tokenizer.json"):
                raise
    assert path is not None
    return path.parent


def get_desklib(repo: str, revision: str, cache_dir: Path, threads: int = 1) -> DesklibScorer:
    key = (repo, revision)
    with _lock:
        if key not in _cache:
            _cache[key] = DesklibScorer(download(repo, revision, cache_dir), f"{repo}@{revision[:7]}", threads)
        return _cache[key]
