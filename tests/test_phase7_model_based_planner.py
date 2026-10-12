from __future__ import annotations

from app.domain.plan import validate
from app.domain.world import WorldState
from app.learning.store import LearningStore
from app.learning.transition_model import LearnedTransitionModel
from app.learning.value_model import ValueModel
from app.planning.model_based_planner import ModelBasedPlanner
from app.runtime.registry import Tool


def make_tool(name: str, goal_word: str, *, cost: float = 1.0, risk: str = "low",
              preconditions=(), produces=(), duration: float = 0.1) -> Tool:
    return Tool(
        name=name,
        description=name,
        params={"value": "number"} if name != "finish" else {},
        fn=lambda **kwargs: kwargs,
        triggers=(goal_word,),
        match=lambda g, word=goal_word: word.casefold() in str(g or "").casefold(),
        capability=name,
        preconditions=tuple(preconditions),
        produces=tuple(produces),
        cost=cost,
        duration=duration,
        risk=risk,
        idempotent=True,
    )


def action(tool: str, value: int | None = 1, *, capability: str | None = None,
           preconditions=(), effects=("done",), risk="low"):
    params = {} if value is None else {"value": value}
    return {
        "capability": capability or tool,
        "tool": tool,
        "parameters": params,
        "preconditions": list(preconditions),
        "expected_effects": list(effects),
        "risk": risk,
        "reversible": True,
    }


def transition(before: str, after: str, act: dict, reward: float) -> dict:
    return {
        "state_before": before,
        "action": act,
        "state_after": after,
        "outcome": {"ok": reward >= -0.5, "verified": reward >= 0.0, "duration_ms": 100, "attempt": 1},
        "verified": reward >= 0.0,
        "reward": reward,
        "failure_class": "" if reward >= 0 else "failure",
        "timestamp": "2026-09-30T12:00:00+00:00",
    }


def learn(tm, before, after, act, count=6, reward=0.2):
    for _ in range(count):
        assert tm.learn_transition(transition(before, after, act, reward))


