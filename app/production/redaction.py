from __future__ import annotations

import hashlib
import json
import time
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_SECRET_KEY = re.compile(r"(?i)(api[_-]?key|access[_-]?token|token|auth(?:orization)?|bearer|cookie|password|passwd|secret|private[_-]?key|refresh[_-]?token|session[_-]?token)")
_SECRET_VALUE = re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|token|authorization|bearer|password|passwd|secret|private[_-]?key|refresh[_-]?token|session[_-]?token)\s*[:=]\s*(?:bearer\s+)?[^\s,;]+")
_WINDOWS_PATH = re.compile(r"(?i)\b[A-Z]:\\[^\s,;]+")
_POSIX_PATH = re.compile(r"(?<!\w)/(?:[^\s,;]+/)+[^\s,;]*")


def _redact_scalar(value: Any, *, key: str = "") -> Any:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    text = str(value)
    if key and _SECRET_KEY.search(key):
        return "<redacted>"
    text = _SECRET_VALUE.sub(lambda m: m.group(0).split("=", 1)[0].split(":", 1)[0] + "=<redacted>", text)
    text = _WINDOWS_PATH.sub("<path>", text)
    text = _POSIX_PATH.sub("<path>", text)
    if len(text) > 2000:
        text = text[:2000] + "…"
    return text


def redact(value: Any, *, key: str = "", max_depth: int = 8) -> Any:
    if max_depth <= 0:
        return "<max-depth>"
    if isinstance(value, Mapping):
        return {str(k): redact(v, key=str(k), max_depth=max_depth - 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact(v, max_depth=max_depth - 1) for v in value]
    return _redact_scalar(value, key=key)


def redact_for_log(value: Any, *, max_chars: int = 4000) -> Any:
    safe = redact(value)
    try:
        encoded = json.dumps(safe, ensure_ascii=False, default=str, sort_keys=True)
    except Exception:
        return "<unserializable>"
    return encoded if len(encoded) <= max_chars else encoded[:max_chars] + "…"


def safe_request_id(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return hashlib.sha256(f"shury:{time.time_ns()}".encode("utf-8")).hexdigest()[:24]
    cleaned = re.sub(r"[^A-Za-z0-9._:-]", "-", raw)[:128]
    return cleaned or hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def fingerprint(payload: Any) -> str:
    """Opaque equality fingerprint; never emit the input or the canonical form to logs."""
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def safe_path_display(path: str | Path) -> str:
    return "<path>" if path else ""


__all__ = ["redact", "redact_for_log", "safe_request_id", "fingerprint", "safe_path_display"]
