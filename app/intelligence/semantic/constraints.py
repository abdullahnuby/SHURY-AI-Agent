from __future__ import annotations
import re
from .models import SemanticConstraint


def extract_constraints(text: str) -> list[SemanticConstraint]:
    out: list[SemanticConstraint] = []
    patterns = [
        (r"(?:within|in)\s+(\d+(?:\.\d+)?)\s*(seconds?|minutes?|hours?)", "deadline", "within", 0.94),
        (r"(?:خلال|في خلال|في غضون)\s+(\d+(?:\.\d+)?)\s*(ثانية|ثواني|دقيقة|دقائق|ساعة|ساعات)", "deadline", "within", 0.94),
        (r"(?:maximum|max|at most)\s+(\d+)\s+(?:steps|actions)", "max_steps", "lte", 0.96),
        (r"(?:بحد أقصى|max steps|حد أقصى)\s*(\d+)", "max_steps", "lte", 0.96),
        (r"(?:budget|cost)\s*(?:is|=|:)?\s*([\d.,]+)", "max_cost", "lte", 0.90),
        (r"(?:ميزانية|تكلفة)\s*(?:=|:|هي)?\s*([\d.,]+)", "max_cost", "lte", 0.90),
        (r"(?:before|prior to)\s+([^,.;!?]+)", "ordering", "before", 0.86),
        (r"(?:after|following)\s+([^,.;!?]+)", "ordering", "after", 0.86),
        (r"(?:قبل|قبل ما)\s+([^،.;!?؟]+)", "ordering", "before", 0.86),
        (r"(?:بعد|بعد ما)\s+([^،.;!?؟]+)", "ordering", "after", 0.86),
        (r"\b(?:only|فقط)\b\s+([^,.;!?]+)", "scope", "only", 0.84),
        (r"\b(?:must|لازم|يجب)\b\s+([^,.;!?]+)", "requirement", "must", 0.88),
        (r"\b(?:don't|do not|must not|ممنوع|متعملش)\b\s+([^,.;!?]+)", "restriction", "must_not", 0.90),
    ]
    for pat, key, op, conf in patterns:
        for m in re.finditer(pat, text, re.I):
            if key == "deadline":
                value = " ".join(str(g).strip() for g in m.groups() if g).strip()
            else:
                value = m.group(1).strip()
            out.append(SemanticConstraint(key, op, value, conf))
    # Dedup exact constraints.
    seen = set(); result=[]
    for item in out:
        k=(item.key,item.operator,item.value.casefold())
        if k in seen: continue
        seen.add(k); result.append(item)
    return result[:16]
