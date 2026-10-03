from __future__ import annotations

import math
import random
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Iterable

from app.domain.plan import validate
from app.planning.planner import RulePlanner
from app.planning.adaptive_planning import skill_to_plan
from app.skills.evaluation import plan_proxy_utility
from .models import ExperienceRecord, ReplayItem, SkillEvaluation
from .transition_model import action_signature


# Phase 2 priority is deliberately transparent and component-based. Positive components
# correspond to the specification's replay signals: prediction error, novelty/rarity,
# failure importance, uncertainty, and learning value. Boundary and contradiction are
# additional bounded boosts so rare transitions and conflicting evidence are not lost.
_PRIORITY_WEIGHTS = {
    "prediction_error": 0.36,
    "novelty": 0.20,
    "failure_importance": 0.18,
    "uncertainty": 0.12,
    "learning_value": 0.10,
    # Recent model changes are a bounded replay signal required by the Phase 11 policy.
    "model_change_recency": 0.04,
}
_BOUNDARY_BONUS = 0.02
_CONTRADICTION_BONUS = 0.06
_MIN_PRIORITY = 1e-6


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def replay_priority(components: dict[str, float]) -> float:
    score = sum(_PRIORITY_WEIGHTS[key] * _clamp(components.get(key, 0.0)) for key in _PRIORITY_WEIGHTS)
    score += _BOUNDARY_BONUS * _clamp(components.get("boundary", 0.0))
    score += _CONTRADICTION_BONUS * _clamp(components.get("contradictory", 0.0))
    return max(_MIN_PRIORITY, round(score, 8))


def replay_priority_components(
    transition: dict,
    *,
    occurrence_count: int = 0,
    contradictory: bool = False,
    boundary: bool = False,
    model_change_recency: float = 0.0,
) -> dict[str, float]:
    """Compute inspectable replay-priority components without executing anything."""
    prediction_error = _clamp(float(transition.get("prediction_error") or 0.0))
    novelty = 1.0 / math.sqrt(1.0 + max(0, int(occurrence_count)))

    outcome = transition.get("outcome")
    action = transition.get("action") or {}
    failed = bool(
        transition.get("verified") is False
        or transition.get("failure_class")
        or (isinstance(outcome, dict) and (outcome.get("ok") is False or outcome.get("status") in {"failed", "error"}))
        or float(transition.get("reward") or 0.0) < 0.0
    )
    failure_importance = 1.0 if failed else 0.0

    uncertainty = _clamp(float(action.get("uncertainty") or 0.0))
    reward = abs(float(transition.get("reward") or 0.0))
    learning_value = _clamp(0.65 * min(1.0, reward) + 0.35 * prediction_error)

    components = {
        "prediction_error": prediction_error,
        "novelty": novelty,
        "failure_importance": failure_importance,
        "uncertainty": uncertainty,
        "learning_value": learning_value,
        "model_change_recency": _clamp(model_change_recency),
        "boundary": 1.0 if boundary else 0.0,
        "contradictory": 1.0 if contradictory else 0.0,
    }
    components["priority"] = replay_priority(components)
    return components


