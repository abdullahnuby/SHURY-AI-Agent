from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean
from typing import Any, Iterable, Mapping, Sequence


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _success(value: Any) -> bool:
    if isinstance(value, Mapping):
        if "success" in value:
            return bool(value["success"])
        if "verified" in value:
            return bool(value["verified"])
        if "ok" in value:
            return bool(value["ok"])
    return bool(value)


@dataclass(frozen=True)
class LearningMetrics:
    transfer_rate: float
    regression_rate: float
    catastrophic_forgetting: float
    learning_speed: float
    exploration_efficiency: float
    action_selection_accuracy: float
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def transfer_rate(source_results: Iterable[Any], target_results: Iterable[Any]) -> float:
    """Rate of target-family success after learning from a distinct but related source family."""
    source = list(source_results)
    target = list(target_results)
    if not target or not source:
        return 0.0
    return _clamp(sum(1 for item in target if _success(item)) / len(target))


def regression_rate(baseline: Mapping[str, Any], after: Mapping[str, Any]) -> float:
    """Fraction of previously passing behaviors that fail after a learning update."""
    passed = [str(key) for key, value in baseline.items() if _success(value)]
    if not passed:
        return 0.0
    regressions = sum(1 for key in passed if not _success(after.get(key, False)))
    return _clamp(regressions / len(passed))


def catastrophic_forgetting(baseline: Mapping[str, Sequence[Any] | Any], after: Mapping[str, Sequence[Any] | Any]) -> float:
    """Maximum performance loss on old tasks after learning new tasks.

    This is deliberately measured on held-out historical tasks, not on replayed training evidence.
    A value of 0 means no measured forgetting; larger values are larger drops.
    """
    drops = []
    details = {}
    for task, before_values in baseline.items():
        if task not in after:
            continue
        before = list(before_values) if isinstance(before_values, (list, tuple)) else [before_values]
        current_values = after[task]
        current = list(current_values) if isinstance(current_values, (list, tuple)) else [current_values]
        if not before:
            continue
        base_rate = sum(1 for item in before if _success(item)) / len(before)
        after_rate = sum(1 for item in current if _success(item)) / max(1, len(current))
        drop = max(0.0, base_rate - after_rate)
        drops.append(drop)
        details[str(task)] = {"baseline": base_rate, "after": after_rate, "drop": drop}
    return _clamp(max(drops) if drops else 0.0)


def learning_speed(history: Sequence[Any], *, threshold: float = 0.80) -> float:
    """Normalized speed score: earlier threshold attainment is better, with no success => 0."""
    values = [float(item.get("score", item.get("reward", 0.0))) if isinstance(item, Mapping) else float(item) for item in history]
    if not values:
        return 0.0
    for index, value in enumerate(values, 1):
        if _clamp(value) >= float(threshold):
            return _clamp(1.0 / index)
    return 0.0


def exploration_efficiency(explorations: Iterable[Mapping[str, Any]]) -> float:
    """Useful verified information gained per normalized exploration cost."""
    rows = list(explorations)
    if not rows:
        return 0.0
    total_gain = sum(max(0.0, float(row.get("realized_information_gain", row.get("information_gain", 0.0)) or 0.0)) for row in rows)
    total_cost = sum(max(0.1, float(row.get("cost", 1.0) or 1.0)) for row in rows if row.get("executed", True))
    useful = sum(
        max(0.0, float(row.get("realized_information_gain", 0.0) or 0.0))
        for row in rows
        if bool(row.get("verified", row.get("success", False)))
    )
    if total_cost <= 0.0:
        return 0.0
    # Efficiency is bounded for cross-run comparisons; both total gain and verified useful gain
    # are included so speculative/unverified probes do not look equivalent to useful inspection.
    raw = 0.5 * (useful / total_cost) + 0.5 * (total_gain / total_cost)
    return _clamp(raw)


def action_selection_accuracy(selected: Iterable[str], oracle: Iterable[str]) -> float:
    selected_list = list(selected)
    oracle_list = list(oracle)
    if not selected_list or len(selected_list) != len(oracle_list):
        return 0.0
    return _clamp(sum(1 for actual, expected in zip(selected_list, oracle_list) if actual == expected) / len(selected_list))


def evaluate_learning_progress(*, source_results: Iterable[Any], target_results: Iterable[Any],
                               baseline: Mapping[str, Any], after: Mapping[str, Any],
                               forgetting_baseline: Mapping[str, Sequence[Any] | Any],
                               forgetting_after: Mapping[str, Sequence[Any] | Any],
                               learning_history: Sequence[Any], explorations: Iterable[Mapping[str, Any]],
                               selected_actions: Iterable[str], oracle_actions: Iterable[str],
                               store: Any | None = None, run_id: str = '') -> LearningMetrics:
    source_items = list(source_results)
    target_items = list(target_results)
    forget = catastrophic_forgetting(forgetting_baseline, forgetting_after)
    metrics = LearningMetrics(
        transfer_rate=transfer_rate(source_items, target_items),
        regression_rate=regression_rate(baseline, after),
        catastrophic_forgetting=forget,
        learning_speed=learning_speed(learning_history),
        exploration_efficiency=exploration_efficiency(explorations),
        action_selection_accuracy=action_selection_accuracy(selected_actions, oracle_actions),
        details={"forgetting_tasks": len(forgetting_baseline), "samples": len(target_items), "source_samples": len(source_items)},
    )
    if store is not None and hasattr(store, "record_learning_metrics"):
        store.record_learning_metrics(metrics.to_dict(), run_id=run_id)
    return metrics
