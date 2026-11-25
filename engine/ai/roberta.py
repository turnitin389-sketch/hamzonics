"""RoBERTa sequence classifier in plain numpy (no PyTorch).

Runs a Hugging Face `RobertaForSequenceClassification` checkpoint (safetensors) on the
CPU. PyTorch is a 700 MB dependency that does not load on every Windows PC; the
forward pass of RoBERTa-base is only a few matrix products, so numpy (OpenBLAS) does
it at a similar speed for one text at a time.

Exactness: same operations as transformers' RobertaModel in eval mode (no dropout),
GELU with erf, LayerNorm eps from config. Inputs are never padded (one chunk per call),
so no attention mask is needed.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np


def _erf(x: np.ndarray) -> np.ndarray:
    """Abramowitz & Stegun 7.1.26 (max abs error 1.5e-7), vectorised."""
    sign = np.sign(x)
    a = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * a)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * np.exp(-a * a)
    return sign * y


def _gelu(x: np.ndarray) -> np.ndarray:
    return 0.5 * x * (1.0 + _erf(x / math.sqrt(2.0)))


def _layer_norm(x: np.ndarray, w: np.ndarray, b: np.ndarray, eps: float) -> np.ndarray:
    mean = x.mean(-1, keepdims=True)
    var = ((x - mean) ** 2).mean(-1, keepdims=True)
    return (x - mean) / np.sqrt(var + eps) * w + b


def _softmax(x: np.ndarray) -> np.ndarray:
    x = x - x.max(-1, keepdims=True)
    e = np.exp(x)
    return e / e.sum(-1, keepdims=True)


@dataclass
class _Layer:
    qkv_w: np.ndarray  # (hidden, 3*hidden), already transposed
    qkv_b: np.ndarray
    attn_out_w: np.ndarray
    attn_out_b: np.ndarray
    ln1_w: np.ndarray
    ln1_b: np.ndarray
    inter_w: np.ndarray
    inter_b: np.ndarray
    out_w: np.ndarray
    out_b: np.ndarray
    ln2_w: np.ndarray
    ln2_b: np.ndarray


class RobertaClassifier:
    """`RobertaClassifier(model_dir).probabilities(input_ids)` -> softmax over labels."""

    def __init__(self, model_dir: Path) -> None:
        from safetensors.numpy import load_file

        cfg = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
        if cfg.get("model_type") != "roberta":
            raise ValueError(f"Expected a RoBERTa checkpoint, got {cfg.get('model_type')!r}")
        self.labels = {int(k): v for k, v in cfg["id2label"].items()}
        self.heads = int(cfg["num_attention_heads"])
        self.hidden = int(cfg["hidden_size"])
        self.eps = float(cfg.get("layer_norm_eps", 1e-5))
        self.pad_id = int(cfg.get("pad_token_id", 1))
        self.max_positions = int(cfg["max_position_embeddings"]) - self.pad_id - 1  # 512 for roberta-base

        w = load_file(str(model_dir / "model.safetensors"))
        f32 = {k: v.astype(np.float32, copy=False) for k, v in w.items()}

        def g(name: str) -> np.ndarray:
            for prefix in ("roberta.", ""):
                if prefix + name in f32:
                    return f32[prefix + name]
            raise KeyError(name)

        self.word_emb = g("embeddings.word_embeddings.weight")
        self.pos_emb = g("embeddings.position_embeddings.weight")
        self.type_emb = g("embeddings.token_type_embeddings.weight")[0]
        self.emb_ln = (g("embeddings.LayerNorm.weight"), g("embeddings.LayerNorm.bias"))
        self.layers: list[_Layer] = []
        for i in range(int(cfg["num_hidden_layers"])):
            p = f"encoder.layer.{i}."
            q, k, v = (g(p + f"attention.self.{n}.weight") for n in ("query", "key", "value"))
            qb, kb, vb = (g(p + f"attention.self.{n}.bias") for n in ("query", "key", "value"))
            self.layers.append(_Layer(
                qkv_w=np.ascontiguousarray(np.concatenate([q, k, v], 0).T),
                qkv_b=np.concatenate([qb, kb, vb]),
                attn_out_w=np.ascontiguousarray(g(p + "attention.output.dense.weight").T),
                attn_out_b=g(p + "attention.output.dense.bias"),
                ln1_w=g(p + "attention.output.LayerNorm.weight"), ln1_b=g(p + "attention.output.LayerNorm.bias"),
                inter_w=np.ascontiguousarray(g(p + "intermediate.dense.weight").T), inter_b=g(p + "intermediate.dense.bias"),
                out_w=np.ascontiguousarray(g(p + "output.dense.weight").T), out_b=g(p + "output.dense.bias"),
                ln2_w=g(p + "output.LayerNorm.weight"), ln2_b=g(p + "output.LayerNorm.bias"),
            ))
        self.cls_dense = (np.ascontiguousarray(f32["classifier.dense.weight"].T), f32["classifier.dense.bias"])
        self.cls_out = (np.ascontiguousarray(f32["classifier.out_proj.weight"].T), f32["classifier.out_proj.bias"])

    def probabilities(self, input_ids: list[int]) -> np.ndarray:
        n = len(input_ids)
        if n == 0 or n > self.max_positions:
            raise ValueError(f"Sequence length {n} is outside 1..{self.max_positions}")
        ids = np.asarray(input_ids, dtype=np.int64)
        positions = np.arange(n) + self.pad_id + 1  # RoBERTa: positions start after the padding index
        x = self.word_emb[ids] + self.pos_emb[positions] + self.type_emb
        x = _layer_norm(x, *self.emb_ln, self.eps)

        h, d = self.heads, self.hidden // self.heads
        scale = 1.0 / math.sqrt(d)
        for L in self.layers:
            qkv = x @ L.qkv_w + L.qkv_b  # (n, 3*hidden)
            q, k, v = (qkv[:, i * self.hidden : (i + 1) * self.hidden].reshape(n, h, d).transpose(1, 0, 2) for i in range(3))
            attn = _softmax((q @ k.transpose(0, 2, 1)) * scale)  # (h, n, n)
            ctx = (attn @ v).transpose(1, 0, 2).reshape(n, self.hidden)
            x = _layer_norm(ctx @ L.attn_out_w + L.attn_out_b + x, L.ln1_w, L.ln1_b, self.eps)
            ff = _gelu(x @ L.inter_w + L.inter_b) @ L.out_w + L.out_b
            x = _layer_norm(ff + x, L.ln2_w, L.ln2_b, self.eps)

        cls = np.tanh(x[0] @ self.cls_dense[0] + self.cls_dense[1])
        logits = cls @ self.cls_out[0] + self.cls_out[1]
        return _softmax(logits.astype(np.float64))
