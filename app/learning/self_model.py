from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .models import ExperienceRecord


@dataclass(frozen=True)
class SelfAssessment:
    capability: str
    tool: str
    context_signature: str
    attempts: int
    successes: int
    failures: int
    verified: int
    reliability: float
    posterior_reliability: float
    confidence: float
    calibration_error: float
    prediction_error: float
    average_cost: float
    recovery_rate: float
    uncertain: bool
    adjustment: float
    model_version: int
    last_updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        out=asdict(self)
        for key in ("reliability","posterior_reliability","confidence","calibration_error","prediction_error","recovery_rate","adjustment"):
            out[key]=round(float(out[key]),6)
        out["average_cost"]=round(float(out["average_cost"]),6)
        return out


class PersistentSelfModel:
    """Persistent metacognitive performance model with no runtime authority."""
    def __init__(self, store):
        self.store=store

    def learn(self, experience: ExperienceRecord) -> dict[str, Any]:
        return self.store.upsert_self_model_observations(experience)

    def assess(self, *, tool: str, capability: str = "", context_signature: str = "") -> SelfAssessment:
        item=self.store.self_model_action_assessment(tool=tool, capability=capability, context_signature=context_signature)
        return SelfAssessment(
            capability=str(item.get("capability") or capability or tool), tool=str(tool),
            context_signature=str(item.get("context_signature") or context_signature), attempts=int(item.get("attempts") or 0),
            successes=int(item.get("successes") or 0), failures=int(item.get("failures") or 0), verified=int(item.get("verified") or 0),
            reliability=float(item.get("reliability") or 0.0), posterior_reliability=float(item.get("posterior_reliability") or item.get("reliability") or 0.0),
            confidence=float(item.get("confidence") or 0.0), calibration_error=float(item.get("calibration_error") or 0.0),
            prediction_error=float(item.get("prediction_error") or 0.0), average_cost=float(item.get("average_cost") or 0.0),
            recovery_rate=float(item.get("recovery_rate") or 0.0), uncertain=bool(item.get("uncertain", True)),
            adjustment=float(item.get("adjustment") or 0.0), model_version=int(item.get("model_version") or 1),
            last_updated_at=str(item.get("last_updated_at") or ""),
        )

    def score_adjustment(self, *, tool: str, capability: str = "", context_signature: str = "") -> float:
        return float(self.assess(tool=tool, capability=capability, context_signature=context_signature).adjustment)

    def snapshot(self, *, limit: int = 200) -> dict[str, Any]:
        return self.store.self_model_snapshot(limit=limit)
