from __future__ import annotations

"""Deterministic machine-verifiable evaluation oracle for SHURY dialogues.

The oracle intentionally performs no generative judging, fuzzy prose scoring, or LLM calls.
It compares structured expectations produced by the deterministic dialogue generator against
structured observations captured from the canonical SHURY runtime.
"""

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

TURN_EXPECTATION_FIELDS = (
    "expected_class",
    "expected_intent",
    "expected_slots",
    "expected_entities",
    "expected_reference",
    "expected_memory_action",
    "expected_tool",
    "expected_clarification",
)

FINAL_STATE_FIELDS = ("memory", "active_reference", "result_keys")


@dataclass(frozen=True)
class OracleMismatch:
    scope: str
    field: str
    expected: Any
    actual: Any
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "field": self.field,
            "expected": self.expected,
            "actual": self.actual,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class OracleResult:
    passed: bool
    checks: tuple[dict[str, Any], ...] = ()
    mismatches: tuple[OracleMismatch, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": list(self.checks),
            "mismatches": [item.to_dict() for item in self.mismatches],
        }


class DeterministicEvaluationOracle:
    """Single structured oracle for SHURY benchmark expectations."""

    version = "shury.oracle.v1"

    @staticmethod
    def validate_turn_expectation(expected: Mapping[str, Any]) -> list[str]:
        errors: list[str] = []
        if set(expected) != set(TURN_EXPECTATION_FIELDS):
            missing = sorted(set(TURN_EXPECTATION_FIELDS) - set(expected))
            extra = sorted(set(expected) - set(TURN_EXPECTATION_FIELDS))
            if missing:
                errors.append(f"missing fields: {missing}")
            if extra:
                errors.append(f"unexpected fields: {extra}")
        if not isinstance(expected.get("expected_class"), str) or not expected.get("expected_class"):
            errors.append("expected_class must be a non-empty string")
        if not isinstance(expected.get("expected_intent"), str) or not expected.get("expected_intent"):
            errors.append("expected_intent must be a non-empty string")
        if not isinstance(expected.get("expected_slots"), dict):
            errors.append("expected_slots must be an object")
        if not isinstance(expected.get("expected_entities"), list):
            errors.append("expected_entities must be an array")
        reference = expected.get("expected_reference")
        if reference is not None and not isinstance(reference, dict):
            errors.append("expected_reference must be an object or null")
        memory_action = expected.get("expected_memory_action")
        if memory_action is not None and not isinstance(memory_action, dict):
            errors.append("expected_memory_action must be an object or null")
        tool = expected.get("expected_tool")
        if tool is not None and not isinstance(tool, str):
            errors.append("expected_tool must be a string or null")
        if not isinstance(expected.get("expected_clarification"), bool):
            errors.append("expected_clarification must be boolean")
        return errors

    @staticmethod
    def validate_final_state(expected: Mapping[str, Any]) -> list[str]:
        errors: list[str] = []
        if not isinstance(expected, Mapping):
            return ["expected_final_state must be an object"]
        required = {"memory", "active_reference"}
        missing = required - set(expected)
        if missing:
            errors.append(f"expected_final_state missing fields: {sorted(missing)}")
        if not isinstance(expected.get("memory"), dict):
            errors.append("expected_final_state.memory must be an object")
        if "active_reference" in expected and expected.get("active_reference") is not None and not isinstance(expected.get("active_reference"), (str, dict)):
            errors.append("expected_final_state.active_reference must be string/object/null")
        if "result_keys" in expected and not isinstance(expected.get("result_keys"), list):
            errors.append("expected_final_state.result_keys must be an array")
        return errors

    def validate_dialogues(self, dialogues: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        errors: list[str] = []
        session_count = 0
        turn_count = 0
        fully_specified = 0
        for position, dialogue in enumerate(dialogues):
            session_count += 1
            cid = str(dialogue.get("conversation_id") or f"session[{position}]")
            turns = dialogue.get("turns")
            if not isinstance(turns, list) or len(turns) < 2:
                errors.append(f"{cid}: turns must be an array with >=2 items")
                continue
            final_errors = self.validate_final_state(dialogue.get("expected_final_state", {}))
            errors.extend(f"{cid}: {item}" for item in final_errors)
            for turn_position, turn in enumerate(turns, 1):
                turn_count += 1
                expected = turn.get("expected") if isinstance(turn, Mapping) else None
                if not isinstance(expected, Mapping):
                    errors.append(f"{cid}/turn{turn_position}: expected must be an object")
                    continue
                turn_errors = self.validate_turn_expectation(expected)
                if turn_errors:
                    errors.extend(f"{cid}/turn{turn_position}: {item}" for item in turn_errors)
                else:
                    fully_specified += 1
        return {
            "valid": not errors,
            "oracle_version": self.version,
            "sessions": session_count,
            "turns": turn_count,
            "fully_specified_turns": fully_specified,
            "errors": errors,
        }

    @staticmethod
    def _normalize_entities(items: Any) -> list[dict[str, Any]]:
        if not isinstance(items, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            normalized.append({
                "text": str(item.get("text") or "").strip(),
                "type": str(item.get("type") or "").strip(),
                "normalized": str(item.get("normalized") or item.get("text") or "").strip(),
            })
        return normalized

    @classmethod
    def from_runtime_result(
        cls,
        result: Any,
        *,
        semantic_parse: Any | None = None,
        memory_actions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Convert a canonical BrainResult into JSON-safe structured observations.

        `semantic_parse` is the deterministic Layer-2 parse captured alongside the canonical
        runtime result. Runtime state remains authoritative for planning/decision/tool/effect
        fields; the parse supplies the original structured intent/entity/reference fields that
        the legacy Brain frame intentionally compresses.
        """
        state = getattr(result, "state", None)
        semantic = semantic_parse
        decision = getattr(state, "decision", None)
        frame = getattr(state, "semantic", None)

        if semantic is not None:
            intent = semantic.top_intent.name if semantic.top_intent else ""
            conversation_class = _conversation_class_from_parse(semantic)
            parsed_slots = dict(semantic.slots)
            frame_slots = dict(frame.slots) if frame else {}
            slots = {**parsed_slots, **frame_slots}
            if frame is not None and frame.requested_operation in {"query_identity", "query_memory"}:
                intent = frame.requested_operation
            entities = [entity.to_dict() for entity in semantic.entities]
            references = [reference.to_dict() for reference in semantic.references]
        else:
            intent = str(frame.requested_operation if frame else "")
            conversation_class = _conversation_class_from_frame(frame)
            slots = dict(frame.slots) if frame else {}
            entities = [
                {"text": str(text), "type": str(entity_type), "normalized": str(text)}
                for text, entity_type in (frame.entities if frame else ())
            ]
            references = []

        plan = list(getattr(state, "plan", ()) or ())
        observations = list(getattr(state, "observations", ()) or ())
        executed_steps = [
            item for item in observations
            if isinstance(item, Mapping) and item.get("ok") is True and item.get("step_id")
        ]
        executed_tools = [str(item.get("tool") or "") for item in executed_steps if item.get("tool")]
        planned_tools = [str(getattr(step, "tool", "") or "") for step in plan if getattr(step, "tool", "")]
        tool = str(getattr(decision, "tool", "") or "")
        if not tool and executed_tools:
            tool = executed_tools[-1]
        if not tool and planned_tools:
            tool = planned_tools[-1]
        if getattr(decision, "kind", "") == "clarify" and not tool:
            tool = None

        action_records = list(memory_actions or [])
        if not action_records:
            action_records = _memory_actions_from_plan(plan, executed_tools)

        selected_reference = None
        for reference in references:
            if reference.get("resolved") and reference.get("target"):
                selected_reference = reference
                break
        if selected_reference is None and references:
            selected_reference = references[0]

        actual = {
            "status": str(getattr(result, "status", "") or "completed"),
            "conversation_class": conversation_class,
            "intent": intent,
            "slots": slots,
            "entities": entities,
            "references": references,
            "reference": selected_reference,
            "memory_actions": action_records,
            "tool": tool,
            "clarification": bool(
                getattr(decision, "kind", "") == "clarify"
                or getattr(frame, "uncertainty", ())
                and any(str(item) for item in getattr(frame, "uncertainty", ()))
            ),
            "decision_kind": str(getattr(decision, "kind", "") or ""),
            "response": str(getattr(result, "response", "") or ""),
        }
        return actual

    @staticmethod
    def capture_final_state(memory: Any, actual_turns: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        """Capture the comparable final state from the canonical durable memory plus turns."""
        memory_state: dict[str, Any] = {}
        if memory is not None:
            try:
                for item in memory.profile(limit=200):
                    if not isinstance(item, Mapping):
                        continue
                    key = str(item.get("key") or "").strip()
                    if key and item.get("value") is not None:
                        memory_state[key] = item.get("value")
            except Exception:
                memory_state = {}
        result_keys: list[str] = []
        active_reference: Any = None
        for turn in actual_turns:
            for action in turn.get("memory_actions", ()) or ():
                if isinstance(action, Mapping) and action.get("action") == "write_result" and action.get("key"):
                    result_keys.append(str(action["key"]))
            reference = turn.get("reference")
            if isinstance(reference, Mapping) and reference.get("resolved") and reference.get("target"):
                active_reference = reference.get("target")
        return {
            "memory": memory_state,
            "active_reference": active_reference,
            "result_keys": list(dict.fromkeys(result_keys)),
        }

    def compare_turn(self, expected: Mapping[str, Any], actual: Mapping[str, Any], *, scope: str = "turn") -> OracleResult:
        mismatches: list[OracleMismatch] = []
        checks: list[dict[str, Any]] = []

        schema_errors = self.validate_turn_expectation(expected)
        if schema_errors:
            return OracleResult(
                False,
                checks=(),
                mismatches=tuple(OracleMismatch(scope, "schema", expected, actual, message) for message in schema_errors),
            )

        def check(field: str, ok: bool, actual_value: Any, reason: str) -> None:
            checks.append({"field": field, "passed": bool(ok)})
            if not ok:
                mismatches.append(OracleMismatch(scope, field, expected[field], actual_value, reason))

        check("expected_class", actual.get("conversation_class") == expected["expected_class"], actual.get("conversation_class"), "conversation class mismatch")
        check("expected_intent", actual.get("intent") == expected["expected_intent"], actual.get("intent"), "intent mismatch")

        expected_slots = expected["expected_slots"]
        actual_slots = actual.get("slots") if isinstance(actual.get("slots"), Mapping) else {}
        slot_ok = all(_structured_value_equal(actual_slots.get(key), value) for key, value in expected_slots.items())
        check("expected_slots", slot_ok, dict(actual_slots), "one or more expected slot values were not preserved")

        expected_entities = self._normalize_entities(expected["expected_entities"])
        actual_entities = self._normalize_entities(actual.get("entities"))
        entity_ok = _contains_entities(actual_entities, expected_entities)
        check("expected_entities", entity_ok, actual_entities, "one or more expected entities were not observed")

        expected_reference = expected["expected_reference"]
        actual_reference = actual.get("reference")
        reference_ok = _reference_matches(expected_reference, actual_reference)
        check("expected_reference", reference_ok, actual_reference, "reference resolution mismatch")

        expected_memory = expected["expected_memory_action"]
        actual_memory = actual.get("memory_actions") or []
        memory_ok = _memory_action_matches(expected_memory, actual_memory)
        check("expected_memory_action", memory_ok, actual_memory, "memory action mismatch")

        expected_tool = expected["expected_tool"]
        actual_tool = actual.get("tool")
        check("expected_tool", actual_tool == expected_tool, actual_tool, "tool routing mismatch")
        check("expected_clarification", bool(actual.get("clarification")) == bool(expected["expected_clarification"]), actual.get("clarification"), "clarification state mismatch")

        return OracleResult(not mismatches, tuple(checks), tuple(mismatches))

    def compare_final_state(self, expected: Mapping[str, Any], actual: Mapping[str, Any], *, scope: str = "final_state") -> OracleResult:
        errors = self.validate_final_state(expected)
        if errors:
            return OracleResult(False, mismatches=tuple(OracleMismatch(scope, "schema", expected, actual, item) for item in errors))
        mismatches: list[OracleMismatch] = []
        checks: list[dict[str, Any]] = []

        expected_memory = expected.get("memory", {})
        actual_memory = actual.get("memory", {}) if isinstance(actual.get("memory", {}), Mapping) else {}
        memory_ok = all(_structured_value_equal(actual_memory.get(key), value) for key, value in expected_memory.items())
        checks.append({"field": "memory", "passed": memory_ok})
        if not memory_ok:
            mismatches.append(OracleMismatch(scope, "memory", expected_memory, actual_memory, "expected durable memory values were not present"))

        expected_ref = expected.get("active_reference")
        actual_ref = actual.get("active_reference")
        reference_ok = _reference_target_matches(expected_ref, actual_ref)
        checks.append({"field": "active_reference", "passed": reference_ok})
        if not reference_ok:
            mismatches.append(OracleMismatch(scope, "active_reference", expected_ref, actual_ref, "final active reference mismatch"))

        if "result_keys" in expected:
            expected_keys = {str(item) for item in expected.get("result_keys", [])}
            actual_keys = {str(item) for item in actual.get("result_keys", [])}
            result_ok = expected_keys <= actual_keys
            checks.append({"field": "result_keys", "passed": result_ok})
            if not result_ok:
                mismatches.append(OracleMismatch(scope, "result_keys", sorted(expected_keys), sorted(actual_keys), "expected result keys were not observed"))

        return OracleResult(not mismatches, tuple(checks), tuple(mismatches))

    def compare_conversation(
        self,
        dialogue: Mapping[str, Any],
        actual_turns: Iterable[Mapping[str, Any]],
        actual_final_state: Mapping[str, Any],
    ) -> dict[str, Any]:
        expected_turns = dialogue.get("turns") or []
        actual_turns_list = list(actual_turns)
        turn_results: list[dict[str, Any]] = []
        for index, expected_turn in enumerate(expected_turns):
            actual = actual_turns_list[index] if index < len(actual_turns_list) else {}
            result = self.compare_turn(expected_turn.get("expected", {}), actual, scope=f"turn:{index + 1}")
            turn_results.append(result.to_dict())
        length_ok = len(expected_turns) == len(actual_turns_list)
        final_result = self.compare_final_state(dialogue.get("expected_final_state", {}), actual_final_state)
        passed = length_ok and all(item["passed"] for item in turn_results) and final_result.passed
        return {
            "conversation_id": dialogue.get("conversation_id"),
            "passed": passed,
            "turn_count_expected": len(expected_turns),
            "turn_count_actual": len(actual_turns_list),
            "turn_count_match": length_ok,
            "turns": turn_results,
            "final_state": final_result.to_dict(),
        }


def _contains_entities(actual: list[dict[str, Any]], expected: list[dict[str, Any]]) -> bool:
    remaining = list(actual)
    for item in expected:
        found = None
        for index, candidate in enumerate(remaining):
            if item["type"] and candidate["type"] != item["type"]:
                continue
            expected_normalized = item["normalized"] or item["text"]
            candidate_normalized = candidate["normalized"] or candidate["text"]
            if expected_normalized == candidate_normalized or item["text"] == candidate["text"]:
                found = index
                break
        if found is None:
            return False
        remaining.pop(found)
    return True


def _reference_matches(expected: Any, actual: Any) -> bool:
    if expected is None:
        return actual is None
    if not isinstance(expected, Mapping) or not isinstance(actual, Mapping):
        return False
    for key in ("kind", "target"):
        if expected.get(key) not in (None, "") and actual.get(key) != expected.get(key):
            return False
    return True


def _reference_target_matches(expected: Any, actual: Any) -> bool:
    if expected is None:
        return actual is None
    if isinstance(expected, Mapping):
        expected = expected.get("target")
    if isinstance(actual, Mapping):
        actual = actual.get("target")
    return expected == actual


def _memory_action_matches(expected: Any, actual_actions: list[dict[str, Any]]) -> bool:
    if expected is None:
        return not actual_actions
    if not actual_actions:
        return False
    actual = actual_actions[-1]
    return all(_structured_value_equal(actual.get(key), value) for key, value in expected.items())


def _structured_value_equal(actual: Any, expected: Any) -> bool:
    if isinstance(actual, str) and isinstance(expected, str):
        return actual.strip().casefold() == expected.strip().casefold()
    if isinstance(actual, Mapping) and isinstance(expected, Mapping):
        return set(actual) == set(expected) and all(_structured_value_equal(actual.get(key), expected.get(key)) for key in expected)
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(_structured_value_equal(a, e) for a, e in zip(actual, expected))
    return actual == expected


def _memory_actions_from_plan(plan: list[Any], executed_tools: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for step in plan:
        tool = str(getattr(step, "tool", "") or "")
        args = dict(getattr(step, "args", {}) or {})
        if executed_tools and tool not in executed_tools:
            continue
        key = str(args.get("key") or "").strip()
        value = args.get("value")
        if tool == "remember_fact":
            records.append({"action": "update" if args.get("replace") else "write", "key": key, "value": value})
        elif tool == "remember_result":
            records.append({"action": "write_result", "key": key})
        elif tool == "forget_fact":
            records.append({"action": "forget", "key": key})
    return records


def _conversation_class_from_parse(parse: Any) -> str:
    from app.intelligence.semantic.contract import from_parse
    return from_parse(parse).conversation_class


def _conversation_class_from_frame(frame: Any) -> str:
    if frame is None:
        return ""
    operation = str(getattr(frame, "requested_operation", "") or "")
    uncertainty = tuple(getattr(frame, "uncertainty", ()) or ())
    speech_act = str(getattr(frame, "speech_act", "") or "")
    if operation in {"greeting", "how_are_you", "thanks", "goodbye", "acknowledgement"}:
        return "SOCIAL"
    if speech_act == "correction" or uncertainty:
        return "CLARIFICATION"
    if operation in {"remember", "remember_fact", "forget_memory", "remember_result", "remember_last_result"}:
        return "MEMORY_WRITE"
    if operation in {"query_identity", "query_memory", "memory_profile", "memory_search", "query_capabilities"}:
        return "MEMORY_READ"
    if operation in {"research", "web_research", "scientific_research", "query_knowledge"}:
        return "RESEARCH" if operation != "query_knowledge" else "INFORMATION"
    if operation in {"data_analysis", "workspace_reasoning"}:
        return "ANALYSIS"
    return "EXECUTION" if operation else "INFORMATION"


__all__ = [
    "DeterministicEvaluationOracle",
    "OracleMismatch",
    "OracleResult",
    "TURN_EXPECTATION_FIELDS",
    "FINAL_STATE_FIELDS",
]
