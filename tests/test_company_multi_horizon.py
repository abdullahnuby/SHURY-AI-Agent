from pathlib import Path
from tempfile import TemporaryDirectory

from app.brain import CognitiveKernel
from app.brain.models import GoalSpec, PlannedAction
from app.learning.store import LearningStore
from app.organization import DEFAULT_COMPANY, CompanyMemory
from app.organization.context import DepartmentExecutionContext
from app.organization.multi_horizon import CompanyPortfolioError, CompanyPortfolioManager, CompanyProjectTask


def make_manager(tmp: str):
    learning = LearningStore(Path(tmp) / "learning.db")
    memory = CompanyMemory(learning if False else None)  # canonical memory facade replaced below
    memory = CompanyMemory(company_id="test-company")
    return CompanyPortfolioManager(learning_store=learning, company_memory=memory, company_id="test-company")


def test_multiple_projects_are_persisted_and_isolated():
    with TemporaryDirectory() as td:
        mgr = make_manager(td)
        p1 = mgr.create_project("p1", "Alpha", "Analyze Alpha", priority=.9, horizon="short")
        p2 = mgr.create_project("p2", "Beta", "Analyze Beta", priority=.4, horizon="long")
        mgr.upsert_task(CompanyProjectTask("p1", "t1", "Alpha task", specialist="data:data-analyst"))
        mgr.upsert_task(CompanyProjectTask("p2", "t1", "Beta task", specialist="data:data-analyst"))
        assert [p.project_id for p in mgr.list_projects()] == ["p1", "p2"]
        assert mgr.list_tasks("p1")[0].objective == "Alpha task"
        assert mgr.list_tasks("p2")[0].objective == "Beta task"
        assert mgr.ready_tasks("p1")[0].project_id == "p1"


def test_project_priority_is_deterministic_and_reprioritizable():
    with TemporaryDirectory() as td:
        mgr = make_manager(td)
        mgr.create_project("low", "Low", "low", priority=.2, horizon="long")
        mgr.create_project("high", "High", "high", priority=.9, horizon="short")
        order = mgr.reprioritize()
        assert order[0]["project_id"] == "high"
        mgr.update_project("low", priority=1.0, criticality=1.0, horizon="immediate")
        order2 = mgr.reprioritize()
        assert order2[0]["project_id"] == "low"


def test_specialist_identity_is_stable_and_uses_persisted_delegation_history():
    with TemporaryDirectory() as td:
        mgr = make_manager(td)
        ident1 = mgr.specialist_identity("data:data-analyst", DEFAULT_COMPANY.registry)
        mgr.learning.record_company_delegation_outcome(
            capability="data_analysis", department="data", specialist="data:data-analyst",
            skill_key="builtin:data-analysis", tool="analyze_dataset", verified=True, run_id="r1"
        )
        ident2 = mgr.specialist_identity("data:data-analyst", DEFAULT_COMPANY.registry)
        mgr2 = CompanyPortfolioManager(learning_store=LearningStore(Path(td) / "learning.db"), company_memory=CompanyMemory(company_id="test-company"), company_id="test-company")
        ident3 = mgr2.specialist_identity("data:data-analyst", DEFAULT_COMPANY.registry)
        assert ident1.identity_key == ident2.identity_key == ident3.identity_key == "specialist:data:data-analyst"
        assert ident2.verified_successes == ident3.verified_successes == 1
        assert ident3.success_rate == 1.0


def test_project_context_never_crosses_project_boundary():
    c1 = DepartmentExecutionContext(
        context_id="company-context:p1:company:s1", company="SHURY Company", task_id="company:s1", step_id="s1",
        department="data", specialist="data:data-analyst", objective="Alpha", allowed_tool="analyze_dataset",
        allowed_capability="data_analysis", allowed_skill="builtin:data-analysis", project_id="p1", horizon="short"
    )
    assert c1.project_id == "p1"
    assert c1.to_dict()["project_id"] == "p1"
    assert "p2" not in c1.to_dict()["context_id"]


def test_company_memory_filters_by_project():
    with TemporaryDirectory() as td:
        # Use an actual canonical Memory instance backed by a temp database.
        from app.knowledge.memory import Memory
        memory_db = Path(td) / "memory.db"
        canonical = Memory(memory_db)
        cm = CompanyMemory(canonical, company_id="test-company")
        cm.remember_decision(decision_key="alpha", decision={"project": "alpha"}, evidence=["e1"], project_id="p1")
        cm.remember_decision(decision_key="beta", decision={"project": "beta"}, evidence=["e2"], project_id="p2")
        p1_hits = cm.recall("project", project_id="p1")
        assert p1_hits and all(h.metadata.get("project_id") == "p1" for h in p1_hits)
        p2_hits = cm.recall("project", project_id="p2")
        assert p2_hits and all(h.metadata.get("project_id") == "p2" for h in p2_hits)


def test_structured_goal_binds_existing_project_without_nlp():
    with TemporaryDirectory() as td:
        # Point the shared learning DB to a temp location for the duration of the test.
        import os
        old = os.environ.get("AGENT_LEARNING_DB")
        os.environ["AGENT_LEARNING_DB"] = str(Path(td) / "learning.db")
        try:
            mgr = DEFAULT_COMPANY.portfolio
            mgr.create_project("analysis-p", "Analysis", "Dataset analysis", priority=.8, horizon="short")
            kernel = CognitiveKernel()
            goal = GoalSpec(name="data_analysis", objective="Analyze the active dataset", required_capability="data_analysis", project_id="analysis-p", horizon="short")
            result = kernel.think_structured(goal, session_id="company-c14-project")
            assert result.state.company_project_id == "analysis-p"
            assert result.state.company_project_context["project_id"] == "analysis-p"
            assert all(a.get("project_id") == "analysis-p" for a in result.state.company_assignments)
        finally:
            if old is None:
                os.environ.pop("AGENT_LEARNING_DB", None)
            else:
                os.environ["AGENT_LEARNING_DB"] = old


def test_coordination_sync_and_status_are_project_scoped():
    with TemporaryDirectory() as td:
        mgr = make_manager(td)
        mgr.create_project("p1", "Alpha", "Alpha objective")
        coordination = {"tasks": [{"step_id": "s1", "objective": "Alpha task", "department": "data", "specialist": "data:data-analyst", "priority": .8}]}
        synced = mgr.sync_coordination("p1", coordination)
        assert synced and synced[0].project_id == "p1"
        assert mgr.ready_tasks("p1")[0].task_id == "s1"
        mgr.mark_task_status("p1", "s1", "completed")
        assert mgr.ready_tasks("p1") == ()
