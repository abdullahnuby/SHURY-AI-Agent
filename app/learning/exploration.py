from __future__ import annotations

"""Phase 8: safe exploration and active information seeking.

Phase 8 converts uncertainty into a *bounded* exploration decision.  The policy is
still advisory: it may select only tools that explicitly opt into safe exploration,
and every selected action continues through the normal runtime validation,
permission, approval, and verification gates.

The implementation deliberately combines three signals rather than using random
exploration:

* UCB-style epistemic optimism for actions with limited evidence.
* Expected information gain from model uncertainty / outcome entropy / evidence deficit.
* Goal-relevant information value from an explicit tool information contract.

The policy reads the canonical LearningStore through Phase 3/4/5 models.  It never
creates synthetic transitions, replay items, rewards, or value updates itself.
"""

from dataclasses import asdict, dataclass
import math
import re
from typing import Any, Iterable, Mapping

from app.learning.transition_model import LearnedTransitionModel, action_signature
from app.learning.bandit import NonStationaryBandit
from app.learning.value_model import ValueModel


_SAFE_RISKS = {"low"}
_MAX_SAFE_COST = 10.0

_STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "for", "of", "in", "on", "with", "from",
    "how", "what", "why", "can", "you", "do", "i", "me", "my", "this", "that", "please",
    "learn", "study", "research", "search", "find", "web", "internet",
    "هل", "ما", "ماذا", "كيف", "ليه", "لماذا", "انا", "أنا", "من", "عن", "في", "على", "إلى",
    "من", "وتعلم", "تعلم", "ابحث", "دور", "عايز", "عاوز", "ممكن",
}

_EXTERNAL_WEB_TERMS = {
    "from web", "from the web", "from internet", "from the internet",
    "online", "on the web", "on internet", "on the internet",
    "الويب", "الإنترنت", "الانترنت", "اونلاين", "أونلاين",
}

_DOMAIN_ALIASES = {
    "research": {"research", "evidence", "paper", "papers", "literature", "study", "source", "scientific", "بحث", "دليل", "أبحاث", "علمي"},
    "learning": {"learn", "learning", "improve", "smarter", "teach", "knowledge", "تعلم", "التعلم", "تحسين", "أذكى", "معرفة"},
    "development": {"project", "repository", "repo", "code", "build", "test", "compile", "development", "software", "github", "مشروع", "كود", "اختبار", "بناء"},
    "memory": {"memory", "remember", "recall", "history", "مذكرات", "ذاكرة", "افتكر", "تذكر", "محفوظ"},
    "analysis": {"data", "dataset", "csv", "analysis", "statistics", "outlier", "بيانات", "تحليل", "إحصاء"},
    "current_data": {"current", "latest", "today", "news", "price", "weather", "live", "حالي", "أحدث", "اليوم", "أخبار", "طقس"},
    "capability": {"capability", "capabilities", "skill", "skills", "can", "ability", "مهارة", "قدرات", "تستطيع"},
}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _tokens(text: str) -> set[str]:
    raw = re.findall(r"[A-Za-z][A-Za-z0-9_+#.-]{1,}|[\u0600-\u06ff]{2,}", str(text or "").casefold())
    return {x for x in raw if x not in _STOPWORDS}


def _goal_domains(goal: str) -> set[str]:
    # Keep explicit intent signals separate.  A pure research request should not be
    # diluted by an automatic learning domain, while a learning request may legitimately
    # require research as its evidence-acquisition path.
    text = str(goal or "").casefold()
    raw_tokens = {x for x in re.findall(r"[A-Za-z][A-Za-z0-9_+#.-]{1,}|[\u0600-\u06ff]{2,}", text)}
    domains = {domain for domain, aliases in _DOMAIN_ALIASES.items() if raw_tokens & aliases}
    explicit_learning = bool(raw_tokens & _DOMAIN_ALIASES["learning"])
    explicit_research = bool(raw_tokens & _DOMAIN_ALIASES["research"])
    if explicit_learning:
        domains.add("learning")
        domains.add("research")
    elif explicit_research:
        domains.add("research")
    if any(term in text for term in _EXTERNAL_WEB_TERMS):
        domains.add("external_web")
    return domains


