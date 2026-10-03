"""Hybrid deterministic memory retrieval.

Signals intentionally mirror current production memory research patterns without
claiming semantic embeddings: BM25-like lexical relevance, character similarity,
entity overlap, recency, importance, confidence, scope, and diversity.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import math
import re
import time
from dataclasses import replace
from typing import Iterable

from app.intelligence.understanding import normalize
from app.knowledge.memory_models import MemoryHit, MemoryItem


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


def _recency_boost(ts: str | None, half_life_days: float = 45.0) -> float:
    if not ts:
        return 0.0
    try:
        then = time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%S"))
        age = max(0.0, time.time() - then)
        return math.exp(-age / (86400.0 * max(half_life_days, 1e-6)))
    except Exception:
        return 0.0


def _temporal_valid(item: MemoryItem, now: str | None = None) -> bool:
    # String ordering is safe for ISO-like timestamps used by this project.
    current = now or time.strftime("%Y-%m-%dT%H:%M:%S")
    if item.status != "active":
        return False
    if item.valid_at and item.valid_at > current:
        return False
    if item.expires_at and item.expires_at < current:
        return False
    if item.invalid_at and item.invalid_at <= current:
        return False
    return True


def search(items: Iterable[MemoryItem], query: str, *, top_k: int = 8,
           kinds: set[str] | None = None, scope: str | None = None,
           include_expired: bool = False) -> list[MemoryHit]:
    q_tokens = tokens(query)
    if not q_tokens:
        return []
    candidates = []
    for item in items:
        if kinds and item.kind not in kinds:
            continue
        if scope and item.scope not in {scope, "global"}:
            continue
        if not include_expired and not _temporal_valid(item):
            continue
        hay = " ".join(x for x in (item.key, item.value, item.kind, jsonish(item.metadata)) if x)
        d = tokens(hay)
        candidates.append((item, d, char_ngrams(hay), set(d)))
    if not candidates:
        return []
    bm25 = _bm25(q_tokens, [c[1] for c in candidates])
    q_ngrams = char_ngrams(query)
    qset = set(q_tokens)
    scored: list[MemoryHit] = []
    for idx, (item, d, ng, dset) in enumerate(candidates):
        lexical = bm25[idx]
        phrase = 1.0 if " ".join(q_tokens) in " ".join(d) else 0.0
        char = _cosine(q_ngrams, ng)
        overlap = len(qset & dset) / max(1, len(qset))
        entity_matches = len(qset & set(tokens(" ".join(item.metadata.get("entities", []))))) if isinstance(item.metadata, dict) else 0
        entity = min(1.0, entity_matches / max(1, len(qset)))
        recency = _recency_boost(item.updated_at or item.created_at)
        importance = (max(1, min(5, item.importance)) - 3) / 2.0
        confidence = max(0.0, min(1.0, item.confidence))
        access = min(item.access_count, 20) / 20.0
        # No unrelated memory may be returned merely because it is recent/important.
        # Character similarity is allowed to rescue typos, but only when it is strong enough.
        lexical_signal = lexical > 0 or phrase > 0 or overlap > 0 or entity > 0
        if not lexical_signal and char < 0.70:
            continue
        score = (1.00 * lexical) + (0.75 * phrase) + (0.55 * char) + (0.45 * overlap)
        score += (0.50 * entity) + (0.24 * recency) + (0.16 * importance) + (0.18 * confidence) + (0.04 * access)
        if item.kind == "preference":
            score += 0.08
        if item.kind == "fact":
            score += 0.06
        reasons = []
        if lexical > 0: reasons.append("lexical")
        if phrase: reasons.append("phrase")
        if char >= 0.25: reasons.append("character")
        if entity: reasons.append("entity")
        if recency > 0.4: reasons.append("recent")
        if item.importance >= 4: reasons.append("important")
        scored.append(MemoryHit(item=item, score=score, reasons=tuple(reasons)))

    scored.sort(key=lambda h: (-h.score, -h.item.importance, -h.item.id))
    # Lightweight MMR-style diversification by kind/key. This avoids returning eight
    # nearly identical revisions of the same fact.
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
