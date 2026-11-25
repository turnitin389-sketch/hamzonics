"""Sentence embeddings for paraphrase and cross-language matching.

Default model: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
(384-dim, 50+ languages incl. Urdu, Apache-2.0), pinned to a commit revision.
Inference is deterministic: fixed seeds, deterministic algorithms, fixed thread
count, eval mode, inference_mode, float32.
"""

from __future__ import annotations

import random
from functools import lru_cache

import numpy as np

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"  # Hugging Face commit, licence apache-2.0
DEFAULT_THRESHOLD = 0.85


class Embedder:
    def __init__(self, model_name: str = DEFAULT_MODEL, revision: str = DEFAULT_REVISION, threads: int = 1) -> None:
        import torch
        from sentence_transformers import SentenceTransformer

        random.seed(0)
        np.random.seed(0)
        torch.manual_seed(0)
        torch.use_deterministic_algorithms(True)
        torch.set_num_threads(threads)
        self._torch = torch
        self.model = SentenceTransformer(model_name, revision=revision, device="cpu")
        self.model.eval()
        self.dim = int(self.model.get_sentence_embedding_dimension() or 0)
        self.name, self.revision = model_name, revision

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        with self._torch.inference_mode():
            vecs = self.model.encode(
                texts, batch_size=32, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False
            )
        return np.asarray(vecs, dtype=np.float32)


@lru_cache(maxsize=2)
def get_embedder(model_name: str = DEFAULT_MODEL, revision: str = DEFAULT_REVISION, threads: int = 1) -> Embedder:
    """Loaded once per worker process."""
    return Embedder(model_name, revision, threads)
