from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Iterable, Sequence

MODEL_NAME = os.getenv("SHURY_NLP_MODEL", "omarelshehy/Arabic-Retrieval-v1.0")

_lock = threading.RLock()
_model = None
_load_error: str | None = None
_passage_cache: dict[tuple[int, tuple[str, ...]], object] = {}


@dataclass(frozen=True)
class SemanticMatch:
    name: str
    score: float
    evidence: tuple[str, ...] = ()


def _mode() -> str:
    value = os.getenv("SHURY_NLP_MODE", "required").strip().casefold()
    if value in {"off", "disabled", "false", "0"}:
        return "off"
    if value in {"required", "strict"}:
        return "required"
    return "auto"


def get_model():
    global _model, _load_error
    if _mode() == "off":
        return None
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(
                os.getenv("SHURY_NLP_MODEL", MODEL_NAME),
                device=os.getenv("SHURY_NLP_DEVICE") or None,
                cache_folder=os.getenv("SHURY_NLP_CACHE") or None,
            )
            model.max_seq_length = min(int(getattr(model, "max_seq_length", 512) or 512), 512)
            _model = model
            _load_error = None
            return _model
        except Exception as exc:
            _load_error = f"{type(exc).__name__}: {exc}"[:500]
            if _mode() == "required":
                raise RuntimeError(f"Arabic retrieval model unavailable: {_load_error}") from exc
            return None


def model_status() -> dict[str, object]:
    mode = _mode()
    model = get_model() if mode != "off" else None
    return {
        "enabled": mode != "off",
        "mode": mode,
        "model": os.getenv("SHURY_NLP_MODEL", MODEL_NAME),
        "loaded": model is not None,
        "dimension": (
            int(model.get_sentence_embedding_dimension())
            if model is not None and hasattr(model, "get_sentence_embedding_dimension")
            else (768 if model is not None else None)
        ),
        "error": _load_error,
    }


def _prefix(text: str, kind: str) -> str:
    value = str(text or "").strip()
    return f"<{kind}>: {value}" if value else f"<{kind}>:"


def encode_queries(texts: Sequence[str] | str):
    model = get_model()
    if model is None:
        return None
    items = [texts] if isinstance(texts, str) else list(texts)
    if not items:
        return None
    return model.encode(
        [_prefix(x, "query") for x in items],
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )


def encode_passages(texts: Sequence[str] | str):
    model = get_model()
    if model is None:
        return None
    items = [texts] if isinstance(texts, str) else list(texts)
    if not items:
        return None
    return model.encode(
        [_prefix(x, "passage") for x in items],
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )


def _cached_passage_vectors(texts: Sequence[str]):
    model = get_model()
    if model is None or not texts:
        return None
    key = (id(model), tuple(str(x or "") for x in texts))
    with _lock:
        cached = _passage_cache.get(key)
    if cached is not None:
        return cached
    encoded = encode_passages(texts)
    if encoded is None:
        return None
    with _lock:
        if len(_passage_cache) >= 8:
            _passage_cache.pop(next(iter(_passage_cache)))
        _passage_cache[key] = encoded
    return encoded


def rank_query_against_texts(query: str, items: Iterable[tuple[str, str]], *, top_k: int = 10) -> list[SemanticMatch]:
    rows = list(items)
    if not rows:
        return []
    query_vec = encode_queries([query])
    passage_vecs = _cached_passage_vectors([text for _, text in rows])
    if query_vec is None or passage_vecs is None:
        return []
    scores = passage_vecs @ query_vec[0]
    ranked = sorted(
        ((name, float(score)) for (name, _), score in zip(rows, scores)),
        key=lambda x: (-x[1], x[0]),
    )
    return [
        SemanticMatch(name, max(0.0, min(1.0, score)), ("arabic-retrieval-v1.0",))
        for name, score in ranked[: max(1, top_k)]
    ]


def query_vector(text: str):
    encoded = encode_queries([text])
    return encoded[0] if encoded is not None else None


def passage_vectors(texts: Sequence[str]):
    return encode_passages(texts)


__all__ = [
    "MODEL_NAME", "SemanticMatch", "get_model", "model_status",
    "encode_queries", "encode_passages", "rank_query_against_texts",
    "query_vector", "passage_vectors",
]
