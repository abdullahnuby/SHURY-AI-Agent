from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.api import run_brain
from app.brain import CognitiveKernel
from app.brain.learning import BrainExperienceStore, LearningStore
from app.brain.store import BrainStateStore
from app.knowledge.memory import Memory
from app.learning.manager import SelfImprovementManager
from app.runtime.registry import Tool
from app.domain.world import WorldState
from app.learning.models import ExperienceRecord
from app.learning.transition_model import action_signature
from app.planning.planner import RulePlanner


def _kernel(tmp_path: Path) -> CognitiveKernel:
    store = LearningStore(tmp_path / "learning.db")
    return CognitiveKernel(
        memory=Memory(tmp_path / "memory.db"),
        registry={
            "calculator": Tool(
                "calculator", "", {"expression": "x"},
                lambda expression: 4,
                capability="calculate", produces=("calculation_completed",),
                verification_level="strong",
            ),
        },
        state_store=BrainStateStore(tmp_path / "brain_state.db"),
        experience_store=store,
    )


def test_brain_experience_store_is_the_canonical_learning_store(tmp_path: Path):
    store = BrainExperienceStore(tmp_path / "learning.db")
    assert store.__class__ is LearningStore
    assert "learning.db" in str(store.path)
    # The compatibility name must not create a Brain-owned parallel DB schema.
    store.record(
        session_id="s", user_text="q", operation="calculate", capability="calculate",
        tool="calculator", status="completed", verified=True, reward=1.0,
    )
    assert store.stats()["experiences"] == 1


def test_kernel_execution_closes_phases_2_to_7_loop(tmp_path: Path):
    brain = _kernel(tmp_path)
    first = brain.act("احسب 2 + 2", session_id="integration")
    assert first.status == "completed"
    first_events = [event for event in first.state.trace if event.get("kind") == "learning_recorded"]
    assert first_events and first_events[-1]["transition_count"] == 1

    manager = brain.learning
    exp1 = manager.store.get_experience(first.run_id)
    assert exp1 is not None and len(exp1.transitions) == 1
    assert manager.status()["transition_model"]["observations"] >= 1
    assert manager.status()["value_model"]["state_visits"] >= 1

    second = brain.act("احسب 2 + 2", session_id="integration")
    assert second.status == "completed"
    exp2 = manager.store.get_experience(second.run_id)
    assert exp2 is not None and len(exp2.transitions) == 1
    status = manager.status()
    assert status["prediction_error"]["predictions"] >= 1
    assert status["replay"]["transitions"] >= 2
    assert any(event.get("kind") == "learning_recorded" for event in second.state.trace)


def test_run_brain_uses_injected_kernel_and_learning_path(tmp_path: Path):
    brain = _kernel(tmp_path)
    result = run_brain("احسب 3 + 1", session_id="api-integration", kernel=brain)
    assert result.status == "completed"
    experience = brain.learning.store.get_experience(result.run_id)
    assert experience is not None
    assert experience.transitions
    assert brain.learning.status()["transition_model"]["observations"] >= 1


def test_rule_planner_uses_phase7_as_default_learned_candidate(tmp_path: Path):
    registry = {
        "finish": Tool(
            "finish", "", {}, lambda: True,
            capability="finish", produces=("finished",), verification_level="standard",
        )
    }
    world = WorldState(capabilities={"finish"})
    store = LearningStore(tmp_path / "learning.db")
    manager = SelfImprovementManager(store=store)
    signature = world.fingerprint()
    action = {
        "action_id": "finish:attempt:1",
        "capability": "finish",
        "tool": "finish",
        "parameters": {},
        "preconditions": [],
        "expected_effects": ["finished"],
        "risk": "low",
        "cost": 1.0,
        "reversible": True,
        "execution_time": 0.0,
        "historical_success": 2,
        "historical_failure": 0,
        "expected_reward": 1.0,
        "uncertainty": 0.1,
    }
    next_state = WorldState(capabilities={"finish", "finished"}).fingerprint()
    transitions = [{
        "state_before": signature,
        "action": action,
        "predicted_state": next_state,
        "state_after": next_state,
        "outcome": {"ok": True, "verified": True},
        "verified": True,
        "timestamp": "2026-09-30T00:00:00+00:00",
        "metadata": (),
        "reward": 1.0,
    }]
    manager.transition_model.learn_episode(transitions)
    manager.transition_model.learn_episode(transitions)
    plan = RulePlanner().plan("finish", memory=Memory(tmp_path / "memory.db"), world=world, learning=manager, registry=registry)
    assert plan.steps
    assert plan.planner.startswith("v23-model-based")
    assert plan.diagnostics.get("precedence") == "phase7-learned-default"


def test_model_based_planner_does_not_reuse_stale_goal_parameters(tmp_path: Path):
    from app.domain.goal import parse_goal
    from app.planning.model_based_planner import ModelBasedPlanner

    registry = {
        "calculator": Tool(
            "calculator", "", {"expression": "x"}, lambda expression: 17,
            capability="calculate", produces=("calculation_completed",),
            match=lambda goal: "احسب" in str(goal),
            build_args=lambda goal: {"expression": str(goal).replace("احسب", "").strip()},
        )
    }
    world = WorldState(capabilities={"calculate"})
    store = LearningStore(tmp_path / "learning.db")
    manager = SelfImprovementManager(store=store)
    old = {
        "action_id": "calculator:attempt:1", "capability": "calculate", "tool": "calculator",
        "parameters": {"expression": "12 * 7"}, "preconditions": [],
        "expected_effects": ["calculation_completed"], "risk": "low", "cost": 1.0,
        "reversible": True, "execution_time": 0.0,
    }
    next_state = WorldState(capabilities={"calculate", "calculation_completed"}).fingerprint()
    transition = {
        "state_before": world.fingerprint(), "action": old, "predicted_state": next_state,
        "state_after": next_state, "outcome": {"ok": True, "verified": True},
        "verified": True, "reward": 1.0, "timestamp": "2026-09-30", "metadata": (),
    }
    manager.transition_model.learn_episode([transition])
    manager.transition_model.learn_episode([transition])
    planner = ModelBasedPlanner(manager.transition_model, manager.value_model, registry=registry)
    result = planner.plan("احسب 5*3+2", world)
    assert not result.steps
    assert result.planner == "v23-model-based-reject"



def test_api_import_keeps_nlp_model_lazy():
    code = "import sys; import app.api; assert 'sentence_transformers' not in sys.modules"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    subprocess.run([sys.executable, "-c", code], check=True, env=env)
