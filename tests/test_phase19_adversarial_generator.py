from pathlib import Path
import json
from app.evaluation.adversarial_generator import generate_adversarial_dialogues, validate_adversarial_dialogues


def test_phase19_generates_deterministically_and_is_unseen(tmp_path: Path):
    a = generate_adversarial_dialogues(80, seed=20261019)
    b = generate_adversarial_dialogues(80, seed=20261019)
    assert a == b
    assert len({d["conversation_id"] for d in a}) == 80
    assert len({"\n".join(t["text"] for t in d["turns"]) for d in a}) == 80


def test_phase19_all_adversarial_dimensions_present():
    dialogues = generate_adversarial_dialogues(140, seed=20261019)
    dims = ["ambiguous_reference", "long_context", "contradictory_information", "rapid_topic_switching",
            "language_switching", "typos", "memory_conflicts", "tool_failures", "rag_failures", "web_failures",
            "unsafe_requests", "prompt_injection", "untrusted_content"]
    for name in dims:
        assert any(d["generation_dimensions"][name] for d in dialogues), name


def test_phase19_has_machine_verifiable_expectations():
    dialogues = generate_adversarial_dialogues(120, seed=20261019)
    for d in dialogues:
        assert d["category"] == "adversarial"
        assert d["metadata"]["independent_session"] is True
        for turn in d["turns"]:
            expected = turn["expected"]
            assert expected["expected_class"]
            assert expected["expected_intent"]
            assert isinstance(expected["expected_slots"], dict)
            assert isinstance(expected["expected_entities"], list)
            assert "expected_reference" in expected
            assert "expected_memory_action" in expected
            assert "expected_tool" in expected
            assert isinstance(expected["expected_clarification"], bool)


def test_phase19_schema_validator_accepts_corpus(tmp_path: Path):
    dialogues = generate_adversarial_dialogues(60, seed=20261019)
    # Use a tiny empty previous corpus only for direct schema validation.
    report = validate_adversarial_dialogues(dialogues, [])
    assert report["valid"] is True
    assert report["fully_specified_turns"] == sum(len(d["turns"]) for d in dialogues)
