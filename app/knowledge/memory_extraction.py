"""Provider-independent memory candidate extraction and privacy filtering.

Only explicit, high-confidence statements are promoted automatically. Secret-like
content is blocked from durable memory; ordinary conversational content remains
episodic until consolidation decides otherwise.
"""
from __future__ import annotations

import re
from app.knowledge.memory_models import MemoryCandidate
from app.intelligence.understanding import normalize

_SECRET_WORDS = re.compile(
    r"(?:password|passcode|api\s*key|access\s*token|refresh\s*token|auth\s*token|secret|cvv|credit\s*card|private\s*key|client\s*secret)",
    re.I,
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?:password|passcode|api\s*key|access\s*token|refresh\s*token|auth\s*token|secret|cvv|credit\s*card|private\s*key|client\s*secret)\s*[:=]\s*\S+",
    re.I,
)

_THEME_PREF_EN = re.compile(r"(?:i\s+prefer|i\s+like|i\s+usually\s+use)\s+(?:the\s+)?(dark|light)(?:\s+mode)?", re.I)
_THEME_PREF_AR = re.compile(r"(?:انا\s+بفضل|انا\s+احب|انا\s+عادة\s+بستخدم)\s+(?:الوضع\s+)?(الداكن|الفاتح)", re.I)

_PATTERNS = [
    ("preference", re.compile(r"(?:i\s+prefer|i\s+like|i\s+love|i\s+usually\s+use)\s+(.+)", re.I), None),
    ("preference", re.compile(r"(?:انا\s+بفضل|انا\s+احب|انا\s+عادة\s+بستخدم)\s+(.+)", re.I), None),
    ("fact", re.compile(r"(?:my\s+)([a-zA-Z][\w -]{1,48})\s+(?:is|=)\s+(.+)", re.I), "key_value"),
    ("fact", re.compile(r"(?:عندي|عندي? اسم|اسمي)\s+([^:=]{1,48})\s*(?:هو|=|:)?\s*(.+)", re.I), "arabic_key_value"),
]


def contains_secret_pattern(text: str) -> bool:
    """Detect explicit credential/secret expressions without blocking ordinary prose."""
    value = str(text or "")
    if _SECRET_ASSIGNMENT.search(value):
        return True
    return bool(re.search(
        r"\b(?:my|your|the|this)\s+(?:password|passcode|api\s*key|access\s*token|refresh\s*token|auth\s*token|secret|cvv|credit\s*card|private\s*key|client\s*secret)\b",
        value, re.I,
    )) or bool(re.search(
        r"\b(?:password|passcode|api\s*key|access\s*token|refresh\s*token|auth\s*token|secret|cvv|credit\s*card|private\s*key|client\s*secret)\s*(?:is|=|:)\s*\S+",
        value, re.I,
    ))


def redact_secrets(text: str) -> str:
    """Redact explicit credential assignments before episodic persistence."""
    value = str(text or "")
    value = _SECRET_ASSIGNMENT.sub(lambda m: re.sub(r"([:=])\s*\S+", r"\1 <redacted>", m.group(0)), value)
    return value


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip(" .،,:;!?؟\"'"))


def extract(text: str) -> list[MemoryCandidate]:
    if not text or contains_secret_pattern(text):
        return []
    out: list[MemoryCandidate] = []
    m = re.search(r"(?:my\s+name\s+is|save\s+my\s+name\s+as|save\s+me\s+name)\s+(.+)", text, re.I)
    if m:
        value = _clean(m.group(1))
        if value and value.casefold() not in {"?", "؟؟"}:
            out.append(MemoryCandidate("fact", value, key="name", confidence=0.98, importance=5))
            return out
    normalized_text = normalize(text)
    theme = _THEME_PREF_EN.search(normalized_text)
    if theme:
        raw = _clean(theme.group(1)).casefold()
        value = f"{raw} mode"
        out.append(MemoryCandidate("preference", value, key="theme", confidence=0.94, importance=4))
        return out
    theme = _THEME_PREF_AR.search(normalized_text)
    if theme:
        raw = _clean(theme.group(1))
        value = "الوضع الداكن" if raw == "الداكن" else "الوضع الفاتح"
        out.append(MemoryCandidate("preference", value, key="theme", confidence=0.94, importance=4))
        return out
    m = re.search(r"(?:i\s*(?:[\'’]m|\s+am)\s+(?:originally\s+)?from|i\s+come\s+from|i\s+originally\s+from|i\s+was\s+born\s+in|انا\s+من|أنا\s+من|انا\s+اصلي\s+من|أنا\s+أصلي\s+من|انا\s+اتولدت\s+في|أنا\s+اتولدت\s+في)\s+(.+)", normalized_text, re.I | re.S)
    if m:
        value = _clean(m.group(1))
        if value:
            out.append(MemoryCandidate("fact", value, key="origin", confidence=0.94, importance=4))
            return out
    m = re.fullmatch(r"(?:انا\s+)?اسمي\s+(?:هو\s+)?(.+)", normalized_text, re.I | re.S)
    if m:
        value = _clean(m.group(1))
        if value:
            out.append(MemoryCandidate("fact", value, key="name", confidence=0.98, importance=5))
            return out
    for kind, pattern, mode in _PATTERNS:
        candidate_text = normalized_text if kind == "preference" else text
        m = pattern.search(candidate_text)
        if not m:
            continue
        if mode is None:
            value = _clean(m.group(1))
            if value:
                out.append(MemoryCandidate(kind, value, key=None, confidence=0.86, importance=3))
            continue
        if mode == "key_value":
            key = _clean(m.group(1)).lower()
            value = _clean(m.group(2))
            if key and value:
                out.append(MemoryCandidate(kind, value, key=key, confidence=0.90, importance=4))
        elif mode == "arabic_key_value":
            raw = _clean(m.group(1))
            value = _clean(m.group(2))
            if raw and value:
                key = "name" if "اسمي" in raw else raw
                out.append(MemoryCandidate(kind, value, key=key, confidence=0.96 if key == "name" else 0.84, importance=5 if key == "name" else 4))
    return out
