from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from app.learning.transition_model import action_signature


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class RewardSignal:
    step_reward: float
    terminal_reward: float
    total_reward: float
    components: tuple[tuple[str, float], ...]
    confidence: float
    raw_components: tuple[tuple[str, float], ...] = ()
    source: str = "observed-runtime-reward"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValuePrediction:
    kind: str
    state_signature: str
    action_signature: str | None
    value: float
    return_mean: float
    return_std: float
    confidence: float
    uncertainty: float
    visits: int
    source: str = "tabular-td-lambda"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValueLearningResult:
    transitions: int
    state_updates: int
    action_updates: int
    episode_return: float
    mean_abs_td_signal: float
    terminal_reward: float
    algorithm: str = "TD(lambda)+SARSA"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RewardModel:
    """Transparent reward construction from observed runtime evidence.

    The reward model never inspects natural-language output for correctness. It consumes
    bounded execution evidence already produced by the governed runtime plus the episode's
    measured outcome. The episode reward remains the task-level score; the small step terms
    are only local learning signals for progress/failure/retry.
    """

    def __init__(self, *, verified_step: float = 0.02, unverified_step: float = 0.01,
                 failure_step: float = -0.25, retry_penalty: float = -0.03,
                 terminal_scale: float = 0.80):
        self.verified_step = float(verified_step)
        self.unverified_step = float(unverified_step)
        self.failure_step = float(failure_step)
        self.retry_penalty = float(retry_penalty)
        self.terminal_scale = max(0.0, float(terminal_scale))

    def score_transition(self, transition: dict[str, Any], *, terminal: bool,
                         episode_reward: float, episode_status: str) -> RewardSignal:
        outcome = transition.get("outcome") or {}
        if not isinstance(outcome, dict):
            outcome = {}
        action = transition.get("action") or {}
        if not isinstance(action, dict):
            action = {}
        metadata = transition.get("metadata") or ()
        if isinstance(metadata, dict):
            meta = dict(metadata)
        else:
            try:
                meta = dict(metadata) if isinstance(metadata, (tuple, list)) else {}
            except Exception:
                meta = {}
        ok = bool(outcome.get("ok", False))
        verified = bool(transition.get("verified", outcome.get("verified", False)))
        attempt = max(1, int(outcome.get("attempt") or transition.get("attempt") or 1))

        def number(*keys: str, default: float = 0.0) -> float:
            for key in keys:
                value = meta.get(key, outcome.get(key, action.get(key)))
                if isinstance(value, bool):
                    return 1.0 if value else 0.0
                if isinstance(value, (int, float)):
                    return float(value)
            return float(default)

        # These are deliberately raw, auditable evidence dimensions. They are not inferred
        # from natural language: callers must provide them from governed runtime evidence.
        goal_alignment = _clamp(number("goal_alignment", "intent_alignment", default=(1.0 if ok else 0.0)))
        unnecessary = bool(meta.get("unnecessary_action", outcome.get("unnecessary_action", False)))
        if meta.get("necessary") is False or outcome.get("necessary") is False:
            unnecessary = True
        resource_consumed = max(0.0, number("resource_consumed", "resource_cost", "consumed_cost", default=number("cost", default=float(action.get("cost") or 0.0))))
        # A bounded resource signal keeps arbitrary tool cost scales from dominating reward.
        resource_norm = _clamp(resource_consumed / 10.0)
        recovery_quality = _clamp(number("recovery_quality", default=0.0))
        raw_components = [
            ("goal_alignment", goal_alignment),
            ("unnecessary_action", 1.0 if unnecessary else 0.0),
            ("retries", float(max(0, attempt - 1))),
            ("resource_consumption", resource_consumed),
            ("resource_consumption_normalized", resource_norm),
            ("verified", 1.0 if verified else 0.0),
            ("recovery_quality", recovery_quality),
        ]

        components: list[tuple[str, float]] = []
        # Keep the historical local learning scale small; raw dimensions remain available for
        # evaluation and later credit assignment.
        local = 0.0
        alignment_gain = 0.025 * goal_alignment if ok else -0.025 * (1.0 - goal_alignment)
        local += alignment_gain
        components.append(("goal_alignment", alignment_gain))
        if not ok:
            local += self.failure_step
            components.append(("failure", self.failure_step))
        elif verified:
            local += self.verified_step
            components.append(("verified_success", self.verified_step))
        else:
            local += self.unverified_step
            components.append(("unverified_success", self.unverified_step))

        retry = self.retry_penalty * min(4, max(0, attempt - 1))
        if retry:
            local += retry
            components.append(("retry_penalty", retry))

        if unnecessary:
            penalty = -0.05
            local += penalty
            components.append(("unnecessary_action", penalty))

        resource_penalty = -0.02 * resource_norm
        if resource_penalty:
            local += resource_penalty
            components.append(("resource_consumption", resource_penalty))

        if recovery_quality > 0.0 and ok:
            recovery_bonus = 0.025 * recovery_quality
            local += recovery_bonus
            components.append(("recovery_quality", recovery_bonus))

        terminal_reward = 0.0
        if terminal:
            task_reward = _clamp(float(episode_reward), 0.0, 1.0)
            if str(episode_status) == "completed":
                terminal_reward = self.terminal_scale * task_reward
            else:
                terminal_reward = -self.terminal_scale * max(0.25, 1.0 - task_reward)
            components.append(("terminal_goal", terminal_reward))

        total = _clamp(local + terminal_reward, -1.0, 1.0)
        confidence = 0.90 if terminal and episode_status == "completed" else (0.75 if verified else 0.55)
        if terminal and episode_status != "completed":
            confidence = 0.65
        return RewardSignal(
            round(local, 6), round(terminal_reward, 6), round(total, 6),
            tuple(components), confidence, tuple((k, round(v, 6)) for k, v in raw_components),
        )

    def annotate_episode(self, transitions: Iterable[dict[str, Any]], *, episode_reward: float,
                         episode_status: str) -> tuple[dict[str, Any], ...]:
        items = [dict(item) for item in transitions if isinstance(item, dict)]
        result: list[dict[str, Any]] = []
        last = len(items) - 1
        for index, transition in enumerate(items):
            signal = self.score_transition(
                transition,
                terminal=(index == last),
                episode_reward=episode_reward,
                episode_status=episode_status,
            )
            updated = dict(transition)
            updated["reward"] = signal.total_reward
            metadata = list(updated.get("metadata") or ())
            metadata.append(("reward_source", signal.source))
            metadata.append(("reward_confidence", signal.confidence))
            metadata.append(("reward_step", signal.step_reward))
            metadata.append(("reward_terminal", signal.terminal_reward))
            metadata.append(("reward_components", dict(signal.components)))
            metadata.append(("reward_raw_components", dict(signal.raw_components)))
            updated["metadata"] = tuple(metadata)
            result.append(updated)
        return tuple(result)


