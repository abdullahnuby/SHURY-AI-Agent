from __future__ import annotations

import json
from pathlib import Path

from app.evaluation.dialogue_generator import (
    DEFAULT_SEED,
    GENERATOR_VERSION,
    SCHEMA_VERSION,
    generate_dialogues,
    validate_dialogues,
    write_dialogues,
)


def test_generator_is_deterministic_and_prefix_stable():
    full = generate_dialogues(64, seed=17)
    again = generate_dialogues(64, seed=17)
    prefix = generate_dialogues(12, seed=17)
    assert full == again
    assert prefix == full[:12]
    assert all(item["seed"] == 17 for item in full)
    assert len({item["conversation_id"] for item in full}) == 64
    assert len({item["session_seed"] for item in full}) == 64
    assert len({"\n".join(turn["text"] for turn in item["turns"]) for item in full}) > 1


def test_generator_schema_contains_structured_turn_expectations():
    dialogues = generate_dialogues(24, seed=23)
    result = validate_dialogues(dialogues, expected_count=24)
    assert result["valid"], result["errors"]
    assert {item["schema_version"] for item in dialogues} == {SCHEMA_VERSION}
    assert {item["generator_version"] for item in dialogues} == {GENERATOR_VERSION}
    assert all(len(item["turns"]) >= 2 for item in dialogues)
    assert all("language_metadata" in item for item in dialogues)
    for dialogue in dialogues:
        for turn in dialogue["turns"]:
            expected = turn["expected"]
            assert set(expected) == {
                "expected_class", "expected_intent", "expected_slots", "expected_entities",
                "expected_reference", "expected_memory_action", "expected_tool", "expected_clarification",
            }


def test_generator_composes_required_variation_dimensions():
    dialogues = generate_dialogues(300, seed=41)
    dimensions = {name: any(item["generation_dimensions"][name] for item in dialogues) for name in ("typo", "noise", "correction", "topic_switch")}
    assert all(dimensions.values())
    modes = {item["language_metadata"]["mode"] for item in dialogues}
    assert {"en", "ar", "mixed", "ar_to_en", "en_to_ar"} <= modes
    dialects = {item["language_metadata"]["dialect"] for item in dialogues}
    assert {"neutral", "egyptian", "msa"} <= dialects


def test_generator_writes_jsonl_and_manifest(tmp_path: Path):
    dialogues = generate_dialogues(10, seed=DEFAULT_SEED)
    jsonl, manifest = write_dialogues(dialogues, tmp_path, seed=DEFAULT_SEED)
    lines = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert len(lines) == 10
    assert manifest_payload["count"] == 10
    assert manifest_payload["seed"] == DEFAULT_SEED
    assert manifest_payload["reproducibility"]["seeded"] is True


def test_generator_cli_is_runnable_from_repository_root(tmp_path: Path):
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "scripts/generate_dialogues.py", "--count", "3", "--seed", "77", "--output-dir", str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["valid"] is True
    assert payload["count"] == 3
    assert (tmp_path / "dialogues_phase10_seed_77.jsonl").exists()


def test_phase10_gate_generates_1000_independent_multiturn_sessions():
    dialogues = generate_dialogues(1000, seed=20261002)
    result = validate_dialogues(dialogues, expected_count=1000)
    assert result["valid"], result["errors"]
    assert result["unique_ids"] == 1000
    assert all(len(item["turns"]) >= 2 for item in dialogues)
    assert all(item["metadata"]["independent_session"] is True for item in dialogues)
    assert all(item["metadata"]["state_scope"] == "session-local" for item in dialogues)
    assert result["unique_transcripts"] >= 500