def test_model_based_planner_finds_learned_two_step_goal(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    tm = LearnedTransitionModel(store)
    vm = ValueModel(store)
    registry = {
        "prepare": make_tool("prepare", "prepare", produces=("prepared",)),
        "finish": make_tool("finish", "finish", produces=("finished",)),
    }
    learn(tm, "S0", "S1", action("prepare"), count=8, reward=0.2)
    learn(tm, "S1", "S2", action("finish", None), count=8, reward=1.0)

    planner = ModelBasedPlanner(tm, vm, registry=registry, max_depth=3)
    plan = planner.plan("prepare then finish", "S0")

    assert plan.steps
    assert [step.tool for step in plan.steps] == ["prepare", "finish"]
    assert plan.planner == "v23-model-based-beam"
    assert plan.diagnostics["certificate"]["ok"] is True
    assert validate(plan, registry) == []


def test_model_based_planner_chooses_higher_expected_return(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    tm = LearnedTransitionModel(store)
    registry = {
        "good": make_tool("good", "complete", cost=1.0),
        "bad": make_tool("bad", "complete", cost=1.0),
    }
    learn(tm, "S", "G", action("good"), count=9, reward=1.0)
    learn(tm, "S", "B", action("bad"), count=9, reward=-0.8)

    planner = ModelBasedPlanner(tm, registry=registry, max_depth=1)
    plan = planner.plan("complete", "S")

    assert [step.tool for step in plan.steps] == ["good"]
    evaluations = plan.diagnostics["candidate_evaluations"]
    assert len(evaluations) >= 2
    assert evaluations[0]["score"] >= evaluations[-1]["score"]


def test_unknown_state_does_not_fabricate_model_plan(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    tm = LearnedTransitionModel(store)
    registry = {"finish": make_tool("finish", "finish", value=None) if False else make_tool("finish", "finish")}
    planner = ModelBasedPlanner(tm, registry=registry, max_depth=2)
    plan = planner.plan("finish", "UNKNOWN")
    assert plan.steps == []
    assert plan.planner == "v23-model-based-reject"
    assert plan.diagnostics["reason"] == "no_supported_certified_goal_sequence"


def test_planner_respects_root_preconditions_and_certificate(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    tm = LearnedTransitionModel(store)
    registry = {
        "finish": make_tool("finish", "finish", preconditions=("ready",)),
    }
    learn(tm, "S", "G", action("finish", None, preconditions=("ready",)), count=8, reward=1.0)
    planner = ModelBasedPlanner(tm, registry=registry, max_depth=1)

    plan = planner.plan("finish", WorldState(facts={"not_ready": "true"}))
    assert plan.steps == []


def test_model_planning_is_read_only(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    tm = LearnedTransitionModel(store)
    registry = {"finish": make_tool("finish", "finish")}
    learn(tm, "S", "G", action("finish", None), count=8, reward=1.0)
    before = store.transition_model_stats()
    before_errors = store.prediction_error_stats()

    planner = ModelBasedPlanner(tm, registry=registry, max_depth=1)
    plan = planner.plan("finish", "S")

    assert plan.steps
    assert store.transition_model_stats() == before
    assert store.prediction_error_stats() == before_errors


def test_evaluate_sequences_does_not_promote_unmodeled_action(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    tm = LearnedTransitionModel(store)
    registry = {"finish": make_tool("finish", "finish")}
    learn(tm, "S", "G", action("finish", None), count=8, reward=1.0)
    planner = ModelBasedPlanner(tm, registry=registry, max_depth=1)

    evaluated = planner.evaluate_sequences("S", "finish", [[action("finish", None)], [action("finish", 2)]])
    assert evaluated
    assert all(item.plan.steps for item in evaluated)
    assert len(evaluated) == 1
    assert store.transition_model_stats()["observations"] >= 1


def test_historical_prediction_error_is_exposed_and_penalized(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    tm = LearnedTransitionModel(store)
    registry = {
        "good": make_tool("good", "complete"),
        "other": make_tool("other", "complete"),
    }
    good_action = action("good")
    other_action = action("other")
    learn(tm, "S", "G", good_action, count=8, reward=1.0)
    learn(tm, "S", "O", other_action, count=8, reward=1.0)
    row = tm.inspect("S", good_action)
    assert row is not None
    # Feed bounded historical prediction-error evidence into only the good action.
    error_record = {
        "transition_id": "phase7-error",
        "state_signature": "S",
        "action_signature": row["action_signature"],
        "predicted_state": "G",
        "observed_state": "WRONG",
        "top_state_probability": 0.9,
        "top_state_hit": 0,
        "state_observed_probability": 0.1,
        "state_log_loss": 0.9,
        "state_brier": 0.8,
        "predicted_success_probability": 0.9,
        "observed_success": 1,
        "success_brier": 0.01,
        "predicted_verified_probability": 0.9,
        "observed_verified": 1,
        "verified_brier": 0.01,
        "outcome_log_loss": 0.01,
        "duration_error": 0.0,
        "reward_error": 0.0,
        "value_error": 0.0,
        "total_error": 0.9,
        "surprise": 0.9,
        "confidence": 0.9,
        "uncertainty": 0.1,
        "evidence_count": 8,
        "created_at": "2026-09-30T12:00:00+00:00",
    }
    assert store.record_prediction_error(error_record)
    planner = ModelBasedPlanner(tm, registry=registry, max_depth=1)
    evaluated = planner.evaluate_sequences("S", "complete", [[good_action], [other_action]])
    assert len(evaluated) == 2
    good_eval = next(x.evaluation for x in evaluated if x.plan.steps[0].tool == "good")
    other_eval = next(x.evaluation for x in evaluated if x.plan.steps[0].tool == "other")
    assert good_eval.expected_prediction_error > other_eval.expected_prediction_error
    assert good_eval.score < other_eval.score
