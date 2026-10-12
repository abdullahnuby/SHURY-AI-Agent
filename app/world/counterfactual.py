from __future__ import annotations

"""Bounded, read-only counterfactual simulation over the learned world model.

Phase 6 deliberately separates simulation from planning and learning:
- it consumes learned transition/value estimates;
- it never executes tools;
- it never updates the learning store;
- it never invents an unknown transition;
- it truncates rollouts when model uncertainty or unsupported state/action pairs make
  the imagined trajectory unreliable.
"""

from dataclasses import dataclass, asdict
from typing import Any, Iterable, Sequence

from app.domain.world import WorldState
from app.learning.transition_model import LearnedTransitionModel, TransitionPrediction
from app.learning.value_model import ValueModel, ValuePrediction


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _action_key(action: dict[str, Any]) -> str:
    from app.learning.transition_model import action_signature
    return action_signature(action)


@dataclass(frozen=True)
class SimulatedStep:
    depth: int
    state_before: str
    action_signature: str
    predicted_state: str | None
    branch_probability: float
    transition_probability: float
    predicted_reward: float | None
    expected_duration_seconds: float
    success_probability: float
    verified_probability: float
    confidence: float
    uncertainty: float
    accumulated_uncertainty: float
    value_estimate: float | None
    value_confidence: float | None
    source: str
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SimulatedBranch:
    branch_id: str
    probability: float
    state_signature: str
    cumulative_reward: float
    discounted_return: float
    terminal_value: float | None
    terminal_value_confidence: float | None
    path_confidence: float
    accumulated_uncertainty: float
    depth: int
    status: str
    termination_reason: str | None
    steps: tuple[SimulatedStep, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["steps"] = [step.to_dict() for step in self.steps]
        return out


@dataclass(frozen=True)
class CounterfactualSimulation:
    initial_state: str
    action_sequence: tuple[dict[str, Any], ...]
    branches: tuple[SimulatedBranch, ...]
    requested_depth: int
    explored_depth: int
    max_branches: int
    branch_probability_floor: float
    max_accumulated_uncertainty: float
    pruned_probability: float
    unsupported_probability: float
    fully_supported: bool
    side_effect_free: bool = True
    source: str = "learned-transition-model"
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["branches"] = [branch.to_dict() for branch in self.branches]
        return out


@dataclass
class _Node:
    branch_id: str
    probability: float
    state_signature: str
    cumulative_reward: float
    discounted_return: float
    path_confidence: float
    accumulated_uncertainty: float
    steps: list[SimulatedStep]
    status: str = "active"
    termination_reason: str | None = None


class CounterfactualSimulator:
    """Finite-horizon, uncertainty-aware simulator over empirical transition evidence.

    The simulator uses exact `(state_signature, action_signature)` contexts from the Phase-3
    model. A rollout can branch over the learned next-state distribution, but it is stopped when
    the model has no evidence or accumulated uncertainty crosses the configured safety bound.
    Value estimates are read-only annotations; they never update during simulation.
    """

    def __init__(
        self,
        transition_model: LearnedTransitionModel,
        value_model: ValueModel | None = None,
        *,
        gamma: float = 0.95,
        max_depth: int = 3,
        max_branches: int = 24,
        branch_probability_floor: float = 0.02,
        max_accumulated_uncertainty: float = 0.80,
        min_prediction_confidence: float = 0.15,
    ):
        if not 0.0 < float(gamma) <= 1.0:
            raise ValueError("gamma must be in (0,1]")
        if int(max_depth) < 1:
            raise ValueError("max_depth must be >= 1")
        if int(max_branches) < 1:
            raise ValueError("max_branches must be >= 1")
        if not 0.0 <= float(branch_probability_floor) < 1.0:
            raise ValueError("branch_probability_floor must be in [0,1)")
        if not 0.0 < float(max_accumulated_uncertainty) <= 1.0:
            raise ValueError("max_accumulated_uncertainty must be in (0,1]")
        if not 0.0 <= float(min_prediction_confidence) <= 1.0:
            raise ValueError("min_prediction_confidence must be in [0,1]")
        self.transition_model = transition_model
        self.value_model = value_model
        self.gamma = float(gamma)
        self.max_depth = int(max_depth)
        self.max_branches = int(max_branches)
        self.branch_probability_floor = float(branch_probability_floor)
        self.max_accumulated_uncertainty = float(max_accumulated_uncertainty)
        self.min_prediction_confidence = float(min_prediction_confidence)

    @staticmethod
    def _initial_signature(initial_state: WorldState | str) -> str:
        if isinstance(initial_state, WorldState):
            return initial_state.fingerprint()
        signature = str(initial_state or "").strip()
        if not signature:
            raise ValueError("initial_state must not be empty")
        return signature

    @staticmethod
    def _clean_actions(actions: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
        cleaned: list[dict[str, Any]] = []
        for action in actions:
            if not isinstance(action, dict):
                raise ValueError("each simulated action must be a JSON object")
            if not str(action.get("tool") or action.get("capability") or "").strip():
                raise ValueError("simulated action requires tool or capability")
            cleaned.append(dict(action))
        return tuple(cleaned)

    @staticmethod
    def _next_state_branches(prediction: TransitionPrediction) -> tuple[tuple[str, float], ...]:
        distribution = tuple(
            (str(state), _clamp(probability))
            for state, probability in prediction.next_state_distribution
            if str(state) and float(probability) > 0.0
        )
        if distribution:
            total = sum(probability for _, probability in distribution)
            if total <= 0.0:
                return ()
            return tuple((state, probability / total) for state, probability in distribution)
        if prediction.predicted_state:
            return ((prediction.predicted_state, 1.0),)
        return ()

    def _read_value(self, state_signature: str) -> ValuePrediction | None:
        if self.value_model is None:
            return None
        try:
            return self.value_model.predict_state(state_signature)
        except Exception:
            return None

    def _expand_node(
        self,
        node: _Node,
        action: dict[str, Any],
        depth: int,
        *,
        horizon_is_last: bool,
    ) -> tuple[list[_Node], float, float, int]:
        prediction = self.transition_model.predict(node.state_signature, action)
        if prediction is None:
            node.status = "truncated"
            node.termination_reason = "unknown_state_action"
            return [node], 0.0, node.probability, 0

        if prediction.confidence < self.min_prediction_confidence:
            node.status = "truncated"
            node.termination_reason = "low_model_confidence"
            return [node], 0.0, node.probability, 0

        branches = self._next_state_branches(prediction)
        if not branches:
            node.status = "truncated"
            node.termination_reason = "no_next_state_distribution"
            return [node], 0.0, node.probability, 0

        candidates: list[_Node] = []
        pruned_probability = 0.0
        unsupported_probability = 0.0
        expanded = 0
        action_sig = _action_key(action)
        predicted_reward = prediction.predicted_reward

        for branch_index, (next_state, transition_probability) in enumerate(branches):
            if transition_probability < self.branch_probability_floor:
                pruned_probability += node.probability * transition_probability
                continue

            branch_probability = node.probability * transition_probability
            accumulated_uncertainty = _clamp(
                1.0 - (1.0 - node.accumulated_uncertainty) * (1.0 - prediction.uncertainty)
            )
            value_prediction = self._read_value(next_state)
            value_estimate = value_prediction.value if value_prediction else None
            value_confidence = value_prediction.confidence if value_prediction else None
            warnings = [
                f"evidence_count={prediction.evidence_count}",
                f"transition_confidence={prediction.confidence:.3f}",
            ]
            if prediction.uncertainty > 0.0:
                warnings.append(f"transition_uncertainty={prediction.uncertainty:.3f}")
            if value_prediction is None and self.value_model is not None:
                warnings.append("no learned state value for predicted state")
            if len(branches) > 1:
                warnings.append("stochastic next-state branch")

            step = SimulatedStep(
                depth=depth,
                state_before=node.state_signature,
                action_signature=action_sig,
                predicted_state=next_state,
                branch_probability=branch_probability,
                transition_probability=transition_probability,
                predicted_reward=predicted_reward,
                expected_duration_seconds=prediction.expected_duration_seconds,
                success_probability=prediction.success_probability,
                verified_probability=prediction.verified_probability,
                confidence=prediction.confidence,
                uncertainty=prediction.uncertainty,
                accumulated_uncertainty=accumulated_uncertainty,
                value_estimate=value_estimate,
                value_confidence=value_confidence,
                source=prediction.source,
                warnings=tuple(warnings),
            )
            child = _Node(
                branch_id=f"{node.branch_id}.{branch_index + 1}",
                probability=branch_probability,
                state_signature=next_state,
                cumulative_reward=node.cumulative_reward + (predicted_reward or 0.0),
                discounted_return=node.discounted_return + (self.gamma ** (depth - 1)) * (predicted_reward or 0.0),
                path_confidence=min(node.path_confidence, prediction.confidence),
                accumulated_uncertainty=accumulated_uncertainty,
                steps=[*node.steps, step],
            )
            if accumulated_uncertainty >= self.max_accumulated_uncertainty:
                child.status = "truncated"
                child.termination_reason = "accumulated_uncertainty"
            elif horizon_is_last:
                child.status = "complete"
                child.termination_reason = "horizon_reached"
            candidates.append(child)
            expanded += 1

        if not candidates:
            node.status = "truncated"
            node.termination_reason = "all_branches_below_probability_floor"
            return [node], pruned_probability, unsupported_probability, expanded
        return candidates, pruned_probability, unsupported_probability, expanded

    def simulate(
        self,
        initial_state: WorldState | str,
        actions: Sequence[dict[str, Any]],
        *,
        max_depth: int | None = None,
        max_branches: int | None = None,
    ) -> CounterfactualSimulation:
        cleaned_actions = self._clean_actions(actions)
        requested_depth = min(len(cleaned_actions), int(max_depth if max_depth is not None else self.max_depth))
        requested_depth = max(0, requested_depth)
        branch_limit = max(1, int(max_branches if max_branches is not None else self.max_branches))
        initial_signature = self._initial_signature(initial_state)

        if requested_depth == 0:
            return CounterfactualSimulation(
                initial_state=initial_signature,
                action_sequence=cleaned_actions[:0],
                branches=(),
                requested_depth=0,
                explored_depth=0,
                max_branches=branch_limit,
                branch_probability_floor=self.branch_probability_floor,
                max_accumulated_uncertainty=self.max_accumulated_uncertainty,
                pruned_probability=0.0,
                unsupported_probability=0.0,
                fully_supported=True,
                notes=("empty action sequence",),
            )

        nodes = [_Node("cf-1", 1.0, initial_signature, 0.0, 0.0, 1.0, 0.0, [])]
        total_pruned = 0.0
        total_unsupported = 0.0
        explored_depth = 0

        for depth in range(1, requested_depth + 1):
            action = cleaned_actions[depth - 1]
            next_nodes: list[_Node] = []
            for node in nodes:
                if node.status != "active":
                    next_nodes.append(node)
                    continue
                expanded, pruned, unsupported, _ = self._expand_node(
                    node, action, depth, horizon_is_last=(depth == requested_depth)
                )
                next_nodes.extend(expanded)
                total_pruned += pruned
                total_unsupported += unsupported

            next_nodes.sort(key=lambda item: (
                item.probability,
                item.path_confidence,
                -item.accumulated_uncertainty,
                item.state_signature,
                item.branch_id,
            ), reverse=True)
            if len(next_nodes) > branch_limit:
                total_pruned += sum(item.probability for item in next_nodes[branch_limit:])
                next_nodes = next_nodes[:branch_limit]
            nodes = next_nodes
            explored_depth = depth
            if not any(node.status == "active" for node in nodes):
                break

        branches: list[SimulatedBranch] = []
        for node in nodes:
            terminal_value_prediction = self._read_value(node.state_signature)
            terminal_value = terminal_value_prediction.value if terminal_value_prediction else None
            terminal_value_confidence = terminal_value_prediction.confidence if terminal_value_prediction else None
            branches.append(SimulatedBranch(
                branch_id=node.branch_id,
                probability=node.probability,
                state_signature=node.state_signature,
                cumulative_reward=round(node.cumulative_reward, 8),
                discounted_return=round(node.discounted_return, 8),
                terminal_value=terminal_value,
                terminal_value_confidence=terminal_value_confidence,
                path_confidence=round(node.path_confidence, 8),
                accumulated_uncertainty=round(node.accumulated_uncertainty, 8),
                depth=len(node.steps),
                status=node.status,
                termination_reason=node.termination_reason,
                steps=tuple(node.steps),
            ))

        supported_probability = sum(branch.probability for branch in branches)
        fully_supported = (
            bool(branches)
            and total_pruned <= 1e-9
            and total_unsupported <= 1e-9
            and all(branch.depth == requested_depth and branch.status == "complete" for branch in branches)
        )
        notes = [
            "read-only simulation; no tools executed",
            "synthetic branches are not fed into learning or replay",
            "transition and outcome probabilities are empirical marginals, not a fabricated joint distribution",
        ]
        if total_pruned > 0.0:
            notes.append(f"pruned_probability={total_pruned:.6f}")
        if total_unsupported > 0.0:
            notes.append(f"unsupported_probability={total_unsupported:.6f}")
        if supported_probability < 1.0 - 1e-9:
            notes.append(f"represented_probability={supported_probability:.6f}")

        return CounterfactualSimulation(
            initial_state=initial_signature,
            action_sequence=cleaned_actions[:requested_depth],
            branches=tuple(branches),
            requested_depth=requested_depth,
            explored_depth=explored_depth,
            max_branches=branch_limit,
            branch_probability_floor=self.branch_probability_floor,
            max_accumulated_uncertainty=self.max_accumulated_uncertainty,
            pruned_probability=round(total_pruned, 8),
            unsupported_probability=round(total_unsupported, 8),
            fully_supported=fully_supported,
            notes=tuple(notes),
        )

    def simulate_alternatives(
        self,
        initial_state: WorldState | str,
        action_sequences: Sequence[Sequence[dict[str, Any]]],
        *,
        max_depth: int | None = None,
        max_branches: int | None = None,
    ) -> tuple[CounterfactualSimulation, ...]:
        """Simulate alternatives independently; deliberately does not rank or select them."""
        results: list[CounterfactualSimulation] = []
        for actions in action_sequences:
            results.append(self.simulate(initial_state, actions, max_depth=max_depth, max_branches=max_branches))
        return tuple(results)


def action_from_tool(tool, args: dict[str, Any]) -> dict[str, Any]:
    """Create the same semantic action representation used by Phase 3/4/5 learning."""
    if not isinstance(args, dict):
        raise ValueError("args must be a JSON object")
    errors = tool.validate_args(args)
    if errors:
        raise ValueError("; ".join(errors))
    return {
        "capability": tool.capability or tool.name,
        "tool": tool.name,
        "parameters": {str(k): v for k, v in args.items()},
        "preconditions": sorted(tool.preconditions),
        "expected_effects": sorted(tool.produces),
        "risk": tool.risk,
        "reversible": bool(getattr(tool, "reversible", False)),
    }
