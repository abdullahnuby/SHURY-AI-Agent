from pathlib import Path

from app.learning.continual import ContinualBeliefTracker
from app.learning.store import LearningStore
from app.learning.transition_model import LearnedTransitionModel, action_signature


def action():
    return {"capability": "inspect", "tool": "inspect_tool", "parameters": {}, "preconditions": [], "expected_effects": ["inspected"], "risk": "low", "reversible": True}


def transition(i: int, *, next_state: str, ok: bool = True, reward: float = 1.0):
    return {
        "transition_id": f"g08-{i}", "state_before": "S", "action": action(), "state_after": next_state,
        "outcome": {"ok": ok, "verified": ok, "duration_ms": 10}, "verified": ok, "reward": reward,
        "timestamp": f"2026-10-01T00:00:{i:02d}",
    }


def test_competing_transition_beliefs_keep_evidence(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    model = LearnedTransitionModel(store)
    model.learn_transition(transition(1, next_state="A", ok=True))
    model.learn_transition(transition(2, next_state="B", ok=False))
    model.learn_transition(transition(3, next_state="A", ok=True))
    sig = action_signature(action())
    beliefs = ContinualBeliefTracker(store).beliefs("S", sig)
    assert {b.hypothesis_key for b in beliefs} >= {"ok=true|verified=true|failure=", "ok=false|verified=false|failure="}
    a = next(b for b in beliefs if b.hypothesis_key.startswith("ok=true"))
    b = next(b for b in beliefs if b.hypothesis_key.startswith("ok=false"))
    assert a.supporting_evidence == 2
    assert b.supporting_evidence == 1
    assert a.contradicting_evidence >= 1
    assert b.contradicting_evidence >= 2
    assert a.probability > b.probability


def test_transition_model_history_is_immutable_and_versioned(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    model = LearnedTransitionModel(store)
    model.learn_transition(transition(1, next_state="A", ok=True))
    sig = action_signature(action())
    history1 = ContinualBeliefTracker(store).history("S", sig)
    assert len(history1) == 1
    old_snapshot = history1[0]["snapshot"]
    old_version = history1[0]["model_version"]
    model.learn_transition(transition(2, next_state="B", ok=False))
    history2 = ContinualBeliefTracker(store).history("S", sig)
    assert len(history2) == 2
    assert history2[0]["model_version"] > old_version
    old = next(x for x in history2 if x["model_version"] == old_version)
    assert old["snapshot"] == old_snapshot
    assert "A" in old["snapshot"]["next_states"]
    assert "B" not in old["snapshot"]["next_states"]


def test_invalidation_adds_historical_version_without_overwriting_old_snapshot(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    model = LearnedTransitionModel(store)
    for i in range(1, 3):
        model.learn_transition(transition(i, next_state="A", ok=True))
    sig = action_signature(action())
    before = ContinualBeliefTracker(store).history("S", sig)
    previous_version = before[0]["model_version"]
    store.invalidate_transition_model("S", sig, reason="distribution-shift", distribution_shift=0.8)
    after = ContinualBeliefTracker(store).history("S", sig)
    assert after[0]["model_version"] > previous_version
    assert after[0]["reason"] == "invalidation:distribution-shift"
    old = next(x for x in after if x["model_version"] == previous_version)
    assert old["snapshot"]["stale"] is False
    assert after[0]["snapshot"]["stale"] is True


def test_exploration_policy_uses_persistent_real_bandit_rewards(tmp_path: Path):
    from app.learning.exploration import ExplorationPolicy

    store = LearningStore(tmp_path / "learning.db")
    policy = ExplorationPolicy(store=store, information_weight=0.0, novelty_weight=0.0, relearning_weight=0.0)
    x = {"capability": "inspect", "tool": "X", "parameters": {}, "preconditions": [], "expected_effects": ["x"], "risk": "low", "reversible": True}
    y = {"capability": "inspect", "tool": "Y", "parameters": {}, "preconditions": [], "expected_effects": ["y"], "risk": "low", "reversible": True}
    class Tool:
        risk = "low"; cost = 1.0; reversible = True; exploration_safe = True; information_domains = (); information_gain_prior = 0.0
        def validate_args(self, args): return False
    registry = {"X": Tool(), "Y": Tool()}
    sx = action_signature(x); sy = action_signature(y)
    for i in range(12):
        store.record_bandit_observation(state_signature="S", arm_signature=sx, reward=1.0, source_event_id=100+i)
        store.record_bandit_observation(state_signature="S", arm_signature=sy, reward=0.0, source_event_id=200+i)
    first = policy._nonstationary_bandit("S", [sx, sy]).choose_arm()
    assert first == sx
    for i in range(12, 24):
        store.record_bandit_observation(state_signature="S", arm_signature=sx, reward=0.0, source_event_id=300+i)
        store.record_bandit_observation(state_signature="S", arm_signature=sy, reward=1.0, source_event_id=400+i)
    second = policy._nonstationary_bandit("S", [sx, sy]).choose_arm()
    assert second == sy


def test_g08_migration_backfills_baseline_history_and_beliefs(tmp_path: Path):
    path = tmp_path / "learning.db"
    store = LearningStore(path)
    model = LearnedTransitionModel(store)
    model.learn_transition(transition(1, next_state="A", ok=True))
    sig = action_signature(action())
    import sqlite3
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM transition_model_versions")
    conn.execute("DELETE FROM transition_beliefs")
    conn.commit(); conn.close()
    migrated = LearningStore(path)
    history = migrated.transition_model_history("S", sig)
    beliefs = migrated.transition_beliefs("S", sig)
    assert len(history) == 1
    assert history[0]["reason"] == "migration:baseline"
    assert beliefs and beliefs[0]["evidence_count"] == 1
