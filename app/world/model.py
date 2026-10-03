from __future__ import annotations

import copy
import hashlib
import json
import time
import uuid
from dataclasses import asdict
from typing import Any

from app.domain.world import WorldState
from app.runtime.registry import Tool
from app.world.models import (
    EntityState, Observation, PredictedTransition, RelationState,
    StateDiff, WorldAssessment,
)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _dict_diff(before: dict, after: dict) -> set[str]:
    keys = set(before) | set(after)
    return {k for k in keys if before.get(k) != after.get(k)}


class WorldModel:
    """State-centric world model that treats observations as evidence, not authority.

    The world model predicts from tool contracts, current state, and learned transition
    evidence. Consequence prediction stays deterministic and evidence-bound.
    """

    def __init__(self, learned_model=None):
        self.learned_model = learned_model

    def predict(self, tool: Tool, args: dict, world: WorldState) -> PredictedTransition:
        warnings: list[str] = []
        learned = self._learned_predict(tool, args, world)
        if learned is not None:
            return learned
        reversible = bool(tool.idempotent)
        risk = tool.risk
        if not reversible:
            warnings.append("الأداة غير idempotent؛ إعادة التنفيذ قد تكرر الأثر")
        if tool.requires_approval:
            warnings.append("الأداة تتطلب موافقة بشرية قبل الأثر")
        if tool.risk == "high":
            warnings.append("الأداة مصنفة عالية المخاطر")
        if not tool.preconditions and tool.produces:
            rationale = "التنبؤ مستنتج من عقد الأداة produces/removes"
        else:
            rationale = "التنبؤ مستنتج من حالة العالم وعقد الأداة"
        expected = StateDiff(
            added_capabilities=tuple(sorted(tool.produces)),
            removed_capabilities=tuple(sorted(tool.removes)),
            changed_resources=tuple(sorted(k for k, _ in tool.resource_costs)),
        )

        return PredictedTransition(
            action=tool.name,
            expected_changes=expected,
            confidence=0.9 if tool.produces or tool.removes else 0.75,
            reversible=reversible,
            risk=risk,
            rationale=rationale,
            source="deterministic-contract",
            warnings=tuple(warnings),
        )

    def _learned_predict(self, tool: Tool, args: dict, world: WorldState) -> PredictedTransition | None:
        model = self.learned_model
        if model is None:
            try:
                from app.learning.transition_model import LearnedTransitionModel
                from app.learning.store import LearningStore
                model = LearnedTransitionModel(LearningStore())
            except Exception:
                return None
        try:
            action = {
                "capability": tool.capability or tool.name,
                "tool": tool.name,
                "parameters": {str(k): v for k, v in (args or {}).items()},
                "preconditions": sorted(tool.preconditions),
                "expected_effects": sorted(tool.produces),
                "risk": tool.risk,
                "cost": float(tool.cost),
            }
            prediction = model.predict(world.fingerprint(), action)
            if prediction is None:
                return None
            warnings = [
                f"تعلم من {prediction.evidence_count} مشاهدة فعلية",
                f"عدم اليقين التجريبي: {prediction.uncertainty:.2f}",
            ]
            return PredictedTransition(
                action=tool.name,
                expected_changes=StateDiff(),
                predicted_state=prediction.predicted_state,
                confidence=prediction.confidence,
                reversible=bool(getattr(tool, "reversible", False)),
                risk=tool.risk,
                rationale=(
                    f"تنبؤ تجريبي من نموذج الانتقالات: next-state probability="
                    f"{prediction.next_state_probability:.2f}, success probability={prediction.success_probability:.2f}"
                ),
                source="learned-transition-model",
                warnings=tuple(warnings),
                prediction_details=prediction.to_dict(),
            )
        except Exception:
            return None

    def simulate_counterfactual(
        self,
        world: WorldState,
        actions: list[dict[str, Any]],
        *,
        max_depth: int | None = None,
        max_branches: int | None = None,
    ):
        """Run a bounded, read-only counterfactual rollout over learned evidence."""
        from app.world.counterfactual import CounterfactualSimulator
        model = self.learned_model
        if model is None:
            from app.learning.transition_model import LearnedTransitionModel
            from app.learning.store import LearningStore
            model = LearnedTransitionModel(LearningStore())
        value_model = None
        try:
            from app.learning.value_model import ValueModel
            value_model = ValueModel(model.store)
        except Exception:
            value_model = None
        simulator = CounterfactualSimulator(model, value_model)
        return simulator.simulate(world, actions, max_depth=max_depth, max_branches=max_branches)

    def observe(
        self,
        *,
        world_before: WorldState,
        world_after: WorldState,
        tool: str,
        ok: bool,
        verified: bool,
        output: Any = None,
        error: str | None = None,
        source: str = "runtime",
        tainted: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> Observation:
        diff = self.diff(world_before, world_after)
        summary = self._summarize_output(output) if ok else str(error or "execution failed")
        confidence = 1.0 if ok and verified else (0.4 if ok else 0.1)
        obs = Observation(
            observation_id=uuid.uuid4().hex,
            timestamp=_now(),
            source=source,
            action=tool,
            ok=ok,
            verified=verified,
            summary=summary,
            raw_output=copy.deepcopy(output),
            error=error,
            state_diff=diff,
            confidence=confidence,
            tainted=tainted,
            metadata=dict(metadata or {}),
        )
        world_after.observations.append(obs.to_dict())
        world_after.observations = world_after.observations[-50:]
        if world_after.history:
            world_after.history[-1]["observation_id"] = obs.observation_id
        return obs

    def apply_structured_observation(self, world: WorldState, output: Any) -> StateDiff:
        """Apply an explicit world_delta emitted by a trusted tool adapter.

        This accepts only a strict dict shape; arbitrary strings are never parsed as state.
        """
        if not isinstance(output, dict):
            return StateDiff()
        delta = output.get("world_delta")
        if not isinstance(delta, dict):
            return StateDiff()
        before = world.snapshot()
        facts_add = [str(x) for x in delta.get("add_facts", []) if str(x)]
        facts_remove = [str(x) for x in delta.get("remove_facts", []) if str(x)]
        for key in facts_add:
            world.facts[key] = "true"
        for key in facts_remove:
            world.facts.pop(key, None)
        variables = delta.get("variables")
        if isinstance(variables, dict):
            world.variables.update(variables)
        resources = delta.get("resources")
        if isinstance(resources, dict):
            for key, value in resources.items():
                world.resources[str(key)] = float(value)
        entities = delta.get("entities")
        if isinstance(entities, dict):
            for entity_id, value in entities.items():
                if isinstance(value, dict):
                    world.entities[str(entity_id)] = EntityState(
                        entity_id=str(entity_id),
                        kind=str(value.get("kind", "entity")),
                        attributes=dict(value.get("attributes", {})),
                        confidence=float(value.get("confidence", 1.0)),
                        status=str(value.get("status", "active")),
                    ).__dict__
        relations = delta.get("relations")
        if isinstance(relations, list):
            for relation in relations:
                if not isinstance(relation, dict):
                    continue
                rid = str(relation.get("relation_id") or uuid.uuid4().hex)
                world.relations[rid] = RelationState(
                    relation_id=rid,
                    subject=str(relation.get("subject", "")),
                    predicate=str(relation.get("predicate", "")),
                    object=str(relation.get("object", "")),
                    confidence=float(relation.get("confidence", 1.0)),
                    status=str(relation.get("status", "active")),
                ).__dict__
        world.version += 1
        world.history.append({"op": "structured_observation", "delta": delta, "version": world.version})
        world.history = world.history[-50:]
        return self.diff(WorldState.from_snapshot(before), world)

    def diff(self, before: WorldState, after: WorldState) -> StateDiff:
        bf, af = before.facts, after.facts
        added_facts = tuple(sorted(k for k in af if k not in bf or af[k] != bf[k]))
        removed_facts = tuple(sorted(k for k in bf if k not in af))
        return StateDiff(
            added_facts=added_facts,
            removed_facts=removed_facts,
            added_capabilities=tuple(sorted(after.capabilities - before.capabilities)),
            removed_capabilities=tuple(sorted(before.capabilities - after.capabilities)),
            changed_variables=tuple(sorted(_dict_diff(before.variables, after.variables))),
            changed_resources=tuple(sorted(_dict_diff(before.resources, after.resources))),
            added_entities=tuple(sorted(k for k in after.entities if k not in before.entities)),
            removed_entities=tuple(sorted(k for k in before.entities if k not in after.entities)),
            added_relations=tuple(sorted(k for k in after.relations if k not in before.relations)),
            removed_relations=tuple(sorted(k for k in before.relations if k not in after.relations)),
        )

    def compare_prediction(self, prediction: PredictedTransition, actual: StateDiff) -> dict[str, Any]:
        expected_added = set(prediction.expected_changes.added_facts)
        expected_removed = set(prediction.expected_changes.removed_facts)
        actual_added = set(actual.added_facts)
        actual_removed = set(actual.removed_facts)
        expected_cap_added = set(prediction.expected_changes.added_capabilities)
        expected_cap_removed = set(prediction.expected_changes.removed_capabilities)
        actual_cap_added = set(actual.added_capabilities)
        actual_cap_removed = set(actual.removed_capabilities)
        unexpected_add = sorted(actual_added - expected_added)
        unexpected_remove = sorted(actual_removed - expected_removed)
        missing_add = sorted(expected_added - actual_added)
        missing_remove = sorted(expected_removed - actual_removed)
        unexpected_cap_add = sorted(actual_cap_added - expected_cap_added)
        unexpected_cap_remove = sorted(actual_cap_removed - expected_cap_removed)
        missing_cap_add = sorted(expected_cap_added - actual_cap_added)
        missing_cap_remove = sorted(expected_cap_removed - actual_cap_removed)
        exact = not any((unexpected_add, unexpected_remove, missing_add, missing_remove, unexpected_cap_add, unexpected_cap_remove, missing_cap_add, missing_cap_remove))
        return {
            "exact": exact,
            "unexpected_added": unexpected_add,
            "unexpected_removed": unexpected_remove,
            "missing_expected_added": missing_add,
            "missing_expected_removed": missing_remove,
            "unexpected_capabilities_added": unexpected_cap_add,
            "unexpected_capabilities_removed": unexpected_cap_remove,
            "missing_expected_capabilities_added": missing_cap_add,
            "missing_expected_capabilities_removed": missing_cap_remove,
            "prediction_confidence": prediction.confidence,
        }

    def assess(self, world: WorldState) -> WorldAssessment:
        unresolved = list(world.uncertainties)
        risks: list[str] = []
        if any(float(x) < 0 for x in world.resources.values()):
            risks.append("resource_negative")
        stale_count = sum(1 for x in world.observations[-20:] if not x.get("verified", False))
        if stale_count >= 3:
            risks.append("low_observation_verification")
        confidence = 1.0
        if stale_count:
            confidence *= max(0.3, 1.0 - stale_count * 0.1)
        return WorldAssessment(
            consistent=not risks and not any(x.startswith("contradiction:") for x in unresolved),
            confidence=round(confidence, 4),
            stale=stale_count >= 3,
            unresolved=tuple(unresolved[-20:]),
            risks=tuple(risks),
            rationale="world consistency assessed from explicit state invariants and verified observations",
        )

    def context(self, world: WorldState, limit: int = 20) -> dict[str, Any]:
        public_observations: list[dict[str, Any]] = []
        for row in world.observations[-limit:]:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            item.pop("raw_output", None)
            item.pop("summary", None)
            public_observations.append(item)
        return {
            "fingerprint": world.fingerprint(),
            "facts": dict(world.facts),
            "variables": dict(world.variables),
            "resources": dict(world.resources),
            "entities": dict(world.entities),
            "relations": dict(world.relations),
            "last_goal": world.last_goal,
            "last_outputs": dict(world.last_outputs),
            "recent_observations": public_observations,
            "uncertainties": list(world.uncertainties[-limit:]),
            "assessment": self.assess(world).to_dict(),
        }

    @staticmethod
    def _summarize_output(output: Any) -> str:
        if isinstance(output, (dict, list, tuple)):
            return json.dumps(output, ensure_ascii=False, default=str)[:1200]
        return str(output if output is not None else "")[:1200]
