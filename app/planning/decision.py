"""Deterministic decision layer: confidence, ambiguity, risk and explicit refusal to guess."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Decision:
    action: str  # execute | clarify | refuse
    confidence: float
    reason: str
    risk: str = "low"


def decide(understanding, plan, registry, semantic=None) -> Decision:
    top = understanding.top_intent
    if not plan.steps:
        return Decision("clarify", 0.0, "لا توجد خطة قابلة للتنفيذ")
    if understanding.ambiguous:
        # Layer 2 may have a richer semantic interpretation than the legacy keyword
        # classifier. A clear semantic-to-tool alignment is sufficient for low-risk
        # read-only capabilities even when the legacy classifier remains ambiguous.
        if semantic is not None and not semantic.needs_clarification and semantic.top_intent is not None:
            alignment = {
                "github_discovery": {"github_search"},
                "github_learning": {"github_research"},
                "scientific_research": {"arxiv_research"},
                "skill_selection": {"match_skills"},
                "skill_discovery": {"discover_skills"},
                "memory_stats": {"memory_stats"},
                "rag_reasoning": {"rag_query"},
                "data_analysis": {"analyze_dataset", "profile_dataset"},
                "workspace_reasoning": {"analyze_workspace"},
                "development_inspection": {"inspect_project"},
                "development_validation": {"check_project"},
                "network_status": {"network_status"},
            }
            planned_tools = {s.tool for s in plan.steps}
            allowed = alignment.get(semantic.top_intent.name, set())
            aligned = bool(allowed & planned_tools)
            low_risk = all(not registry[s.tool].requires_approval and registry[s.tool].risk == "low" for s in plan.steps)
            if aligned and low_risk and semantic.top_intent.confidence >= 0.40:
                return Decision("execute", semantic.top_intent.confidence, "explicit semantic intent aligns with a low-risk tool plan", "low")
            if semantic.top_intent.confidence >= 0.78:
                risk = "high" if any(registry[s.tool].requires_approval for s in plan.steps) else "low"
                return Decision("execute", semantic.top_intent.confidence, "semantic understanding resolves legacy ambiguity", risk)
        return Decision("clarify", top.score if top else 0.0, "أكثر من نية متقاربة؛ لا أخمن")
    if top is None:
        # A registered tool can be an explicit capability even when the language
        # classifier has no semantic intent rule for it. The plan itself is evidence.
        return Decision("execute", 0.56, "الخطة تطابق أداة مسجلة مباشرة")
    # A deterministic threshold, deliberately conservative for side effects.
    risk = "high" if any(registry[s.tool].requires_approval for s in plan.steps) else "low"
    if top.score < 0.55:
        return Decision("clarify", top.score, "الثقة أقل من حد التنفيذ")
    return Decision("execute", top.score, "نية واضحة وخطة قابلة للتنفيذ", risk)
