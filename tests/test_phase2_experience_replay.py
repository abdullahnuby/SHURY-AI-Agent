from __future__ import annotations

from app.brain.models import ActionSpec, Transition
from app.learning.models import ExperienceRecord
from app.learning.replay import PrioritizedReplayBuffer, replay_priority_components
from app.learning.store import LearningStore


def _transition(run_id: str, idx: int, *, state="s", outcome_ok=True, error="", prediction_error=None, uncertainty=0.2, reward=None):
    action = ActionSpec(
        action_id=f"step-{idx}", capability="test", tool="calculator",
        parameters=(("expression", f"{idx}+{idx}"),), uncertainty=uncertainty,
    )
    t = Transition(
        state_before=state,
        action=action,
        state_after=f"{state}-after-{idx}",
        outcome={"ok": outcome_ok, "verified": outcome_ok, "error": error},
        reward=reward,
        prediction_error=prediction_error,
        verified=outcome_ok,
        timestamp=f"2026-09-30T00:00:0{idx}",
        metadata=(("episode_id", run_id), ("state_fingerprint_kind", "world")),
    )
    payload = t.to_dict()
    payload["transition_id"] = t.fingerprint()
    if error:
        payload["failure_class"] = "execution"
    return payload


def _episode(run_id: str, transitions):
    return ExperienceRecord(
        run_id=run_id, goal="test replay", task_signature="test replay",
        status="failed" if any(not t["verified"] for t in transitions) else "completed",
        reward=0.5, verified_rate=0.5, steps=tuple({"step": str(i), "tool": "calculator", "status": "done" if t["verified"] else "failed"} for i, t in enumerate(transitions)),
        failure_class="execution" if any(not t["verified"] for t in transitions) else None,
        lesson_keys=(), session_id=None, created_at="2026-09-30T00:00:00",
        environment_signature="env", transitions=tuple(transitions),
    )


