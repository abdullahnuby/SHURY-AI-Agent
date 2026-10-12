from __future__ import annotations

from pathlib import Path

from app.learning.models import ExperienceRecord
from app.learning.replay import ExperienceReplayLearner, PrioritizedReplayBuffer
from app.learning.store import LearningStore
from app.learning.transition_model import action_signature
from app.learning.value_model import RewardModel, ValueModel


def _transition(run_id: str, idx: int, before: str, after: str, *, reward: float, error: float, ok: bool = True):
    action = {
        "capability": "probe",
        "tool": f"action_{idx}",
        "parameters": {},
        "preconditions": (),
        "expected_effects": (f"state_{after}",),
        "risk": "low",
        "reversible": True,
    }
    return {
        "transition_id": f"{run_id}:t{idx}",
        "state_before": before,
        "state_after": after,
        "action": action,
        "outcome": {"ok": ok, "verified": ok, "attempt": 1},
        "verified": ok,
        "reward": reward,
        "prediction_error": error,
        "failure_class": "" if ok else "execution",
        "timestamp": "2026-09-30T00:00:00",
    }


def _episode(run_id: str, transitions: tuple[dict, ...], reward: float = 1.0):
    return ExperienceRecord(
        run_id=run_id,
        goal="probe",
        task_signature="probe",
        status="completed",
        reward=reward,
        verified_rate=1.0,
        steps=({"step": "s1", "tool": "action_0", "status": "done", "verified": True},),
        failure_class=None,
        lesson_keys=(),
        session_id=None,
        created_at="2026-09-30T00:00:00",
        environment_signature="env",
        transitions=transitions,
        operation="probe",
    )


def _seed(store: LearningStore, replay: PrioritizedReplayBuffer):
    episode = _episode("run-a", (
        _transition("run-a", 0, "S0", "S1", reward=0.2, error=0.05),
        _transition("run-a", 1, "S1", "S2", reward=0.9, error=0.9),
    ))
    store.record_experience(episode)
    replay.add_episode(episode)
    return episode


