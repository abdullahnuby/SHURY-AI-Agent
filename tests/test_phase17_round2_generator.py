from __future__ import annotations

import json
from pathlib import Path

from app.evaluation.round2_dialogue_generator import (
    ROUND2_GENERATOR_VERSION,
    ROUND2_SEED,
    generate_round2_dialogues,
    validate_round2,
)


ROUND1 = Path("benchmarks/dialogues/dialogues_phase10_seed_20261002.jsonl")


def test_round2_has_1000_independent_sessions_and_required_fields():
    rows = generate_round2_dialogues(1000, ROUND2_SEED)
    assert len(rows) == 1000
    assert len({r["conversation_id"] for r in rows}) == 1000
    assert len({r["session_seed"] for r in rows}) == 1000
    assert all(len(r["turns"]) >= 2 for r in rows)
    assert {r["generator_version"] for r in rows} == {ROUND2_GENERATOR_VERSION}
    for row in rows:
        for turn in row["turns"]:
            expected = turn["expected"]
            assert set((
                "expected_class", "expected_intent", "expected_slots", "expected_entities",
                "expected_reference", "expected_memory_action", "expected_tool", "expected_clarification"
            )).issubset(expected)
        assert "expected_final_state" in row


def test_round2_replays_deterministically():
    a = generate_round2_dialogues(100, ROUND2_SEED)
    b = generate_round2_dialogues(100, ROUND2_SEED)
    assert a == b


def test_round2_is_unseen_vs_round1():
    rows = generate_round2_dialogues(1000, ROUND2_SEED)
    result = validate_round2(rows, ROUND1)
    assert result["valid"] is True
    assert result["round1_id_overlap"] == 0
    assert result["round1_transcript_overlap"] == 0
    assert result["gate_ready"] is True


def test_round2_has_new_topic_and_reference_dimensions():
    rows = generate_round2_dialogues(1000, ROUND2_SEED)
    assert sum(bool(r["generation_dimensions"].get("round2_new_topics")) for r in rows) > 0
    assert sum(bool(r["generation_dimensions"].get("round2_new_references")) for r in rows) > 0
    assert all(r["generation_dimensions"].get("round2_new_wording") is True for r in rows)
