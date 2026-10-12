from __future__ import annotations

def clean_list(value, limit=8, item_limit=360):
    out = []
    for item in value or []:
        s = str(item or "").strip()
        if s:
            out.append(s[:item_limit])
    return out[:limit]

def infer_task_type(goal: str, intents: list[dict]) -> str:
    names = {str(i.get("name")) for i in intents[:4]}
    if names & {"development_validation", "development_inspection", "development_git", "development_learning"}:
        return "development"
    if names & {"web_research", "scientific_research", "open_world_learning", "github_discovery", "github_learning", "rag_reasoning"}:
        return "research"
    if "data_analysis" in names or "workspace_reasoning" in names:
        return "analysis"
    if names & {"remember_fact", "recall_fact", "memory_search", "memory_profile", "remember_memory", "forget_fact"}:
        return "memory"
    if "calculate" in names:
        return "computation"
    return "open_ended" if not names else "task"

def normalize_payload(payload: dict, fallback_goal: str, context: dict) -> dict:
    strategy = str(payload.get("strategy") or "hybrid").strip().lower()
    if strategy not in {"deterministic", "hybrid", "reactive", "research_first", "clarify"}:
        strategy = "hybrid"
    if payload.get("needs_clarification"):
        strategy = "clarify"
    risk = str(payload.get("risk") or "low").strip().lower()
    if risk not in {"low", "medium", "high"}:
        risk = "low"
    try:
        confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "goal": str(payload.get("goal") or fallback_goal).strip()[:2000],
        "task_type": str(payload.get("task_type") or infer_task_type(fallback_goal, context.get("intents", [])))[:80],
        "success_criteria": clean_list(payload.get("success_criteria"), 8),
        "constraints": clean_list(payload.get("constraints"), 8),
        "ambiguities": clean_list(payload.get("ambiguities"), 8),
        "assumptions": clean_list(payload.get("assumptions"), 8),
        "subgoals": clean_list(payload.get("subgoals"), 12),
        "information_gaps": clean_list(payload.get("information_gaps"), 8),
        "hypotheses": payload.get("hypotheses") if isinstance(payload.get("hypotheses"), list) else [],
        "strategy": strategy, "risk": risk, "confidence": confidence,
        "needs_clarification": bool(payload.get("needs_clarification")),
        "clarification_question": str(payload.get("clarification_question") or "").strip()[:500],
        "first_action_hint": str(payload.get("first_action_hint") or "").strip()[:500],
    }
