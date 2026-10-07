from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any


@dataclass(frozen=True)
class CompetencyProfile:
    capability: str
    specialist: str
    department: str
    tool: str
    attempts: int
    verified_successes: int
    verified_failures: int
    observed_rate: float
    conservative_rate: float
    evidence_state: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "specialist": self.specialist,
            "department": self.department,
            "tool": self.tool,
            "attempts": self.attempts,
            "verified_successes": self.verified_successes,
            "verified_failures": self.verified_failures,
            "observed_rate": round(self.observed_rate, 4),
            "conservative_rate": round(self.conservative_rate, 4),
            "evidence_state": self.evidence_state,
        }


class CompanyCompetencyCalibrator:
    """Calibrate specialist competence from canonical organizational outcome evidence.

    This layer is advisory. It never changes ownership, authority, SkillBank state, or
    reviewer policy. Sparse evidence is deliberately treated conservatively so a single
    successful run cannot make an unproven specialist look equivalent to a well-supported one.
    """

    MIN_OBSERVATIONS = 3
    Z_95 = 1.959963984540054

    def __init__(self, learning_store: Any):
        if learning_store is None or not hasattr(learning_store, "company_delegation_evidence"):
            raise TypeError("canonical LearningStore with company delegation evidence is required")
        self.learning = learning_store

    @classmethod
    def _wilson_lower_bound(cls, successes: int, attempts: int) -> float:
        n = max(0, int(attempts))
        k = max(0, min(n, int(successes)))
        if n <= 0:
            return 0.0
        p = k / n
        z = cls.Z_95
        denominator = 1.0 + (z * z) / n
        center = p + (z * z) / (2.0 * n)
        margin = z * sqrt((p * (1.0 - p) / n) + (z * z) / (4.0 * n * n))
        return max(0.0, min(1.0, (center - margin) / denominator))

    @classmethod
    def _state(cls, attempts: int, conservative_rate: float) -> str:
        if int(attempts) < cls.MIN_OBSERVATIONS:
            return "insufficient_evidence"
        if conservative_rate >= 0.75:
            return "proven"
        if conservative_rate >= 0.50:
            return "mixed"
        return "weak"

    def profiles(self, *, capability: str | None = None, specialist: str | None = None, limit: int = 200) -> tuple[CompetencyProfile, ...]:
        rows = self.learning.company_delegation_evidence(capability=capability, limit=max(1, int(limit)))
        wanted_specialist = str(specialist or "").strip()
        profiles: list[CompetencyProfile] = []
        for row in rows:
            role = str(row.get("specialist") or "")
            if wanted_specialist and role != wanted_specialist:
                continue
            attempts = max(0, int(row.get("attempts") or 0))
            successes = max(0, min(attempts, int(row.get("verified_successes") or 0)))
            failures = max(0, int(row.get("verified_failures") or 0))
            observed = successes / max(1, attempts)
            conservative = self._wilson_lower_bound(successes, attempts)
            profiles.append(CompetencyProfile(
                capability=str(row.get("capability") or ""),
                specialist=role,
                department=str(row.get("department") or ""),
                tool=str(row.get("tool") or ""),
                attempts=attempts,
                verified_successes=successes,
                verified_failures=failures,
                observed_rate=observed,
                conservative_rate=conservative,
                evidence_state=self._state(attempts, conservative),
            ))
        profiles.sort(key=lambda x: (-x.conservative_rate, -x.attempts, x.specialist, x.tool))
        return tuple(profiles)

    def profile_for(self, *, capability: str, specialist: str, tool: str = "") -> CompetencyProfile | None:
        matches = self.profiles(capability=capability, specialist=specialist, limit=500)
        exact = [x for x in matches if not tool or x.tool == tool]
        return exact[0] if exact else None

    def score(self, *, capability: str, specialist: str, tool: str = "") -> float:
        profile = self.profile_for(capability=capability, specialist=specialist, tool=tool)
        if profile is None:
            return 0.0
        return profile.conservative_rate

    def snapshot(self, *, capability: str | None = None, specialist: str | None = None, limit: int = 200) -> dict[str, Any]:
        rows = self.profiles(capability=capability, specialist=specialist, limit=limit)
        return {
            "source": "LearningStore.company_delegation_evidence",
            "minimum_observations": self.MIN_OBSERVATIONS,
            "profiles": [x.to_dict() for x in rows],
            "specialist_count": len({x.specialist for x in rows if x.specialist}),
            "capability_count": len({x.capability for x in rows if x.capability}),
        }
