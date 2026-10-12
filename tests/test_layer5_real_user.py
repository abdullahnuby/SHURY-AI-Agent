from __future__ import annotations

import app.knowledge.memory as memory_mod
from app.brain import CognitiveKernel
from app.brain.learning import BrainExperienceStore
from app.brain.store import BrainStateStore
from app.learning.diagnosis import task_signature
from app.learning.manager import SelfImprovementManager
from app.runtime.cognitive_agent import run_cognitive
from app.runtime.registry import Tool


def _setup(tmp_path, monkeypatch):
    memory_mod.configure(tmp_path / "memory.db")
    monkeypatch.setenv("AGENT_LEARNING_DB", str(tmp_path / "learning.db"))
    monkeypatch.setenv("AGENT_SKILLS_DB", str(tmp_path / "skills.db"))
    monkeypatch.setenv("SHURY_NLP_MODE", "off")


def _kernel(tmp_path, *, calculator):
    registry = {
        "calculator": Tool(
            "calculator", "deterministic calculator", {"expression": "x"}, calculator,
            capability="calculate", produces=("calculation_completed",),
            match=lambda goal: "calculate" in str(goal).casefold(),
            build_args=lambda goal: {"expression": "2+2"},
            verification_level="standard",
        )
    }
    return CognitiveKernel(
        memory=memory_mod.get_memory(),
        registry=registry,
        state_store=BrainStateStore(tmp_path / "state.db"),
        experience_store=BrainExperienceStore(tmp_path / "learning.db"),
    )


def test_real_user_failure_then_success_creates_contrastive_lesson(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    goal = "calculate 2+2"

    def fail(expression):
        raise ValueError("forced failure")

    failed = run_cognitive(goal, kernel=_kernel(tmp_path, calculator=fail), max_steps=2)
    assert failed.status == "failed"

    succeeded = run_cognitive(goal, kernel=_kernel(tmp_path, calculator=lambda expression: 4), max_steps=2)
    assert succeeded.status == "completed"

    mgr = SelfImprovementManager()
    guidance = mgr.guidance(goal)
    assert any(x["kind"] == "contrastive" for x in guidance)
    assert mgr.status()["failed"] >= 1
    assert mgr.status()["completed"] >= 1


def test_successful_real_user_run_does_not_create_failure_reflection_lesson(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    goal = "calculate 2+2"
    succeeded = run_cognitive(goal, kernel=_kernel(tmp_path, calculator=lambda expression: 4), max_steps=2)
    assert succeeded.status == "completed"
    mgr = SelfImprovementManager()
    lessons = mgr.store.search_lessons(task_signature(goal), set(task_signature(goal).split()), limit=10)
    assert not any(x.kind == "reflection" and "failed" in x.lesson.lower() for x in lessons)
