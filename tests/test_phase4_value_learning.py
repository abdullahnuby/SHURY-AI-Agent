from __future__ import annotations

from app.brain.models import ActionSpec
from app.learning.store import LearningStore
from app.learning.value_model import RewardModel, ValueModel


def action(name: str) -> dict:
    return ActionSpec(
        action_id=f"runtime-{name}", capability="demo", tool=name,
        parameters=(('mode', name),), preconditions=(), expected_effects=("next",),
        risk="low", cost=1.0, reversible=True, uncertainty=1.0,
    ).to_dict()


def tr(before: str, after: str, tool: str, *, ok=True, verified=True, attempt=1, reward=None):
    return {
        "state_before": before,
        "action": action(tool),
        "state_after": after,
        "outcome": {
            "ok": ok,
            "verified": verified,
            "duration_ms": 100,
            "attempt": attempt,
            "error": "" if ok else "execution failure",
        },
        "verified": verified,
        "reward": reward,
        "failure_class": "execution" if not ok else "",
        "timestamp": "2026-09-30T12:00:00+00:00",
    }


def test_reward_model_is_evidence_based_and_terminal_goal_is_separate(tmp_path):
    model = RewardModel()
    items = model.annotate_episode(
        [tr("S", "M", "prepare", ok=True, verified=True), tr("M", "G", "finish", ok=True, verified=True)],
        episode_reward=1.0,
        episode_status="completed",
    )
    assert items[0]["reward"] > 0
    assert items[1]["reward"] > items[0]["reward"]
    assert "terminal_goal" in dict(dict(items[1]["metadata"])["reward_components"])
    metadata = dict(items[1]["metadata"])
    assert metadata["reward_source"] == "observed-runtime-reward"
    assert metadata["reward_terminal"] > 0


def test_failed_episode_gets_negative_terminal_signal(tmp_path):
    model = RewardModel()
    items = model.annotate_episode(
        [tr("S", "BAD", "finish", ok=False, verified=False)],
        episode_reward=0.0,
        episode_status="failed",
    )
    metadata = dict(items[0]["metadata"])
    assert items[0]["reward"] < 0
    assert metadata["reward_terminal"] < 0
    assert dict(metadata["reward_components"])["failure"] < 0


def test_td_lambda_assigns_delayed_credit_without_model_rollout(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    learner = ValueModel(store, gamma=0.9, alpha=0.4, lam=0.9)
    reward_model = RewardModel()
    episode = reward_model.annotate_episode(
        [
            tr("S0", "S1", "a0", ok=True, verified=True),
            tr("S1", "S2", "a1", ok=True, verified=True),
            tr("S2", "G", "a2", ok=True, verified=True),
        ],
        episode_reward=1.0,
        episode_status="completed",
    )
    result = learner.learn_episode(episode, episode_reward=1.0, episode_status="completed")
    assert result.transitions == 3
    assert result.state_updates == 3
    v0 = learner.predict_state("S0")
    v1 = learner.predict_state("S1")
    v2 = learner.predict_state("S2")
    assert v0 and v1 and v2
    assert v0.value > 0 and v1.value > 0 and v2.value > 0
    assert v2.value >= v1.value >= v0.value
    assert v0.visits == 1


def test_behavioral_action_values_separate_good_and_failed_actions(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    learner = ValueModel(store, gamma=0.9, alpha=0.5, lam=0.8)
    reward_model = RewardModel()

    good = reward_model.annotate_episode(
        [tr("S", "G", "good", ok=True, verified=True)],
        episode_reward=1.0,
        episode_status="completed",
    )
    bad = reward_model.annotate_episode(
        [tr("S", "B", "bad", ok=False, verified=False)],
        episode_reward=0.0,
        episode_status="failed",
    )
    learner.learn_episode(good, episode_reward=1.0, episode_status="completed")
    learner.learn_episode(bad, episode_reward=0.0, episode_status="failed")

    good_pred = learner.predict_action("S", action("good"))
    bad_pred = learner.predict_action("S", action("bad"))
    assert good_pred and bad_pred
    assert good_pred.value > bad_pred.value
    assert good_pred.visits == 1 and bad_pred.visits == 1
    assert good_pred.confidence < 1.0 and good_pred.uncertainty > 0.0


def test_value_tables_persist_and_action_estimates_are_inspectable(tmp_path):
    path = tmp_path / "learning.db"
    store = LearningStore(path)
    learner = ValueModel(store)
    episode = RewardModel().annotate_episode(
        [tr("S", "G", "do", ok=True, verified=True)],
        episode_reward=1.0,
        episode_status="completed",
    )
    learner.learn_episode(episode, episode_reward=1.0, episode_status="completed")

    reopened = ValueModel(LearningStore(path))
    assert reopened.predict_state("S") is not None
    estimates = reopened.action_estimates("S")
    assert len(estimates) == 1
    stats = reopened.stats()
    assert stats["states"] >= 1
    assert stats["actions"] >= 1
    assert stats["state_visits"] >= 1