def _entropy(probabilities: Iterable[float]) -> float:
    values = [max(0.0, float(p)) for p in probabilities]
    total = sum(values)
    if total <= 0.0:
        return 0.0
    normalized = [p / total for p in values if p > 0.0]
    if len(normalized) <= 1:
        return 0.0
    raw = -sum(p * math.log(p) for p in normalized)
    return _clamp(raw / math.log(len(normalized)))




def _expected_information_gain(counts: Mapping[str, Any], alpha: float = 0.5) -> float:
    """Estimate normalized one-observation information gain for a categorical model.

    We use a small symmetric Dirichlet prior over observed outcomes plus one explicit
    ``unseen`` bucket.  The result is a bounded epistemic signal: observations are
    valuable when one more sample is expected to materially reduce uncertainty, and the
    signal decays as evidence accumulates.  It is intentionally not a reward or a
    synthetic transition.
    """
    positive = {str(k): max(0.0, float(v or 0.0)) for k, v in (counts or {}).items() if float(v or 0.0) > 0.0}
    if not positive:
        return 1.0
    keys = list(positive)
    if "__unseen__" not in positive:
        keys.append("__unseen__")
    k = max(2, len(keys))
    alphas = {key: float(positive.get(key, 0.0)) + float(alpha) for key in keys}
    total = sum(alphas.values())

    def entropy(pairs: Mapping[str, float]) -> float:
        values = [max(0.0, float(v)) for v in pairs.values()]
        denom = sum(values) or 1.0
        probs = [v / denom for v in values if v > 0.0]
        raw = -sum(p * math.log(p) for p in probs) if probs else 0.0
        return _clamp(raw / math.log(k)) if k > 1 else 0.0

    current = entropy(alphas)
    expected_after = 0.0
    for key, probability in alphas.items():
        predictive = probability / total
        updated = dict(alphas)
        updated[key] = updated[key] + 1.0
        expected_after += predictive * entropy(updated)
    return _clamp(current - expected_after)
def _binary_entropy(probability: float) -> float:
    p = _clamp(probability)
    if p <= 0.0 or p >= 1.0:
        return 0.0
    raw = -(p * math.log(p) + (1.0 - p) * math.log(1.0 - p))
    return _clamp(raw / math.log(2.0))


def is_safe_exploration_tool(tool: Any) -> bool:
    """Strict gate for actions that can be used to deliberately acquire information."""
    if tool is None or not bool(getattr(tool, "exploration_safe", False)):
        return False
    if bool(getattr(tool, "requires_approval", False)):
        return False
    if str(getattr(tool, "risk", "high")).casefold() not in _SAFE_RISKS:
        return False
    if not bool(getattr(tool, "idempotent", False)):
        return False
    if bool(getattr(tool, "emits_world_delta", False)):
        return False
    if tuple(getattr(tool, "exclusive_resources", ()) or ()):
        return False
    if tuple(getattr(tool, "resources_required", ()) or ()):
        return False
    try:
        cost = float(getattr(tool, "cost", 0.0) or 0.0)
    except Exception:
        return False
    return 0.0 <= cost <= _MAX_SAFE_COST


def _goal_alignment(action: Mapping[str, Any], tool: Any, goal: str) -> float:
    if tool is None:
        return 0.0
    try:
        if tool.matches(goal):
            return 1.0
    except Exception:
        pass

    goal_tokens = _tokens(goal)
    goal_domains = _goal_domains(goal)
    tool_domains = {str(x).casefold() for x in (getattr(tool, "information_domains", ()) or ())}
    domain_overlap = len(goal_domains & tool_domains) / max(1, len(goal_domains)) if goal_domains else 0.0

    capability = str(getattr(tool, "capability", "") or "").casefold()
    name = str(getattr(tool, "name", "") or "").casefold()
    description = str(getattr(tool, "description", "") or "").casefold()
    action_capability = str(action.get("capability") or "").casefold()
    lexical = 0.0
    for candidate in (capability, name, action_capability, description):
        if not candidate:
            continue
        terms = _tokens(candidate)
        if goal_tokens and terms:
            lexical = max(lexical, len(goal_tokens & terms) / max(1, len(goal_tokens | terms)))
    score = 0.62 * domain_overlap + 0.38 * lexical
    return _clamp(score)


