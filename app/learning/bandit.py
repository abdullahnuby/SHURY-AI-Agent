from __future__ import annotations

import math
from collections import deque
from dataclasses import asdict, dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class BanditArmStats:
    arm: str
    pulls: int
    reward_sum: float
    mean_reward: float
    ucb_score: float
    change_detected: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ChangePoint:
    arm: str
    pull_index: int
    direction: str
    magnitude: float
    baseline_mean: float
    recent_mean: float

    def to_dict(self) -> dict:
        return asdict(self)


class PageHinkley:
    """Two-sided Page-Hinkley detector for persistent distribution shifts."""

    def __init__(self, *, delta: float = 0.01, threshold: float = 3.5):
        self.delta = float(delta)
        self.threshold = float(threshold)
        self.reset()

    def reset(self) -> None:
        self.n = 0
        self.mean = 0.0
        self.cumulative = 0.0
        self.minimum = 0.0
        self.maximum = 0.0
        self.last_mean_before_reset = 0.0
        self.window = deque(maxlen=12)

    def observe(self, value: float) -> tuple[bool, str, float]:
        x = float(value)
        self.n += 1
        self.mean += (x - self.mean) / self.n
        self.window.append(x)
        deviation = x - self.mean
        self.cumulative += deviation - self.delta
        self.minimum = min(self.minimum, self.cumulative)
        self.maximum = max(self.maximum, self.cumulative)
        upward = self.cumulative - self.minimum
        downward = self.maximum - self.cumulative
        if upward >= self.threshold:
            magnitude = float(upward)
            mean_before_reset = sum(self.window) / max(1, len(self.window))
            self.reset()
            self.last_mean_before_reset = mean_before_reset
            return True, "up", magnitude
        if downward >= self.threshold:
            magnitude = float(downward)
            mean_before_reset = sum(self.window) / max(1, len(self.window))
            self.reset()
            self.last_mean_before_reset = mean_before_reset
            return True, "down", magnitude
        return False, "", 0.0


class NonStationaryBandit:
    """Empirical non-stationary bandit with genuine online action selection.

    The environment owns rewards. This learner only receives observed rewards for the arm it
    selected. Distribution changes are detected independently from recency and trigger a bounded
    reset of UCB evidence so post-change exploration can discover the new best arm.
    """

    def __init__(self, arms: Iterable[str], *, exploration: float = 1.25,
                 detector_delta: float = 0.01, detector_threshold: float = 3.5):
        unique = tuple(dict.fromkeys(str(x) for x in arms if str(x).strip()))
        if not unique:
            raise ValueError("at least one arm is required")
        self.arms = unique
        self.exploration = float(exploration)
        self.detector_delta = float(detector_delta)
        self.detector_threshold = float(detector_threshold)
        self._pulls = {arm: 0 for arm in self.arms}
        self._reward_sum = {arm: 0.0 for arm in self.arms}
        self._detectors = {
            arm: PageHinkley(delta=self.detector_delta, threshold=self.detector_threshold)
            for arm in self.arms
        }
        self.pull_index = 0
        self.last_change: ChangePoint | None = None
        self.change_points: list[ChangePoint] = []

    def _score(self, arm: str) -> float:
        pulls = self._pulls[arm]
        if pulls == 0:
            return float("inf")
        total = max(1, sum(self._pulls.values()))
        mean_reward = self._reward_sum[arm] / pulls
        bonus = self.exploration * math.sqrt(math.log(total + 1.0) / pulls)
        return mean_reward + bonus

    def choose_arm(self) -> str:
        # Deterministic tie breaking makes experiments reproducible while still being real online
        # bandit control: the choice is generated from observed reward statistics, not a schedule.
        return max(self.arms, key=lambda arm: (self._score(arm), arm))

    def observe_history(self, observations: Iterable[tuple[str, float]]) -> None:
        """Replay persisted arm rewards into this in-memory controller in chronological order."""
        for arm, reward in observations:
            if str(arm) in self._pulls:
                self.observe_reward(str(arm), float(reward))

    def scores(self) -> dict[str, float]:
        return {arm: float(self._score(arm)) for arm in self.arms}

    def observe_reward(self, arm: str, reward: float) -> bool:
        arm = str(arm)
        if arm not in self._pulls:
            raise KeyError(arm)
        reward = max(0.0, min(1.0, float(reward)))
        self.pull_index += 1
        self._pulls[arm] += 1
        self._reward_sum[arm] += reward
        changed, direction, magnitude = self._detectors[arm].observe(reward)
        if changed and self._pulls[arm] >= 4:
            # Capture evidence from the detector window before it is reset. ``baseline_mean`` is
            # the arm's historical empirical mean; ``recent_mean`` is the detector window mean.
            pulls = self._pulls[arm]
            recent_mean = self._detectors[arm].last_mean_before_reset
            baseline_mean = self._reward_sum[arm] / pulls
            point = ChangePoint(arm, self.pull_index, direction, magnitude,
                                baseline_mean, recent_mean)
            self.last_change = point
            self.change_points.append(point)
            # Reset all estimates because the environment distribution may have changed globally.
            for candidate in self.arms:
                self._pulls[candidate] = 0
                self._reward_sum[candidate] = 0.0
                self._detectors[candidate].reset()
            # Preserve an immediately useful changed arm sample.
            self._pulls[arm] = 1
            self._reward_sum[arm] = reward
            return True
        return False

    def stats(self) -> list[BanditArmStats]:
        return [
            BanditArmStats(
                arm=arm,
                pulls=self._pulls[arm],
                reward_sum=self._reward_sum[arm],
                mean_reward=self._reward_sum[arm] / max(1, self._pulls[arm]),
                ucb_score=self._score(arm),
                change_detected=bool(self.last_change and self.last_change.arm == arm),
            )
            for arm in self.arms
        ]

    def snapshot(self) -> dict:
        return {
            "arms": list(self.arms),
            "pull_index": self.pull_index,
            "last_change": self.last_change.to_dict() if self.last_change else None,
            "change_points": [item.to_dict() for item in self.change_points],
            "stats": [item.to_dict() for item in self.stats()],
        }
