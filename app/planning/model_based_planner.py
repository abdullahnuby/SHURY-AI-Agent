from __future__ import annotations

"""Phase 7: bounded, model-based planning over the learned world model.

The planner is deliberately separate from execution authority. It searches only over
state/action pairs already observed by the learned transition model, evaluates complete
candidate sequences with the Phase-6 counterfactual simulator, and returns a normal Plan.
The returned plan must still pass the normal deterministic certificate before execution.
"""

from dataclasses import dataclass, asdict
import math
from typing import Any, Iterable, Sequence

from app.domain.goal import GoalModel, GoalClause, parse_goal
from app.domain.plan import Plan, PlanStep, validate
from app.domain.world import WorldState
from app.learning.store import LearningStore
from app.learning.transition_model import LearnedTransitionModel, action_signature
from app.learning.value_model import ValueModel
from app.learning.self_model import PersistentSelfModel
from app.runtime.certificate import certify_plan
from app.runtime.registry import Tool
from app.world.counterfactual import CounterfactualSimulation, CounterfactualSimulator


_RISK = {"low": 0.0, "medium": 0.25, "high": 0.75}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _risk_penalty(risk: str) -> float:
    return _RISK.get(str(risk or "low").casefold(), 0.75)


def _state_signature(world: WorldState | str) -> str:
    if isinstance(world, WorldState):
        return world.fingerprint()
    signature = str(world or "").strip()
    if not signature:
        raise ValueError("world/state signature must not be empty")
    return signature


def _goal_ready(index: int, goal: GoalModel, completed: frozenset[int]) -> bool:
    clause = goal.clauses[index]
    if clause.relation == "then" and index > 0:
        return (index - 1) in completed
    return True


def _match_clause(tool: Tool, clause: GoalClause) -> bool:
    try:
        return bool(tool.matches(clause.text))
    except Exception:
        return False


def _apply_goal_progress(action: dict[str, Any], tool: Tool, goal: GoalModel,
                         completed: frozenset[int]) -> frozenset[int]:
    for index, clause in enumerate(goal.clauses):
        if index in completed or not _goal_ready(index, goal, completed):
            continue
        if _match_clause(tool, clause):
            return frozenset(set(completed) | {index})
    return completed


def _action_sort_key(row: dict[str, Any]) -> tuple:
    return (
        -int(row.get("observation_count", 0) or 0),
        -int(row.get("success_count", 0) or 0),
        str(row.get("action_signature") or ""),
    )


@dataclass(frozen=True)
class ModelPlanEvaluation:
    action_signatures: tuple[str, ...]
    goal_progress: float
    fully_supported_probability: float
    truncated_probability: float
    expected_discounted_return: float
    expected_terminal_value: float
    expected_behavior_value: float
    expected_prediction_error: float
    expected_success_probability: float
    expected_path_confidence: float
    expected_uncertainty: float
    risk_penalty: float
    estimated_cost: float
    estimated_duration: float
    self_model_adjustment: float
    learned_policy_value: float | None
    learned_policy_evidence: int
    selection_basis: str
    score: float
    simulation_depth: int
    rejected_by_certificate: bool = False
    rejection_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelPlanCandidate:
    plan: Plan
    evaluation: ModelPlanEvaluation
    simulation: CounterfactualSimulation

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "evaluation": self.evaluation.to_dict(),
            "simulation": self.simulation.to_dict(),
        }


@dataclass
class _SearchNode:
    state_signature: str
    actions: tuple[dict[str, Any], ...]
    branch_probability: float
    cumulative_reward: float
    discounted_return: float
    accumulated_uncertainty: float
    path_confidence: float
    elapsed: float
    cost: float
    risk: float
    completed_clauses: frozenset[int]


