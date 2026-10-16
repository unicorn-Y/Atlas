"""Optional local text embeddings for memory search."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)
_lock = threading.Lock()
_warn_lock = threading.Lock()
_model: Any = None
_attempted = False
_last_failed_at: float | None = None
_warned = False


def _warn_unavailable(error: Exception) -> None:
    global _warned
    with _warn_lock:
        if not _warned:
            log.warning("memory.library.embed_unavailable", error=str(error))
            _warned = True


def _load_model() -> Any:
    global _model, _attempted, _last_failed_at, _warned
    with _lock:
        if _model is not None:
            return _model
        now = time.monotonic()
        if _attempted and _last_failed_at is not None and now - _last_failed_at < 600:
            return None
        _attempted = True
        try:
            from fastembed import TextEmbedding

            from atlas.config import DATA_ROOT

            cache = Path(DATA_ROOT) / "cache" / "fastembed"
            cache.mkdir(parents=True, exist_ok=True)
            _model = TextEmbedding(model_name="BAAI/bge-small-zh-v1.5", cache_dir=str(cache))
            _last_failed_at = None
            _warned = False
        except Exception as exc:  # noqa: BLE001 - missing package, download and model-load failures all disable vectors.
            _last_failed_at = time.monotonic()
            _warn_unavailable(exc)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    if not texts:
        return []
    model = _load_model()
    if model is None:
        return None
    try:
        return [list(map(float, vector)) for vector in model.embed(texts)]
    except Exception as exc:  # noqa: BLE001 - inference failures fall back to keyword search.
        _warn_unavailable(exc)
        return None
