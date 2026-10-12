"""Verifier-backed procedural skill compilation from agent experience."""
from __future__ import annotations
import hashlib
from app.skills.registry import SkillBank
from app.intelligence.understanding import normalize


def _skill_key(goal: str) -> str:
    return "auto:" + hashlib.sha256(normalize(goal).encode("utf-8")).hexdigest()[:16]


def _triggers(goal: str) -> list[str]:
    raw = normalize(goal).split()
    stop = {"the", "and", "for", "with", "from", "then", "that", "this", "عن", "في", "من", "و", "ثم", "على", "إلى"}
    out = []
    for token in raw:
        if len(token) < 3 or token in stop or token.isdigit():
            continue
        if token not in out:
            out.append(token)
    return out[:12]


def compile_verified_run(state, memory, *, minimum_steps: int = 2):
    if state.status != "completed" or not state.plan:
        return None
    done = [s for s in state.plan.steps if s.status == "done"]
    if len(done) < minimum_steps:
        return None
    effects = memory.effects(state.run_id)
    by_step = {e["step_id"]: e for e in effects if e["verified"]}
    if len(by_step) < len(done):
        return None
    workflow = []
    evidence = []
    for step in done:
        workflow.append({
            "tool": step.tool,
            "depends_on": list(step.depends_on),
            "capability": step.capability,
            "args_policy": "derive-from-live-goal",
        })
        effect = by_step.get(step.id)
        if effect:
            evidence.append({"run_id": state.run_id, "step": step.id, "tool": step.tool,
                             "verified": True, "effect_id": effect.get("id")})
    bank = SkillBank()
    key = _skill_key(state.goal)
    existing = None
    try:
        existing = bank.get(key)
    except KeyError:
        pass
    status = existing.status if existing else "candidate"
    confidence = min(1.0, 0.55 + 0.08 * len(done))
    skill = bank.upsert(
        key=key,
        name=f"Learned workflow: {normalize(state.goal)[:80]}",
        triggers=_triggers(state.goal),
        contraindications=("unknown arguments",),
        preconditions=tuple(sorted({c for s in done for c in ()})),
        workflow=workflow,
        termination="stop after all steps verified or replan on failed postcondition",
        outputs=tuple(sorted({p for s in done for p in memory_plan_outputs(state, s)})),
        evidence=evidence,
        confidence=confidence,
        source="verified-runtime",
        source_run_id=state.run_id,
        status=status,
    )
    return skill


def memory_plan_outputs(state, step):
    # This compiler intentionally records no raw external data. It records only the
    # tool contract's capability/effect vocabulary, keeping skills portable and safe.
    try:
        return tuple([state.world.last_outputs.get("last_result") and "verified_output"])
    except Exception:
        return ()


def compile_project_skill(path: str, inspection: dict):
    stack = ",".join(inspection.get("stack", [])) or "unknown-stack"
    key = "project:" + hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]
    workflow = [
        {"tool": "inspect_project", "depends_on": [], "args_policy": "derive-from-live-goal"},
        {"tool": "git_status", "depends_on": ["s1"], "args_policy": "derive-from-live-goal"},
        {"tool": "check_project", "depends_on": ["s2"], "args_policy": "derive-from-live-goal"},
    ]
    evidence = [{"kind": "project-inspection", "path": str(path), "stack": inspection.get("stack", []),
                 "commands": inspection.get("commands", [])}]
    return SkillBank().upsert(
        key=key,
        name=f"Project development/validation ({stack})",
        triggers=("build project", "test project", "check project", "افحص المشروع", "اختبر المشروع", "ابني المشروع", *inspection.get("stack", [])),
        contraindications=("untrusted repository", "missing manifest"),
        preconditions=("project path exists",),
        workflow=workflow,
        termination="project inspection + git status + approved build/test checks verified",
        outputs=("project_inspected", "git_status_observed", "project_checked"),
        evidence=evidence,
        confidence=0.7,
        source="project-manifest",
        source_run_id=None,
        status="candidate",
    )
