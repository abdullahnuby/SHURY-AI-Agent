"""Deterministic verification for first-class executable Skill contracts."""
from __future__ import annotations

from typing import Any


def _executed_step_ids(state: Any) -> set[str]:
    return {
        str(item.get("step_id"))
        for item in getattr(state, "observations", ()) or ()
        if item.get("ok") and item.get("step_id")
    }


def verify_skill_contract(skill: Any, state: Any, outputs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Verify the selected Skill as a whole, independent from individual tool checks."""
    if skill is None:
        return {"verified": True, "checks": [], "errors": []}

    contract = tuple(getattr(skill, "verification", ()) or ())
    # Legacy skills receive the conservative default contract. New first-party skills
    # persist an explicit contract, but old candidate records remain executable safely.
    if not contract:
        contract = ({"type": "all_steps_verified"}, {"type": "expected_effects_observed"})

    plan = list(getattr(state, "plan", ()) or ())
    executed = _executed_step_ids(state)
    outputs = outputs or {}
    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    for rule in contract:
        if not isinstance(rule, dict):
            errors.append("invalid skill verification rule")
            continue
        kind = str(rule.get("type") or "").strip().casefold()
        if kind == "all_steps_verified":
            workflow = [item for item in (getattr(skill, "workflow", ()) or ()) if isinstance(item, dict)]
            required = [str(item.get("step_id") or f"s{index}") for index, item in enumerate(workflow, 1)]
            if not required:
                required = [str(step.step_id) for step in plan if str(getattr(step, "skill_key", "")) == str(getattr(skill, "key", ""))]
            ok = bool(required) and all(step_id in executed for step_id in required)
            checks.append({"type": kind, "verified": ok, "required_steps": required, "executed_steps": sorted(executed)})
            if not ok:
                errors.append("not all Skill steps were observed as successfully executed")
        elif kind == "expected_effects_observed":
            skill_effects = set(str(x) for x in (getattr(skill, "outputs", ()) or ()) if str(x))
            observed = set()
            for item in getattr(state, "observations", ()) or ():
                if item.get("ok"):
                    observed.update(str(x) for x in (item.get("effects") or ()) if str(x))
            ok = not skill_effects or skill_effects.issubset(observed)
            checks.append({"type": kind, "verified": ok, "required_effects": sorted(skill_effects), "observed_effects": sorted(observed)})
            if not ok:
                errors.append("Skill outputs/effects were not fully observed")
        elif kind == "goal_verified":
            goal_ok = False
            goal_checks = []
            for value in outputs.values():
                if isinstance(value, dict) and isinstance(value.get("goal_verification"), dict):
                    goal = value.get("goal_verification") or {}
                    goal_checks.append(goal)
                    if goal.get("ok") is True:
                        goal_ok = True
            if not goal_checks:
                errors.append("selected Skill did not provide goal-verification evidence")
            elif not goal_ok:
                errors.append("selected Skill goal verification failed")
            checks.append({"type": kind, "verified": goal_ok, "goal_verifications": goal_checks})
        elif kind == "outputs_present":
            required = [str(x) for x in (rule.get("step_ids") or [])]
            ok = all(step_id in outputs for step_id in required)
            checks.append({"type": kind, "verified": ok, "required": required})
            if not ok:
                errors.append("required Skill outputs are missing")
        else:
            errors.append(f"unsupported skill verification rule: {kind or '<empty>'}")
            checks.append({"type": kind or "<empty>", "verified": False})

    return {"verified": not errors, "checks": checks, "errors": errors}
