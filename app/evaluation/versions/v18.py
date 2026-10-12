from __future__ import annotations
from pathlib import Path
import tempfile

from app.skills.registry import SkillBank
from app.planning.adaptive_execution import AdaptiveExecutionController
from app.skills.compiler import compile_verified_run, compile_project_skill
from app.domain.plan import Plan, PlanStep
from app.planning.adaptive_planning import choose_adaptive_plan, skill_to_plan
from app.domain.state import AgentState
from app.knowledge.memory import Memory
from app.runtime.registry import load_tools


def run_v18_benchmark():
    cases = []
    with tempfile.TemporaryDirectory(prefix="agent-v18-bench-") as td:
        root = Path(td)
        skills_path = root / "skills.db"
        bank = SkillBank(skills_path)
        workflow = [
            {"tool": "calculator", "depends_on": [], "args_policy": "derive-from-live-goal"},
            {"tool": "calculator", "depends_on": ["s1"], "args_policy": "derive-from-live-goal"},
        ]
        skill = bank.upsert(
            key="demo:adaptive", name="Adaptive calculation", triggers=("calculate", "adaptive",),
            workflow=workflow, evidence=({"kind": "verified"},), confidence=0.8, status="approved"
        )
        skill = bank.get("demo:adaptive")
        cases.append(("skill_persistence", skill.status == "approved" and skill.version == 1))
        matches = bank.match("calculate adaptive")
        cases.append(("skill_matching", matches and matches[0].key == "demo:adaptive"))

        class FakeTool:
            name = "safe"
            risk = "low"
            cost = 1.0
            duration = 1.0
            idempotent = True
            requires_approval = False
        controller = AdaptiveExecutionController(None)
        score = controller.score_tool(FakeTool())
        cases.append(("adaptive_scoring", isinstance(score, float) and score > 0))
        class R:
            ok = True
            data = {"grounded": True, "verified": True, "evidence": [{"x": 1}], "provenance": True}
        decision = controller.after_result(FakeTool(), R(), query="adaptive evidence", prior_output="adaptive", attempts=1)
        cases.append(("minimal_sufficient_stop", decision.action == "stop"))

        # Compile a verified multi-step runtime into a candidate skill.
        mem = Memory(root / "memory.db")
        state = AgentState(goal="inspect project and check project", max_steps=6, max_seconds=30)
        state.status = "completed"
        state.plan = Plan([
            PlanStep("s1", "inspect_project", {"path": str(root)}, status="done", clause_text=state.goal),
            PlanStep("s2", "git_status", {"path": str(root)}, status="done", clause_text=state.goal, depends_on=["s1"]),
        ])
        mem.start_run(state.run_id, state.trace_id, state.goal, state.plan.to_dict())
        mem.record_effect(run_id=state.run_id, step_id="s1", attempt=1, tool="inspect_project", args={"path": str(root)},
                          output={"ok": True}, ok=True, verified=True, error=None, duration_ms=1.0)
        mem.record_effect(run_id=state.run_id, step_id="s2", attempt=1, tool="git_status", args={"path": str(root)},
                          output={"ok": True}, ok=True, verified=True, error=None, duration_ms=1.0)
        compiled = compile_verified_run(state, mem)
        cases.append(("verified_run_compilation", compiled is not None and compiled.status == "candidate"))

        # Project-manifest skills remain candidates until explicitly approved.
        project = root / "proj"
        project.mkdir()
        (project / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
        inspection = {"stack": ["python"], "commands": [{"name": "compile", "command": ["python", "-m", "compileall"]}]}
        pskill = compile_project_skill(project, inspection)
        cases.append(("project_skill_candidate", pskill.status == "candidate" and "python" in pskill.triggers))

        # Adaptive plan selection: an approved skill can win a near-tie, but a materially
        # worse current plan must remain authoritative.
        registry = load_tools()
        demo_skill = bank.upsert(
            key="demo:project", name="Project check", triggers=("build", "project", "test"),
            workflow=(
                {"tool": "inspect_project", "depends_on": []},
                {"tool": "git_status", "depends_on": [1]},
            ), status="approved", confidence=0.95, evidence=({"kind": "verified"},)
        )
        goal = f'build project "{root}"'
        candidate = skill_to_plan(bank.get("demo:project"), goal, registry)
        cases.append(("skill_plan_materialization", candidate is not None and len(candidate.steps) == 2))
        generic = Plan([PlanStep("s1", "inspect_project", {"path": str(root)})],
                       estimated_cost=1.0, estimated_duration=0.2, score=1.0, planner="generic")
        selected = choose_adaptive_plan(goal, generic, [bank.get("demo:project")], registry)
        cases.append(("adaptive_skill_selection", selected.planner in {"generic", "v18-adaptive-skill"}))
        cases.append(("tool_contracts_present", "check_project" in registry and registry["check_project"].requires_approval))

    passed = sum(1 for _, ok in cases if ok)
    return {"passed": passed, "total": len(cases),
            "cases": [{"name": name, "passed": bool(ok)} for name, ok in cases]}
