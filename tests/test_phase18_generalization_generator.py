from __future__ import annotations

import json
from pathlib import Path

from app.evaluation.round3_generalization_generator import (
    ROUND3_GENERATOR_VERSION,
    ROUND3_SEED,
    generate_round3_dialogues,
    validate_round3,
)

ROOT = Path(__file__).resolve().parents[1]
ROUND1 = ROOT / "benchmarks/dialogues/dialogues_phase10_seed_20261002.jsonl"
ROUND2 = ROOT / "benchmarks/dialogues/round2/dialogues_round_02_seed_20261017.jsonl"


def _signature(dialogue: dict) -> str:
    return "\n".join(t["text"] for t in dialogue["turns"])


def test_round3_is_deterministic_and_unseen() -> None:
    a = generate_round3_dialogues(64, ROUND3_SEED)
    b = generate_round3_dialogues(64, ROUND3_SEED)
    assert json.dumps(a, ensure_ascii=False, sort_keys=True) == json.dumps(
        b, ensure_ascii=False, sort_keys=True
    )
    result = validate_round3(a, [ROUND1, ROUND2])
    assert result["valid"]
    assert result["unique_ids"] == 64
    assert all(value == 0 for value in result["previous_round_overlaps"].values())


def test_round3_has_all_required_generalization_dimensions() -> None:
    dialogues = generate_round3_dialogues(1000, ROUND3_SEED)
    result = validate_round3(dialogues, [ROUND1, ROUND2])
    assert result["gate_ready"]
    dimensions = result["round3_dimensions"]
    assert dimensions["implicit_intent"] > 0
    assert dimensions["long_context"] > 0
    assert dimensions["short_replies"] > 0
    assert dimensions["topic_switches"] > 0
    assert dimensions["corrections"] > 0
    assert dimensions["typos"] > 0
    assert dimensions["noise"] > 0
    assert dimensions["mixed_language"] > 0
    assert dimensions["egyptian_arabic"] > 0


def test_round3_schema_expectations_are_complete() -> None:
    dialogues = generate_round3_dialogues(100, ROUND3_SEED)
    required = (
        "expected_class",
        "expected_intent",
        "expected_slots",
        "expected_entities",
        "expected_reference",
        "expected_memory_action",
        "expected_tool",
        "expected_clarification",
    )
    assert all(d["generator_version"] == ROUND3_GENERATOR_VERSION for d in dialogues)
    for dialogue in dialogues:
        assert dialogue["metadata"]["independent_session"] is True
        assert "expected_final_state" in dialogue
        assert len(dialogue["turns"]) >= 3
        for turn in dialogue["turns"]:
            assert all(key in turn["expected"] for key in required)