def test_episode_persists_transitions_and_legacy_records_remain_readable(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    old = ExperienceRecord("old", "legacy", "legacy", "completed", 1.0, 1.0, (), None, (), None, "2026-09-30T00:00:00")
    assert store.record_experience(old)
    assert store.get_experience("old").transitions == ()

    transition = _transition("ep1", 0)
    episode = _episode("ep1", [transition])
    assert store.record_experience(episode)
    loaded = store.get_experience("ep1")
    assert loaded is not None
    assert loaded.episode_id == "ep1"
    assert loaded.transitions[0]["transition_id"] == transition["transition_id"]


def test_prioritized_replay_prefers_error_and_failure_and_is_bounded(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    replay = PrioritizedReplayBuffer(store, capacity=3, alpha=0.8, seed=7)

    low = _transition("low", 0, state="low-state", uncertainty=0.1, reward=0.1)
    failing = _transition("fail", 0, state="fail-state", outcome_ok=False, error="execution failed", uncertainty=0.4)
    high_error = _transition("err", 0, state="err-state", prediction_error=1.0, uncertainty=0.9)
    extra = _transition("extra", 0, state="extra-state", uncertainty=0.05, reward=0.1)

    for episode in (_episode("low", [low]), _episode("fail", [failing]), _episode("err", [high_error]), _episode("extra", [extra])):
        store.record_experience(episode)
        replay.add_episode(episode)

    assert replay.size() == 3
    ids = {item.episode_id for item in replay.top(10)}
    assert "fail" in ids
    assert "err" in ids
    assert replay.stats()["capacity"] == 3


def test_contradictory_outcomes_receive_replay_priority(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    replay = PrioritizedReplayBuffer(store, capacity=10, seed=1)
    first = _transition("a", 0, state="same-state", outcome_ok=True)
    second = _transition("b", 0, state="same-state", outcome_ok=False, error="failed")
    for episode in (_episode("a", [first]), _episode("b", [second])):
        store.record_experience(episode)
        replay.add_episode(episode)
    items = replay.top(10)
    assert len(items) == 2
    assert all(item.contradictory == 1.0 for item in items)
    assert all(item.priority > 0 for item in items)


def test_sampling_is_data_only_and_marks_replay(tmp_path, monkeypatch):
    store = LearningStore(tmp_path / "learning.db")
    replay = PrioritizedReplayBuffer(store, capacity=10, seed=4)
    episode = _episode("safe", [_transition("safe", 0, prediction_error=0.8), _transition("safe", 1, state="s2")])
    store.record_experience(episode)
    replay.add_episode(episode)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("a replay sample must never execute an action")

    monkeypatch.setattr("app.runtime.registry.Tool.run", forbidden)
    sampled = replay.sample(1, seed=99)
    assert len(sampled) == 1
    assert store.replay_stats()["replays"] == 1


def test_replay_supports_required_category_views(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    replay = PrioritizedReplayBuffer(store, capacity=20, seed=2)
    items = [
        _transition("recent", 0, state="recent-state", outcome_ok=True, uncertainty=0.2),
        _transition("failure", 0, state="failure-state", outcome_ok=False, error="failed", uncertainty=0.4),
        _transition("error", 0, state="error-state", prediction_error=1.0),
    ]
    for run_id, item in (("recent", items[0]), ("failure", items[1]), ("error", items[2])):
        store.record_experience(_episode(run_id, [item]))
        replay.add_episode(_episode(run_id + "-reindex", [item]))
    assert replay.items(mode="recent")
    assert replay.items(mode="high_error")[0].prediction_error == 1.0
    assert replay.items(mode="failures")
    assert replay.items(mode="rare")
    assert replay.items(mode="successful")
    assert replay.items(mode="boundary")
    assert replay.items(mode="under_explored")


def test_existing_learning_db_is_migrated_without_losing_experiences(tmp_path):
    import sqlite3

    path = tmp_path / "legacy-learning.db"
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE experiences (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT UNIQUE NOT NULL, goal TEXT NOT NULL,
                task_signature TEXT NOT NULL, status TEXT NOT NULL, reward REAL NOT NULL,
                verified_rate REAL NOT NULL, steps TEXT NOT NULL, failure_class TEXT,
                lesson_keys TEXT NOT NULL DEFAULT '[]', session_id TEXT,
                environment_signature TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
            )
        """)
        conn.execute(
            "INSERT INTO experiences(run_id,goal,task_signature,status,reward,verified_rate,steps,created_at) VALUES(?,?,?,?,?,?,?,?)",
            ("legacy-1", "legacy", "legacy", "completed", 1.0, 1.0, "[]", "2026-09-30T00:00:00"),
        )
        conn.commit()

    store = LearningStore(path)
    loaded = store.get_experience("legacy-1")
    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(experiences)").fetchall()}
    assert loaded is not None
    assert loaded.transitions == ()
    assert "transitions" in columns



def test_priority_components_are_inspectable():
    low = replay_priority_components(_transition("x", 0, uncertainty=0.1, reward=0.1), occurrence_count=9)
    high = replay_priority_components(_transition("x", 0, prediction_error=1.0, outcome_ok=False, error="failed", uncertainty=1.0), occurrence_count=0)
    assert high["prediction_error"] > low["prediction_error"]
    assert high["failure_importance"] == 1.0
    assert high["novelty"] > low["novelty"]
    assert high["priority"] > low["priority"]


def test_self_improvement_manager_promotes_real_runtime_effects_to_replay(tmp_path):
    from types import SimpleNamespace
    from app.domain.plan import Plan, PlanStep
    from app.domain.world import WorldState
    from app.learning.manager import SelfImprovementManager

    manager = SelfImprovementManager(learning_path=tmp_path / "learning.db", bank_path=tmp_path / "skills.db")
    state = SimpleNamespace(
        run_id="runtime-1", goal="calculate result", status="completed", replans=0,
        world=WorldState(),
        plan=Plan([PlanStep("s1", "calculator", {"expression": "2+2"}, status="done", capability="calculation")]),
    )

    class Memory:
        def effects(self, run_id):
            before = "world-before"
            after = "world-after"
            return [{
                "step_id": "s1", "attempt": 1, "tool": "calculator", "args": {"expression": "2+2"},
                "output": 4, "ok": True, "verified": True, "error": None,
                "duration_ms": 3.5, "ts": "2026-09-30T00:00:00",
                "state_before": before, "state_after": after,
            }]

    result = manager.observe_run(state, Memory(), registry={})
    assert result["replay_indexed"] == 1
    items = manager.store.replay_items(limit=5)
    assert len(items) == 1
    assert items[0].episode_id == "runtime-1"
    assert items[0].transition["action"]["tool"] == "calculator"
    assert items[0].transition["predicted_state"] is None
