"""Safe failure-to-skill distillation inspired by self-evolving agent research.

A failed run can create a small candidate card in SkillBank. The card is descriptive,
not executable: no workflow is inferred from the failure text. Later verified runs or
explicit review may refine/promote it through the existing governance lifecycle.
"""
from __future__ import annotations
import hashlib
import re
from app.skills.registry import SkillBank, DEFAULT_PATH
from app.intelligence.understanding import normalize


def _tokens(text: str) -> list[str]:
    stop = {"the", "and", "for", "with", "from", "then", "that", "this", "about",
            "عن", "في", "من", "و", "ثم", "على", "إلى", "من", "هذا", "هذه"}
    out = []
    for token in normalize(text).split():
        if len(token) < 3 or token in stop or token.isdigit():
            continue
        if token not in out:
            out.append(token)
    return out[:12]


def _pattern(error: str) -> str:
    text = re.sub(r"[A-Za-z]:\\[^\n]+|/[^\n ]+", "<path>", str(error or ""))
    text = re.sub(r"\b\d+(?:\.\d+)?\b", "<n>", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:240]


def distill_failure(goal: str, tool: str, error: str, *, clause: str = "", path=DEFAULT_PATH) -> dict:
    goal_norm = normalize(goal)
    pattern = _pattern(error)
    seed = f"{goal_norm}|{tool}|{pattern}".casefold()
    key = "failure:" + hashlib.sha256(seed.encode("utf-8", errors="replace")).hexdigest()[:16]
    bank = SkillBank(path)
    existing = None
    try:
        existing = bank.get(key)
    except KeyError:
        pass
    evidence = [{
        "kind": "failed-run",
        "goal": goal,
        "tool": tool,
        "error_pattern": pattern,
        "clause": clause,
    }]
    triggers = tuple(dict.fromkeys(_tokens(goal) + _tokens(tool)))
    skill = bank.upsert(
        key=key,
        name=f"Failure heuristic: {goal_norm[:70] or tool}",
        triggers=triggers,
        contraindications=("repeat known failure pattern",),
        preconditions=(),
        workflow=(),
        termination="candidate only; require verified procedure before activation",
        outputs=("failure_pattern_recorded",),
        evidence=evidence if existing is None else tuple(existing.evidence) + tuple(evidence),
        confidence=0.20 if existing is None else min(0.60, existing.confidence + 0.03),
        source="failure-distilled",
        source_run_id=None,
        status="candidate",
    )
    return {"key": skill.key, "name": skill.name, "version": skill.version,
            "status": skill.status, "confidence": skill.confidence,
            "error_pattern": pattern, "policy": "descriptive candidate only; no executable workflow inferred"}
