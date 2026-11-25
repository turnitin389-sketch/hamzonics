"""Feasibility: a small logistic-regression head on frozen detector features
(Fakespot + SuperAnnotate first-token hidden states) trained on marketing-style data.

  python -m scripts.train_style_head /data/train_pool.json

Items with "holdout": true (e.g. the user's BetPro / TransLabs texts) are never trained on.
Reports cross-validated scores (each text scored by a model that did not see it).
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


def features(texts: list[str]) -> np.ndarray:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    from engine.ai.superannotate import get_superannotate

    s = get_settings()
    torch.set_num_threads(max(1, s.torch_threads))
    sa = get_superannotate(s.ai_confirm_model, s.ai_confirm_model_revision, Path(s.model_dir), s.torch_threads)
    from huggingface_hub import snapshot_download

    fk_dir = snapshot_download(s.ai_model, revision=s.ai_model_revision, cache_dir=str(s.model_dir),
                               allow_patterns=["*.json", "*.safetensors", "*.txt"])
    fk_tok = AutoTokenizer.from_pretrained(fk_dir)
    fk = AutoModelForSequenceClassification.from_pretrained(fk_dir).eval()
    out = []
    t0 = time.time()
    for i, t in enumerate(texts):
        with torch.inference_mode():
            enc = sa.tokenizer(t, truncation=True, max_length=512, return_tensors="pt")
            h_sa = sa.encoder(input_ids=enc["input_ids"], attention_mask=enc["attention_mask"]).last_hidden_state[0, 0]
            p_sa = torch.sigmoid(sa.head(h_sa)).item()
            enc2 = fk_tok(t, truncation=True, max_length=512, return_tensors="pt")
            o = fk(**enc2, output_hidden_states=True)
            h_fk = o.hidden_states[-1][0, 0]
            p_fk = torch.softmax(o.logits, -1)[0, -1].item()
        out.append(np.concatenate([h_sa.numpy(), h_fk.numpy(), [p_sa, p_fk]]))
        if i % 50 == 0:
            print(f"  features {i}/{len(texts)}  {(time.time() - t0) / (i + 1):.2f}s each", flush=True)
    return np.array(out, dtype=np.float32)


def main() -> int:
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    path = Path(sys.argv[1])
    items = json.loads(path.read_text())
    cache = Path(str(path) + ".features.npy")
    if cache.exists() and len(np.load(cache)) == len(items):
        X = np.load(cache)
    else:
        X = features([clean_for_model(it["text"]) for it in items])
        np.save(cache, X)
    y = np.array([it["label"] == "ai" for it in items], dtype=int)
    hold = np.array([bool(it.get("holdout")) for it in items])
    groups = [it["group"] for it in items]
    tr = np.where(~hold)[0]

    def model():  # type: ignore[no-untyped-def]
        return make_pipeline(StandardScaler(), LogisticRegression(C=0.05, max_iter=5000, class_weight="balanced"))

    cv = np.zeros(len(items))
    skf = StratifiedKFold(5, shuffle=True, random_state=0)
    strat = [f"{y[i]}-{groups[i]}" for i in tr]
    strat = [s if strat.count(s) >= 5 else str(y[i]) for s, i in zip(strat, tr)]
    for a, b in skf.split(tr, strat):
        m = model().fit(X[tr[a]], y[tr[a]])
        cv[tr[b]] = m.predict_proba(X[tr[b]])[:, 1]
    full = model().fit(X[tr], y[tr])
    cv[hold] = full.predict_proba(X[hold])[:, 1]

    human_cv = np.sort(cv[tr][y[tr] == 0])[::-1]
    print(f"\n{len(tr)} training texts ({y[tr].sum()} AI), {hold.sum()} hold-out texts never trained on")
    print("top human CV scores:", np.round(human_cv[:8], 4))
    for th in (human_cv[0] + 1e-6, human_cv[1] + 1e-6, 0.9, 0.95, 0.99):
        print(f"\n=== threshold {th:.4f}: human wrongly flagged {np.sum(cv[y == 0] >= th)} / {np.sum(y == 0)}")
        for g in sorted(set(groups)):
            idx = [i for i in range(len(items)) if groups[i] == g]
            kind = "AI det" if y[idx[0]] else "WRONG "
            print(f"    {g:34s} n={len(idx):3d} {kind} {np.mean(cv[idx] >= th):5.0%}  median {np.median(cv[idx]):.3f}"
                  + ("  [HOLD-OUT]" if hold[idx[0]] else ""))
    Path(str(path) + ".cv.json").write_text(json.dumps({"cv": cv.tolist(), "groups": groups, "y": y.tolist()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
