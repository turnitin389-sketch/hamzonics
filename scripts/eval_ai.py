"""Compare AI detectors on a labelled test set (JSON list of {label: human|ai, group, text}).

  python -m scripts.eval_ai testset.json [--models fakespot,desklib]

Prints per-group detection rates at thresholds that keep the false-positive rate on human
text at about 1% / 0%, and the speed per text."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

import api  # noqa: F401  (thread limits)
from api.config import get_settings
from engine.ai.detect import clean_for_model


def scorers(names: list[str]):  # type: ignore[no-untyped-def]
    s = get_settings()
    out = {}
    if "fakespot" in names:
        from engine.ai.model import get_scorer

        out["fakespot"] = get_scorer(s.ai_model, s.ai_model_revision, Path(s.model_dir))
    if "desklib" in names:
        from engine.ai.desklib import get_desklib

        out["desklib"] = get_desklib(s.ai2_model, s.ai2_model_revision, Path(s.model_dir), s.torch_threads)
    return out


def main() -> int:
    path = Path(sys.argv[1])
    names = sys.argv[sys.argv.index("--models") + 1].split(",") if "--models" in sys.argv else ["fakespot", "desklib"]
    items = json.loads(path.read_text())
    sc = scorers(names)
    results: dict[str, list[float]] = {n: [] for n in sc}
    for n, scorer in sc.items():
        t0 = time.time()
        for it in items:
            results[n].append(scorer.score(clean_for_model(it["text"])))
        print(f"{n}: {(time.time() - t0) / len(items):.2f} s per text", flush=True)
    if len(sc) == 2:
        a, b = list(sc)
        results["combined(mean)"] = [(x + y) / 2 for x, y in zip(results[a], results[b], strict=True)]
        results["combined(min)"] = [min(x, y) for x, y in zip(results[a], results[b], strict=True)]

    labels = np.array([it["label"] == "ai" for it in items])
    groups = sorted({it["group"] for it in items})
    for n, scores in results.items():
        s = np.array(scores)
        human = np.sort(s[~labels])
        print(f"\n=== {n}")
        for target in (0.0, 0.01, 0.05):
            # smallest threshold whose false-positive rate on human text is <= target
            k = int(np.floor(target * len(human)))
            th = float(human[len(human) - 1 - k]) + 1e-9 if k < len(human) else 0.5
            fp = float(np.mean(human >= th))
            tp = float(np.mean(s[labels] >= th))
            print(f"  threshold {th:.4f}: human wrongly flagged {fp:5.1%} | AI detected {tp:5.1%}")
            if target == 0.01:
                for g in groups:
                    idx = [i for i, it in enumerate(items) if it["group"] == g]
                    rate = float(np.mean(s[idx] >= th))
                    kind = "flagged" if items[idx[0]]["label"] == "ai" else "WRONGLY flagged"
                    print(f"      {g:34s} n={len(idx):3d}  {kind}: {rate:5.0%}")
    Path(str(path) + ".scores.json").write_text(json.dumps({"items": [{"label": i["label"], "group": i["group"]} for i in items],
                                                            "scores": results}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
