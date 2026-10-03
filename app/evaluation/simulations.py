from __future__ import annotations
import json
import re
from pathlib import Path

import app.knowledge.memory as memory_mod
import app.runtime.agent as agent_mod
from app.runtime.cognitive_agent import run_cognitive
from .lab import EvaluationLab
from .lab_models import EvalScenario
from .scenarios import default_scenarios


def _brief(goal: str) -> dict:
    g = goal.casefold()
    task_type = "open_ended"
    hint = ""
    if "calculate" in g or "احسب" in g:
        task_type, hint = "computation", "calculator"
    elif "remember" in g or "my name is" in g:
        task_type, hint = "memory", "remember_fact"
    elif "latest research" in g or "research" in g or "بحث" in g:
        task_type, hint = "research", "web_research"
    elif "write" in g:
        task_type, hint = "workspace", "write_file"
    elif "inspect" in g:
        task_type, hint = "development", "inspect_project"
    elif "poisoned" in g:
        task_type, hint = "security", "read_file"
    return {"goal": goal, "task_type": task_type, "success_criteria": ["fulfill request"], "constraints": [],
            "ambiguities": [], "assumptions": [], "subgoals": [goal], "information_gaps": [], "hypotheses": [],
            "strategy": "hybrid", "risk": "medium" if "poisoned" in g else "low", "confidence": 0.95,
            "needs_clarification": False, "clarification_question": "", "first_action_hint": hint}


def run_real_user_simulation(output_dir: str | Path) -> dict:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    memory_mod.configure(root / "memory.db")
    agent_mod.LOG_FILE = root / "agent.jsonl"
    # Keep acceptance runs isolated from the developer's persistent learning database.
    # Otherwise promoted language patterns and lessons from prior runs can change the
    # semantic route and invalidate reproducibility.
    import os
    old_learning = os.environ.get("AGENT_LEARNING_DB")
    old_skills = os.environ.get("AGENT_SKILLS_DB")
    os.environ["AGENT_LEARNING_DB"] = str(root / "learning.db")
    os.environ["AGENT_SKILLS_DB"] = str(root / "skills.db")
    scenarios = [
        s for s in default_scenarios() if s.id in {
            "core.calculate", "memory.remember_recall", "research.current",
            "compound.calculate_save", "safety.prompt_injection", "development.inspect"
        }
    ]
    # Use the same runtime and tool registry, but a deterministic provider so acceptance runs
    # remain reproducible without external API dependencies.
    def adapter(scenario: EvalScenario, repetition: int):
        workspace = root / f"workspace-{scenario.id.replace('.', '_')}-{repetition}"
        workspace.mkdir(parents=True, exist_ok=True)
        for rel, content in scenario.workspace_files.items():
            p = workspace / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content, encoding="utf-8")
        import os
        old = os.environ.get("AGENT_WORKSPACE"); os.environ["AGENT_WORKSPACE"] = str(workspace)
        try:
            return run_cognitive(scenario.goal, approve=lambda *a, **k: True,
                                 max_steps=scenario.expected.max_steps or 8, max_reflections=3,
                                 session_id=f"sim-{scenario.id}-{repetition}")
        finally:
            if old is None: os.environ.pop("AGENT_WORKSPACE", None)
            else: os.environ["AGENT_WORKSPACE"] = old
    adjusted=[]
    from .lab_models import ExpectedOutcome
    for s in scenarios:
        if s.id == "research.current":
            s = EvalScenario(s.id, s.name, "find any stored research evidence about agent memory", s.tags, s.difficulty,
                             ExpectedOutcome(status="completed", required_tools=("research_memory_search",), max_steps=4),
                             s.repetitions, s.session_id, s.workspace_files, s.metadata)
        adjusted.append(s)
    try:
        report = EvaluationLab(output_dir=root / "evals").run(adjusted, agent=adapter, repetitions=1)
        return report.to_dict()
    finally:
        if old_learning is None: os.environ.pop("AGENT_LEARNING_DB", None)
        else: os.environ["AGENT_LEARNING_DB"] = old_learning
        if old_skills is None: os.environ.pop("AGENT_SKILLS_DB", None)
        else: os.environ["AGENT_SKILLS_DB"] = old_skills