class PrioritizedReplayBuffer:
    """Persistent, bounded, non-executing experience replay index.

    The buffer delegates durability to the existing LearningStore. It never invokes
    tools, planners, or external side effects; later phases can consume sampled
    transitions to update models/policies.
    """

    def __init__(self, store, *, capacity: int = 5000, alpha: float = 0.70, seed: int = 0):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if alpha <= 0:
            raise ValueError("alpha must be > 0")
        self.store = store
        self.capacity = int(capacity)
        self.alpha = float(alpha)
        self._rng = random.Random(seed)

    def add_episode(self, episode: ExperienceRecord) -> int:
        if not episode.meaningful or not episode.transitions:
            return 0
        inserted = self.store.index_replay_transitions(episode)
        self.store.prune_replay(self.capacity)
        return inserted

    def add(self, episode: ExperienceRecord) -> int:
        return self.add_episode(episode)

    def size(self) -> int:
        return int(self.store.replay_stats()["transitions"])

    def stats(self) -> dict:
        out = dict(self.store.replay_stats())
        out.update({"capacity": self.capacity, "alpha": self.alpha})
        return out

    def _weighted_sample(self, items: list[ReplayItem], batch_size: int) -> list[ReplayItem]:
        if batch_size >= len(items):
            return list(items)
        remaining = list(items)
        selected: list[ReplayItem] = []
        for _ in range(batch_size):
            weights = [max(_MIN_PRIORITY, item.priority) ** self.alpha for item in remaining]
            chosen = self._rng.choices(remaining, weights=weights, k=1)[0]
            selected.append(chosen)
            remaining.remove(chosen)
        return selected

    def sample(self, batch_size: int, *, mode: str = "prioritized", min_priority: float = 0.0,
               seed: int | None = None, mark_replayed: bool = True) -> list[ReplayItem]:
        if batch_size < 1:
            return []
        items = self.items(mode=mode, min_priority=min_priority)
        if not items:
            return []
        if seed is not None:
            previous = self._rng
            self._rng = random.Random(seed)
            try:
                selected = self._weighted_sample(items, min(batch_size, len(items)))
            finally:
                self._rng = previous
        else:
            selected = self._weighted_sample(items, min(batch_size, len(items)))
        if mark_replayed:
            self.store.mark_replayed([item.transition_id for item in selected])
        return selected

    def items(self, *, mode: str = "prioritized", min_priority: float = 0.0, limit: int | None = None) -> list[ReplayItem]:
        mode = str(mode or "prioritized").strip().lower()
        items = self.store.replay_items(
            limit=max(self.capacity, int(limit or self.capacity)),
            min_priority=min_priority,
        )
        if mode == "prioritized":
            return items
        if mode == "recent":
            return sorted(items, key=lambda x: (x.created_at, x.transition_id), reverse=True)
        if mode == "high_error":
            return sorted(items, key=lambda x: (x.prediction_error, x.priority), reverse=True)
        if mode == "failures":
            return [x for x in items if x.failure_importance > 0]
        if mode in {"rare", "novel", "under_explored"}:
            return sorted(items, key=lambda x: (x.novelty, x.priority), reverse=True)
        if mode in {"recent_model", "model_recent", "recent_model_change"}:
            return sorted(items, key=lambda x: (x.model_change_recency, x.priority), reverse=True)
        if mode == "successful":
            return [x for x in items if bool((x.transition.get("verified") is True))]
        if mode == "boundary":
            return [x for x in items if x.boundary > 0]
        if mode == "contradictory":
            return [x for x in items if x.contradictory > 0]
        raise ValueError(f"unknown replay mode: {mode}")

    def top(self, limit: int = 20) -> list[ReplayItem]:
        return self.store.replay_items(limit=max(1, int(limit)))

    def reindex_priorities(self, *, limit: int | None = None) -> int:
        items = self.store.replay_items(limit=max(1, int(limit or self.capacity)))
        updates = []
        for item in items:
            updates.append({
                "transition_id": item.transition_id,
                "transition": item.transition,
                # The store recomputes live occurrence counts and model-version recency.
                "contradictory": item.contradictory > 0,
                "boundary": item.boundary > 0,
                "model_version": item.model_version,
            })
        return self.store.update_replay_priorities(updates)


