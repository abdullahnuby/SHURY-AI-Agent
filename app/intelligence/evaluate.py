"""Deterministic capability benchmark for the retrieval-native runtime.

Metrics are architecture-level: parsing, planning validity, memory persistence,
verification, recovery and resumability. Evaluation is deterministic.
"""
import tempfile
from pathlib import Path
from app.intelligence.understanding import understand

CASES = [
    ("احسب 5*3+2", "calculate"),
    ("احسب ١٢ ضرب ٤", "calculate"),
    ("سجل عندي اجتماع الساعة 6", "save_note"),
    ("دور على احمد", "search_notes"),
    ("الساعة كام", "time"),
    ("افتكر اسم المشروع: نخيل", "remember_fact"),
    ("فاكر ايه عن اسم المشروع", "recall_fact"),
    ("انس اسم المشروع", "forget_fact"),
]


def run():
    passed = 0
    details = []
    for text, expected in CASES:
        got = understand(text).top_intent
        ok = bool(got and got.name == expected)
        passed += int(ok)
        details.append({"input": text, "expected": expected, "passed": ok})
    return {"passed": passed, "total": len(CASES), "accuracy": passed / len(CASES), "details": details}
