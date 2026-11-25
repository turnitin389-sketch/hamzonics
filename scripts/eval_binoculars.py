"""Evaluate Binoculars raw scores on a labelled test set (lower score = more AI-like).

  python -m scripts.eval_binoculars testset.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

import api  # noqa: F401
from api.config import get_settings
from engine.ai.binoculars import get_binoculars
from engine.ai.detect import clean_for_model


def main() -> int:
    path = Path(sys.argv[1])
    items = json.loads(path.read_text())
    s = get_settings()
    t0 = time.time()
    sc = get_binoculars(s.ai3_observer, s.ai3_observer_revision, s.ai3_performer, s.ai3_performer_revision,
                        Path(s.model_dir), s.ai3_threshold, s.torch_threads)
    print(f"models loaded in {time.time() - t0:.0f}s", flush=True)
    t0 = time.time()
    raw = []
    for i, it in enumerate(items):
        raw.append(sc.raw(clean_for_model(it["text"])))
        if i % 25 == 0:
            print(f"  {i}/{len(items)}  {(time.time() - t0) / (i + 1):.2f}s per text", flush=True)
    raw_a = np.array(raw)
    labels = np.array([it["label"] == "ai" for it in items])
    human = np.sort(raw_a[~labels])
    print(f"\n{(time.time() - t0) / len(items):.2f} s per text")
    print("human scores: min %.3f  p1 %.3f  p5 %.3f  median %.3f" % (human[0], np.quantile(human, .01), np.quantile(human, .05), np.median(human)))
    groups = sorted({it["group"] for it in items})
    for target in (0.0, 0.01, 0.03):
        k = int(np.floor(target * len(human)))
        th = float(human[k]) - 1e-6  # AI = score BELOW this
        fp = float(np.mean(human < th))
        print(f"\n=== threshold {th:.4f}: human wrongly flagged {fp:.1%} | AI detected {np.mean(raw_a[labels] < th):.1%}")
        for g in groups:
            idx = [i for i, it in enumerate(items) if it["group"] == g]
            kind = "flagged" if items[idx[0]]["label"] == "ai" else "WRONGLY flagged"
            print(f"    {g:34s} n={len(idx):3d}  {kind}: {np.mean(raw_a[idx] < th):5.0%}   median score {np.median(raw_a[idx]):.3f}")
    Path(str(path) + ".binoculars.json").write_text(json.dumps({"raw": raw, "items": [{"label": i["label"], "group": i["group"]} for i in items]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