def _normalize_action(action: Any) -> dict[str, Any]:
    if hasattr(action, "to_dict"):
        try:
            raw = dict(action.to_dict())
        except Exception:
            raw = dict(action.__dict__)
    elif isinstance(action, Mapping):
        raw = dict(action)
    else:
        raw = {}
    parameters = raw.get("parameters", raw.get("args", {}))
    if isinstance(parameters, (list, tuple)):
        parameters = {
            str(item[0]): item[1]
            for item in parameters
            if isinstance(item, (list, tuple)) and len(item) == 2
        }
    raw["parameters"] = dict(parameters or {}) if isinstance(parameters, Mapping) else {}
    raw["tool"] = str(raw.get("tool") or "").strip()
    raw["capability"] = str(raw.get("capability") or raw["tool"])
    raw["expected_effects"] = tuple(raw.get("expected_effects") or raw.get("effects") or ())
    raw["preconditions"] = tuple(raw.get("preconditions") or ())
    raw["risk"] = str(raw.get("risk") or "low")
    raw["reversible"] = bool(raw.get("reversible", False))
    return raw


def build_exploration_actions(
    goal: str,
    registry: Mapping[str, Any],
    seed_actions: Iterable[Any] = (),
) -> list[dict[str, Any]]:
    """Materialize all *safe and argument-grounded* information actions for a goal.

    The old implementation only scored actions that semantic planning had already seen.
    That made exploration circular: an unknown action could never be explored.  Phase 8
    deliberately expands the candidate set from the explicit safe-tool registry while
    still requiring deterministic argument grounding and contract validation.
    """
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(action: dict[str, Any], tool: Any) -> None:
        action = _normalize_action(action)
        if not action["tool"] or not is_safe_exploration_tool(tool):
            return
        try:
            errors = tool.validate_args(action["parameters"])
        except Exception:
            return
        if errors:
            return
        sig = action_signature(action)
        if sig in seen:
            return
        seen.add(sig)
        result.append(action)

    for raw in seed_actions or ():
        action = _normalize_action(raw)
        tool = registry.get(action["tool"])
        add(action, tool)

    seed_tools = {str(action.get("tool") or "") for action in result}
    for name, tool in sorted(registry.items(), key=lambda item: item[0]):
        if name in seed_tools:
            # Prefer the semantically grounded seed action for a tool over rebuilding its
            # arguments from the raw goal. This prevents an exploratory duplicate from
            # accidentally broadening a query (e.g. dropping "learn from web").
            continue
        if not is_safe_exploration_tool(tool):
            continue
        domains = {str(x).casefold() for x in (getattr(tool, "information_domains", ()) or ())}
        if not domains:
            # An explicit existing candidate can still be explored; arbitrary safe tools
            # without an information contract are not promoted into open exploration.
            continue
        try:
            args = tool.args_for(goal)
        except Exception:
            continue
        add({
            "capability": str(getattr(tool, "capability", None) or name),
            "tool": name,
            "parameters": args or {},
            "preconditions": tuple(getattr(tool, "preconditions", ()) or ()),
            "expected_effects": tuple(getattr(tool, "produces", ()) or ()),
            "risk": str(getattr(tool, "risk", "low")),
            "reversible": bool(getattr(tool, "reversible", False)),
            "cost": float(getattr(tool, "cost", 0.0) or 0.0),
        }, tool)
    return result


