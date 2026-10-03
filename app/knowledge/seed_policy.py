from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

SEED_SOURCE = "synthetic_seed"
SEED_VERSION = "100k-v1"
SEED_DATA_CLASS = "benchmark"
SEED_RUNTIME_ROLE = "capability_prior"
SEED_KNOWLEDGE_ALLOWED = False
SEED_USER_MEMORY_ALLOWED = False
SEED_EXECUTION_EVIDENCE_ALLOWED = False
SEED_PROMOTION_EVIDENCE_ALLOWED = False
SEED_AUTHORITATIVE = False

_SEED_QUERY_TERMS = (
    "seed", "seeded", "seed catalog", "synthetic seed",
    "benchmark seed", "benchmark corpus", "synthetic corpus",
    "البذرة", "بيانات البذرة", "سيناريوهات البداية", "البيانات الاصطناعية",
)


@dataclass(frozen=True)
class SeedClassification:
    data_class: str = SEED_DATA_CLASS
    runtime_role: str = SEED_RUNTIME_ROLE
    source: str = SEED_SOURCE
    seed_version: str = SEED_VERSION
    authoritative: bool = SEED_AUTHORITATIVE
    user_memory: bool = SEED_USER_MEMORY_ALLOWED
    execution_evidence: bool = SEED_EXECUTION_EVIDENCE_ALLOWED
    promotion_evidence: bool = SEED_PROMOTION_EVIDENCE_ALLOWED
    knowledge_base: bool = SEED_KNOWLEDGE_ALLOWED

    def to_dict(self) -> dict[str, Any]:
        return {
            "data_class": self.data_class,
            "runtime_role": self.runtime_role,
            "source": self.source,
            "seed_version": self.seed_version,
            "authoritative": self.authoritative,
            "user_memory": self.user_memory,
            "execution_evidence": self.execution_evidence,
            "promotion_evidence": self.promotion_evidence,
            "knowledge_base": self.knowledge_base,
        }


CLASSIFICATION = SeedClassification()


def is_explicit_seed_query(query: str) -> bool:
    text = str(query or "").casefold().strip()
    return any(term in text for term in _SEED_QUERY_TERMS)


def validate_seed_payload(payload: Mapping[str, Any] | None, *, source: str = SEED_SOURCE) -> tuple[bool, str]:
    payload = dict(payload or {})
    if str(source or "").casefold().strip() != SEED_SOURCE:
        return False, "unexpected-source"
    if payload.get("not_user_memory") is not True:
        return False, "missing-not-user-memory-marker"
    if payload.get("not_execution_evidence") is not True:
        return False, "missing-not-execution-evidence-marker"
    provenance = payload.get("provenance")
    if not isinstance(provenance, Mapping):
        return False, "missing-provenance"
    if not provenance.get("seed_version"):
        return False, "missing-seed-version"
    if not provenance.get("anchor_from_real_user_campaign") and not provenance.get("generation_method"):
        return False, "missing-generation-provenance"
    return True, "valid"


def seed_prior_metadata(*, seed_version: str = SEED_VERSION, source_ref: str = "seed://100k-v1") -> dict[str, Any]:
    return {
        "origin_class": SEED_RUNTIME_ROLE,
        "data_class": SEED_DATA_CLASS,
        "source": SEED_SOURCE,
        "source_ref": source_ref,
        "seed_version": seed_version,
        "authoritative": False,
        "not_user_memory": True,
        "not_execution_evidence": True,
        "not_promotion_evidence": True,
        "not_knowledge": True,
    }


def is_seed_prior(record: Mapping[str, Any] | None) -> bool:
    record = dict(record or {})
    source = str(record.get("source") or "").casefold().strip()
    origin_class = str(record.get("origin_class") or "").casefold().strip()
    return source == SEED_SOURCE or origin_class == SEED_RUNTIME_ROLE


def can_be_used_as_execution_evidence(record: Mapping[str, Any] | None) -> bool:
    return not is_seed_prior(record)


def can_be_promoted_to_memory(record: Mapping[str, Any] | None) -> bool:
    return not is_seed_prior(record)


def can_be_knowledge(record: Mapping[str, Any] | None) -> bool:
    return not is_seed_prior(record)


__all__ = [
    "CLASSIFICATION", "SEED_SOURCE", "SEED_VERSION", "SEED_DATA_CLASS", "SEED_RUNTIME_ROLE",
    "SeedClassification", "can_be_knowledge", "can_be_promoted_to_memory",
    "can_be_used_as_execution_evidence", "is_explicit_seed_query", "is_seed_prior",
    "seed_prior_metadata", "validate_seed_payload",
]
