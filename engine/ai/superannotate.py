"""Confirming AI detector: SuperAnnotate/ai-detector (RoBERTa-large + one linear output on the
first token, sigmoid = probability of AI). Licence: SAIPL 1.0 (commercial use allowed; attribution
and a link to the model source are required, see THIRD_PARTY.md). Needs PyTorch (server/Docker).

It is used only to CONFIRM windows the primary model already calls AI (engine/ai/combined.py,
GateScorer): measured 2026-11-23 it removed every false alarm of the primary model on 289 human
texts without losing AI detections (scripts/eval_classifiers.py).
"""

from __future__ import annotations

import threading
from pathlib import Path

FILES = ("model.safetensors", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
         "vocab.json", "merges.txt", "config.json")
BACKBONE = ("FacebookAI/roberta-large", "722cf37b1afa9454edce342e7895e588b6ff1d59")
MAX_TOKENS = 512

_lock = threading.Lock()
_cache: dict[tuple[str, str], "SuperAnnotateScorer"] = {}


class SuperAnnotateScorer:
    def __init__(self, model_dir: Path, backbone_config_dir: Path, name: str, threads: int = 1) -> None:
        import torch
        from safetensors.torch import load_file
        from transformers import AutoTokenizer, RobertaConfig, RobertaModel

        torch.set_num_threads(max(1, threads))
        self.torch = torch
        self.name = name
        self.encoder = RobertaModel(RobertaConfig.from_pretrained(str(backbone_config_dir)), add_pooling_layer=False)
        state = load_file(str(model_dir / "model.safetensors"))
        self.encoder.load_state_dict({k[len("roberta."):]: state.pop(k) for k in list(state) if k.startswith("roberta.")},
                                     strict=True)
        self.head = torch.nn.Linear(self.encoder.config.hidden_size, 1)
        self.head.load_state_dict({"weight": state["dense.weight"], "bias": state["dense.bias"]})
        del state
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
            return float(torch.sigmoid(self.head(hidden[:, 0])).item())


def _download(repo: str, revision: str, files: tuple[str, ...], cache_dir: Path) -> Path:
    from huggingface_hub import hf_hub_download

    path = None
    for f in files:
        try:
            path = Path(hf_hub_download(repo, f, revision=revision, cache_dir=str(cache_dir)))
        except Exception:
            if f in ("model.safetensors", "tokenizer.json", "config.json"):
                raise
    assert path is not None
    return path.parent


def download_all(repo: str, revision: str, cache_dir: Path) -> tuple[Path, Path]:
    return (_download(repo, revision, FILES, cache_dir),
            _download(BACKBONE[0], BACKBONE[1], ("config.json",), cache_dir))


def get_superannotate(repo: str, revision: str, cache_dir: Path, threads: int = 1) -> SuperAnnotateScorer:
    key = (repo, revision)
    with _lock:
        if key not in _cache:
            model_dir, cfg_dir = download_all(repo, revision, cache_dir)
            _cache[key] = SuperAnnotateScorer(model_dir, cfg_dir, f"{repo}@{revision[:7]}", threads)
        return _cache[key]