@dataclass(frozen=True)
class ExplorationDecision:
    mode: str
    state_signature: str
    selected_tool: str | None
    selected_action_signature: str | None
    selected_action: dict[str, Any] | None
    score: float
    goal_alignment: float
    exploitation: float
    ucb_bonus: float
    information_gain: float
    historical_information_gain: float | None
    novelty: float
    relearning_pressure: float
    risk_penalty: float
    evidence_count: int
    model_confidence: float
    model_uncertainty: float
    reason: str
    candidates: tuple[dict[str, Any], ...] = ()
    expected_failure_cost: float = 0.0
    information_value: float = 0.0
    strategy: str = 'exploit'

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExplorationPolicy:
    """Deterministic active-exploration policy over a bounded safe action set."""

    def __init__(
        self,
        store=None,
        transition_model: LearnedTransitionModel | None = None,
        value_model: ValueModel | None = None,
        *,
        goal_weight: float = 2.20,
        exploitation_weight: float = 0.90,
        information_weight: float = 1.55,
        novelty_weight: float = 0.55,
        relearning_weight: float = 1.20,
        ucb_weight: float = 0.80,
        risk_weight: float = 1.50,
        uncertainty_threshold: float = 0.55,
        min_relearning_evidence: int = 3,
        explore_margin: float = 0.16,
        min_goal_alignment: float = 0.32,
        max_candidates: int = 16,
    ):
        if transition_model is None:
            if store is None:
                from app.learning.store import LearningStore
                store = LearningStore()
            transition_model = LearnedTransitionModel(store)
        if value_model is None:
            value_model = ValueModel(transition_model.store)
        self.store = transition_model.store
        self.transition_model = transition_model
        self.value_model = value_model
        self.goal_weight = float(goal_weight)
        self.exploitation_weight = float(exploitation_weight)
        self.information_weight = float(information_weight)
        self.novelty_weight = float(novelty_weight)
        self.relearning_weight = float(relearning_weight)
        self.ucb_weight = float(ucb_weight)
        self.risk_weight = float(risk_weight)
        self.uncertainty_threshold = float(uncertainty_threshold)
        self.min_relearning_evidence = int(min_relearning_evidence)
        self.explore_margin = float(explore_margin)
        self.min_goal_alignment = float(min_goal_alignment)
        self.max_candidates = int(max_candidates)

    def _metrics(self, state_signature: str, action: dict[str, Any]) -> dict[str, float | int]:
        action = _normalize_action(action)
        model = self.transition_model.inspect(state_signature, action)
        if not model:
            return {
                "n": 0,
                "confidence": 0.0,
                "uncertainty": 1.0,
                "success_probability": 0.5,
                "next_entropy": 1.0,
                "outcome_entropy": 1.0,
                "prediction_error": 0.0,
                "novelty": 1.0,
                "information_gain": 1.0,
                "stale": 0.0,
                "exploration_multiplier": 1.0,
            }

        n = int(model.get("observation_count", 0) or 0)
        prediction = self.transition_model.predict(state_signature, action)
        confidence = float(prediction.confidence) if prediction else 0.0
        uncertainty = float(prediction.uncertainty) if prediction else 1.0
        success_probability = float(prediction.success_probability) if prediction else 0.5
        next_distribution = dict(prediction.next_state_distribution) if prediction else {}
        outcome_distribution = dict(prediction.outcome_distribution) if prediction else {}
        next_entropy = _entropy(next_distribution.values()) if next_distribution else 1.0
        outcome_entropy = _entropy(outcome_distribution.values()) if outcome_distribution else _binary_entropy(success_probability)
        raw_next_states = dict(model.get("next_states") or {})
        raw_outcomes = dict(model.get("outcomes") or {})
        bayesian_gain = _expected_information_gain(raw_next_states) if raw_next_states else 1.0
        outcome_gain = _expected_information_gain(raw_outcomes) if raw_outcomes else _binary_entropy(success_probability)
        evidence_deficit = 1.0 / math.sqrt(n + 1.0)
        uncertainty_gain = _clamp(0.5 * bayesian_gain + 0.25 * outcome_gain + 0.25 * uncertainty)
        information_gain = _clamp(0.42 * uncertainty_gain + 0.33 * next_entropy + 0.25 * evidence_deficit)
        novelty = 1.0 / math.sqrt(n + 1.0)
        prediction_error = _clamp(float(model.get("prediction_error_mean", 0.0) or 0.0))
        stale = 1.0 if bool(model.get("stale", 0)) else 0.0
        exploration_multiplier = 2.25 if stale else 1.0
        return {
            "n": n,
            "confidence": confidence,
            "uncertainty": uncertainty,
            "success_probability": success_probability,
            "next_entropy": next_entropy,
            "outcome_entropy": outcome_entropy,
            "prediction_error": prediction_error,
            "novelty": novelty,
            "information_gain": information_gain,
            "stale": stale,
            "exploration_multiplier": exploration_multiplier,
        }

    def _historical_information_gain(self, tool_name: str, action_sig: str) -> float | None:
        try:
            return self.store.exploration_information_gain(tool_name, action_sig)
        except Exception:
            return None

    def _action_value(self, state_signature: str, action_sig: str, visits: int) -> float:
        try:
            row = self.store.get_action_value(state_signature, action_sig)
            if row:
                value = float(row.get("value", 0.0) or 0.0)
                return _clamp((math.tanh(value) + 1.0) / 2.0)
        except Exception:
            pass
        return 0.5 if visits <= 0 else 0.45

    @staticmethod
    def _requires_external_source(goal: str) -> bool:
        text = str(goal or "").casefold()
        return any(term in text for term in _EXTERNAL_WEB_TERMS)

    def _nonstationary_bandit(self, state_signature: str, arm_signatures: Iterable[str]) -> NonStationaryBandit:
        arms = [str(x) for x in arm_signatures if str(x)]
        bandit = NonStationaryBandit(arms, exploration=max(0.40, self.ucb_weight), detector_threshold=7.0)
        try:
            history = self.store.bandit_observations(str(state_signature), limit=4000)
            bandit.observe_history((row["arm_signature"], float(row["reward"])) for row in history)
        except Exception:
            pass
        return bandit

    def decide(
        self,
        state_signature: str,
        goal: str,
        candidate_actions: Iterable[Any],
        registry: Mapping[str, Any],
    ) -> ExplorationDecision | None:
        state_signature = str(state_signature or "").strip()
        if not state_signature:
            return None

        goal_domains = _goal_domains(goal)
        learned_rows = self.transition_model.actions_for_state(state_signature, limit=128)
        total_visits = sum(int(row.get("observation_count", 0) or 0) for row in learned_rows)
        try:
            state_row = self.store.get_state_value(state_signature)
            total_visits += int((state_row or {}).get("visits", 0) or 0)
        except Exception:
            pass
        total_visits = max(1, total_visits)

        arm_candidates = [_normalize_action(raw) for raw in candidate_actions or ()]
        arm_signature_map = {action_signature(action): action for action in arm_candidates if str(action.get("tool") or "")}
        bandit = self._nonstationary_bandit(state_signature, arm_signature_map.keys()) if arm_signature_map else None
        bandit_scores = bandit.scores() if bandit else {}
        bandit_selected = bandit.choose_arm() if bandit else ""
        scored: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in candidate_actions or ():
            action = _normalize_action(raw)
            tool_name = action["tool"]
            tool = registry.get(tool_name)
            if not tool_name or tool_name.startswith("simulate_") or not is_safe_exploration_tool(tool):
                continue
            try:
                if tool.validate_args(action["parameters"]):
                    continue
            except Exception:
                continue
            sig = action_signature(action)
            if sig in seen:
                continue
            seen.add(sig)

            metrics = self._metrics(state_signature, action)
            n = int(metrics["n"])
            value_term = self._action_value(state_signature, sig, n)
            success_probability = float(metrics["success_probability"])
            exploitation = _clamp(0.65 * success_probability + 0.35 * value_term)
            # UCB1-style optimism is kept separate from the utility score so the
            # decision evidence can show exactly how much uncertainty contributed.
            ucb_raw = math.sqrt(2.0 * math.log(max(2, total_visits + 1.0)) / (n + 1.0))
            ucb = _clamp((ucb_raw / 2.25) * float(metrics.get("exploration_multiplier", 1.0)))
            bandit_raw = float(bandit_scores.get(sig, 0.0))
            bandit_bonus = _clamp((math.tanh(bandit_raw) + 1.0) / 2.0) if math.isfinite(bandit_raw) else 1.0
            if sig == bandit_selected:
                bandit_bonus = max(bandit_bonus, 0.85)
            relearning = _clamp(float(metrics["prediction_error"]) * (1.0 if n >= self.min_relearning_evidence else 0.5))
            historical_info = self._historical_information_gain(tool_name, sig)
            model_information = float(metrics["information_gain"])
            prior_information = float(getattr(tool, "information_gain_prior", 0.0) or 0.0)
            if historical_info is not None:
                information = _clamp(0.50 * historical_info + 0.30 * model_information + 0.20 * prior_information)
            else:
                information = _clamp(0.68 * model_information + 0.32 * prior_information)
            novelty = _clamp(float(metrics["novelty"]))
            goal_alignment = _goal_alignment(action, tool, goal)
            tool_domains = {str(x).casefold() for x in (getattr(tool, "information_domains", ()) or ())}
            local_information_bonus = 0.0
            if self._requires_external_source(goal):
                # Explicit source requirements are hard semantic constraints: local research
                # memory is not a substitute for a user request to investigate the web.
                if "external_web" not in tool_domains:
                    goal_alignment *= 0.35
                else:
                    goal_alignment = max(goal_alignment, 0.85)
            risk_penalty = _clamp({"low": 0.0, "medium": 0.45, "high": 1.0}.get(str(getattr(tool, "risk", "high")).casefold(), 1.0))
            cost_penalty = _clamp(float(getattr(tool, "cost", 0.0) or 0.0) / _MAX_SAFE_COST)
            if not self._requires_external_source(goal) and "learning" in goal_domains and "memory" in tool_domains:
                # Prefer local, durable evidence when it is cheaper; external research becomes
                # the next step only when the local probe does not settle the uncertainty.
                local_information_bonus = 0.32 * (1.0 - cost_penalty)
            expected_failure_cost = _clamp((1.0 - success_probability) * (1.0 + cost_penalty + 0.50 * risk_penalty))
            # One-step value-of-information proxy: uncertainty reduction weighted by
            # how costly it is to act blindly on the current evidence.  It is not a
            # fabricated reward and is surfaced explicitly as a planning heuristic.
            information_value = _clamp(information * goal_alignment * max(0.15, expected_failure_cost))
            score = (
                self.goal_weight * goal_alignment
                + self.exploitation_weight * exploitation
                + self.information_weight * information
                + self.novelty_weight * novelty
                + self.relearning_weight * relearning
                + self.ucb_weight * ucb
                + 0.70 * bandit_bonus
                + 0.90 * information_value
                + local_information_bonus
                - self.risk_weight * risk_penalty
                - 0.35 * cost_penalty
            )
            scored.append({
                "action": action,
                "tool": tool,
                "signature": sig,
                "score": float(score),
                "goal_alignment": goal_alignment,
                "exploitation": exploitation,
                "ucb_bonus": ucb,
                "information_gain": information,
                "historical_information_gain": historical_info,
                "novelty": novelty,
                "relearning_pressure": relearning,
                "stale_model": bool(metrics.get("stale", 0.0)),
                "exploration_multiplier": float(metrics.get("exploration_multiplier", 1.0)),
                "risk_penalty": risk_penalty,
                "evidence_count": n,
                "model_confidence": float(metrics["confidence"]),
                "model_uncertainty": float(metrics["uncertainty"]),
                "expected_failure_cost": expected_failure_cost,
                "information_value": information_value,
                "local_information_bonus": local_information_bonus,
            })

        # Do not turn an unrelated safe tool into a fake information action.
        scored = [row for row in scored if row["goal_alignment"] >= self.min_goal_alignment]
        if not scored:
            return None

        scored.sort(key=lambda row: (-row["score"], row["tool"].name, row["signature"]))
        top = scored[0]
        second_score = scored[1]["score"] if len(scored) > 1 else float("-inf")
        # Calculate the best score using only exploitation terms. Exploration should be
        # justified relative to the action SHURY would choose if it ignored uncertainty.
        def exploit_score(row: dict[str, Any]) -> float:
            return (
                self.goal_weight * float(row["goal_alignment"])
                + self.exploitation_weight * float(row["exploitation"])
                - self.risk_weight * float(row["risk_penalty"])
                - 0.35 * min(1.0, float(getattr(row["tool"], "cost", 0.0) or 0.0) / _MAX_SAFE_COST)
            )
        exploit_best = max(scored, key=lambda row: (exploit_score(row), row["tool"].name))
        exploit_top_score = exploit_score(top)
        best_exploit_score = exploit_score(exploit_best)
        unknown = int(top["evidence_count"]) == 0
        high_uncertainty = float(top["model_uncertainty"]) >= self.uncertainty_threshold
        high_error = (
            float(top["relearning_pressure"]) >= 0.35
            and int(top["evidence_count"]) >= self.min_relearning_evidence
        )
        selected_mode = "exploit"
        reason = "best safe action by observed utility"
        if high_error and (len(scored) == 1 or top["score"] >= second_score - 0.25):
            selected_mode = "relearn"
            reason = "historical prediction error is high enough to justify fresh evidence"
        elif float(top["information_value"]) >= 0.18 and (unknown or high_uncertainty or float(top["information_gain"]) >= 0.68):
            selected_mode = "information"
            reason = "expected uncertainty reduction is worth the modeled cost of acting with current evidence"
        elif (unknown or high_uncertainty) and top["score"] >= best_exploit_score + self.explore_margin:
            selected_mode = "explore"
            reason = "safe uncertainty bonus outweighs the current exploitation choice"

        summary = tuple(
            {
                "tool": row["tool"].name,
                "score": round(float(row["score"]), 6),
                "mode_candidate": int(row["evidence_count"]) == 0,
                "goal_alignment": round(float(row["goal_alignment"]), 6),
                "information_gain": round(float(row["information_gain"]), 6),
                "historical_information_gain": (None if row["historical_information_gain"] is None else round(float(row["historical_information_gain"]), 6)),
                "novelty": round(float(row["novelty"]), 6),
                "relearning_pressure": round(float(row["relearning_pressure"]), 6),
                "stale_model": bool(row.get("stale_model", False)),
                "exploration_multiplier": round(float(row.get("exploration_multiplier", 1.0)), 6),
                "ucb_bonus": round(float(row["ucb_bonus"]), 6),
                "exploitation": round(float(row["exploitation"]), 6),
                "evidence_count": int(row["evidence_count"]),
                "expected_failure_cost": round(float(row["expected_failure_cost"]), 6),
                "information_value": round(float(row["information_value"]), 6),
                "local_information_bonus": round(float(row.get("local_information_bonus", 0.0)), 6),
            }
            for row in scored[: self.max_candidates]
        )
        return ExplorationDecision(
            mode=selected_mode,
            state_signature=state_signature,
            selected_tool=top["tool"].name,
            selected_action_signature=top["signature"],
            selected_action=top["action"],
            score=float(top["score"]),
            goal_alignment=float(top["goal_alignment"]),
            exploitation=float(top["exploitation"]),
            ucb_bonus=float(top["ucb_bonus"]),
            information_gain=float(top["information_gain"]),
            historical_information_gain=(None if top["historical_information_gain"] is None else float(top["historical_information_gain"])),
            novelty=float(top["novelty"]),
            relearning_pressure=float(top["relearning_pressure"]),
            risk_penalty=float(top["risk_penalty"]),
            evidence_count=int(top["evidence_count"]),
            model_confidence=float(top["model_confidence"]),
            model_uncertainty=float(top["model_uncertainty"]),
            reason=reason,
            candidates=summary,
            expected_failure_cost=float(top["expected_failure_cost"]),
            information_value=float(top["information_value"]),
            strategy=selected_mode,
        )
