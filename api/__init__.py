"""Hamzonics API package."""

import os

# Must happen before numpy is imported anywhere: OpenBLAS with one thread per core
# oversubscribes the CPU when several checks run at once (10x slower matrix products).
os.environ.setdefault("OPENBLAS_NUM_THREADS", os.environ.get("BLAS_THREADS", "2"))
os.environ.setdefault("OMP_NUM_THREADS", os.environ.get("BLAS_THREADS", "2"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
