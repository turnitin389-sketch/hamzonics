"""DeskLib loader: meta-device loading and the int8 option, on a tiny random DeBERTa-v2 model.

Needs PyTorch (present in the Docker image; skipped where torch cannot load, e.g. some Windows PCs).
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _tiny_model(tmp_path: Path) -> Path:
    torch = pytest.importorskip("torch")
    from safetensors.torch import save_file
    from transformers import DebertaV2Config, DebertaV2Model

    torch.manual_seed(0)
    cfg = DebertaV2Config(vocab_size=128, hidden_size=32, num_hidden_layers=2, num_attention_heads=2,
                          intermediate_size=64, max_position_embeddings=64)
    enc = DebertaV2Model(cfg)
    head = torch.nn.Linear(cfg.hidden_size, 1)
    state = {f"model.{k}": v.contiguous() for k, v in enc.state_dict().items() if "position_ids" not in k}
    state.update({f"classifier.{k}": v.contiguous() for k, v in head.state_dict().items()})
    save_file(state, str(tmp_path / "model.safetensors"))
    cfg.save_pretrained(str(tmp_path))
    return tmp_path


class _Tok:
    """Minimal tokenizer stand-in: one id per character (no tokenizer files needed)."""

    def __call__(self, text, truncation=True, max_length=768, return_tensors=None, add_special_tokens=True):  # type: ignore[no-untyped-def]
        import torch

        ids = [min(ord(c), 127) for c in text][:max_length] or [0]
        if return_tensors == "pt":
            return {"input_ids": torch.tensor([ids]), "attention_mask": torch.ones(1, len(ids), dtype=torch.long)}
        return {"input_ids": ids}


def _scorer(model_dir: Path, quantize: bool, monkeypatch):  # type: ignore[no-untyped-def]
    import transformers

    from engine.ai.desklib import DesklibScorer

    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained", staticmethod(lambda *a, **k: _Tok()))
    return DesklibScorer(model_dir, "tiny", threads=1, quantize=quantize)


def test_loads_without_meta_tensors_and_scores(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    s = _scorer(_tiny_model(tmp_path), False, monkeypatch)
    assert not any(p.is_meta for p in s.encoder.parameters())
    assert not any(b.is_meta for b in s.encoder.buffers())
    p = s.score("Some text to score.")
    assert 0.0 <= p <= 1.0


def test_int8_scores_stay_close_to_fp32(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    model_dir = _tiny_model(tmp_path)
    full = _scorer(model_dir, False, monkeypatch)
    small = _scorer(model_dir, True, monkeypatch)
    assert small.name.endswith("int8")
    for text in ("A short sentence.", "Another, somewhat longer piece of text for the model to read."):
        assert abs(full.score(text) - small.score(text)) < 0.05
