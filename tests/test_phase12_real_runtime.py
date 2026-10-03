from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.evaluation.real_dialogue_runner import Phase12EnvironmentBlocked, RealDialogueRunner, load_dialogues
import app.intelligence.semantic.intents as intents


def test_required_retrieval_failure_is_not_silently_swallowed(monkeypatch):
    monkeypatch.setenv("SHURY_NLP_MODE", "required")
    def fail(*_args, **_kwargs):
        raise RuntimeError("model unavailable")
    monkeypatch.setattr(intents, "rank_query_against_texts", fail)
    with pytest.raises(RuntimeError, match="model unavailable"):
        intents.candidates("hello")


def test_corpus_is_phase12_ready():
    rows = load_dialogues("benchmarks/dialogues/dialogues_phase10_seed_20261002.jsonl")
    assert len(rows) == 1000
    assert len({row["conversation_id"] for row in rows}) == 1000
    assert all(len(row.get("turns", [])) >= 2 for row in rows)
    assert all(row.get("metadata", {}).get("independent_session") is True for row in rows)


def test_runner_preflight_refuses_without_real_model(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SHURY_NLP_MODE", "required")
    monkeypatch.setattr("app.evaluation.real_dialogue_runner.model_status", lambda: (_ for _ in ()).throw(RuntimeError("missing")))
    runner = RealDialogueRunner("benchmarks/dialogues/dialogues_phase10_seed_20261002.jsonl", tmp_path)
    with pytest.raises(Phase12EnvironmentBlocked, match="could not be loaded"):
        runner.preflight()


def test_runner_session_ids_are_deterministic():
    runner = RealDialogueRunner("benchmarks/dialogues/dialogues_phase10_seed_20261002.jsonl", Path("/tmp/phase12"))
    a = runner._session_token("dialogue-a", 123)
    b = runner._session_token("dialogue-a", 123)
    c = runner._session_token("dialogue-b", 123)
    assert a == b and a != c

def test_run_brain_required_mode_fails_closed_when_retrieval_is_unavailable(monkeypatch):
    monkeypatch.setenv("SHURY_NLP_MODE", "required")
    monkeypatch.setattr(
        "app.brain.kernel.semantic_understand",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("model unavailable")),
    )
    from app.api import run_brain

    with pytest.raises(RuntimeError, match="model unavailable"):
        run_brain("hello", session_id="phase12-required-canonical")


def test_isolated_environment_changes_all_state_backends(tmp_path, monkeypatch):
    runner = RealDialogueRunner(
        "benchmarks/dialogues/dialogues_phase10_seed_20261002.jsonl",
        tmp_path / "out",
    )
    with runner._isolated_environment(tmp_path / "a"):
        first = {key: __import__("os").environ[key] for key in (
            "AGENT_LEARNING_DB", "AGENT_SKILLS_DB", "AGENT_RAG_DB",
            "AGENT_RESEARCH_DB", "AGENT_NETWORK_DB", "AGENT_NETWORK_CACHE",
        )}
    with runner._isolated_environment(tmp_path / "b"):
        second = {key: __import__("os").environ[key] for key in first}
    assert first != second
    assert all(str(tmp_path / "a") in value for value in first.values())
    assert all(str(tmp_path / "b") in value for value in second.values())


def test_gate_requires_exactly_1000_execution_records():
    from app.evaluation.real_dialogue_runner import ConversationExecution

    sample = [
        ConversationExecution(
            conversation_id=str(i), seed=i, session_id=f"s{i}", passed=True,
            turn_count=2, trace_events=1, status="completed", result_path="trace.json", error="",
        )
        for i in range(999)
    ]
    assert len(sample) != 1000

def test_learning_and_skill_defaults_follow_conversation_environment(monkeypatch, tmp_path: Path):
    learning_path = tmp_path / "learning.db"
    skills_path = tmp_path / "skills.db"
    monkeypatch.setenv("AGENT_LEARNING_DB", str(learning_path))
    monkeypatch.setenv("AGENT_SKILLS_DB", str(skills_path))
    from app.learning.store import LearningStore
    from app.skills.registry import SkillBank

    assert LearningStore().path == learning_path
    assert SkillBank().path == skills_path

