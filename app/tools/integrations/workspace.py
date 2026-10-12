from app.runtime.registry import tool
from app.runtime.security import safe_workspace_path
from app.knowledge.memory import get_memory
from app.services.workspace_service import workspace_analyze, compare_sources
import re
from pathlib import Path


def _extract_path(goal: str) -> str:
    text = goal.strip()
    m = re.search(r'["\']([^"\']+)["\']', text)
    if m:
        return m.group(1)
    # Prefer a filesystem token, preserving spaces when the path is quoted.
    m = re.search(r'((?:[A-Za-z]:[\\/]|/)[^\n]+?)(?:\s+(?:عن|for|with|و|ثم)\s+|$)', text)
    if m:
        return m.group(1).strip().rstrip('.,')
    for marker in ("workspace ", "مساحة البيانات ", "المجلد ", "حلل المجلد ", "analyze workspace "):
        pos = text.casefold().find(marker.casefold())
        if pos >= 0:
            return text[pos + len(marker):].strip()
    return text


@tool(
    "اكتشاف وتحليل Workspace محلي متعدد المصادر: فهرسة CSV/JSON/SQLite والمستندات النصية واستخراج مفاتيح الربط وإنشاء evidence graph قابل للتدقيق",
    {"path": "str"},
    name="analyze_workspace",
    triggers=("workspace", "مساحة البيانات", "المجلد", "عدة ملفات", "اربط البيانات", "join files", "heterogeneous workspace"),
    match=lambda g: any(x in g.casefold() for x in ("workspace", "مساحة البيانات", "عدة ملفات", "اربط البيانات", "join files", "heterogeneous workspace")),
    build_args=lambda g: {"path": _extract_path(g)},
    capability="workspace_reasoning",
    produces=("workspace_catalogued", "workspace_evidence"),
    cost=4.0,
    duration=1.2,
    parallel_safe=True,
    idempotent=True,
    verification_level="strong",
)
def analyze_workspace_tool(path: str):
    report = workspace_analyze(str(safe_workspace_path(path)))
    get_memory().record_event("workspace_analysis", {
        "workspace": report["workspace"], "fingerprint": report["fingerprint"],
        "sources": report["catalog"]["source_count"], "join_candidates": report["quality"]["join_candidates"],
        "verified": report["verified"],
    })
    return report


@tool(
    "مقارنة مصدرين واكتشاف الانحراف متعدد المتغيرات باستخدام Sliced Wasserstein حتمي مع تفسير لكل عمود",
    {"left": "str", "right": "str"},
    name="compare_sources_drift",
    triggers=("compare sources", "distribution drift", "multivariate drift", "انحراف التوزيع", "قارن مصدرين"),
    match=lambda g: any(x in g.casefold() for x in ("compare sources", "distribution drift", "multivariate drift", "انحراف التوزيع", "قارن مصدرين")),
    build_args=lambda g: _two_paths(g),
    capability="data_drift_analysis",
    produces=("distribution_drift_analyzed",),
    cost=3.0,
    duration=0.9,
    parallel_safe=True,
    idempotent=True,
    verification_level="strong",
)
def compare_sources_tool(left: str, right: str):
    return compare_sources(str(safe_workspace_path(left)), str(safe_workspace_path(right)))


def _two_paths(goal: str) -> dict:
    quoted = re.findall(r'["\']([^"\']+)["\']', goal)
    if len(quoted) >= 2:
        return {"left": quoted[0], "right": quoted[1]}
    paths = re.findall(r'((?:[A-Za-z]:[\\/]|/)[^\s,]+)', goal)
    if len(paths) >= 2:
        return {"left": paths[-2], "right": paths[-1]}
    raise ValueError("أحتاج مسارين لمقارنة مصدرين؛ استخدم quotes حول كل مسار")
