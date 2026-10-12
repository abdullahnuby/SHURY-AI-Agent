"""Adaptive execution controller.

Model-free policy inspired by path-centric reward shaping and minimal sufficient
search depth. It scores execution actions from live verification, reliability,
remaining cost, and marginal evidence gain, then chooses continue/retry/replan/
abstain. It never executes tools directly.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import re
from typing import Any


@dataclass(frozen=True)
class ExecutionDecision:
    action: str  # execute | retry | replan | stop | abstain
    confidence: float
    utility: float
    reason: str
    evidence_gain: float = 0.0


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[\w\u0600-\u06ff]+", str(text).casefold(), flags=re.UNICODE))


def _coverage(query: str, text: str) -> float:
    q = _tokens(query)
    if not q:
        return 0.0
    return len(q & _tokens(text)) / len(q)


def _verified_score(result_data: Any) -> float:
    if not isinstance(result_data, dict):
        return 0.0
    score = 0.0
    if result_data.get("grounded"):
        score += 0.35
    if result_data.get("verified"):
        score += 0.25
    if result_data.get("evidence"):
        score += min(0.25, len(result_data["evidence"]) * 0.05)
    if result_data.get("provenance") or result_data.get("policy"):
        score += 0.15
    return min(1.0, score)


class AdaptiveExecutionController:
    """Small state machine for execution-time adaptation."""
    def __init__(self, memory=None):
        self.memory = memory

    def tool_success_probability(self, tool_name: str) -> float:
        if not self.memory:
            return 0.70
        try:
            return float(self.memory.tool_reliability_posterior(tool_name))
        except Exception:
            return 0.70

    def score_tool(self, tool, *, information_value=0.0, irreversible=False) -> float:
        p = self.tool_success_probability(tool.name)
        risk = {"low": 0.0, "medium": 0.18, "high": 0.40}.get(tool.risk, 0.18)
        approval = 0.12 if tool.requires_approval else 0.0
        cost = math.log1p(max(0.0, tool.cost)) / 4.0
        utility = 0.55 * p + 0.35 * min(1.0, information_value) - 0.20 * cost - risk - approval
        if irreversible and not tool.idempotent:
            utility -= 0.15
        return utility

    def choose_next(self, ready_steps, registry, *, query: str = "", previous_output=None,
                    attempts: int = 0, max_attempts: int = 2) -> ExecutionDecision:
        if not ready_steps:
            return ExecutionDecision("stop", 1.0, 0.0, "لا توجد خطوة جاهزة")
        ranked = []
        for step in ready_steps:
            tool = registry[step.tool]
            information = 0.0
            if previous_output is not None:
                information = 1.0 - _coverage(query, str(previous_output))
            utility = self.score_tool(tool, information_value=information, irreversible=not tool.idempotent)
            ranked.append((utility, step))
        ranked.sort(key=lambda x: (-x[0], x[1].id))
        utility, step = ranked[0]
        p = self.tool_success_probability(step.tool)
        return ExecutionDecision("retry" if attempts > 0 else "execute", max(0.0, min(1.0, p)), utility,
                                 f"اختيار {step.tool} حسب reliability+cost+information value", 0.0)

    def after_result(self, tool, result, *, query: str = "", prior_output=None, attempts: int = 1) -> ExecutionDecision:
        if not result.ok:
            if attempts < tool.retries + 1:
                return ExecutionDecision("retry", 0.25, -0.2, f"فشل {tool.name} مع retry متاح")
            return ExecutionDecision("replan", 0.10, -0.4, f"فشل {tool.name} ولا يوجد retry إضافي")
        evidence = _verified_score(result.data)
        prior = _coverage(query, str(prior_output)) if prior_output is not None else 0.0
        current = _coverage(query, str(result.data))
        gain = max(0.0, current - prior)
        # Minimal sufficient search depth: stop when verification is strong and marginal gain is low.
        if evidence >= 0.70 and gain <= 0.10:
            return ExecutionDecision("stop", evidence, evidence - 0.05, "الأدلة الموثقة كافية والمكسب الهامشي منخفض", gain)
        if evidence < 0.35 and gain > 0.0:
            return ExecutionDecision("execute", evidence, gain, "الأدلة ما زالت ضعيفة لكن الخطوة أنتجت إشارة مفيدة", gain)
        return ExecutionDecision("execute", evidence, evidence + gain, "استمرار تكيفي للمسار", gain)

    def path_reward(self, *, verified: bool, evidence_gain: float, coverage: float,
                    steps: int, failures: int, cost: float) -> float:
        base = (0.45 if verified else 0.0) + 0.30 * min(1.0, coverage) + 0.25 * min(1.0, evidence_gain)
        penalty = 0.08 * failures + 0.02 * max(0, steps - 1) + 0.02 * math.log1p(max(0.0, cost))
        return max(-1.0, min(1.0, base - penalty))
