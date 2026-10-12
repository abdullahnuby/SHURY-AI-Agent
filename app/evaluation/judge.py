from __future__ import annotations

"""Backward-compatible deterministic facade for SHURY's single evaluation oracle."""

from typing import Any

from .oracle import DeterministicEvaluationOracle


class EvaluationJudge(DeterministicEvaluationOracle):
    """Compatibility API backed by the canonical deterministic evaluation oracle.

    New benchmark code should use ``DeterministicEvaluationOracle`` directly. The legacy
    ``judge(expected={status, required_tools}, actual={...})`` shape remains deterministic
    for existing callers and does not invoke a generative model.
    """

    def __init__(self, *, calibration_threshold: float = 0.90):
        self.calibration_threshold = max(0.0, min(1.0, float(calibration_threshold)))
        super().__init__()

    def judge(self, *, expected: dict[str, Any] | None = None, actual: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
        expected = dict(expected or {})
        actual = dict(actual or {})
        if any(key in expected for key in self.TURN_FIELDS):
            return self.compare_turn(expected, actual).to_dict()
        checks = []
        if "status" in expected:
            checks.append(("status", actual.get("status") == expected.get("status")))
        required = tuple(expected.get("required_tools") or ())
        actual_tools = tuple(actual.get("tools") or ())
        if required:
            checks.append(("required_tools", all(tool in actual_tools for tool in required)))
        passed = all(ok for _, ok in checks) if checks else bool(actual)
        return {
            "passed": passed,
            "checks": [{"name": name, "passed": bool(ok)} for name, ok in checks],
            "reason": "deterministic compatibility checks",
        }


EvaluationJudge.TURN_FIELDS = frozenset((
    "expected_class", "expected_intent", "expected_slots", "expected_entities",
    "expected_reference", "expected_memory_action", "expected_tool", "expected_clarification",
))
