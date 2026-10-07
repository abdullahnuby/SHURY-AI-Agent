from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path


class _Intent:
    name = "cross_department_data_move"
    confidence = 1.0


class _Semantic:
    needs_clarification = False
    canonical_goal = ""
    top_intent = _Intent()
    slots = {}
    entities = ()
    original = "cross"
    language = "en"
    speech_act = "command"
    required_information = ()
    ambiguity_reasons = ()

    def to_dict(self):
        return {"intent": self.top_intent.name, "operation": self.top_intent.name}


def _semantic_stub():
    return _Semantic()


def test_legacy_runtime_uses_company_qa_gate_and_returns_verified_result(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE", str(tmp_path))
    (tmp_path / "a.csv").write_text("id,total\n1,10\n2,20\n", encoding="utf-8")
    (tmp_path / "b.csv").write_text("id,total\n1,5\n2,7\n", encoding="utf-8")

    import app.runtime.agent as agent_mod
    import app.knowledge.memory as memory_mod
    memory_mod.configure(tmp_path / "memory.db")
    agent_mod.LOG_FILE = tmp_path / "agent.jsonl"
    monkeypatch.setattr(agent_mod, "semantic_understand", lambda *a, **kw: _semantic_stub())
    monkeypatch.setattr(agent_mod.SemanticContract, "from_parse", staticmethod(lambda parsed: SimpleNamespace(
        operation="cross_department_data_move", conversation_class="TASK", intent="cross_department_data_move",
        needs_clarification=False, canonical_goal="", target="workspace", capability="cross_department_data_move",
    )))
    monkeypatch.setattr(agent_mod, "compile_task_ir", lambda *a, **kw: None)
    monkeypatch.setattr(agent_mod, "understand", lambda text: SimpleNamespace(normalized=text, intents=[], entities=[], ambiguous=False))
    monkeypatch.setattr(agent_mod, "decide", lambda *a, **kw: SimpleNamespace(action="execute", confidence=1.0, reason="test", risk="low"))

    from app.domain.plan import Plan, PlanStep
    class FixedPlanner:
        def plan(self, goal, memory=None, world=None, task_ir=None, learning=None, registry=None):
            return Plan([
                PlanStep("s1", "list_files_recursive", {"path": ".", "exclude_path": "company_data_report.md"}, clause_text="recursive workspace", capability="workspace_recursive_inventory"),
                PlanStep("s2", "analyze_csv_collection", {"file_list": "{{s1}}", "question": goal}, depends_on=["s1"], clause_text="analyze csv", capability="cross_department_data_move"),
                PlanStep("s3", "move_workspace_file", {"analysis_result": "{{s2}}", "destination_dir": "processed_data"}, depends_on=["s2"], clause_text="move selected csv", capability="cross_department_data_move"),
                PlanStep("s4", "create_company_data_report", {"analysis_result": "{{s2}}", "move_result": "{{s3}}", "output_path": "company_data_report.md"}, depends_on=["s2", "s3"], clause_text="create company report", capability="cross_department_data_move"),
                PlanStep("s5", "read_file", {"path": "company_data_report.md"}, depends_on=["s4"], clause_text="read report", capability="file_read"),
            ])

    state = agent_mod.run_agent("cross department data workflow", planner=FixedPlanner(), approve=lambda _t, _a: True)
    assert state.status == "completed", state.final_message
    assert state.company_assignments
    assert state.company_review and state.company_review["ok"] is True
    assert "Operations نقله" in state.final_message
    assert (tmp_path / "processed_data").exists()
    assert list((tmp_path / "processed_data").glob("*.csv"))
