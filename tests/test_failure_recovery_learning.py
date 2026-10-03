from pathlib import Path

from app.learning.diagnosis import task_signature
from app.learning.failure_recovery import FailureRecoveryLearner
from app.learning.store import LearningStore
from app.learning.transition_model import LearnedTransitionModel, action_signature
from app.learning.models import ExperienceRecord


def _action(tool, cost=1.0):
    return {"capability": tool, "tool": tool, "parameters": {}, "preconditions": [],
            "expected_effects": [tool + "_done"], "risk": "low", "reversible": True, "cost": cost}


def _exp(run_id, failed=False, tool="A", recovery_tool="D"):
    root = {"transition_id": run_id + ":root", "state_before": "S", "action": _action(tool),
            "state_after": "S1", "outcome": {"ok": not failed, "verified": not failed},
            "verified": not failed, "prediction_error": 0.85 if failed else 0.01, "failure_class": "execution" if failed else ""}
    transitions = [root]
    if not failed:
        transitions.append({"transition_id": run_id + ":next", "state_before": "S", "action": _action(recovery_tool, 0.5),
                            "state_after": "S2", "outcome": {"ok": True, "verified": True}, "verified": True, "prediction_error": 0.01})
    return ExperienceRecord(run_id, "do task", task_signature("do task"), "completed" if not failed else "failed",
                            1.0 if not failed else 0.0, 1.0 if not failed else 0.0, (),
                            None if not failed else "execution", (), "s", "2026-10-01T00:00:00", transitions=tuple(transitions), operation="do_task")


def test_failure_diagnosis_finds_verified_alternative(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    model = LearnedTransitionModel(store)
    learner = FailureRecoveryLearner(store, model)
    failed = _exp("f1", failed=True, tool="A")
    success = _exp("s1", failed=False, tool="D")
    diagnosis = learner.diagnose(failed, similar=[success])
    assert diagnosis is not None
    assert diagnosis.avoidable is True
    assert diagnosis.root_state_signature == "S"
    assert any(x["action"]["tool"] == "D" for x in diagnosis.alternative_actions)


def test_recovery_selection_is_model_only_before_execution(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    model = LearnedTransitionModel(store)
    model.learn_transition({"transition_id":"seed1","state_before":"S","action":_action("D",0.5),"state_after":"S2",
                            "outcome":{"ok":True,"verified":True},"verified":True,"reward":1.0,"timestamp":"2026-10-01T00:00:00"})
    learner = FailureRecoveryLearner(store, model)
    diagnosis = learner.diagnose(_exp("f1", failed=True, tool="A"), similar=[_exp("s1", failed=False, tool="D")])
    recovery = learner.choose_recovery(diagnosis)
    assert recovery.simulation
    assert all(item["simulation_only"] and item["side_effects"] == 0 for item in recovery.simulation)
    assert all(item.get("side_effects") == 0 for item in recovery.candidates)


def test_recovery_lesson_promotes_after_repeated_verified_recovery(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    model = LearnedTransitionModel(store)
    # Teach D from S so bounded simulation has real evidence.
    model.learn_transition({"transition_id":"seed1","state_before":"S","action":_action("D",0.5),"state_after":"S2",
                            "outcome":{"ok":True,"verified":True},"verified":True,"reward":1.0,"timestamp":"2026-10-01T00:00:00"})
    learner = FailureRecoveryLearner(store, model)
    failed = _exp("f1", failed=True, tool="A")
    success = _exp("s1", failed=False, tool="D")
    for run in ("f1", "f2"):
        current = failed if run == "f1" else _exp("f2", failed=True, tool="A")
        diagnosis = learner.diagnose(current, similar=[success])
        recovery = learner.choose_recovery(diagnosis)
        result = learner.learn(diagnosis, recovery, recovery_verified=True)
    assert result["promotion"]["status"] == "promoted"
    assert store.recovery_lessons(status="promoted")[0]["verified_successes"] == 2
