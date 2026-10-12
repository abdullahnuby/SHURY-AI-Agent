from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from app.learning.diagnosis import task_signature
from .models import IntentCandidate, SemanticParse


# Phase 13 deliberately starts with a conservative static-pattern subset. Dynamic slots,
# references and fresh-data requests stay behind normal semantic understanding.
_STATIC_OPERATIONS = {
    "query_time",
    "time",
    "query_identity",
    "query_capabilities",
    "query_memory",
    "memory_profile",
    "memory_stats",
    "history",
    "list_notes",
    "recall_last_result",
}


@dataclass(frozen=True)
class PatternMapping:
    pattern_key: str
    operation: str
    capability: str
    language: str
    domain: str
    canonical_goal: str
    speech_act: str
    actionability: str
    intents: tuple[dict[str, Any], ...]
    slots: dict[str, str]
    confidence: float
    fingerprint: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "capability": self.capability,
            "language": self.language,
            "domain": self.domain,
            "canonical_goal": self.canonical_goal,
            "speech_act": self.speech_act,
            "actionability": self.actionability,
            "intents": list(self.intents),
            "slots": dict(self.slots),
        }


class LanguagePatternCache:
    """Verified language-pattern cache that can bypass repeated semantic inference only after promotion."""

    def __init__(self, store, *, promotion_threshold: int = 3, min_confidence: float = 0.82):
        self.store = store
        self.promotion_threshold = max(2, int(promotion_threshold))
        self.min_confidence = max(0.0, min(1.0, float(min_confidence)))

    @staticmethod
    def pattern_key(text: str, language: str = "") -> str:
        # task_signature removes volatile numeric/path values and sensitive tokens. Prefixing
        # language prevents cross-language collisions for otherwise similar phrases.
        material = f"{str(language or '').casefold()}|{task_signature(text)}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _eligible(parse: SemanticParse) -> bool:
        top = parse.top_intent
        if top is None:
            return False
        if top.name not in _STATIC_OPERATIONS:
            return False
        if parse.needs_clarification or parse.required_information or parse.safety_signals:
            return False
        if parse.references or parse.entities or parse.temporal or parse.constraints:
            return False
        if parse.slots or parse.requires_fresh_data:
            return False
        if parse.actionability not in {"information", "action"}:
            return False
        return float(parse.confidence) >= 0.72 and float(top.confidence) >= 0.72

    @classmethod
    def mapping_from_parse(cls, parse: SemanticParse) -> PatternMapping | None:
        if not cls._eligible(parse):
            return None
        top = parse.top_intent
        assert top is not None
        intents = []
        for item in parse.intent_candidates[:4]:
            intents.append({
                "name": item.name,
                "confidence": round(float(item.confidence), 6),
                "evidence": list(item.evidence[:6]),
                "capability": item.capability,
                "required_slots": list(item.required_slots[:6]),
                "missing_slots": list(item.missing_slots[:6]),
                "source": item.source,
            })
        payload = {
            "operation": top.name,
            "capability": top.capability or top.name,
            "language": parse.language,
            "domain": parse.domain,
            "canonical_goal": parse.canonical_goal or top.name,
            "speech_act": parse.speech_act,
            "actionability": parse.actionability,
            "intents": intents,
            "slots": {},
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:32]
        return PatternMapping(
            pattern_key=cls.pattern_key(parse.original, parse.language),
            operation=top.name,
            capability=top.capability or top.name,
            language=parse.language,
            domain=parse.domain,
            canonical_goal=parse.canonical_goal or top.name,
            speech_act=parse.speech_act,
            actionability=parse.actionability,
            intents=tuple(intents),
            slots={},
            confidence=float(parse.confidence),
            fingerprint=fingerprint,
        )

    def observe(self, parse: SemanticParse, *, run_id: str, success: bool, verified: bool) -> dict[str, Any]:
        mapping = self.mapping_from_parse(parse)
        if mapping is None:
            return {"eligible": False, "inserted": False, "promoted": False, "reason": "non-static-or-uncertain"}
        result = self.store.record_language_pattern_observation(
            pattern_key=mapping.pattern_key,
            mapping_fingerprint=mapping.fingerprint,
            pattern=task_signature(parse.original),
            operation=mapping.operation,
            capability=mapping.capability,
            goal_payload=mapping.to_payload(),
            confidence=mapping.confidence,
            success=success,
            verified=verified,
            source=parse.source,
            run_id=run_id,
            promotion_threshold=self.promotion_threshold,
        )
        result["eligible"] = True
        result["pattern_key"] = mapping.pattern_key
        result["operation"] = mapping.operation
        return result

    @staticmethod
    def _intents(payload: dict[str, Any]) -> list[IntentCandidate]:
        items=[]
        for item in payload.get("intents") or []:
            if not isinstance(item, dict):
                continue
            try:
                confidence=max(0.0,min(1.0,float(item.get("confidence",0.0))))
            except (TypeError, ValueError):
                confidence=0.0
            items.append(IntentCandidate(
                str(item.get("name") or ""), confidence,
                tuple(str(x) for x in item.get("evidence", []) if str(x))[:6],
                str(item.get("capability") or ""),
                tuple(str(x) for x in item.get("required_slots", []) if str(x))[:6],
                tuple(str(x) for x in item.get("missing_slots", []) if str(x))[:6],
                "language-pattern-cache",
            ))
        return [x for x in items if x.name]

    def materialize(self, current: SemanticParse, mapping: dict[str, Any]) -> SemanticParse:
        payload=dict(mapping.get("goal_payload") or {})
        intents=self._intents(payload)
        if not intents:
            return current
        # Preserve the user's current raw text and deterministic grounding; only replace the
        # semantic decision skeleton learned from prior verified episodes.
        return SemanticParse(
            original=current.original,
            normalized=current.normalized,
            language=str(payload.get("language") or current.language),
            domain=str(payload.get("domain") or current.domain),
            canonical_goal=str(payload.get("canonical_goal") or current.canonical_goal),
            intent_candidates=intents[:10],
            entities=[],
            references=[],
            temporal=[],
            constraints=[],
            slots={},
            required_information=[],
            ambiguity_reasons=[],
            safety_signals=list(current.safety_signals) + ["language-pattern-cache"],
            needs_clarification=False,
            clarification_question="",
            confidence=max(float(current.confidence), float(mapping.get("confidence_mean") or 0.0)),
            speech_act=str(payload.get("speech_act") or current.speech_act),
            actionability=str(payload.get("actionability") or current.actionability),
            requires_fresh_data=False,
            source="language-pattern-cache",
        )

    def lookup(self, parse: SemanticParse) -> dict[str, Any] | None:
        # Never use the cache when current input contains grounded/dynamic material.
        if not self._eligible(parse):
            return None
        key=self.pattern_key(parse.original, parse.language)
        return self.store.language_pattern_lookup(key)

    def stats(self) -> dict[str, Any]:
        return self.store.language_pattern_stats()

    def snapshot(self, *, limit: int = 100) -> dict[str, Any]:
        return {"version": 1, "stats": self.stats(), "mappings": self.store.language_pattern_mappings(limit=limit)}


__all__ = ["LanguagePatternCache", "PatternMapping"]