@dataclass(frozen=True)
class ReplayLearningResult:
    batch_id: str
    requested: int
    sampled: int
    episodes_replayed: int
    updates: int
    completed: int
    mean_importance_weight: float
    mean_td_signal: float
    side_effects_executed: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class ExperienceReplayLearner:
    """Apply historical experience to learned value estimates without execution.

    Replay is sequence-based: a prioritized transition selects its episode, then the complete
    historical trajectory is replayed through the existing TD(lambda)+SARSA value learner.
    World-model observation counts are deliberately not incremented; repeating evidence is not
    a new observation of reality. Importance weights compensate approximately for prioritized
    sampling bias in the tabular learner.
    """

    def __init__(self, buffer: PrioritizedReplayBuffer, store, value_model):
        self.buffer = buffer
        self.store = store
        self.value_model = value_model

    def _distribution(self, items: list[ReplayItem]) -> dict[str, float]:
        if not items:
            return {}
        weights = {item.transition_id: max(_MIN_PRIORITY, item.priority) ** self.buffer.alpha for item in items}
        total = sum(weights.values()) or 1.0
        return {key: value / total for key, value in weights.items()}

    def replay(self, batch_size: int = 4, *, beta: float = 0.40, seed: int | None = None,
               exclude_episode_id: str | None = None, learning_rate_scale: float | None = None) -> ReplayLearningResult:
        requested = max(0, int(batch_size))
        batch_id = uuid.uuid4().hex
        if requested == 0:
            return ReplayLearningResult(batch_id, 0, 0, 0, 0, 0, 0.0, 0.0)

        items = self.buffer.items(mode="prioritized")
        if exclude_episode_id:
            items = [item for item in items if item.episode_id != str(exclude_episode_id)]
        if not items:
            return ReplayLearningResult(batch_id, requested, 0, 0, 0, 0, 0.0, 0.0)

        beta = max(0.0, min(1.0, float(beta)))
        probabilities = self._distribution(items)
        rng = random.Random(seed) if seed is not None else random.Random()
        selected = []
        remaining = list(items)
        for _ in range(min(requested, len(remaining))):
            weights = [probabilities[item.transition_id] for item in remaining]
            chosen = rng.choices(remaining, weights=weights, k=1)[0]
            selected.append(chosen)
            remaining.remove(chosen)

        if not selected:
            return ReplayLearningResult(batch_id, requested, 0, 0, 0, 0, 0.0, 0.0)

        n = max(1, len(items))
        raw_is = {item.transition_id: (n * probabilities[item.transition_id]) ** (-beta) for item in selected}
        max_is = max(raw_is.values()) or 1.0
        is_weights = {key: value / max_is for key, value in raw_is.items()}

        # Multiple sampled transitions can belong to one episode. Replay an episode once using
        # the strongest weight represented by its sampled transitions.
        grouped: dict[str, list[ReplayItem]] = {}
        for item in selected:
            grouped.setdefault(item.episode_id, []).append(item)

        updates = 0
        completed = 0
        td_values: list[float] = []
        scales: list[float] = []
        seen_transition_ids: list[str] = []
        for episode_id, episode_items in grouped.items():
            exp = self.store.get_experience(episode_id)
            if exp is None or not exp.transitions:
                for item in episode_items:
                    self.store.record_replay_update(
                        batch_id=batch_id, transition_id=item.transition_id, episode_id=item.episode_id,
                        sampling_probability=probabilities.get(item.transition_id, 0.0),
                        importance_weight=is_weights.get(item.transition_id, 1.0), learning_rate_scale=0.0,
                        td_signal=0.0, status="skipped", error="missing_experience",
                    )
                continue
            weight = max(is_weights[item.transition_id] for item in episode_items)
            scale = float(learning_rate_scale if learning_rate_scale is not None else 0.35)
            scale = max(0.0, min(1.0, scale * weight))

            # Replay is learning-only. Snapshot values so the persistent audit ledger can show
            # what changed without claiming that historical replay created new observations.
            before_values: dict[str, tuple[float, float]] = {}
            for transition in exp.transitions:
                tid = str(transition.get("transition_id") or "")
                state = str(transition.get("state_before") or "")
                action_sig = action_signature(transition.get("action") or {})
                state_row = self.store.get_state_value(state) if state else None
                action_row = self.store.get_action_value(state, action_sig) if state and action_sig else None
                before_values[tid] = (
                    float(state_row.get("value", 0.0)) if state_row else 0.0,
                    float(action_row.get("value", 0.0)) if action_row else 0.0,
                )
            try:
                result = self.value_model.replay_episode(
                    exp.transitions, episode_reward=exp.reward, episode_status=exp.status,
                    learning_rate_scale=scale,
                )
                td = float(result.mean_abs_td_signal)
                updates += int(result.state_updates + result.action_updates)
                completed += 1
                td_values.append(td)
                scales.append(scale)
                for item in episode_items:
                    transition = next((x for x in exp.transitions if str(x.get("transition_id") or "") == item.transition_id), None)
                    state_delta = action_delta = 0.0
                    if transition is not None:
                        state = str(transition.get("state_before") or "")
                        action_sig = action_signature(transition.get("action") or {})
                        before_state, before_action = before_values.get(item.transition_id, (0.0, 0.0))
                        state_row = self.store.get_state_value(state) if state else None
                        action_row = self.store.get_action_value(state, action_sig) if state and action_sig else None
                        state_delta = (float(state_row.get("value", 0.0)) if state_row else 0.0) - before_state
                        action_delta = (float(action_row.get("value", 0.0)) if action_row else 0.0) - before_action
                    self.store.record_replay_update(
                        batch_id=batch_id, transition_id=item.transition_id, episode_id=item.episode_id,
                        sampling_probability=probabilities.get(item.transition_id, 0.0),
                        importance_weight=is_weights.get(item.transition_id, 1.0),
                        learning_rate_scale=scale, td_signal=td,
                        state_value_delta=state_delta, action_value_delta=action_delta, status="completed",
                    )
                    seen_transition_ids.append(item.transition_id)
            except Exception as exc:
                for item in episode_items:
                    self.store.record_replay_update(
                        batch_id=batch_id, transition_id=item.transition_id, episode_id=item.episode_id,
                        sampling_probability=probabilities.get(item.transition_id, 0.0),
                        importance_weight=is_weights.get(item.transition_id, 1.0),
                        learning_rate_scale=scale, td_signal=0.0, status="failed",
                        error=f"{type(exc).__name__}: {exc}",
                    )

        if seen_transition_ids:
            self.store.mark_replayed(seen_transition_ids)
        return ReplayLearningResult(
            batch_id=batch_id, requested=requested, sampled=len(selected),
            episodes_replayed=completed, updates=updates, completed=completed,
            mean_importance_weight=round(sum(is_weights.values()) / max(1, len(is_weights)), 6),
            mean_td_signal=round(sum(td_values) / max(1, len(td_values)), 6),
            side_effects_executed=0,
        )


