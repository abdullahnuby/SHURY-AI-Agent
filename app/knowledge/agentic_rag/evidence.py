from __future__ import annotations
import hashlib
import math
import re
from datetime import date
from urllib.parse import urlparse
from app.knowledge.web_research import _tokens


def _authority(url: str) -> float:
    host = (urlparse(url).hostname or "").casefold()
    if not host:
        return 0.50
    if host.endswith(".gov") or host.endswith(".edu") or host.endswith(".ac.uk"):
        return 1.0
    if host in {"github.com", "raw.githubusercontent.com", "arxiv.org"}:
        return 0.94
    if host.endswith(".org"):
        return 0.86
    return 0.72 if host.endswith(".com") else 0.66


def _freshness(value: str | None, query: str = "") -> float:
    if not value:
        return 0.45
    m = re.match(r"(20\d\d)-(\d\d)-(\d\d)", str(value)[:10])
    if not m:
        return 0.45
    try:
        age = max(0, (date.today() - date(int(m.group(1)), int(m.group(2)), int(m.group(3)))).days)
    except Exception:
        return 0.45
    current = any(x in query.casefold() for x in ("latest", "newest", "today", "current", "أحدث", "اليوم", "حالي"))
    half = 90.0 if current else 365.0
    return math.exp(-age / half)


def _relevance(query: str, text: str) -> float:
    q = set(_tokens(query)); t = set(_tokens(text))
    if not q or not t:
        return 0.0
    return len(q & t) / len(q)


def make_evidence(source_kind: str, title: str, url: str, text: str, query: str,
                  rank: int = 0, metadata: dict | None = None, indexed: bool = False,
                  content_hash: str = "", diversity: float = 0.5, freshness_value: str | None = None):
    if not content_hash:
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    authority = 0.15 if source_kind == "synthetic_seed" else _authority(url)
    return {
        "source_kind": source_kind,
        "title": title,
        "url": url,
        "text": text,
        "query": query,
        "rank": rank,
        "relevance": round(_relevance(query, f"{title} {text}"), 6),
        "authority": round(authority, 6),
        "freshness": round(_freshness(freshness_value, query), 6),
        "diversity": round(diversity, 6),
        "indexed": indexed,
        "content_hash": content_hash,
        "metadata": dict(metadata or {}),
    }


def sentence_units(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?؟])\s+|\n+", text or "")
    return [x.strip(" -•\t") for x in parts if len(x.strip()) >= 18]


def claim_support_score(claim: str, evidence_text: str) -> float:
    q = set(_tokens(claim)); t = set(_tokens(evidence_text))
    if not q or not t:
        return 0.0
    overlap = len(q & t) / len(q)
    # Numeric tokens must be preserved exactly for a high-confidence support decision.
    qnums = set(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", claim))
    tnums = set(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", evidence_text))
    if qnums and not qnums.issubset(tnums):
        overlap *= 0.45
    return round(overlap, 6)


def extract_claims_from_evidence(query: str, evidence: list[dict], limit: int = 8) -> list[dict]:
    qterms = set(_tokens(query))
    scored = []
    for e in evidence:
        for sentence in sentence_units(e["text"]):
            overlap = len(qterms & set(_tokens(sentence))) / max(1, len(qterms))
            if overlap <= 0:
                continue
            score = 0.68 * overlap + 0.32 * (0.55 * e["relevance"] + 0.45 * e["authority"])
            scored.append((score, e, sentence))
    scored.sort(key=lambda x: (-x[0], x[1]["evidence_id"]))
    out = []
    seen = set()
    for score, e, sentence in scored:
        key = sentence.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append({"text": sentence, "support_ids": [e["evidence_id"]], "score": round(score, 6)})
        if len(out) >= limit:
            break
    return out


def detect_conflicts(claims: list[dict], evidence: list[dict]) -> list[dict]:
    # Conservative numeric and polarity conflict detector. It only compares evidence
    # that is about the same vocabulary to avoid false conflicts from unrelated sources.
    out = []
    for i, a in enumerate(evidence):
        for b in evidence[i+1:]:
            if a["source_kind"] == b["source_kind"] and a["url"] == b["url"]:
                continue
            ta, tb = set(_tokens(a["text"])), set(_tokens(b["text"]))
            overlap = len(ta & tb) / max(1, len(ta | tb))
            if overlap < 0.28:
                continue
            na = set(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", a["text"]))
            nb = set(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", b["text"]))
            if na and nb and na != nb:
                out.append({"type": "numeric", "a": a["evidence_id"], "b": b["evidence_id"],
                            "overlap": round(overlap, 6), "values_a": sorted(na), "values_b": sorted(nb)})
                continue
            pos = {" is ", " are ", " true", "yes", "نعم", "صحيح", "هو ", "هي "}
            neg = {" not ", " no ", "false", "ليس", "ليست", "غير "}
            sa, sb = a["text"].casefold(), b["text"].casefold()
            if ((any(x in sa for x in pos) and any(x in sb for x in neg)) or
                (any(x in sa for x in neg) and any(x in sb for x in pos))):
                out.append({"type": "polarity", "a": a["evidence_id"], "b": b["evidence_id"], "overlap": round(overlap, 6)})
    return out[:12]
