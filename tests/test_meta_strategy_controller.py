from pathlib import Path

from app.learning.meta_strategy import MetaStrategyController
from app.learning.store import LearningStore


def test_meta_strategy_learns_preferred_strategy_per_state_type(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    ctrl = MetaStrategyController(store, exploration=0.0)
    for _ in range(5):
        ctrl.record_outcome(state_type="compound", strategy="sequential", reward=1.0, success=True)
        ctrl.record_outcome(state_type="compound", strategy="search", reward=0.2, success=False)
    decision = ctrl.recommend("compound", available=("sequential", "search"))
    assert decision.preferred_strategy == "sequential"
    table = ctrl.preferred_table()
    assert any(row["state_type"] == "compound" and row["strategy"] == "sequential" for row in table)


def test_meta_strategy_is_persistent(tmp_path: Path):
    path = tmp_path / "learning.db"
    LearningStore(path).record_meta_strategy_observation("atomic", "direct", 1.0, True, {})
    ctrl = MetaStrategyController(LearningStore(path), exploration=0.0)
    decision = ctrl.recommend("atomic", available=("direct", "search"))
    assert decision.preferred_strategy == "direct"
    assert decision.alternatives[0]["attempts"] == 1
