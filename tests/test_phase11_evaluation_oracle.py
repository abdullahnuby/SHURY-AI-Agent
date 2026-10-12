from __future__ import annotations

import json
from pathlib import Path

from app.brain import CognitiveKernel
from app.brain.store import BrainStateStore
from app.evaluation.dialogue_generator import generate_dialogues
from app.evaluation.oracle import DeterministicEvaluationOracle
from app.intelligence.semantic import semantic_understand
from app.knowledge.memory import Memory


CORPUS = Path(__file__).resolve().parents[1] / "benchmarks" / "dialogues" / "dialogues_phase10_seed_20261002.jsonl"


def _load_corpus() -> list[dict]:
    return [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_oracle_validates_all_1000_sessions_and_all_turn_fields():
    dialogues = _load_corpus()
    result = DeterministicEvaluationOracle().validate_dialogues(dialogues)
    assert result["valid"], result["errors"][:20]
    assert result["sessions"] == 1000
    assert result["turns"] == 3216
    assert result["fully_specified_turns"] == 3216


def test_oracle_rejects_missing_or_invalid_expectations():
    dialogue = generate_dialogues(1, seed=900)
    expected = dialogue[0]["turns"][0]["expected"]
    expected.pop("expected_tool")
    errors = DeterministicEvaluationOracle().validate_turn_expectation(expected)
    assert any("missing fields" in item for item in errors)


def test_oracle_compares_every_structured_turn_field():
    oracle = DeterministicEvaluationOracle()
    expected = {
        "expected_class": "MEMORY_WRITE",
        "expected_intent": "remember_fact",
        "expected_slots": {"fact:name": "Abdullah", "key": "name", "value": "Abdullah"},
        "expected_entities": [{"text": "Abdullah", "type": "person", "normalized": "Abdullah"}],
        "expected_reference": None,
        "expected_memory_action": {"action": "write", "key": "name", "value": "Abdullah"},
        "expected_tool": "remember_fact",
        "expected_clarification": False,
    }
    actual = {
        "conversation_class": "MEMORY_WRITE",
        "intent": "remember_fact",
        "slots": {"fact:name": "Abdullah", "key": "name", "value": "Abdullah"},
        "entities": [{"text": "Abdullah", "type": "person", "normalized": "Abdullah"}],
        "reference": None,
        "memory_actions": [{"action": "write", "key": "name", "value": "Abdullah"}],
        "tool": "remember_fact",
        "clarification": False,
    }
    result = oracle.compare_turn(expected, actual)
    assert result.passed, result.to_dict()
    assert len(result.checks) == 8


def test_oracle_reports_deterministic_field_mismatch():
    oracle = DeterministicEvaluationOracle()
    expected = generate_dialogues(1, seed=901)[0]["turns"][0]["expected"]
    actual = {
        "conversation_class": "EXECUTION",
        "intent": "calculate",
        "slots": {},
        "entities": [],
        "reference": None,
        "memory_actions": [],
        "tool": "calculator",
        "clarification": False,
    }
    result = oracle.compare_turn(expected, actual)
    assert not result.passed
    fields = {item.field for item in result.mismatches}
    assert "expected_class" in fields
    assert "expected_intent" in fields
    assert "expected_tool" in fields


def test_oracle_compares_final_state_without_llm_or_prose_scoring():
    oracle = DeterministicEvaluationOracle()
    expected = {"memory": {"name": "Abdullah"}, "active_reference": None}
    actual = {"memory": {"name": "Abdullah", "city": "Luxor"}, "active_reference": None}
    result = oracle.compare_final_state(expected, actual)
    assert result.passed, result.to_dict()


def test_oracle_captures_real_canonical_runtime_observation(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    brain = CognitiveKernel(
        memory=memory,
        state_store=BrainStateStore(tmp_path / "brain_state.db"),
    )
    session_id = "oracle-memory-1"
    text = "My name is Abdullah."
    semantic = semantic_understand(text, mem=memory, registry=brain.registry, session_id=session_id)
    result = brain.act(text, session_id=session_id, approve=lambda *_: True)
    actual = DeterministicEvaluationOracle.from_runtime_result(result, semantic_parse=semantic)
    assert actual["conversation_class"] == "MEMORY_WRITE"
    assert actual["intent"] == "remember_fact"
    assert actual["tool"] == "remember_fact"
    assert actual["clarification"] is False

    expected = {
        "expected_class": "MEMORY_WRITE",
        "expected_intent": "remember_fact",
        "expected_slots": {"fact:name": "Abdullah"},
        "expected_entities": [{"text": "Abdullah", "type": "person", "normalized": "Abdullah"}],
        "expected_reference": None,
        "expected_memory_action": {"action": "write", "key": "name", "value": "Abdullah"},
        "expected_tool": "remember_fact",
        "expected_clarification": False,
    }
    comparison = DeterministicEvaluationOracle().compare_turn(expected, actual, scope="real-runtime-turn")
    assert comparison.passed, comparison.to_dict()

    final_state = DeterministicEvaluationOracle.capture_final_state(memory, [actual])
    final = DeterministicEvaluationOracle().compare_final_state(
        {"memory": {"name": "abdullah"}, "active_reference": None, "result_keys": []},
        final_state,
    )
    assert final.passed, final.to_dict()


def test_oracle_is_reproducible_for_the_same_snapshot():
    oracle = DeterministicEvaluationOracle()
    dialogues = generate_dialogues(1, seed=903)
    expected = dialogues[0]["turns"][0]["expected"]
    actual = {
        "conversation_class": expected["expected_class"],
        "intent": expected["expected_intent"],
        "slots": expected["expected_slots"],
        "entities": expected["expected_entities"],
        "reference": expected["expected_reference"],
        "memory_actions": [expected["expected_memory_action"]] if expected["expected_memory_action"] else [],
        "tool": expected["expected_tool"],
        "clarification": expected["expected_clarification"],
    }
    first = oracle.compare_turn(expected, actual).to_dict()
    second = oracle.compare_turn(expected, actual).to_dict()
    assert first == second


def test_oracle_contains_no_generative_judge_dependency():
    import ast

    source = (Path(__file__).resolve().parents[1] / "app" / "evaluation" / "oracle.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module.split(".")[0])
    forbidden = {"openai", "anthropic", "transformers", "ollama", "google", "litellm"}
    assert not (set(imported) & forbidden)


def test_oracle_evaluates_real_canonical_multiturn_conversation(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    brain = CognitiveKernel(memory=memory, state_store=BrainStateStore(tmp_path / "brain_state.db"))
    oracle = DeterministicEvaluationOracle()
    session_id = "oracle-conversation-1"
    turns = [
        (
            "My name is Abdullah.",
            {
                "expected_class": "MEMORY_WRITE",
                "expected_intent": "remember_fact",
                "expected_slots": {"fact:name": "Abdullah"},
                "expected_entities": [{"text": "Abdullah", "type": "person", "normalized": "Abdullah"}],
                "expected_reference": None,
                "expected_memory_action": {"action": "write", "key": "name", "value": "Abdullah"},
                "expected_tool": "remember_fact",
                "expected_clarification": False,
            },
        ),
        (
            "What is my name?",
            {
                "expected_class": "MEMORY_READ",
                "expected_intent": "query_identity",
                "expected_slots": {"recall:key": "name", "key": "name"},
                "expected_entities": [],
                "expected_reference": None,
                "expected_memory_action": None,
                "expected_tool": "recall_fact",
                "expected_clarification": False,
            },
        ),
        (
            "Tell me my name again.",
            {
                "expected_class": "MEMORY_READ",
                "expected_intent": "query_identity",
                "expected_slots": {"recall:key": "name", "key": "name"},
                "expected_entities": [],
                "expected_reference": None,
                "expected_memory_action": None,
                "expected_tool": "recall_fact",
                "expected_clarification": False,
            },
        ),
    ]
    actual_turns = []
    for text, expected in turns:
        semantic = semantic_understand(text, mem=memory, registry=brain.registry, session_id=session_id)
        result = brain.act(text, session_id=session_id, approve=lambda *_: True)
        actual_turns.append(oracle.from_runtime_result(result, semantic_parse=semantic))
        assert oracle.compare_turn(expected, actual_turns[-1]).passed
    actual_final_state = oracle.capture_final_state(memory, actual_turns)
    dialogue = {
        "conversation_id": session_id,
        "turns": [{"expected": expected} for _, expected in turns],
        "expected_final_state": {"memory": {"name": "abdullah"}, "active_reference": None, "result_keys": []},
    }
    report = oracle.compare_conversation(dialogue, actual_turns, actual_final_state)
    assert report["passed"], report


def test_legacy_evaluation_judge_is_a_deterministic_compatibility_facade():
    from app.evaluation.judge import EvaluationJudge

    judge = EvaluationJudge()
    legacy = judge.judge(
        expected={"status": "completed", "required_tools": ["calculator"]},
        actual={"status": "completed", "tools": ["calculator"]},
    )
    assert legacy["passed"] is True
    structured = generate_dialogues(1, seed=904)[0]["turns"][0]["expected"]
    actual = {
        "conversation_class": structured["expected_class"],
        "intent": structured["expected_intent"],
        "slots": structured["expected_slots"],
        "entities": structured["expected_entities"],
        "reference": structured["expected_reference"],
        "memory_actions": [structured["expected_memory_action"]] if structured["expected_memory_action"] else [],
        "tool": structured["expected_tool"],
        "clarification": structured["expected_clarification"],
    }
    structured_result = judge.judge(expected=structured, actual=actual)
    assert structured_result["passed"] is True
