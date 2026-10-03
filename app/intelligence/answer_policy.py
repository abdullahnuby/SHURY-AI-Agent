"""Deterministic answer-policy primitives for SHURY.

The policy separates *where an answer should come from* from *how the answer is phrased*.
It deliberately contains no generative-model dependency.  Questions are routed to the
least powerful source that can answer them safely, and an evidence gate decides whether
SHURY should answer or abstain.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from app.intelligence.understanding import normalize


_GENERIC_QUESTION_STARTS = (
    "what ", "what's ", "what is ", "what are ", "who ", "where ", "when ",
    "why ", "how ", "which ", "whose ", "is ", "are ", "tell me about ", "explain ",
    "ما ", "ماذا ", "لماذا ", "ليه ", "كيف ", "ازاي ", "إزاي ", "هل ",
    "أين ", "اين ", "فين ", "متى ", "مين ", "أي ", "اي ", "اشرح ", "إشرح ",
)

_KNOWN_INTENTS = {
    "greeting", "time", "calculate", "remember_fact", "recall_fact", "memory_search",
    "memory_profile", "memory_stats", "forget_fact", "remember_result", "remember_last_result",
    "web_research", "scientific_research", "open_world_learning", "github_discovery",
    "github_learning", "skill_selection", "skill_discovery", "data_analysis", "workspace_reasoning",
    "development_validation", "development_inspection", "development_git", "rag_reasoning",
    "agentic_rag", "list_notes", "list_skills", "skill_inventory", "skill_routing", "knowledge_query",
}

_FRESH_MARKERS = (
    "today", "now", "current", "latest", "newest", "recent", "live", "news", "price", "weather",
    "today's", "هذا اليوم", "اليوم", "دلوقتي", "حالي", "الحالي", "أحدث", "احدث", "الجديد", "آخر",
    "اخر", "الأخبار", "الاخبار", "السعر", "الطقس", "مباشر",
)

_MEMORY_MARKERS = (
    "my name", "my city", "my project", "my preference", "remember", "memory", "what do you know about me",
    "اسمي", "مدينتي", "مشروعي", "تفضيلاتي", "ذاكرتي", "فاكر", "تتذكر", "ماذا تعرف عني",
)


@dataclass(frozen=True)
class AnswerDecision:
    mode: str
    query: str
    confidence: float
    requires_fresh_data: bool = False
    evidence_required: bool = True
    reasons: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def can_answer_without_external_source(self) -> bool:
        return self.mode in {"memory", "rag", "execution"}


def is_generic_question(text: str) -> bool:
    n = normalize(text).strip()
    if not n:
        return False
    if n.endswith(("?", "؟")):
        return True
    return any(n.startswith(prefix) for prefix in _GENERIC_QUESTION_STARTS)


def requires_fresh_data(text: str) -> bool:
    n = normalize(text)
    return any(marker in n for marker in _FRESH_MARKERS)


def is_personal_question(text: str) -> bool:
    n = normalize(text)
    return any(marker in n for marker in _MEMORY_MARKERS)


def classify_question(text: str, top_intent: str = "", top_confidence: float = 0.0) -> AnswerDecision:
    n = normalize(text).strip()
    fresh = requires_fresh_data(n)
    personal = is_personal_question(n)
    reasons: list[str] = []

    if top_intent in {"memory_search", "memory_profile", "recall_fact"} or personal:
        reasons.append("personal-context")
        return AnswerDecision("memory", text.strip(), max(0.86, top_confidence), fresh, True, tuple(reasons))

    if top_intent in {"rag_reasoning", "agentic_rag"}:
        reasons.append("explicit-knowledge-base")
        return AnswerDecision("rag", text.strip(), max(0.86, top_confidence), fresh, True, tuple(reasons))

    if fresh:
        reasons.append("fresh-data-required")
        return AnswerDecision("web", text.strip(), max(0.84, top_confidence), True, True, tuple(reasons))

    reasons.append("open-knowledge-question")
    return AnswerDecision("adaptive", text.strip(), max(0.72, top_confidence), False, True, tuple(reasons),
                           {"fallback_order": ["rag", "web"]})


def infer_knowledge_question_candidate(text: str, top_intent: str = "", top_confidence: float = 0.0):
    """Return a semantic candidate tuple for the generic-question route.

    Kept as tuples to avoid importing semantic models here and creating an import cycle.
    """
    if not is_generic_question(text):
        return None
    if top_intent in _KNOWN_INTENTS and top_confidence >= 0.62:
        return None
    confidence = 0.84 if requires_fresh_data(text) else 0.72
    evidence = ("generic-question-form", "no-strong-known-intent")
    return ("knowledge_query", confidence, evidence, "question_answering")
