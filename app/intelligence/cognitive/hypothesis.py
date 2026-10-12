from __future__ import annotations
import re

def normalize_hypotheses(payload: dict) -> list[dict]:
    out = []
    for item in payload.get("hypotheses") or []:
        if not isinstance(item, dict):
            continue
        statement = str(item.get("statement", "")).strip()
        if not statement:
            continue
        try:
            confidence = max(0.0, min(1.0, float(item.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        evidence = [str(x).strip() for x in (item.get("evidence_needed") or []) if str(x).strip()][:6]
        out.append({"statement": statement[:500], "evidence_needed": evidence, "confidence": confidence})
    return out[:5]

def heuristic_hypotheses(goal: str, intents: list[dict], baseline_steps: list[dict]) -> list[dict]:
    n = goal.casefold()
    out = []
    names = {i.get("name") for i in intents}
    if names & {"web_research", "scientific_research", "open_world_learning", "rag_reasoning"}:
        out.append({"statement": "The task likely needs external evidence rather than only local memory.",
                    "evidence_needed": ["relevant current sources", "source provenance"], "confidence": 0.65})
    if "data_analysis" in names:
        out.append({"statement": "The task depends on inspecting the actual dataset before choosing an analysis.",
                    "evidence_needed": ["dataset schema", "data quality", "analysis results"], "confidence": 0.75})
    if baseline_steps:
        out.append({"statement": "The deterministic candidate is an execution skeleton and may need revision after observations.",
                    "evidence_needed": ["tool results", "post-action verification"], "confidence": 0.70})
    if re.search(r"\b(?:fix|debug|repair|solve|اصلح|صلح|مشكلة|bug|error)\b", n, re.I):
        out.append({"statement": "The visible failure may not be the root cause; inspect before modifying.",
                    "evidence_needed": ["failure evidence", "relevant files/logs", "verification after change"], "confidence": 0.78})
    return out[:5]
