from __future__ import annotations

from app.learning.brain_store import BrainKnowledgeStore
from app.planning.capabilities import INTENT_TO_CAPABILITY
from .models import IntentCandidate


def _reverse_capability_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for intent, capability in INTENT_TO_CAPABILITY.items():
        out.setdefault(str(capability).casefold(), intent)
    return out


def apply_brain_priors(query: str, base: list[IntentCandidate], registry: dict | None = None,
                       *, limit: int = 6, speech_act: str = "request") -> list[IntentCandidate]:
    """Use bootstrapped examples as a weak prior, never as executable truth."""
    try:
        matches = BrainKnowledgeStore().match_capabilities(query, registry=registry or {}, limit=limit)
    except Exception:
        return base
    reverse = _reverse_capability_map()
    by_name = {item.name: item for item in base}
    for item in matches:
        intent = reverse.get(str(item.get("capability", "")).casefold())
        if not intent:
            # If the seed capability is not one of the semantic intents, bind it through
            # a single installed tool only when that tool has a stable semantic capability.
            tools = item.get("available_tools") or []
            if len(tools) == 1:
                tool = (registry or {}).get(tools[0])
                tool_cap = str(getattr(tool, "capability", "") or "").casefold()
                intent = reverse.get(tool_cap)
        if not intent:
            continue
        score = float(item.get("score", 0.0))
        if score < 0.34:
            continue
        prior_boost = min(0.26, score * 0.30)
        if speech_act == "question" and intent in {"remember_fact", "remember_memory", "save_note", "remember_result"}:
            prior_boost = -min(0.30, 0.14 + score * 0.18)
        existing = by_name.get(intent)
        if existing:
            by_name[intent] = IntentCandidate(
                existing.name,
                max(0.0, min(0.99, existing.confidence + prior_boost)),
                existing.evidence + (f"brain-prior:{item.get('domain')}:{item.get('capability')}",),
                existing.capability,
                existing.required_slots,
                existing.missing_slots,
                "brain-prior",
            )
        else:
            by_name[intent] = IntentCandidate(
                intent,
                min(0.92, 0.42 + prior_boost),
                (f"brain-prior:{item.get('domain')}:{item.get('capability')}",),
                str(item.get("capability") or ""),
                source="brain-prior",
            )
    result = list(by_name.values())
    result.sort(key=lambda x: (-x.confidence, x.name))
    return result[:10]
