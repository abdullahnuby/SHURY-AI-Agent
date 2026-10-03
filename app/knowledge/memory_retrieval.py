"""Deterministic hybrid retrieval for scoped personal memory.

Phase 11 fuses multiple independent signals only after the candidate set has been
security-filtered. No recency, importance, or semantic similarity signal can
bypass ownership/scope constraints.
"""
from __future__ import annotations

from collections import Counter
import math
import re
import time
from typing import Iterable

from app.intelligence.understanding import normalize
from app.knowledge.memory_models import MemoryHit, MemoryItem


# Fixed fusion weights. When semantic retrieval is unavailable, the remaining
# active signals are renormalized deterministically; no signal can create a
# candidate that failed the scope/ownership gate.
_SIGNAL_WEIGHTS = {
    "semantic": 0.30,
    "lexical": 0.22,
    "exact_key": 0.18,
    "entity": 0.08,
    "character": 0.06,
    "temporal": 0.05,
    "confidence": 0.04,
    "importance": 0.03,
    "recency": 0.02,
    "type": 0.02,
}


def tokens(text: str) -> list[str]:
    return re.findall(r"[\w\u0600-\u06ff]+", normalize(text), flags=re.UNICODE)


def char_ngrams(text: str, n: int = 3) -> set[str]:
    t = " ".join(tokens(text))
    return {t[i : i + n] for i in range(max(0, len(t) - n + 1))}


def _cosine(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a) * len(b))


def _bm25(query_tokens: list[str], docs: list[list[str]]) -> list[float]:
    n = len(docs)
    if not n:
        return []
    df: Counter[str] = Counter()
    avgdl = sum(len(d) for d in docs) / max(1, n)
    tf_docs: list[Counter[str]] = []
    for d in docs:
        tf = Counter(d)
        tf_docs.append(tf)
        df.update(tf.keys())
    scores: list[float] = []
    for tf, doc in zip(tf_docs, docs):
        score = 0.0
        dl = len(doc)
        for term in query_tokens:
            freq = tf.get(term, 0)
            if not freq:
                continue
            dft = df.get(term, 0)
            idf = math.log(1.0 + (n - dft + 0.5) / (dft + 0.5))
            k1, b = 1.2, 0.75
            score += idf * ((freq * (k1 + 1.0)) / (freq + k1 * (1.0 - b + b * dl / max(avgdl, 1.0))))
        scores.append(score)
    return scores


def _recency_boost(ts: str | None, half_life_days: float = 45.0, reference: str | None = None) -> float:
    if not ts:
        return 0.0
    try:
        then = time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%S"))
        reference_epoch = time.time() if reference is None else time.mktime(time.strptime(reference, "%Y-%m-%dT%H:%M:%S"))
        age = max(0.0, reference_epoch - then)
        return math.exp(-age / (86400.0 * max(half_life_days, 1e-6)))
    except Exception:
        return 0.0


def _temporal_relevance(item: MemoryItem, now: str | None = None) -> float:
    current = now or time.strftime("%Y-%m-%dT%H:%M:%S")
    if item.valid_at and item.valid_at > current:
        return 0.0
    if item.invalid_at and item.invalid_at <= current:
        return 0.0
    if item.expires_at and item.expires_at < current:
        return 0.0
    return 1.0


def _temporal_valid(item: MemoryItem, now: str | None = None) -> bool:
    current = now or time.strftime("%Y-%m-%dT%H:%M:%S")
    if now is None and item.status != "active":
        return False
    if item.valid_at and item.valid_at > current:
        return False
    if item.expires_at and item.expires_at < current:
        return False
    if item.invalid_at and item.invalid_at <= current:
        return False
    return True


def _canonical_query_key(query: str) -> str:
    value = re.sub(r"\s+", " ", str(query or "").strip(" \t:،,؟?"))
    folded = value.casefold()
    if folded.startswith("my "):
        value = value[3:].strip()
    return value.casefold()


def _exact_key_signal(query: str, key: str | None) -> float:
    if not key:
        return 0.0
    q = _canonical_query_key(query)
    k = _canonical_query_key(key)
    return 1.0 if q and k and q == k else 0.0


def _type_signal(kind: str) -> float:
    # Use the canonical Phase-4 contract as the source of type priority so the
    # retrieval layer cannot silently invent a second type hierarchy.
    try:
        from app.knowledge.memory_types import contract_for
        priority = int(contract_for(str(kind).casefold()).retrieval_priority)
        return max(0.0, min(1.0, priority / 100.0))
    except Exception:
        return 0.5


def _semantic_scores(query: str, rows: list[tuple[str, str]]) -> dict[str, float]:
    if not rows:
        return {}
    try:
        from app.intelligence.semantic.retrieval import rank_query_against_texts
        matches = rank_query_against_texts(query, rows, top_k=len(rows))
    except Exception:
        # Semantic retrieval is an optional signal at runtime. Failure here must
        # degrade to deterministic lexical retrieval, never fail the memory query.
        return {}
    return {str(match.name): max(0.0, min(1.0, float(match.score))) for match in matches}


def _scope_allows(
    item: MemoryItem,
    *,
    scope: str | None,
    owner_id: str | None,
    session_id: str | None,
    run_id: str | None,
) -> bool:
    """Security gate: candidate eligibility is decided before ranking."""
    if scope is not None and item.scope != scope:
        return False
    if scope in {"user", "session", "run"}:
        if str(item.owner_id or "") != str(owner_id or ""):
            return False
    if scope in {"session", "run"} and str(item.session_id or "") != str(session_id or ""):
        return False
    if scope == "run" and str(item.run_id or "") != str(run_id or ""):
        return False
    return True


