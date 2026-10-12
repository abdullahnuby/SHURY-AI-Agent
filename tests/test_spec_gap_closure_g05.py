from __future__ import annotations

import json
import uuid
from pathlib import Path

from app.evaluation.learning_metrics import (
    action_selection_accuracy,
    catastrophic_forgetting,
    evaluate_learning_progress,
    exploration_efficiency,
    learning_speed,
    regression_rate,
    transfer_rate,
)
from app.learning.bandit import NonStationaryBandit
from app.learning.manager import SelfImprovementManager
from app.learning.replay import replay_priority_components
from app.learning.store import LearningStore
from app.learning.transition_model import LearnedTransitionModel
from app.learning.value_model import RewardModel, ValueModel
from app.planning.model_based_planner import ModelBasedPlanner
from app.runtime.registry import Tool


def _action(name: str, *, cost: float = 1.0) -> dict:
    return {
        "action_id": f"{name}:test",
        "capability": name,
        "tool": name,
        "parameters": {},
        "preconditions": [],
        "expected_effects": [name],
        "risk": "low",
        "reversible": True,
        "cost": cost,
    }


def _transition(state: str, action: dict, next_state: str, *, ok: bool = True,
                reward: float | None = None, error: float = 0.0, metadata=()) -> dict:
    return {
        "transition_id": uuid.uuid4().hex,
        "state_before": state,
        "action": action,
        "state_after": next_state,
        "outcome": {"ok": ok, "verified": ok, "attempt": 1},
        "verified": ok,
        "reward": (1.0 if ok else 0.0) if reward is None else reward,
        "prediction_error": error,
        "timestamp": "2026-10-01T00:00:00+00:00",
        "metadata": metadata,
        "failure_class": "execution" if not ok else "",
    }


def _tool(name: str, *, goal_word: str, cost: float = 1.0, exploration_safe: bool = False,
          info_domain: tuple[str, ...] = ()) -> Tool:
    return Tool(
        name=name,
        description=name,
        params={},
        fn=lambda **_: True,
        capability=name,
        produces=(name,),
        cost=cost,
        duration=0.1,
        risk="low",
        idempotent=True,
        exploration_safe=exploration_safe,
        emits_world_delta=False,
        information_domains=info_domain,
        information_gain_prior=0.95 if info_domain else 0.0,
        match=lambda goal, token=goal_word: token.casefold() in str(goal or "").casefold(),
    )


def test_g05_1_reward_keeps_raw_multi_dimensional_evidence(tmp_path: Path):
    model = RewardModel()
    transition = _transition(
        "S", _action("do"), "G", metadata=(
            ("goal_alignment", 0.40),
            ("unnecessary_action", True),
            ("resource_consumed", 7.5),
            ("recovery_quality", 0.8),
        )
    )
    annotated = model.annotate_episode([transition], episode_reward=1.0, episode_status="completed")[0]
    meta = dict(annotated["metadata"])
    raw = meta["reward_raw_components"]
    assert raw["goal_alignment"] == 0.4
    assert raw["unnecessary_action"] == 1.0
    assert raw["resource_consumption"] == 7.5
    assert raw["recovery_quality"] == 0.8
    assert "terminal_goal" in meta["reward_components"]


def test_g05_3_real_nonstationary_bandit_detects_distribution_change(tmp_path: Path):
    bandit = NonStationaryBandit(["X", "Y"], exploration=1.0, detector_threshold=7.0)
    seed = 17

    def rnd() -> float:
        nonlocal seed
        seed = (1103515245 * seed + 12345) % 2**31
        return seed / 2**31

    selections: list[str] = []
    change_points = []
    for i in range(240):
        arm = bandit.choose_arm()
        selections.append(arm)
        probability = (0.80 if arm == "X" else 0.20) if i < 120 else (0.20 if arm == "X" else 0.80)
        observed_reward = 1.0 if rnd() < probability else 0.0
        if bandit.observe_reward(arm, observed_reward):
            change_points.append(bandit.last_change)

    assert change_points
    assert any(point and point.pull_index > 120 for point in change_points)
    assert selections[30:110].count("X") > selections[30:110].count("Y")
    assert selections[170:240].count("Y") > selections[170:240].count("X")


