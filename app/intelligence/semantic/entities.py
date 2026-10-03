from __future__ import annotations
import re
from app.intelligence.understanding import normalize
from .models import EntityMention

ENTITY_PATTERNS = [
    ("url", re.compile(r"https?://[^\s<>]+", re.I)),
    ("repository", re.compile(r"\b[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\b")),
    ("file", re.compile(r"(?:[A-Za-z]:[\\/]|\./|\.\\/|/)?[^\s,;]+\.(?:csv|json|sqlite|db|py|ts|tsx|js|md|txt|pdf|xlsx|zip)\b", re.I)),
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    ("currency", re.compile(r"(?:\$|£|€|ريال|جنيه)\s?\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?\s?(?:USD|EGP|SAR|EUR|ريال|جنيه)\b", re.I)),
    ("number", re.compile(r"(?<!\w)\d+(?:\.\d+)?(?!\w)")),
]


def _add_named(patterns, text, out, etype, conf=0.86):
    for m in re.finditer(patterns, text, re.I | re.S):
        raw = m.group(1).strip()
        if not raw:
            continue
        out.append(EntityMention(raw, etype, normalize(raw), conf, m.start(1), m.end(1)))


def extract_entities(text: str, slots: dict[str, str] | None = None) -> list[EntityMention]:
    out: list[EntityMention] = []
    for etype, pat in ENTITY_PATTERNS:
        for m in pat.finditer(text):
            raw = m.group(0).strip(".,;!?؟)")
            out.append(EntityMention(raw, etype, normalize(raw), 0.96 if etype in {"url", "repository", "email", "file"} else 0.86,
                                     m.start(), m.end()))
    # Common user-profile/entity phrases. Captures are intentionally conservative.
    named = [
        (r"(?:my\s+name\s+is|my\s+name\s*[:=]|save\s+my\s+name(?:\s+as)?|اسمي(?: هو|=|:)?)\s+([^,.!?؟\n]+)", "person", 0.96),
        (r"(?:my\s+city\s+is|i\s+live\s+in|مدينتي\s+(?:هي|=|:)?|انا\s+ساكن\s+في)\s+([^,.!?؟\n]+)", "location", 0.96),
        (r"(?:i\s*(?:[\'’]m|\s+am)\s+(?:originally\s+)?from|i\s+come\s+from|i\s+originally\s+from|i\s+was\s+born\s+in|انا\s+من|أنا\s+من|انا\s+اصلي\s+من|أنا\s+أصلي\s+من|انا\s+اتولدت\s+في|أنا\s+اتولدت\s+في)\s+([^,.!?؟\n]+)", "location", 0.96),
        (r"(?:project|مشروع)\s+([A-Za-z][A-Za-z0-9_-]{1,48}(?:\s+[A-Za-z][A-Za-z0-9_-]{1,48}){0,2})", "project", 0.88),
        (r"(?:company|شركة)\s+([A-Za-z0-9][^,.!?؟\n]+)", "organization", 0.86),
        (r"(?:language|لغة)\s+(?:is|هي)?\s*([A-Za-z+#.-]+)", "programming_language", 0.88),
    ]
    for pat, etype, conf in named:
        _add_named(pat, text, out, etype, conf)
    # Preference key extraction is useful for semantic memory routing.
    if slots:
        for key, value in slots.items():
            if key.startswith("preference:"):
                name = key.split(":", 1)[1]
                out.append(EntityMention(name, "preference_key", normalize(name), 0.90, source="deterministic"))
                out.append(EntityMention(value, "preference_value", normalize(value), 0.90, source="deterministic"))
    # Exact duplicate removal.
    seen = set()
    deduped = []
    for e in sorted(out, key=lambda x: (x.start if x.start >= 0 else 10**9, -x.confidence, len(x.text))):
        k = (e.type, e.normalized, e.start, e.end)
        if k in seen:
            continue
        seen.add(k)
        deduped.append(e)
    return deduped[:40]