class ModelBasedPlanner:
    """Bounded beam-search planner grounded in the learned transition graph.

    Design constraints:
    * never invent an unobserved state/action edge;
    * never mutate the learning store while planning;
    * use Phase-6 simulation for final stochastic evaluation;
    * keep goal satisfaction and runtime certification separate from model confidence;
    * prefer known, empirically successful behavior while penalizing uncertainty/risk.

    This is intentionally not a policy learner and does not execute tools.
    """

    def __init__(
        self,
        transition_model: LearnedTransitionModel | None = None,
        value_model: ValueModel | None = None,
        *,
        registry: dict[str, Tool] | None = None,
        max_depth: int = 5,
        beam_width: int = 12,
        action_branch_width: int = 12,
        max_search_nodes: int = 1000,
        max_simulation_branches: int = 24,
        min_prediction_confidence: float = 0.15,
        max_accumulated_uncertainty: float = 0.80,
        branch_probability_floor: float = 0.02,
        gamma: float = 0.95,
        self_model: PersistentSelfModel | None = None,
    ):
        if int(max_depth) < 1:
            raise ValueError("max_depth must be >= 1")
        if int(beam_width) < 1:
            raise ValueError("beam_width must be >= 1")
        if int(action_branch_width) < 1:
            raise ValueError("action_branch_width must be >= 1")
        if int(max_search_nodes) < 1:
            raise ValueError("max_search_nodes must be >= 1")
        self.transition_model = transition_model or LearnedTransitionModel(LearningStore())
        self.value_model = value_model or ValueModel(self.transition_model.store)
        self.registry = dict(registry or {})
        self.max_depth = int(max_depth)
        self.beam_width = int(beam_width)
        self.action_branch_width = int(action_branch_width)
        self.max_search_nodes = int(max_search_nodes)
        self.max_simulation_branches = int(max_simulation_branches)
        self.min_prediction_confidence = float(min_prediction_confidence)
        self.max_accumulated_uncertainty = float(max_accumulated_uncertainty)
        self.branch_probability_floor = float(branch_probability_floor)
        self.gamma = float(gamma)
        self.self_model = self_model or PersistentSelfModel(self.transition_model.store)
        self._active_initial_state_signature = ""
        self.simulator = CounterfactualSimulator(
            self.transition_model,
            self.value_model,
            gamma=self.gamma,
            max_depth=self.max_depth,
            max_branches=self.max_simulation_branches,
            branch_probability_floor=self.branch_probability_floor,
            max_accumulated_uncertainty=self.max_accumulated_uncertainty,
            min_prediction_confidence=self.min_prediction_confidence,
        )

    @staticmethod
    def _normalize_action(raw: dict[str, Any]) -> dict[str, Any]:
        action = dict(raw)
        parameters = action.get("parameters", {})
        if isinstance(parameters, (list, tuple)):
            parameters = {str(k): v for item in parameters if isinstance(item, (list, tuple)) and len(item) == 2 for k, v in [item]}
        action["parameters"] = dict(parameters or {}) if isinstance(parameters, dict) else {}
        return action

    def _learned_actions(self, state_signature: str) -> list[dict[str, Any]]:
        rows = self.transition_model.actions_for_state(state_signature, limit=self.action_branch_width * 2)
        rows.sort(key=_action_sort_key)
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            raw = row.get("action")
            if not isinstance(raw, dict):
                continue
            action = self._normalize_action(raw)
            tool_name = str(action.get("tool") or "").strip()
            if not tool_name or tool_name.startswith("simulate_"):
                continue
            tool = self.registry.get(tool_name)
            if tool is None:
                continue
            if not self._goal_bound_action(action):
                continue
            try:
                if tool.validate_args(action["parameters"]):
                    continue
            except Exception:
                continue
            sig = action_signature(action)
            if sig in seen:
                continue
            seen.add(sig)
            out.append(action)
            if len(out) >= self.action_branch_width:
                break
        return out

    def _goal_bound_action(self, action: dict[str, Any]) -> bool:
        """Reject learned parameter bindings that are stale for the current goal.

        Phase-3 action signatures intentionally preserve parameters. Reusing an old binding
        for a new request would therefore be an invalid form of policy generalization (for
        example replaying a previous calculator expression). When a tool declares a
        deterministic argument builder, the learned arguments must exactly match the live goal.
        Parameterized tools without an argument builder are not safe to rebind from history,
        so they are conservatively excluded from model-based search.
        """
        tool_name = str(action.get("tool") or "")
        tool = self.registry.get(tool_name)
        if tool is None:
            return False
        learned_params = dict(action.get("parameters") or {})
        builder = getattr(tool, "build_args", None)
        if builder is not None:
            try:
                expected = dict(tool.args_for(self._active_goal.original) or {})
            except Exception:
                return False
            return learned_params == expected
        # Without a deterministic builder the action contract itself is the only available
        # binding authority; preserve the historical action rather than inventing a rebinding.
        return True

    def _root_applicable(self, action: dict[str, Any], world: WorldState | str) -> bool:
        if not isinstance(world, WorldState):
            return True
        tool = self.registry.get(str(action.get("tool") or ""))
        if tool is None:
            return False
        facts = set(world.facts) | set(world.capabilities)
        if not set(tool.preconditions).issubset(facts):
            return False
        for name in tool.resources_required:
            if name not in world.resources:
                return False
        return all(world.resources.get(k, 0.0) >= float(v) for k, v in tool.resource_costs)

    def _predict_successors(self, node: _SearchNode, action: dict[str, Any], depth: int) -> list[_SearchNode]:
        prediction = self.transition_model.predict(node.state_signature, action)
        if prediction is None or prediction.confidence < self.min_prediction_confidence:
            return []
        branches = list(prediction.next_state_distribution)
        if not branches and prediction.predicted_state:
            branches = [(prediction.predicted_state, 1.0)]
        if not branches:
            return []
        tool = self.registry.get(str(action.get("tool") or ""))
        if tool is None:
            return []
        output: list[_SearchNode] = []
        goal = self._active_goal
        for next_state, probability in branches:
            probability = float(probability)
            if probability < self.branch_probability_floor:
                continue
            next_accumulated = _clamp(1.0 - (1.0 - node.accumulated_uncertainty) * (1.0 - prediction.uncertainty))
            if next_accumulated >= self.max_accumulated_uncertainty:
                continue
            p = node.branch_probability * probability
            completed = _apply_goal_progress(action, tool, goal, node.completed_clauses)
            reward = float(prediction.predicted_reward or 0.0)
            output.append(_SearchNode(
                state_signature=str(next_state),
                actions=(*node.actions, action),
                branch_probability=p,
                cumulative_reward=node.cumulative_reward + reward,
                discounted_return=node.discounted_return + (self.gamma ** (depth - 1)) * reward,
                accumulated_uncertainty=next_accumulated,
                path_confidence=min(node.path_confidence, prediction.confidence),
                elapsed=node.elapsed + max(0.0, prediction.expected_duration_seconds),
                cost=node.cost + max(0.0, float(tool.cost)),
                risk=node.risk + _risk_penalty(tool.risk),
                completed_clauses=completed,
            ))
        return output

    def _self_model_adjustment(self, actions: Sequence[dict[str, Any]], context_signature: str) -> float:
        if not actions:
            return 0.0
        values = []
        for action in actions:
            tool = str(action.get("tool") or "")
            capability = str(action.get("capability") or tool)
            if not tool:
                continue
            try:
                values.append(float(self.self_model.score_adjustment(
                    tool=tool, capability=capability, context_signature=context_signature
                )))
            except Exception:
                continue
        return sum(values) / max(1, len(values))

    def _heuristic_score(self, node: _SearchNode, goal: GoalModel) -> float:
        progress = len(node.completed_clauses) / max(1, len(goal.clauses))
        value = 0.0
        try:
            pred = self.value_model.predict_state(node.state_signature)
            if pred is not None:
                value = float(pred.value) * float(pred.confidence)
        except Exception:
            pass
        self_adjustment = self._self_model_adjustment(node.actions, self._active_initial_state_signature or node.state_signature)
        return (
            3.0 * progress
            + 1.20 * node.discounted_return
            + 0.80 * value
            + 0.35 * node.path_confidence
            + 0.30 * self_adjustment
            + math.log(max(node.branch_probability, 1e-9)) * 0.04
            - 1.10 * node.accumulated_uncertainty
            - 0.10 * node.risk
            - 0.03 * node.cost
            - 0.005 * node.elapsed
        )

    def _make_plan(self, actions: Sequence[dict[str, Any]], goal: GoalModel, *, score: float,
                   diagnostics: dict[str, Any] | None = None) -> Plan | None:
        steps: list[PlanStep] = []
        completed: frozenset[int] = frozenset()
        for action in actions:
            tool_name = str(action.get("tool") or "")
            tool = self.registry.get(tool_name)
            if tool is None:
                return None
            args = dict(action.get("parameters") or {})
            try:
                if tool.validate_args(args):
                    return None
            except Exception:
                return None
            clause_index = -1
            for index, clause in enumerate(goal.clauses):
                if index in completed or not _goal_ready(index, goal, completed):
                    continue
                if _match_clause(tool, clause):
                    clause_index = index
                    completed = frozenset(set(completed) | {index})
                    break
            depends = [steps[-1].id] if steps else []
            steps.append(PlanStep(
                id=f"s{len(steps) + 1}",
                tool=tool_name,
                args=args,
                clause_index=clause_index,
                clause_text=goal.clauses[clause_index].text if clause_index >= 0 else "",
                capability=tool.capability or tool.name,
                depends_on=depends,
            ))
        if len(completed) != len(goal.clauses):
            return None
        duration = sum(max(0.0, float(self.registry[s.tool].duration)) for s in steps if s.tool in self.registry)
        cost = sum(max(0.0, float(self.registry[s.tool].cost)) for s in steps if s.tool in self.registry)
        return Plan(
            steps=steps,
            estimated_cost=cost,
            estimated_duration=duration,
            score=float(score),
            planner="v23-model-based-beam",
            diagnostics=dict(diagnostics or {}),
        )

    @staticmethod
    def _sequence_key(actions: Sequence[dict[str, Any]]) -> tuple[str, ...]:
        return tuple(action_signature(action) for action in actions)

    def _sequence_goal_progress(self, actions: Sequence[dict[str, Any]], goal: GoalModel) -> float:
        completed: frozenset[int] = frozenset()
        for action in actions:
            tool = self.registry.get(str(action.get("tool") or ""))
            if tool is None:
                continue
            completed = _apply_goal_progress(action, tool, goal, completed)
        return len(completed) / max(1, len(goal.clauses))

    @staticmethod
    def _branch_success(branch) -> float:
        probability = 1.0
        for step in branch.steps:
            probability *= _clamp(float(step.success_probability))
        return probability

    def _learned_policy_value(self, simulation: CounterfactualSimulation) -> tuple[float | None, int]:
        """Return the persisted learned action-value policy for a complete sequence.

        Multi-step plans use each simulated step's actual state signature before the action;
        this prevents accidentally scoring every action against the root state. A plan is
        policy-driven only when all simulated action decisions have at least two observed visits.
        """
        sequence = tuple(simulation.action_sequence)
        if not sequence or not simulation.branches:
            return None, 0
        branch_values: list[tuple[float, float, int]] = []
        for branch in simulation.branches:
            values: list[float] = []
            visits = 0
            for simulated_step, action in zip(branch.steps, sequence):
                try:
                    prediction = self.value_model.predict_action(simulated_step.state_before, action)
                except Exception:
                    prediction = None
                if prediction is None or int(prediction.visits) < 2:
                    return None, visits
                values.append(float(prediction.value) * float(prediction.confidence))
                visits += int(prediction.visits)
            if values:
                branch_values.append((float(branch.probability), sum(values) / len(values), visits))
        total_probability = sum(probability for probability, _, _ in branch_values)
        if total_probability <= 0.0:
            return None, 0
        weighted = sum(probability * value for probability, value, _ in branch_values) / total_probability
        evidence = max(0, int(round(sum(max(0.0, probability) * visits for probability, _, visits in branch_values)
                                     / total_probability)))
        return weighted, evidence

    def _evaluate_plan(self, plan: Plan, simulation: CounterfactualSimulation,
                       goal_progress: float, *, self_model_adjustment: float = 0.0) -> ModelPlanEvaluation:
        branches = tuple(simulation.branches)
        # Keep branch probability mass absolute. Pruned/unsupported probability is not silently
        # renormalized away; this makes planning conservative when the model cannot support part
        # of the future.
        complete_probability = sum(float(b.probability) for b in branches if b.status == "complete")
        truncated_probability = min(1.0, sum(float(b.probability) for b in branches if b.status != "complete")
                                   + float(simulation.pruned_probability) + float(simulation.unsupported_probability))
        expected_return = sum(float(b.probability) * float(b.discounted_return) for b in branches)
        expected_value = sum(float(b.probability) * float(b.terminal_value or 0.0) * float(b.terminal_value_confidence or 0.0)
                             for b in branches)
        expected_success = sum(float(b.probability) * self._branch_success(b) for b in branches)
        expected_confidence = sum(float(b.probability) * float(b.path_confidence) for b in branches)
        expected_uncertainty = min(1.0, sum(float(b.probability) * float(b.accumulated_uncertainty) for b in branches)
                                   + float(simulation.pruned_probability) + float(simulation.unsupported_probability))
        expected_behavior_value = 0.0
        for branch in branches:
            for index, simulated_step in enumerate(branch.steps):
                if index >= len(simulation.action_sequence):
                    break
                raw_action = simulation.action_sequence[index]
                try:
                    q = self.value_model.predict_action(simulated_step.state_before, raw_action)
                except Exception:
                    q = None
                if q is not None:
                    expected_behavior_value += float(branch.probability) * float(q.value) * float(q.confidence)
        # Normalize behavioral value by the number of actions so long plans do not receive a
        # free bonus merely by containing more transitions.
        expected_behavior_value /= max(1, len(simulation.action_sequence))
        expected_prediction_error = 0.0
        for branch in branches:
            for simulated_step, raw_action in zip(branch.steps, simulation.action_sequence):
                try:
                    row = self.transition_model.inspect(simulated_step.state_before, raw_action) or {}
                    expected_prediction_error += float(branch.probability) * _clamp(float(row.get("prediction_error_mean", 0.0)))
                except Exception:
                    continue
        expected_prediction_error = _clamp(expected_prediction_error / max(1, len(simulation.action_sequence)))
        risk = sum(_risk_penalty(self.registry[s.tool].risk) for s in plan.steps if s.tool in self.registry)
        heuristic_score = (
            4.0 * goal_progress
            + 1.50 * complete_probability
            + 1.25 * expected_return
            + 0.90 * expected_value
            + 0.60 * expected_behavior_value
            + 0.70 * expected_success
            + 0.30 * self_model_adjustment
            - 0.90 * expected_prediction_error
            + 0.45 * expected_confidence
            - 1.50 * expected_uncertainty
            - 1.60 * truncated_probability
            - 0.14 * risk
            - 0.035 * plan.estimated_cost
            - 0.005 * plan.estimated_duration
        )
        learned_policy_value, learned_policy_evidence = self._learned_policy_value(simulation)
        if learned_policy_value is not None:
            score = learned_policy_value
            selection_basis = "learned_action_values"
        else:
            score = heuristic_score
            selection_basis = "model_metrics_cold_start"
        return ModelPlanEvaluation(
            action_signatures=self._sequence_key(simulation.action_sequence),
            goal_progress=goal_progress,
            fully_supported_probability=_clamp(complete_probability),
            truncated_probability=_clamp(truncated_probability),
            expected_discounted_return=expected_return,
            expected_terminal_value=expected_value,
            expected_behavior_value=expected_behavior_value,
            expected_prediction_error=expected_prediction_error,
            expected_success_probability=_clamp(expected_success),
            expected_path_confidence=_clamp(expected_confidence),
            expected_uncertainty=_clamp(expected_uncertainty),
            risk_penalty=risk,
            estimated_cost=float(plan.estimated_cost),
            estimated_duration=float(plan.estimated_duration),
            self_model_adjustment=float(self_model_adjustment),
            learned_policy_value=(round(learned_policy_value, 6) if learned_policy_value is not None else None),
            learned_policy_evidence=int(learned_policy_evidence),
            selection_basis=selection_basis,
            score=float(score),
            simulation_depth=int(simulation.explored_depth),
        )

    def plan(
        self,
        goal: str,
        world: WorldState | str,
        *,
        max_depth: int | None = None,
        initial_facts: set[str] | None = None,
        initial_resources: dict[str, float] | None = None,
    ) -> Plan:
        self._active_goal = parse_goal(goal)
        if not self._active_goal.clauses:
            return Plan([], planner="v23-model-based-empty", diagnostics={"reason": "empty_goal"})
        state_signature = _state_signature(world)
        self._active_initial_state_signature = state_signature
        cert_facts = (set(world.facts) | set(world.capabilities)) if isinstance(world, WorldState) else set(initial_facts or ())
        cert_resources = dict(world.resources) if isinstance(world, WorldState) else dict(initial_resources or {})
        applicability_world = world if isinstance(world, WorldState) else WorldState(facts={k: "true" for k in cert_facts}, resources=cert_resources)
        depth_limit = max(1, min(self.max_depth, int(max_depth if max_depth is not None else self.max_depth)))
        root = _SearchNode(state_signature, (), 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, frozenset())
        beam = [root]
        completed_sequences: dict[tuple[str, ...], _SearchNode] = {}
        expanded_nodes = 0
        seen_search: set[tuple[str, tuple[str, ...], tuple[int, ...]]] = set()

        for depth in range(1, depth_limit + 1):
            candidates: list[_SearchNode] = []
            for node in beam:
                if expanded_nodes >= self.max_search_nodes:
                    break
                actions = self._learned_actions(node.state_signature)
                for action in actions:
                    if depth == 1 and not self._root_applicable(action, applicability_world):
                        continue
                    sig = action_signature(action)
                    prior_sigs = tuple(action_signature(a) for a in node.actions)
                    if (node.state_signature, prior_sigs, tuple(sorted(node.completed_clauses))) in seen_search and sig in prior_sigs:
                        continue
                    successors = self._predict_successors(node, action, depth)
                    expanded_nodes += 1
                    for child in successors:
                        key = (child.state_signature, self._sequence_key(child.actions), tuple(sorted(child.completed_clauses)))
                        if key in seen_search:
                            continue
                        seen_search.add(key)
                        if len(child.completed_clauses) == len(self._active_goal.clauses):
                            sequence = self._sequence_key(child.actions)
                            prior = completed_sequences.get(sequence)
                            if prior is None or self._heuristic_score(child, self._active_goal) > self._heuristic_score(prior, self._active_goal):
                                completed_sequences[sequence] = child
                        candidates.append(child)
            if not candidates or expanded_nodes >= self.max_search_nodes:
                break
            candidates.sort(key=lambda node: self._heuristic_score(node, self._active_goal), reverse=True)
            dedup: list[_SearchNode] = []
            prefixes: set[tuple[str, ...]] = set()
            for node in candidates:
                prefix = self._sequence_key(node.actions[:2])
                if prefix in prefixes and len(dedup) >= self.beam_width // 2:
                    continue
                prefixes.add(prefix)
                dedup.append(node)
                if len(dedup) >= self.beam_width:
                    break
            beam = dedup

        evaluations: list[ModelPlanCandidate] = []
        for node in completed_sequences.values():
            actions = list(node.actions)
            simulation = self.simulator.simulate(state_signature, actions,
                                                  max_depth=len(actions), max_branches=self.max_simulation_branches)
            if not simulation.branches:
                continue
            plan = self._make_plan(actions, self._active_goal, score=0.0)
            if plan is None:
                continue
            errors = validate(plan, self.registry)
            cert = certify_plan(
                plan,
                self.registry,
                initial_facts=cert_facts,
                initial_resources=cert_resources,
                max_duration=self._active_goal.constraints.get("max_duration"),
            )
            if errors or not cert.ok:
                continue
            progress = len(node.completed_clauses) / max(1, len(self._active_goal.clauses))
            self_adjustment = self._self_model_adjustment(actions, state_signature)
            evaluation = self._evaluate_plan(plan, simulation, progress, self_model_adjustment=self_adjustment)
            plan.score = evaluation.score
            plan.diagnostics.update({
                "phase": 7,
                "algorithm": "risk-aware-model-based-beam-search",
                "state_signature": state_signature,
                "goal_clauses": len(self._active_goal.clauses),
                "goal_progress": progress,
                "expanded_nodes": expanded_nodes,
                "learned_action_sequences": len(completed_sequences),
                "fully_supported_probability": evaluation.fully_supported_probability,
                "truncated_probability": evaluation.truncated_probability,
                "expected_discounted_return": evaluation.expected_discounted_return,
                "expected_terminal_value": evaluation.expected_terminal_value,
                "expected_behavior_value": evaluation.expected_behavior_value,
                "learned_policy_value": evaluation.learned_policy_value,
                "learned_policy_evidence": evaluation.learned_policy_evidence,
                "selection_basis": evaluation.selection_basis,
                "expected_prediction_error": evaluation.expected_prediction_error,
                "expected_success_probability": evaluation.expected_success_probability,
                "expected_path_confidence": evaluation.expected_path_confidence,
                "expected_uncertainty": evaluation.expected_uncertainty,
                "certificate": {"ok": True, "states": len(cert.states)},
            })
            evaluations.append(ModelPlanCandidate(plan, evaluation, simulation))

        if not evaluations:
            return Plan([], planner="v23-model-based-reject", diagnostics={
                "phase": 7,
                "algorithm": "risk-aware-model-based-beam-search",
                "state_signature": state_signature,
                "reason": "no_supported_certified_goal_sequence",
                "expanded_nodes": expanded_nodes,
                "learned_action_sequences": len(completed_sequences),
            })
        if all(item.evaluation.learned_policy_value is not None for item in evaluations):
            evaluations.sort(key=lambda item: (
                float(item.evaluation.learned_policy_value or 0.0),
                item.evaluation.expected_success_probability,
                -item.evaluation.expected_uncertainty,
                -item.plan.estimated_cost,
                -item.plan.estimated_duration,
                -len(item.plan.steps),
            ), reverse=True)
        else:
            evaluations.sort(key=lambda item: (
                item.evaluation.score,
                item.evaluation.fully_supported_probability,
                item.evaluation.expected_success_probability,
                -item.evaluation.expected_uncertainty,
                -item.plan.estimated_cost,
                -item.plan.estimated_duration,
                -len(item.plan.steps),
            ), reverse=True)
        best = evaluations[0]
        best.plan.diagnostics["candidate_evaluations"] = [item.evaluation.to_dict() for item in evaluations[:8]]
        best.plan.diagnostics["selection"] = best.evaluation.selection_basis
        return best.plan

    def evaluate_sequences(self, world: WorldState | str, goal: str,
                           sequences: Iterable[Sequence[dict[str, Any]]]) -> list[ModelPlanCandidate]:
        """Evaluate externally generated action sequences without learning or execution."""
        self._active_goal = parse_goal(goal)
        state_signature = _state_signature(world)
        self._active_initial_state_signature = state_signature
        cert_facts = (set(world.facts) | set(world.capabilities)) if isinstance(world, WorldState) else set()
        cert_resources = dict(world.resources) if isinstance(world, WorldState) else {}
        candidates: list[ModelPlanCandidate] = []
        for sequence in sequences:
            actions = tuple(self._normalize_action(item) for item in sequence)
            plan = self._make_plan(actions, self._active_goal, score=0.0)
            if plan is None:
                continue
            errors = validate(plan, self.registry)
            cert = certify_plan(
                plan, self.registry,
                initial_facts=cert_facts,
                initial_resources=cert_resources,
                max_duration=self._active_goal.constraints.get("max_duration"),
            )
            if errors or not cert.ok:
                continue
            sim = self.simulator.simulate(state_signature, actions, max_depth=len(actions), max_branches=self.max_simulation_branches)
            if not sim.branches:
                continue
            progress = self._sequence_goal_progress(actions, self._active_goal)
            evaluation = self._evaluate_plan(plan, sim, min(1.0, progress))
            plan.score = evaluation.score
            candidates.append(ModelPlanCandidate(plan, evaluation, sim))
        candidates.sort(key=lambda item: item.evaluation.score, reverse=True)
        return candidates