def test_g05_3_a_to_d_to_c_is_chosen_when_it_is_lower_cost(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    tm = LearnedTransitionModel(store)
    vm = ValueModel(store)
    registry = {
        "to_b": _tool("to_b", goal_word="move", cost=5.0),
        "to_d": _tool("to_d", goal_word="move", cost=1.0),
        "finish": _tool("finish", goal_word="finish", cost=1.0),
    }
    for _ in range(8):
        tm.learn_transition(_transition("A", _action("to_b", cost=5.0), "B", reward=0.8))
        tm.learn_transition(_transition("B", _action("finish"), "C", reward=1.0))
        tm.learn_transition(_transition("A", _action("to_d"), "D", reward=0.8))
        tm.learn_transition(_transition("D", _action("finish"), "C", reward=1.0))
    planner = ModelBasedPlanner(tm, vm, registry=registry, max_depth=2)
    plan = planner.plan("move then finish", "A")
    assert [step.tool for step in plan.steps] == ["to_d", "finish"]
    assert plan.estimated_cost == 2.0


def test_g05_3_x_is_context_specific(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    tm = LearnedTransitionModel(store)
    vm = ValueModel(store)
    registry = {"X": _tool("X", goal_word="complete"), "Y": _tool("Y", goal_word="complete")}
    for _ in range(12):
        tm.learn_transition(_transition("C", _action("X"), "G", ok=True))
        tm.learn_transition(_transition("C", _action("Y"), "YFAIL", ok=False))
        tm.learn_transition(_transition("N", _action("X"), "XFAIL", ok=False))
        tm.learn_transition(_transition("N", _action("Y"), "G", ok=True))
    planner = ModelBasedPlanner(tm, vm, registry=registry, max_depth=1)
    assert [s.tool for s in planner.plan("complete", "C").steps] == ["X"]
    assert [s.tool for s in planner.plan("complete", "N").steps] == ["Y"]


def test_g05_3_rare_high_error_failure_gets_replay_priority(tmp_path: Path):
    normal = _transition("S", _action("normal"), "G", ok=True, error=0.02)
    rare = _transition("S", _action("rare"), "BAD", ok=False, reward=-0.8, error=0.95)
    low = replay_priority_components(normal, occurrence_count=20)
    high = replay_priority_components(rare, occurrence_count=0, contradictory=True)
    assert high["failure_importance"] == 1.0
    assert high["prediction_error"] > low["prediction_error"]
    assert high["priority"] > low["priority"]


def test_g05_4_metrics_and_catastrophic_forgetting_gate():
    assert transfer_rate([True, True], [True, False]) == 0.5
    assert regression_rate({"old-a": True, "old-b": True}, {"old-a": True, "old-b": False}) == 0.5
    forget = catastrophic_forgetting({"A": [True, True], "B": [True, True]}, {"A": [True, False], "B": [True, True]})
    assert forget == 0.5
    assert learning_speed([0.2, 0.6, 0.81]) == 1 / 3
    assert exploration_efficiency([
        {"executed": True, "verified": True, "realized_information_gain": 0.8, "cost": 1.0},
        {"executed": True, "verified": False, "realized_information_gain": 0.4, "cost": 1.0},
    ]) > 0
    assert action_selection_accuracy(["X", "Y"], ["X", "Y"]) == 1.0

    metrics = evaluate_learning_progress(
        source_results=[True], target_results=[True, False],
        baseline={"A": True}, after={"A": True},
        forgetting_baseline={"A": [True, True]}, forgetting_after={"A": [True, False]},
        learning_history=[0.4, 0.9], explorations=[{"verified": True, "realized_information_gain": 0.8, "cost": 1.0}],
        selected_actions=["X"], oracle_actions=["X"],
    )
    assert metrics.transfer_rate == 0.5
    assert metrics.catastrophic_forgetting == 0.5
    assert metrics.action_selection_accuracy == 1.0


def test_g05_4_context_specific_self_model_influences_planning(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    manager = SelfImprovementManager(store=store)
    from app.learning.models import ExperienceRecord

    def exp(run_id: str, context: str, tool: str, ok: bool) -> ExperienceRecord:
        action = _action(tool)
        tr = _transition("state", action, "next" if ok else "bad", ok=ok,
                         metadata=(("context_signature", context), ("confidence_before", 0.9)))
        return ExperienceRecord(
            run_id, "goal", "family", "completed" if ok else "failed", 1.0 if ok else 0.0, 1.0 if ok else 0.0,
            [{"status": "done" if ok else "failed", "tool": tool}], "" if ok else "execution",
            (), None, "2026-10-01T00:00:00+00:00", context, (tr,), "",
        )

    for i in range(5):
        manager.self_model.learn(exp(f"ok-{i}", "context-good", "X", True))
        manager.self_model.learn(exp(f"bad-{i}", "context-bad", "X", False))
    good = manager.self_model.assess(tool="X", capability="X", context_signature="context-good")
    bad = manager.self_model.assess(tool="X", capability="X", context_signature="context-bad")
    assert good.reliability > bad.reliability
    assert good.adjustment > bad.adjustment


def test_g05_4_credit_assignment_propagates_a_to_b_to_c(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    learner = ValueModel(store, gamma=0.9, alpha=0.4, lam=0.9)
    episode = RewardModel().annotate_episode([
        _transition("A", _action("a"), "B"),
        _transition("B", _action("b"), "C"),
        _transition("C", _action("c"), "G"),
    ], episode_reward=1.0, episode_status="completed")
    learner.learn_episode(episode, episode_reward=1.0, episode_status="completed")
    qa = learner.predict_action("A", _action("a"))
    qb = learner.predict_action("B", _action("b"))
    qc = learner.predict_action("C", _action("c"))
    assert qa and qb and qc
    assert qa.value > 0 and qb.value > 0 and qc.value > 0
    assert qc.value >= qb.value >= qa.value


def test_g05_4_information_gain_prefers_safe_inspection_over_uncertain_action(tmp_path: Path):
    manager = SelfImprovementManager(store=LearningStore(tmp_path / "learning.db"))
    inspect = _tool("inspect", goal_word="complete", cost=0.2, exploration_safe=True, info_domain=("research",))
    execute = _tool("execute", goal_word="complete", cost=1.0, exploration_safe=False)
    state = "S"
    execute_action = _action("execute")
    # Create a learned high-failure execution path; inspect remains safe and information-bearing.
    for _ in range(8):
        manager.transition_model.learn_transition(_transition(state, execute_action, "BAD", ok=False, reward=-0.8, error=0.8))
    decision = manager.exploration_policy.decide(
        state, "complete", [_action("inspect"), execute_action], {"inspect": inspect, "execute": execute}
    )
    assert decision is not None
    assert decision.selected_tool == "inspect"
    assert decision.information_value >= 0.18
    assert decision.expected_failure_cost >= 0.0


def test_g05_5_procedure_family_transfers_across_value_slots():
    from app.learning.procedures import task_family_signature
    assert task_family_signature("calculate 20+30") == task_family_signature("calculate 40+50")


def test_g05_5_catastrophic_forgetting_is_measured_after_new_learning(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    learner = ValueModel(store, gamma=0.9, alpha=0.4, lam=0.9)
    old = RewardModel().annotate_episode([_transition("OLD", _action("old"), "OLD-G")], episode_reward=1.0, episode_status="completed")
    learner.learn_episode(old, episode_reward=1.0, episode_status="completed")
    old_before = learner.predict_action("OLD", _action("old"))
    assert old_before

    new = RewardModel().annotate_episode([_transition("NEW", _action("new"), "NEW-G")], episode_reward=1.0, episode_status="completed")
    for _ in range(30):
        learner.learn_episode(new, episode_reward=1.0, episode_status="completed")
    old_after = learner.predict_action("OLD", _action("old"))
    assert old_after
    measured = catastrophic_forgetting({"old-task": [old_before.value > 0]}, {"old-task": [old_after.value > 0]})
    assert measured == 0.0


def test_g05_5_self_model_context_actually_changes_planner_choice(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    manager = SelfImprovementManager(store=store)
    from app.learning.models import ExperienceRecord

    registry = {"X": _tool("X", goal_word="complete"), "Y": _tool("Y", goal_word="complete")}
    # Equal world-model evidence: only contextual self-model reliability differentiates the actions.
    for _ in range(8):
        manager.transition_model.learn_transition(_transition("CTX", _action("X"), "G", ok=True))
        manager.transition_model.learn_transition(_transition("CTX", _action("Y"), "G", ok=True))

    def experience(run_id: str, tool: str, ok: bool) -> ExperienceRecord:
        tr = _transition("CTX", _action(tool), "G" if ok else "BAD", ok=ok, metadata=(("context_signature", "CTX"), ("confidence_before", 0.8)))
        return ExperienceRecord(run_id, "complete", "complete-family", "completed" if ok else "failed", 1.0 if ok else 0.0, 1.0 if ok else 0.0,
                                [{"status": "done" if ok else "failed", "tool": tool}], "" if ok else "execution", (), None,
                                "2026-10-01T00:00:00+00:00", "CTX", (tr,), "")
    for i in range(6):
        manager.self_model.learn(experience(f"good-{i}", "X", True))
        manager.self_model.learn(experience(f"bad-{i}", "Y", False))

    planner = ModelBasedPlanner(manager.transition_model, manager.value_model, registry=registry, max_depth=1, self_model=manager.self_model)
    plan = planner.plan("complete", "CTX")
    assert [step.tool for step in plan.steps] == ["X"]
    assert plan.diagnostics["candidate_evaluations"][0]["self_model_adjustment"] >= plan.diagnostics["candidate_evaluations"][-1]["self_model_adjustment"]


def test_g03_procedure_generalization_aggregates_distinct_value_slots(tmp_path: Path):
    from app.learning.procedures import task_family_signature
    store = LearningStore(tmp_path / "learning.db")
    family_a = task_family_signature("calculate 20+30")
    family_b = task_family_signature("calculate 40+50")
    assert family_a == family_b
    workflow = [{"tool": "calculator", "capability": "calculate", "parameters": {"expression": "<expr>"}}]
    for run_id, success in [("r-20", True), ("r-40", True)]:
        store.upsert_procedural_memory(
            task_family_signature=family_a,
            operation="calculate",
            capability="calculate",
            workflow=workflow,
            trigger_conditions=["operation:calculate"],
            termination_conditions=["calculation_verified"],
            recovery_strategy=["retry-with-validated-expression"],
            context_boundary=["calculator-input"],
            evidence_run_ids=[run_id],
            success=success,
            confidence=0.92,
        )
    rows = store.procedural_memories(task_family_signature=family_b, operation="calculate", include_invalidated=True)
    assert len(rows) == 1
    assert rows[0]["successes"] == 2
    assert set(rows[0]["evidence_run_ids"]) == {"r-20", "r-40"}
    assert rows[0]["task_family_signature"] == family_b


def test_g05_6_learning_metrics_are_persisted(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    metrics = evaluate_learning_progress(
        source_results=[True, True],
        target_results=[True, False],
        baseline={"old": True},
        after={"old": True},
        forgetting_baseline={"old": [True, True]},
        forgetting_after={"old": [True, True]},
        learning_history=[0.2, 0.9],
        explorations=[{"executed": True, "verified": True, "realized_information_gain": 0.8, "cost": 1}],
        selected_actions=["inspect"],
        oracle_actions=["inspect"],
        store=store,
        run_id="metrics-proof",
    )
    rows = store.latest_learning_metrics(limit=1)
    assert rows and rows[0]["run_id"] == "metrics-proof"
    assert rows[0]["metrics"]["transfer_rate"] == metrics.transfer_rate
    assert rows[0]["metrics"]["catastrophic_forgetting"] == 0.0


def test_g05_4_planner_prefers_information_first_when_failure_cost_is_high(tmp_path: Path):
    from app.brain.models import CandidateAction, GoalSpec, SemanticFrame, CognitiveState
    from app.brain.planner import plan as brain_plan

    store = LearningStore(tmp_path / "learning.db")
    manager = SelfImprovementManager(store=store)
    for _ in range(8):
        store.record_meta_strategy_observation("atomic", "information-first", 1.0, True, {})
        store.record_meta_strategy_observation("atomic", "direct", 0.0, False, {})

    inspect = Tool(
        "inspect", "Inspect current state", {}, lambda **_: True,
        capability="inspect", produces=("state_inspected",), cost=0.2, duration=0.1,
        risk="low", idempotent=True, exploration_safe=True, emits_world_delta=False,
        information_domains=("task",), information_gain_prior=0.95,
        match=lambda goal: "task" in str(goal or "").casefold(),
    )
    execute = Tool(
        "execute", "Execute target operation", {}, lambda **_: True,
        capability="execute", produces=("completed",), cost=5.0, duration=0.2,
        risk="low", idempotent=True, exploration_safe=False,
    )
    registry = {"inspect": inspect, "execute": execute}
    frame = SemanticFrame(
        text="complete the task", language="en", speech_act="command",
        concepts=("complete",), requested_operation="project_task", slots=(), uncertainty=(),
    )
    goal = GoalSpec(name="project_task", objective="complete the task", desired_state=("completed",))
    state = CognitiveState(user_text=frame.text, semantic=frame)
    state.world_facts = {"task_uncertain": "true"}
    deterministic_candidates = [
        CandidateAction("execute", "execute", 2.0, "direct", (), True, (), ("completed",), "low", 5.0),
    ]
    result = brain_plan(
        goal, frame, deterministic_candidates, state=state,
        experiences=manager.store, learning=manager, registry=registry,
    )
    assert result and result[0].tool == "inspect"
    routes = [e for e in state.trace if e.get("kind") == "meta_strategy_route"]
    assert routes and routes[-1]["strategy"] == "information-first"
    assert result[0].exploration_mode in {"information", "explore", "relearn"}