class ReplayEvaluator:
    """Counterfactual replay first; actual execution remains an explicit sandbox decision.

    Replay never executes side-effecting tools. It asks whether a candidate skill is a valid,
    lower-risk/no-worse plan on historical tasks and records the result as counterfactual evidence.
    """
    def __init__(self, registry, store, memory):
        self.registry=registry
        self.store=store
        self.memory=memory

    def evaluate(self, skill, experiences, *, holdout_goals=()):
        results=[]
        for exp in experiences:
            baseline = RulePlanner().plan(exp.goal, self.memory, None) if self.memory is not None else RulePlanner().plan(exp.goal)
            candidate = skill_to_plan(skill, exp.goal, self.registry)
            if candidate is None:
                base_reward = plan_proxy_utility(baseline, self.registry, verified=exp.status == "completed", coverage=1.0) if baseline else -1.0
                ev=SkillEvaluation(skill.key,exp.goal,base_reward,-1.0,-1.0,False,True,"counterfactual",datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S"))
                self.store.record_evaluation(ev); results.append(ev); continue
            errors=validate(candidate,self.registry)
            if errors:
                base_reward=plan_proxy_utility(baseline,self.registry,verified=exp.status=="completed") if baseline else -1.0
                ev=SkillEvaluation(skill.key,exp.goal,base_reward,-1.0,-1.0,False,True,"counterfactual",datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S"))
                self.store.record_evaluation(ev); results.append(ev); continue
            base_reward=plan_proxy_utility(baseline,self.registry,verified=exp.status=="completed",coverage=1.0) if baseline else -1.0
            cand_reward=plan_proxy_utility(candidate,self.registry,verified=(exp.status=="completed" and exp.verified_rate>=0.80),coverage=1.0)
            delta=cand_reward-base_reward
            regression=delta < -0.05
            ev=SkillEvaluation(skill.key,exp.goal,base_reward,cand_reward,delta,(exp.status=="completed" and exp.verified_rate>=0.80),regression,"counterfactual",datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S"))
            self.store.record_evaluation(ev); results.append(ev)
        return results
