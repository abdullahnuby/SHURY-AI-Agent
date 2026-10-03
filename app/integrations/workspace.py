"""Deterministic heterogeneous-workspace discovery and join reasoning."""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path
from typing import Any

from app.knowledge.data_analysis import load_rows, _clean, _infer_type

SUPPORTED_DATA = {".csv", ".json", ".sqlite", ".sqlite3", ".db"}
DOC_EXT = {".md", ".txt"}


def _norm_key(name: str) -> str:
    s = re.sub(r"[^a-z0-9\u0600-\u06ff]+", "_", str(name).casefold()).strip("_")
    aliases = {
        "id": "id", "key": "id", "identifier": "id",
        "رقم": "id", "معرف": "id", "كود": "code", "code": "code",
        "name": "name", "اسم": "name", "date": "date", "تاريخ": "date",
    }
    return aliases.get(s, s)


def _file_fingerprint(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def discover_workspace(root: str | Path) -> list[Path]:
    p = Path(root).expanduser().resolve()
    if p.is_file():
        return [p] if p.suffix.casefold() in SUPPORTED_DATA | DOC_EXT else []
    if not p.exists() or not p.is_dir():
        raise ValueError(f"المسار غير موجود: {p}")
    return sorted(x for x in p.rglob("*") if x.is_file() and x.suffix.casefold() in SUPPORTED_DATA | DOC_EXT)


def _document_meta(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "path": str(path), "kind": "document", "extension": path.suffix.lower(),
        "fingerprint": _file_fingerprint(path), "bytes": path.stat().st_size,
        "lines": text.count("\n") + (1 if text else 0),
        "tokens": len(re.findall(r"[\w\u0600-\u06ff]+", text, flags=re.UNICODE)),
        "headings": re.findall(r"^#{1,6}\s+(.+)$", text, flags=re.M)[:30],
    }


def _data_meta(path: Path) -> dict[str, Any]:
    resolved, fields, rows = load_rows(path)
    types = {f: _infer_type([r.get(f) for r in rows]) for f in fields}
    key_stats = {}
    for field in fields:
        vals = [_clean(r.get(field)) for r in rows]
        present = [v for v in vals if v is not None]
        if not present:
            continue
        unique = len(set(present))
        key_stats[field] = {
            "type": types[field], "unique": unique, "nonmissing": len(present),
            "unique_ratio": unique / len(present),
            "candidate_key": unique == len(present) and unique >= 2,
        }
    return {
        "path": str(resolved), "kind": "table", "extension": resolved.suffix.lower(),
        "fingerprint": _file_fingerprint(resolved), "rows": len(rows),
        "columns": len(fields), "fields": fields, "types": types,
        "key_stats": key_stats,
    }


def catalog_workspace(root: str | Path) -> dict:
    files = discover_workspace(root)
    sources = []
    errors = []
    for path in files:
        try:
            sources.append(_data_meta(path) if path.suffix.casefold() in SUPPORTED_DATA else _document_meta(path))
        except Exception as exc:
            errors.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
    return {
        "root": str(Path(root).expanduser().resolve()),
        "source_count": len(sources), "data_sources": sum(s["kind"] == "table" for s in sources),
        "document_sources": sum(s["kind"] == "document" for s in sources),
        "sources": sources, "errors": errors,
    }


def _value_overlap(left: list[str], right: list[str]) -> float:
    a = {x for x in left if x is not None}
    b = {x for x in right if x is not None}
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, min(len(a), len(b)))


def join_candidates(left: str | Path, right: str | Path) -> list[dict]:
    lp, lf, lr = load_rows(left); rp, rf, rr = load_rows(right)
    candidates = []
    for lc in lf:
        for rc in rf:
            if _norm_key(lc) != _norm_key(rc):
                continue
            lv = [_clean(r.get(lc)) for r in lr]; rv = [_clean(r.get(rc)) for r in rr]
            overlap = _value_overlap(lv, rv)
            if overlap <= 0:
                continue
            unique_bonus = 1.0 if len(set(x for x in lv if x is not None)) == len([x for x in lv if x is not None]) else 0.0
            score = 0.75 * overlap + 0.25 * unique_bonus
            candidates.append({"left_column": lc, "right_column": rc,
                               "normalized_key": _norm_key(lc), "value_overlap": overlap,
                               "left_unique_key": bool(unique_bonus), "score": score})
    candidates.sort(key=lambda x: (-x["score"], x["left_column"], x["right_column"]))
    return candidates[:20]


def _join_rows(left_rows: list[dict], right_rows: list[dict], left_key: str, right_key: str) -> list[dict]:
    index = {}
    for row in right_rows:
        key = _clean(row.get(right_key))
        if key is None:
            continue
        index.setdefault(key, []).append(row)
    joined = []
    for left in left_rows:
        key = _clean(left.get(left_key))
        for right in index.get(key, []):
            row = dict(left)
            for k, v in right.items():
                nk = k if k not in row else f"right.{k}"
                row[nk] = v
            joined.append(row)
    return joined


def deterministic_join(left: str | Path, right: str | Path, left_key: str | None = None,
                       right_key: str | None = None) -> dict:
    lp, lf, lr = load_rows(left); rp, rf, rr = load_rows(right)
    candidates = join_candidates(left, right)
    if not candidates:
        raise ValueError("لم أجد مفتاح ربط مدعومًا بين المصدرين")
    choice = next((c for c in candidates if c["left_column"] == left_key and c["right_column"] == right_key), None) if left_key and right_key else candidates[0]
    joined = _join_rows(lr, rr, choice["left_column"], choice["right_column"])
    return {
        "left": str(lp), "right": str(rp), "key": choice,
        "candidate_keys": candidates, "joined_rows": len(joined),
        "left_rows": len(lr), "right_rows": len(rr),
        "match_rate_left": len({i for i, row in enumerate(lr) if _clean(row.get(choice["left_column"])) is not None and any(_clean(rrr.get(choice["right_column"])) == _clean(row.get(choice["left_column"])) for rrr in rr)}) / max(1, len(lr)),
        "sample": joined[:10], "join_method": "deterministic_exact_key_join",
    }