def test_replay_applies_real_historical_evidence_without_new_observations(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    replay = PrioritizedReplayBuffer(store, capacity=20, seed=7)
    episode = _seed(store, replay)
    value = ValueModel(store, reward_model=RewardModel())
    learner = ExperienceReplayLearner(replay, store, value)

    value.learn_episode(episode.transitions, episode_reward=episode.reward, episode_status=episode.status)
    before = value.predict_action("S0", episode.transitions[0]["action"])
    observations_before = store.transition_model_stats()["observations"]
    replay_before = store.replay_stats()["replays"]

    result = learner.replay(batch_size=1, seed=11)

    after = value.predict_action("S0", episode.transitions[0]["action"])
    observations_after = store.transition_model_stats()["observations"]
    replay_after = store.replay_stats()["replays"]

    assert result.completed == 1
    assert result.side_effects_executed == 0
    assert observations_after == observations_before
    assert replay_after == replay_before + 1
    assert before is not None and after is not None
    assert after.value != before.value
    assert store.replay_update_stats()["completed"] == 1


def test_replay_does_not_increase_empirical_visit_counts(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    replay = PrioritizedReplayBuffer(store, capacity=20, seed=2)
    episode = _seed(store, replay)
    value = ValueModel(store)
    value.learn_episode(episode.transitions, episode_reward=episode.reward, episode_status=episode.status)
    before = value.stats()

    learner = ExperienceReplayLearner(replay, store, value)
    learner.replay(batch_size=1, seed=5)

    after = value.stats()
    assert after["state_visits"] == before["state_visits"]
    assert after["action_visits"] == before["action_visits"]


def test_prioritized_replay_learning_excludes_current_episode(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    replay = PrioritizedReplayBuffer(store, capacity=20, seed=4)
    old = _seed(store, replay)
    current = _episode("run-current", (_transition("run-current", 0, "S0", "Sx", reward=1.0, error=0.2),))
    store.record_experience(current)
    replay.add_episode(current)
    value = ValueModel(store)
    learner = ExperienceReplayLearner(replay, store, value)

    result = learner.replay(batch_size=8, seed=9, exclude_episode_id="run-current")
    assert result.sampled >= 1
    sampled_updates = store.replay_update_stats()["updates"]
    assert sampled_updates >= 1
    assert all(item.episode_id != "run-current" for item in replay.items() if item.replay_count > 0)


def test_second_real_run_activates_historical_replay_inside_learning_cycle(tmp_path: Path):
    from app.brain import CognitiveKernel
    from app.brain.store import BrainStateStore
    from app.knowledge.memory import Memory
    from app.runtime.registry import Tool

    store = LearningStore(tmp_path / "learning.db")
    brain = CognitiveKernel(
        memory=Memory(tmp_path / "memory.db"),
        registry={
            "calculator": Tool(
                "calculator", "", {"expression": "x"}, lambda expression: 42,
                capability="calculate", produces=("calculation_completed",), verification_level="strong",
            )
        },
        state_store=BrainStateStore(tmp_path / "brain_state.db"),
        experience_store=store,
    )

    first = brain.act("calculate 6*7", session_id="replay-cycle-1")
    second = brain.act("calculate 6*7", session_id="replay-cycle-2")
    assert first.status == second.status == "completed"
    cycle = store.learning_cycle(second.run_id)
    assert cycle is not None
    replay_stage = next(item for item in cycle["stages"] if item["stage"] == "replay_learning")
    assert replay_stage["status"] == "completed"
    assert replay_stage["payload"]["sampled"] >= 1
    assert store.replay_update_stats()["completed"] >= 1


def test_replay_index_persists_across_store_instances_and_retains_priority_metadata(tmp_path: Path):
    path = tmp_path / "learning.db"
    first_store = LearningStore(path)
    replay = PrioritizedReplayBuffer(first_store, capacity=20, seed=3)
    episode = _seed(first_store, replay)
    before = replay.top(10)[0]
    assert before.model_version >= 1
    assert 0.0 < before.model_change_recency <= 1.0

    second_store = LearningStore(path)
    second_replay = PrioritizedReplayBuffer(second_store, capacity=20, seed=3)
    after = second_replay.top(10)
    assert len(after) == 2
    assert {item.episode_id for item in after} == {episode.run_id}
    restored = next(item for item in after if item.transition_id == before.transition_id)
    assert restored.model_version == before.model_version
    assert restored.model_change_recency == before.model_change_recency


def test_recent_model_change_gets_bounded_replay_priority(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    replay = PrioritizedReplayBuffer(store, capacity=20, seed=5)
    old_t = _transition("old-model", 0, "S0", "S1", reward=0.4, error=0.1)
    new_t = dict(_transition("new-model", 0, "S0", "S2", reward=0.4, error=0.1))
    old_t["metadata"] = (("world_model_version", 1),)
    new_t["metadata"] = (("world_model_version", 3),)
    old = _episode("old-model", (old_t,))
    new = _episode("new-model", (new_t,))

    from app.learning.transition_model import action_signature
    action = new_t["action"]
    store.upsert_transition_observation(
        state_signature="S0", action_signature=action_signature(action), action=action,
        next_state="seed", outcome_key="ok", failure_key=None, ok=True, verified=True,
        duration_seconds=0.1, reward=0.5, observed_at="2026-09-30T00:00:00",
    )
    store.upsert_transition_observation(
        state_signature="S0", action_signature=action_signature(action), action=action,
        next_state="seed2", outcome_key="ok", failure_key=None, ok=True, verified=True,
        duration_seconds=0.1, reward=0.5, observed_at="2026-09-30T00:00:01",
    )
    # The current model version is now 2; the transition captured at version 3 is newer than
    # the legacy version-1 transition and must retain a larger recency signal when reindexed.
    for exp in (old, new):
        store.record_experience(exp)
        replay.add_episode(exp)
    items = {item.episode_id: item for item in replay.items(mode="recent_model")}
    assert items["new-model"].model_change_recency >= items["old-model"].model_change_recency
    assert 0.0 < items["new-model"].model_change_recency <= 1.0


def test_replay_ledger_records_value_deltas_without_visit_increments(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    replay = PrioritizedReplayBuffer(store, capacity=20, seed=7)
    episode = _seed(store, replay)
    value = ValueModel(store, reward_model=RewardModel())
    value.learn_episode(episode.transitions, episode_reward=episode.reward, episode_status=episode.status)
    visits_before = value.stats()
    learner = ExperienceReplayLearner(replay, store, value)
    result = learner.replay(batch_size=1, seed=13)
    visits_after = value.stats()
    assert result.completed == 1
    assert visits_after == visits_before
    assert store.replay_update_stats()["completed"] >= 1
    import sqlite3
    with sqlite3.connect(tmp_path / "learning.db") as conn:
        row = conn.execute(
            "SELECT state_value_delta,action_value_delta FROM replay_updates WHERE status='completed' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert abs(float(row[0])) + abs(float(row[1])) > 0.0

