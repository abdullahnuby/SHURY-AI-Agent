"""Deterministic query-aware routing for the canonical memory controller.

Phase 12 maps an already-understood semantic need to the smallest set of memory
classes that can answer it. It never bypasses Phase 2 ownership/scope filters or
Phase 11 hybrid ranking.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Mapping


@dataclass(frozen=True)
class MemoryQueryPlan:
    """Canonical memory retrieval requirement emitted by the semantic layer."""

    need: str
    memory_types: tuple[str, ...] = ()
    stores: tuple[str, ...] = ()
    rationale: str = ""
    confidence: float = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.memory_types or self.stores)

    def to_dict(self) -> dict[str, object]:
        return {
            "need": self.need,
            "memory_types": list(self.memory_types),
            "stores": list(self.stores),
            "rationale": self.rationale,
            "confidence": round(float(self.confidence), 3),
        }


NONE = MemoryQueryPlan("none", rationale="turn does not require memory retrieval", confidence=1.0)


def _joined_slots(slots: Mapping[str, object] | None) -> str:
    if not slots:
        return ""
    return " ".join(f"{key} {value}" for key, value in slots.items())


def plan_memory_query(
    query: str,
    *,
    intent: str | None = None,
    slots: Mapping[str, object] | None = None,
    entities: Iterable[object] | None = None,
    references: Iterable[object] | None = None,
) -> MemoryQueryPlan:
    """Route a semantic request to the minimum justified memory classes.

    This is capability routing, not sentence memorization. Broad conceptual markers
    are used only where the semantic intent itself is generic (e.g. ``memory_search``).
    """
    intent = str(intent or "").strip().casefold()
    text = " ".join(str(query or "").split()).casefold()
    context = " ".join([text, _joined_slots(slots).casefold()])

    if intent in {"recall_fact", "memory_profile", "query_identity", "query_memory"}:
        return MemoryQueryPlan(
            "user_fact",
            ("fact", "preference", "note"),
            ("durable_user_memory",),
            "identity/profile/fact recall requires user-owned durable memory",
            0.99,
        )

    if intent in {"memory_stats", "remember_fact", "remember_memory", "remember_result", "remember_last_result", "forget_fact", "forget_memory"}:
        return NONE

    # Deictic follow-ups are best served by current short-lived context first, then
    # prior experience if needed. This must run before generic knowledge intent routing.
    deictic = (
        "this task", "that task", "this request", "that request", "this", "that",
        "المهمة دي", "المهمة ده", "الطلب ده", "الطلب دي", "ذلك الطلب", "هذه المهمة", "هذا الطلب",
    )
    if any(marker in context for marker in deictic):
        return MemoryQueryPlan(
            "working_context",
            ("working", "episode"),
            ("working", "episodic"),
            "resolved/deictic follow-up may need current working context and recent experience",
            0.88,
        )

    # Explicit experience markers should also beat a generic knowledge intent.
    episode_markers = (
        "earlier", "before", "previous", "last time", "what happened", "what did we do",
        "earlier task", "previous task", "previous conversation", "what happened in",
        "قبل كده", "قبل كدا", "السابق", "السابقة", "آخر", "اخر", "الحاجة اللي حصلت", "ايه اللي حصل", "إيه اللي حصل",
        "عملنا ايه", "عملنا إيه", "حصل ايه", "حصل إيه", "المرة اللي فاتت", "المهمة السابقة", "المحادثة السابقة",
    )
    if intent in {"query_knowledge", "knowledge_query"} and any(marker in context for marker in episode_markers):
        return MemoryQueryPlan(
            "episodic", ("episode",), ("episodic",),
            "the question explicitly asks about prior interaction experience, not world knowledge", 0.95,
        )

    if intent in {"recall_last_result", "history"}:
        return MemoryQueryPlan(
            "episodic",
            ("episode",),
            ("episodic",),
            "previous-result/history questions require prior interaction experience",
            0.98,
        )

    if intent in {"query_knowledge", "knowledge_query", "rag_reasoning"}:
        return MemoryQueryPlan(
            "knowledge",
            ("knowledge",),
            ("knowledge",),
            "world/project information requires explicitly classified knowledge only",
            0.97,
        )

    if intent in {"agentic_rag"}:
        return MemoryQueryPlan(
            "knowledge",
            ("knowledge",),
            ("knowledge",),
            "agentic evidence queries use knowledge context; RAG remains a separate source",
            0.97,
        )

    if intent in {"memory_search"}:
        procedural_markers = (
            "how did we solve", "how did we fix", "how we solved", "how we fixed", "what steps did we use",
            "إزاي حلينا", "ازاي حلينا", "إزاي حلينا", "ازاي حلنا", "إزاي حلنا", "إزاي صلحنا", "ازاي صلحنا",
            "حلينا", "حلنا", "صلحنا", "الطريقة اللي استخدمناها", "الخطوات اللي استخدمناها",
        )
        episode_markers = (
            "earlier", "before", "previous", "last time", "what happened", "what did we do",
            "earlier task", "previous task", "previous conversation", "what happened in",
            "قبل كده", "قبل كدا", "السابق", "السابقة", "آخر", "اخر", "الحاجة اللي حصلت", "ايه اللي حصل", "إيه اللي حصل",
            "عملنا ايه", "عملنا إيه", "حصل ايه", "حصل إيه", "المرة اللي فاتت", "المهمة السابقة", "المحادثة السابقة",
        )
        entity_markers = (
            "relationship", "relation", "alias", "who is", "origin", "علاقة", "علاقات", "صلة", "أصله", "اصله", "مين هو", "مين هي",
        )
        if any(marker in context for marker in procedural_markers):
            return MemoryQueryPlan(
                "procedural_experience",
                ("procedural", "episode"),
                ("procedural", "episodic"),
                "method-solving questions need verified procedure plus originating experience",
                0.94,
            )
        if any(marker in context for marker in entity_markers):
            return MemoryQueryPlan(
                "entity_relation",
                ("entity", "relation"),
                ("entity_graph",),
                "identity/relation questions require canonical entities and relations",
                0.91,
            )
        if any(marker in context for marker in episode_markers):
            return MemoryQueryPlan(
                "episodic",
                ("episode",),
                ("episodic",),
                "experience-oriented memory search requires episodic memory only",
                0.93,
            )
        return MemoryQueryPlan(
            "mixed_personal",
            ("fact", "preference", "note", "episode"),
            ("durable_user_memory", "episodic"),
            "generic memory search may need personal facts or interaction experience; graph/knowledge stores are excluded",
            0.78,
        )

    return NONE
