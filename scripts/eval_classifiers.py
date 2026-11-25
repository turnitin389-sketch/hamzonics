"""Compare open AI-text classifiers on a labelled test set (higher score = more AI-like).

  python -m scripts.eval_classifiers testset.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

import api  # noqa: F401
from api.config import get_settings
from engine.ai.detect import clean_for_model

CANDIDATES = {
    "superannotate": ("SuperAnnotate/ai-detector", "74b2b8580915c202607c09f64f8170eaa87a6a14"),
    "e5-small-raid": ("MayZhou/e5-small-lora-ai-generated-detector", "483fc4969592dc20e00e5130e7187b5dd25dbcc7"),
    "roberta-mixed": ("andreas122001/roberta-mixed-detector", "17778f6961de03fe331e57cb29ca349877f00b24"),
    "hc3-roberta": ("Hello-SimpleAI/chatgpt-detector-roberta", "d2b342c61775d5dd0221808a79983ed3b86ffd86"),
}


def _download(repo: str, rev: str, cache: Path) -> Path:
    from huggingface_hub import snapshot_download

    return Path(snapshot_download(repo, revision=rev, cache_dir=str(cache),
                                  allow_patterns=["*.json", "*.safetensors", "*.txt", "pytorch_model.bin", "merges.txt", "vocab.*"]))


def make_scorer(name: str, cache: Path):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    repo, rev = CANDIDATES[name]
    path = _download(repo, rev, cache)
    tok = AutoTokenizer.from_pretrained(str(path))
    if name == "superannotate":
        from safetensors.torch import load_file
        from transformers import RobertaConfig, RobertaModel

        cfg_path = _download("FacebookAI/roberta-large", "722cf37b1afa9454edce342e7895e588b6ff1d59", cache)
        backbone = RobertaModel(RobertaConfig.from_pretrained(str(cfg_path)), add_pooling_layer=False)
        sd = load_file(str(path / "model.safetensors"))
        backbone.load_state_dict({k[len("roberta."):]: v for k, v in sd.items() if k.startswith("roberta.")}, strict=True)
        head = torch.nn.Linear(1024, 1)
        head.load_state_dict({"weight": sd["dense.weight"], "bias": sd["dense.bias"]})
        backbone.eval()

        def score(text: str) -> float:
            enc = tok(text, truncation=True, max_length=512, return_tensors="pt")
            with torch.inference_mode():
                h = backbone(**{k: v for k, v in enc.items() if k != "token_type_ids"}).last_hidden_state[:, 0]
                return torch.sigmoid(head(h)).item()
        return score

    model = AutoModelForSequenceClassification.from_pretrained(str(path)).eval()
    ai_idx = 1
    labels = {int(k): v.lower() for k, v in (model.config.id2label or {}).items()}
    for i, lab in labels.items():
        if any(w in lab for w in ("machine", "chatgpt", "ai", "generated", "fake")) and "human" not in lab:
            ai_idx = i

    def score(text: str) -> float:
        enc = tok(text, truncation=True, max_length=512, return_tensors="pt")
        with torch.inference_mode():
            return torch.softmax(model(**enc).logits, -1)[0, ai_idx].item()
    return score


def report(name: str, scores: list[float], items: list[dict], secs: float) -> None:
    s = np.array(scores)
    is_ai = np.array([it["label"] == "ai" for it in items])
    human = np.sort(s[~is_ai])[::-1]
    print(f"\n######## {name}   {secs:.2f} s per text   human max {human[0]:.4f}")
    groups = sorted({it["group"] for it in items})
    for target in (0.0, 0.01):
        k = int(np.floor(target * len(human)))
        th = float(human[k]) + 1e-9
        print(f"=== threshold {th:.4f}: human wrongly flagged {np.mean(s[~is_ai] > th):.1%} | AI detected {np.mean(s[is_ai] > th):.1%}")
        for g in groups:
            idx = [i for i, it in enumerate(items) if it["group"] == g]
            kind = "flagged" if items[idx[0]]["label"] == "ai" else "WRONG"
            print(f"    {g:34s} n={len(idx):3d}  {kind:7s} {np.mean(s[idx] > th):5.0%}   median {np.median(s[idx]):.3f}")


def main() -> int:
    path = Path(sys.argv[1])
    names = sys.argv[2:] or ["fakespot", *CANDIDATES]
    items = json.loads(path.read_text())
    texts = [clean_for_model(it["text"]) for it in items]
    s = get_settings()
    out = {}
    for name in names:
        try:
            if name == "fakespot":
                from engine.ai.model import get_scorer

                sc = get_scorer(s.ai_model, s.ai_model_revision, Path(s.model_dir)).score
            else:
                sc = make_scorer(name, Path(s.model_dir))
        except Exception as e:  # keep going with the other models
            print(f"!! {name} failed to load: {e!r}", flush=True)
            continue
        t0 = time.time()
        scores = [float(sc(t)) for t in texts]
        report(name, scores, items, (time.time() - t0) / len(texts))
        out[name] = scores
        sys.stdout.flush()
    Path(str(path) + ".classifiers.json").write_text(json.dumps({"scores": out, "items": [{"label": i["label"], "group": i["group"]} for i in items]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