class ValueModel:
    """Persistent tabular value learner over observed, exact state/action identities.

    State values use accumulating-trace TD(lambda). Action values use SARSA-style backups over
    the observed continuation, not a max operator. This intentionally evaluates behavior rather
    than silently training a policy. Planning/control may consume these values only in later phases.
    """

    def __init__(self, store, *, reward_model: RewardModel | None = None,
                 gamma: float = 0.95, alpha: float = 0.15, lam: float = 0.80):
        if not 0.0 < float(gamma) <= 1.0:
            raise ValueError("gamma must be in (0,1]")
        if not 0.0 < float(alpha) <= 1.0:
            raise ValueError("alpha must be in (0,1]")
        if not 0.0 <= float(lam) <= 1.0:
            raise ValueError("lambda must be in [0,1]")
        self.store = store
        self.reward_model = reward_model or RewardModel()
        self.gamma = float(gamma)
        self.alpha = float(alpha)
        self.lam = float(lam)

    @staticmethod
    def _state_key(transition: dict[str, Any]) -> str:
        return str(transition.get("state_before") or "")

    @staticmethod
    def _action_key(transition: dict[str, Any]) -> tuple[str, str]:
        state = str(transition.get("state_before") or "")
        action = transition.get("action") or {}
        return state, action_signature(action)

    @staticmethod
    def _next_action_key(transitions: list[dict[str, Any]], index: int) -> tuple[str, str] | None:
        if index + 1 >= len(transitions):
            return None
        current = transitions[index]
        nxt = transitions[index + 1]
        expected_state = str(current.get("state_after") or "")
        state = str(nxt.get("state_before") or "")
        action = nxt.get("action") or {}
        if not expected_state or not state or expected_state != state or not isinstance(action, dict):
            # Do not bridge a broken trajectory with an unrelated action value.
            return None
        return state, action_signature(action)

    def _cached_state_value(self, cache: dict[str, float], state: str) -> float:
        if not state:
            return 0.0
        if state not in cache:
            row = self.store.get_state_value(state)
            cache[state] = float(row.get("value", 0.0)) if row else 0.0
        return cache[state]

    def _cached_action_value(self, cache: dict[tuple[str, str], float], key: tuple[str, str] | None) -> float:
        if not key or not key[0] or not key[1]:
            return 0.0
        if key not in cache:
            row = self.store.get_action_value(*key)
            cache[key] = float(row.get("value", 0.0)) if row else 0.0
        return cache[key]

    def learn_episode(self, transitions: Iterable[dict[str, Any]], *, episode_reward: float | None = None,
                      episode_status: str = "completed", evidence_update: bool = True,
                      learning_rate_scale: float = 1.0) -> ValueLearningResult:
        raw = [dict(item) for item in transitions if isinstance(item, dict)]
        if not raw:
            return ValueLearningResult(0, 0, 0, 0.0, 0.0, 0.0)
        learning_rate_scale = max(0.0, min(1.0, float(learning_rate_scale)))
        effective_alpha = self.alpha * learning_rate_scale

        if episode_reward is None:
            episode_reward = float(raw[-1].get("reward") or 0.0)
        items = []
        for index, transition in enumerate(raw):
            reward = transition.get("reward")
            if not isinstance(reward, (int, float)):
                signal = self.reward_model.score_transition(
                    transition, terminal=(index == len(raw) - 1),
                    episode_reward=float(episode_reward), episode_status=episode_status,
                )
                reward = signal.total_reward
            items.append((transition, float(reward)))

        states: dict[str, float] = {}
        actions: dict[tuple[str, str], float] = {}
        state_visits: dict[str, int] = {}
        action_visits: dict[tuple[str, str], int] = {}
        state_returns: dict[str, list[float]] = {}
        action_returns: dict[tuple[str, str], list[float]] = {}
        state_trace: dict[str, float] = {}
        action_trace: dict[tuple[str, str], float] = {}
        td_signals: list[float] = []

        # Empirical Monte-Carlo returns are retained as a separate diagnostic statistic. The
        # learned value itself is driven by TD(lambda), giving delayed outcomes backward credit
        # without inventing counterfactual trajectories.
        returns = [0.0] * len(items)
        running = 0.0
        for index in range(len(items) - 1, -1, -1):
            running = items[index][1] + self.gamma * running
            returns[index] = running

        for index, (transition, reward) in enumerate(items):
            state = self._state_key(transition)
            action_key = self._action_key(transition)
            next_state = str(transition.get("state_after") or "")
            terminal = index == len(items) - 1 or not next_state
            current_v = self._cached_state_value(states, state)
            next_v = 0.0 if terminal else self._cached_state_value(states, next_state)
            delta_v = reward + (0.0 if terminal else self.gamma * next_v) - current_v
            state_trace[state] = state_trace.get(state, 0.0) + 1.0
            for trace_state in list(state_trace):
                states[trace_state] = self._cached_state_value(states, trace_state) + effective_alpha * delta_v * state_trace[trace_state]
                state_trace[trace_state] *= self.gamma * self.lam
                if abs(state_trace[trace_state]) < 1e-7:
                    state_trace.pop(trace_state, None)

            current_q = self._cached_action_value(actions, action_key)
            next_action = self._next_action_key([x[0] for x in items], index)
            next_q = 0.0 if terminal else self._cached_action_value(actions, next_action)
            delta_q = reward + (0.0 if terminal else self.gamma * next_q) - current_q
            action_trace[action_key] = action_trace.get(action_key, 0.0) + 1.0
            for trace_action in list(action_trace):
                actions[trace_action] = self._cached_action_value(actions, trace_action) + effective_alpha * delta_q * action_trace[trace_action]
                action_trace[trace_action] *= self.gamma * self.lam
                if abs(action_trace[trace_action]) < 1e-7:
                    action_trace.pop(trace_action, None)

            if state:
                state_visits[state] = state_visits.get(state, 0) + 1
                state_returns.setdefault(state, []).append(returns[index])
            if action_key[0] and action_key[1]:
                action_visits[action_key] = action_visits.get(action_key, 0) + 1
                action_returns.setdefault(action_key, []).append(returns[index])
            td_signals.append(abs(delta_v))

        now = _now()
        for state, value in states.items():
            self.store.upsert_state_value(
                state_signature=state,
                value=value,
                visits_increment=state_visits.get(state, 0) if evidence_update else 0,
                return_samples=state_returns.get(state, ()) if evidence_update else (),
                last_updated_at=now,
            )
        for (state, action_sig), value in actions.items():
            action_row = None
            # The persisted action JSON is diagnostic only. Reuse the most recent matching action.
            for transition, _ in items:
                if self._action_key(transition) == (state, action_sig):
                    action_row = transition.get("action") or {}
                    break
            self.store.upsert_action_value(
                state_signature=state,
                action_signature=action_sig,
                action=action_row or {},
                value=value,
                visits_increment=action_visits.get((state, action_sig), 0) if evidence_update else 0,
                return_samples=action_returns.get((state, action_sig), ()) if evidence_update else (),
                last_updated_at=now,
            )

        return ValueLearningResult(
            transitions=len(items),
            state_updates=len(states),
            action_updates=len(actions),
            episode_return=round(sum((self.gamma ** i) * reward for i, (_, reward) in enumerate(items)), 6),
            mean_abs_td_signal=round(sum(td_signals) / max(1, len(td_signals)), 6),
            terminal_reward=float(items[-1][1]) if items else 0.0,
        )

    def replay_episode(self, transitions: Iterable[dict[str, Any]], *, episode_reward: float | None = None,
                       episode_status: str = "completed", learning_rate_scale: float = 0.35) -> ValueLearningResult:
        """Reapply historical value evidence without increasing empirical visit counts.

        Replay changes learned estimates but never pretends the replayed transition was observed
        again. The evidence counters therefore remain faithful to real-world experience.
        """
        return self.learn_episode(
            transitions,
            episode_reward=episode_reward,
            episode_status=episode_status,
            evidence_update=False,
            learning_rate_scale=learning_rate_scale,
        )

    def predict_state(self, state_signature: str) -> ValuePrediction | None:
        row = self.store.get_state_value(str(state_signature or ""))
        if row is None or int(row.get("visits", 0)) <= 0:
            return None
        visits = int(row["visits"])
        std = math.sqrt(max(0.0, float(row.get("return_m2", 0.0)) / max(1, visits - 1))) if visits > 1 else 0.0
        confidence = _clamp((visits / (visits + 5.0)) * (1.0 / (1.0 + std)), 0.0, 1.0)
        return ValuePrediction("state", str(state_signature), None, float(row["value"]),
                               float(row.get("return_mean", 0.0)), std, confidence, 1.0 - confidence, visits)

    def predict_action(self, state_signature: str, action: dict[str, Any]) -> ValuePrediction | None:
        state, action_sig = str(state_signature or ""), action_signature(action)
        row = self.store.get_action_value(state, action_sig)
        if row is None or int(row.get("visits", 0)) <= 0:
            return None
        visits = int(row["visits"])
        std = math.sqrt(max(0.0, float(row.get("return_m2", 0.0)) / max(1, visits - 1))) if visits > 1 else 0.0
        confidence = _clamp((visits / (visits + 5.0)) * (1.0 / (1.0 + std)), 0.0, 1.0)
        return ValuePrediction("action", state, action_sig, float(row["value"]),
                               float(row.get("return_mean", 0.0)), std, confidence, 1.0 - confidence, visits)

    def action_estimates(self, state_signature: str, *, limit: int = 20) -> list[ValuePrediction]:
        out = []
        for row in self.store.list_action_values(str(state_signature or ""), limit=limit):
            visits = int(row.get("visits", 0))
            if visits <= 0:
                continue
            std = math.sqrt(max(0.0, float(row.get("return_m2", 0.0)) / max(1, visits - 1))) if visits > 1 else 0.0
            confidence = _clamp((visits / (visits + 5.0)) * (1.0 / (1.0 + std)), 0.0, 1.0)
            out.append(ValuePrediction("action", row["state_signature"], row["action_signature"], float(row["value"]),
                                       float(row.get("return_mean", 0.0)), std, confidence, 1.0 - confidence, visits))
        out.sort(key=lambda item: (item.value, item.confidence, item.visits), reverse=True)
        return out

    def stats(self) -> dict[str, Any]:
        return self.store.value_model_stats()
