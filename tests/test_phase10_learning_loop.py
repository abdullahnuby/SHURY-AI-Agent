from __future__ import annotations

from pathlib import Path

from app.brain import CognitiveKernel
from app.brain.store import BrainStateStore
from app.knowledge.memory import Memory
from app.learning.store import LearningStore
from app.runtime.registry import Tool


def _kernel(tmp_path: Path) -> CognitiveKernel:
    store = LearningStore(tmp_path / "learning.db")
    return CognitiveKernel(
        memory=Memory(tmp_path / "memory.db"),
        registry={
            "calculator": Tool(
                "calculator", "", {"expression": "x"},
                lambda expression: 42,
                capability="calculate", produces=("calculation_completed",),
                verification_level="strong",
            ),
        },
        state_store=BrainStateStore(tmp_path / "brain_state.db"),
        experience_store=store,
    )


def test_phase10_learning_cycle_records_the_real_ordered_loop(tmp_path: Path):
    brain = _kernel(tmp_path)
    result = brain.act("calculate 6*7", session_id="phase10-order")
    assert result.status == "completed"

    cycle = brain.learning.store.learning_cycle(result.run_id)
    assert cycle is not None
    assert cycle["status"] == "completed"
    names = [item["stage"] for item in cycle["stages"]]
    assert names[:7] == [
        "reward_calculated",
        "prediction_error_scored",
        "experience_recorded",
        "replay_indexed",
        "world_model_update",
        "value_update",
        "policy_update",
    ]
    assert "procedure_update" in names
    assert "lesson_update" in names
    assert "skill_update" in names
    assert "self_model_refresh" in names
    assert all(item["status"] == "completed" for item in cycle["stages"])


def test_phase10_same_run_id_does_not_double_apply_learning(tmp_path: Path):
    brain = _kernel(tmp_path)
    result = brain.act("calculate 8*5", session_id="phase10-idempotent")
    assert result.status == "completed"
    before_model = brain.learning.status()["transition_model"]["observations"]
    before_values = brain.learning.status()["value_model"]["state_visits"]

    proxy = brain._learning_proxy(result.state, [], status=result.status, run_id=result.run_id)
    duplicate = brain.learning.observe_run(proxy, brain.memory, trajectory=[], registry=brain.registry)
    after_model = brain.learning.status()["transition_model"]["observations"]
    after_values = brain.learning.status()["value_model"]["state_visits"]

    assert duplicate["duplicate"] is True
    assert before_model == after_model
    assert before_values == after_values


def test_phase10_policy_evidence_is_real_action_value_update(tmp_path: Path):
    brain = _kernel(tmp_path)
    result = brain.act("calculate 9*9", session_id="phase10-policy")
    assert result.status == "completed"
    experience = brain.learning.store.get_experience(result.run_id)
    assert experience is not None and experience.transitions
    state_signature = str(experience.transitions[0]["state_before"])
    estimates = brain.learning.value_model.action_estimates(state_signature)
    assert estimates
    assert estimates[0].visits >= 1
    assert result.state.trace[-1]["kind"] == "learning_recorded"
    learning = result.state.trace[-1]["learning"]
    assert learning["learning_cycle"]["policy_updated"] is True