def search(
    items: Iterable[MemoryItem],
    query: str,
    *,
    top_k: int = 8,
    kinds: set[str] | None = None,
    scope: str | None = None,
    owner_id: str | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
    include_expired: bool = False,
    as_of: str | None = None,
) -> list[MemoryHit]:
    q_tokens = tokens(query)
    if not q_tokens:
        return []

    # Phase 11 requirement: ownership/scope filtering happens before ANY scoring.
    raw_items = list(items)
    eligible: list[MemoryItem] = []
    for item in raw_items:
        if kinds and item.kind not in kinds:
            continue
        if not _scope_allows(item, scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id):
            continue
        if not include_expired and not _temporal_valid(item, now=as_of):
            continue
        eligible.append(item)
    if not eligible:
        return []

    candidates: list[tuple[MemoryItem, list[str], set[str], set[str], str]] = []
    for item in eligible:
        hay = " ".join(x for x in (item.key, item.value, item.kind, jsonish(item.metadata)) if x)
        d = tokens(hay)
        candidates.append((item, d, char_ngrams(hay), set(d), hay))

    bm25 = _bm25(q_tokens, [c[1] for c in candidates])
    q_ngrams = char_ngrams(query)
    qset = set(q_tokens)
    semantic_rows = [(str(c[0].id), c[4]) for c in candidates]
    semantic_scores = _semantic_scores(query, semantic_rows)
    retrieval_reference = as_of or time.strftime("%Y-%m-%dT%H:%M:%S")

    scored: list[MemoryHit] = []
    for idx, (item, d, ng, dset, _hay) in enumerate(candidates):
        lexical_raw = bm25[idx]
        max_bm25 = max(bm25) if bm25 else 0.0
        lexical = lexical_raw / max_bm25 if max_bm25 > 0 else 0.0
        phrase = 1.0 if " ".join(q_tokens) in " ".join(d) else 0.0
        char = _cosine(q_ngrams, ng)
        overlap = len(qset & dset) / max(1, len(qset))
        lexical_signal = max(lexical, phrase, overlap)

        entity_values = item.metadata.get("entities", []) if isinstance(item.metadata, dict) else []
        entity_matches = len(qset & set(tokens(jsonish(entity_values)))) if entity_values else 0
        entity = min(1.0, entity_matches / max(1, len(qset)))
        semantic = semantic_scores.get(str(item.id), 0.0)
        exact_key = _exact_key_signal(query, item.key)
        temporal = _temporal_relevance(item, now=as_of)
        recency = _recency_boost(item.updated_at or item.created_at, reference=retrieval_reference)
        confidence = max(0.0, min(1.0, item.confidence))
        importance = max(0.0, min(1.0, (max(1, min(5, item.importance)) - 1) / 4.0))
        type_signal = _type_signal(item.kind)

        # Do not let auxiliary signals retrieve an unrelated record.
        # Semantic similarity is now a valid primary evidence signal; when the model
        # is unavailable, lexical/character/exact-key evidence remains sufficient.
        primary = max(semantic, lexical_signal, char if char >= 0.70 else 0.0, exact_key, entity)
        if primary <= 0.0:
            continue

        signals = {
            "semantic": semantic,
            "lexical": lexical_signal,
            "exact_key": exact_key,
            "entity": entity,
            "character": char,
            "temporal": temporal,
            "confidence": confidence,
            "importance": importance,
            "recency": recency,
            "type": type_signal,
        }
        active_weights = {name: weight for name, weight in _SIGNAL_WEIGHTS.items() if name != "semantic" or bool(semantic_scores)}
        denominator = sum(active_weights.values()) or 1.0
        score = sum(active_weights[name] * signals[name] for name in active_weights) / denominator

        reasons: list[str] = []
        if semantic >= 0.45: reasons.append("semantic")
        if lexical > 0: reasons.append("lexical")
        if phrase: reasons.append("phrase")
        if exact_key: reasons.append("exact_key")
        if char >= 0.25: reasons.append("character")
        if entity: reasons.append("entity")
        if temporal: reasons.append("temporal")
        if recency > 0.4: reasons.append("recent")
        if item.importance >= 4: reasons.append("important")
        if item.confidence >= 0.9: reasons.append("confident")
        reasons.append(f"type:{item.kind}")
        scored.append(MemoryHit(item=item, score=score, reasons=tuple(reasons)))

    scored.sort(key=lambda h: (-h.score, -h.item.importance, -h.item.id))

    # Lightweight deterministic MMR-style diversification by value similarity.
    selected: list[MemoryHit] = []
    remaining = scored[:]
    while remaining and len(selected) < max(1, int(top_k)):
        if not selected:
            chosen = remaining.pop(0)
        else:
            def mmr(hit: MemoryHit) -> float:
                redundancy = max(
                    _cosine(char_ngrams(hit.item.value), char_ngrams(other.item.value))
                    for other in selected
                )
                return hit.score - 0.28 * redundancy
            idx = max(range(len(remaining)), key=lambda i: (mmr(remaining[i]), -remaining[i].item.id))
            chosen = remaining.pop(idx)
        selected.append(chosen)
    return selected


def jsonish(value: object) -> str:
    if not isinstance(value, dict):
        return str(value or "")
    return " ".join(f"{k} {v}" for k, v in value.items())
