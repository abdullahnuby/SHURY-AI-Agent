"""Workspace file tools. لا تُكتشف تلقائيًا بواسطة الـRulePlanner؛ تُستخدم فقط عبر المسارات الصريحة المناسبة.
كل المسارات محبوسة جوه الـworkspace (AGENT_WORKSPACE أو ./workspace). الكتابة بموافقة.
"""
import os
from pathlib import Path

from app.runtime.registry import tool

DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "workspace"
MAX_READ_BYTES = 1_000_000
MAX_READ_CHARS = 3_500   # لازم يتماشى مع MAX_OBS_CHARS في react.py
MAX_WRITE_CHARS = 200_000
MAX_LIST = 200


def workspace_root() -> Path:
    root = Path(os.environ.get("AGENT_WORKSPACE") or DEFAULT_ROOT).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_path(rel: str) -> Path:
    root = workspace_root()
    p = (root / str(rel)).resolve()   # resolve بيحل symlinks و".." والمسارات المطلقة
    if p != root and root not in p.parents:
        raise ValueError("المسار برة الـworkspace")
    return p


_safe = safe_path  # alias للتوافق

_common = dict(stage=0, match=lambda g: False, capability="workspace_files")


@tool(description="يعرض محتويات مجلد جوه الـworkspace (استخدم '.' للجذر)",
      params={"path": "مسار نسبي، '.' للجذر"}, cost=0.5, **_common)
def list_files(path: str):
    p = safe_path(path)
    if not p.is_dir():
        raise ValueError("مش مجلد")
    rows = []
    for x in sorted(p.iterdir())[:MAX_LIST]:
        rows.append({"name": x.name, "type": "dir" if x.is_dir() else "file",
                     "bytes": x.stat().st_size if x.is_file() else None})
    return rows


def _read_text(path: str) -> tuple[Path, str]:
    p = safe_path(path)
    if not p.is_file():
        raise ValueError("الملف مش موجود")
    if p.stat().st_size > MAX_READ_BYTES:
        raise ValueError("الملف أكبر من الحد المسموح")
    return p, p.read_text(encoding="utf-8", errors="replace")


def _chunk(p: Path, text: str, start: int) -> dict:
    end = min(len(text), start + MAX_READ_CHARS)
    return {"path": str(p.relative_to(workspace_root())), "total_chars": len(text), "start": start,
            "end": end, "content": text[start:end],
            "next_start": end if end < len(text) else None}   # None = وصلت لآخر الملف


@tool(description="يقرا بداية ملف نصي (أول 3500 حرف). لو next_start مش null كمل بـread_file_part أو دور بـsearch_in_file",
      params={"path": "مسار الملف النسبي"}, cost=0.5, **_common)
def read_file(path: str):
    p, text = _read_text(path)
    return _chunk(p, text, 0)


@tool(description="يقرا جزء من ملف نصي ابتداءً من موضع حرف معين (استخدم next_start من القراءة السابقة)",
      params={"path": "مسار الملف النسبي", "start": "رقم الحرف اللي تبدأ منه (عدد صحيح)"}, cost=0.5, **_common)
def read_file_part(path: str, start: int):
    p, text = _read_text(path)
    start = int(start)
    if start < 0 or start >= max(len(text), 1):
        raise ValueError(f"start خارج نطاق الملف (طوله {len(text)} حرف)")
    return _chunk(p, text, start)


@tool(description="يدور على نص داخل ملف ويرجع السطور المطابقة بأرقامها (grep). مفيد للملفات الكبيرة",
      params={"path": "مسار الملف النسبي", "query": "النص المطلوب"}, cost=0.5, **_common)
def search_in_file(path: str, query: str):
    if not str(query).strip():
        raise ValueError("query فاضي")
    _, text = _read_text(path)
    q, hits = str(query).casefold(), []
    for i, line in enumerate(text.splitlines(), 1):
        if q in line.casefold():
            hits.append({"line": i, "text": line[:300]})
            if len(hits) >= 20:
                break
    return {"query": query, "matches": hits, "capped": len(hits) >= 20}


@tool(description="يكتب/يستبدل ملف نصي في الـworkspace (بموافقة)",
      params={"path": "مسار الملف النسبي", "content": "المحتوى"},
      requires_approval=True, risk="medium", cost=1.5, **_common)
def write_file(path: str, content: str):
    if len(content) > MAX_WRITE_CHARS:
        raise ValueError("المحتوى أكبر من الحد المسموح")
    p = safe_path(path)
    if p == workspace_root() or p.is_dir():
        raise ValueError("المسار مجلد")
    existed = p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"path": str(p.relative_to(workspace_root())), "bytes": len(content.encode("utf-8")),
            "overwrote": existed}
