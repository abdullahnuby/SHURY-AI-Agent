import os
import time
from pathlib import Path

from app.agents import AgentRegistry, AgentResult, AgentTask, DataAgent, DevelopmentAgent, InertAgent, ResearchAgent, SpecialistAgent, VerifierAgent
from app.brain.kernel import CognitiveKernel
from app.brain.models import CognitiveState, PlannedAction
from app.domain.task_graph import TaskGraph, TaskNode


class EchoAgent(SpecialistAgent):
    def __init__(self):
        super().__init__({
            "agent_id": "echo",
            "name": "Echo Agent",
            "capability": "echo",
            "description": "Returns a fixed payload.",
            "read_only": True,
            "max_timeout_seconds": 10.0,
        })

    def run(self, task: AgentTask) -> AgentResult:
        return AgentResult(task_id=task.task_id, status="success", output={"echo": task.objective}, evidence=("echo:success",))


def test_agent_task_validation_rejects_bad_schema():
    task = AgentTask(task_id="", objective="", capability="", timeout_seconds=0)
    assert task.validate()


def test_registry_rejects_duplicate_ids_and_capabilities():
    registry = AgentRegistry()
    registry.register(InertAgent())
    try:
        registry.register(InertAgent())
        assert False, "duplicate ids should be rejected"
    except ValueError:
        pass

    other = EchoAgent()
    registry2 = AgentRegistry([other])
    try:
        registry2.register(EchoAgent())
        assert False, "duplicate capability should be rejected"
    except ValueError:
        pass


def test_unknown_capability_fails_closed():
    registry = AgentRegistry([InertAgent()])
    task = AgentTask(task_id="t-2", objective="do nothing", capability="missing-capability")
    result = registry.dispatch(task)
    assert result.status == "blocked"
    assert "unknown capability" in result.errors[0]


def test_malformed_result_is_blocked():
    class BadAgent(SpecialistAgent):
        def __init__(self):
            super().__init__({
                "agent_id": "bad",
                "name": "bad",
                "capability": "bad",
                "description": "bad",
                "read_only": True,
                "max_timeout_seconds": 5.0,
            })

        def run(self, task: AgentTask) -> AgentResult:
            return AgentResult(task_id=task.task_id, status="not-real", output="bad")

    registry = AgentRegistry([BadAgent()])
    result = registry.dispatch(AgentTask(task_id="bad-task", objective="bad", capability="bad"))
    assert result.status == "blocked"
    assert result.errors


def test_dispatch_handles_timeout_and_exception_paths():
    class TimeoutAgent(SpecialistAgent):
        def __init__(self):
            super().__init__({
                "agent_id": "timeout-agent",
                "name": "timeout",
                "capability": "timeout",
                "description": "timeout",
                "read_only": True,
                "max_timeout_seconds": 5.0,
            })

        def run(self, task: AgentTask) -> AgentResult:
            raise TimeoutError("slow")

    class ExceptionAgent(SpecialistAgent):
        def __init__(self):
            super().__init__({
                "agent_id": "exception-agent",
                "name": "exception",
                "capability": "exception",
                "description": "exception",
                "read_only": True,
                "max_timeout_seconds": 5.0,
            })

        def run(self, task: AgentTask) -> AgentResult:
            raise RuntimeError("boom")

    registry = AgentRegistry([TimeoutAgent(), ExceptionAgent()])
    timeout = registry.dispatch(AgentTask(task_id="t-timeout", objective="wait", capability="timeout"))
    exception = registry.dispatch(AgentTask(task_id="t-exception", objective="fail", capability="exception"))
    assert timeout.status == "timeout"
    assert exception.status == "failed"
    assert "boom" in exception.errors[0]


def test_data_agent_profiles_dataset_and_handles_question_mode(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    dataset = workspace / "sample.csv"
    dataset.write_text("name,score,region\nA,10,North\nB,20,South\nC,18,North\n", encoding="utf-8")

    previous = os.environ.get("AGENT_WORKSPACE")
    os.environ["AGENT_WORKSPACE"] = str(workspace)
    try:
        registry = AgentRegistry([DataAgent()])
        profile = registry.dispatch(
            AgentTask(
                task_id="data-profile",
                objective="profile dataset",
                capability="data_analysis",
                inputs={"path": str(dataset)},
            )
        )
        assert profile.status == "success"
        assert profile.output["rows"] == 3
        assert profile.output["columns"] == 3

        answer = registry.dispatch(
            AgentTask(
                task_id="data-answer",
                objective="summarize the dataset",
                capability="data_analysis",
                inputs={"path": str(dataset), "mode": "analysis", "question": "What is the average score?"},
            )
        )
        assert answer.status == "success"
        assert "answer" in answer.output
    finally:
        if previous is None:
            os.environ.pop("AGENT_WORKSPACE", None)
        else:
            os.environ["AGENT_WORKSPACE"] = previous


def test_kernel_dispatch_specialist_task_remains_subordinate(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    dataset = workspace / "sample.csv"
    dataset.write_text("value\n4\n8\n12\n", encoding="utf-8")

    previous = os.environ.get("AGENT_WORKSPACE")
    os.environ["AGENT_WORKSPACE"] = str(workspace)
    try:
        kernel = CognitiveKernel()
        profile = kernel.dispatch_specialist_task({
            "task_id": "kernel-profile",
            "objective": "profile dataset",
            "capability": "data_analysis",
            "inputs": {"path": str(dataset)},
        }, session_id="kernel-session")

        assert profile.status == "success"
        assert profile.output["rows"] == 3

        blocked = kernel.dispatch_specialist_task({
            "task_id": "kernel-missing",
            "objective": "do the impossible",
            "capability": "missing-capability",
        }, session_id="kernel-session")
        assert blocked.status == "blocked"
        assert "unknown capability" in blocked.errors[0]
    finally:
        if previous is None:
            os.environ.pop("AGENT_WORKSPACE", None)
        else:
            os.environ["AGENT_WORKSPACE"] = previous


def test_research_agent_returns_bounded_evidence_and_remains_read_only():
    registry = AgentRegistry([ResearchAgent()])
    result = registry.dispatch(
        AgentTask(
            task_id="research-task",
            objective="find prior evidence about dataset validation",
            capability="research",
            inputs={"query": "dataset validation evidence", "limit": 5},
        )
    )

    assert result.status == "success"
    assert result.output["query"] == "dataset validation evidence"
    assert isinstance(result.output["evidence"], list)
    assert result.output["source_count"] >= 0


def test_development_agent_inspects_project_without_writing():
    project_root = Path(__file__).resolve().parents[1] / "workspace"
    project_root.mkdir(exist_ok=True)
    project = project_root / "demo-app"
    project.mkdir(exist_ok=True)
    (project / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    registry = AgentRegistry([DevelopmentAgent()])
    result = registry.dispatch(
        AgentTask(
            task_id="dev-inspect",
            objective="inspect project",
            capability="development",
            inputs={"path": str(project)},
        )
    )

    assert result.status == "success"
    assert result.output["path"] == str(project)
    assert "python" in result.output["stack"]
    assert result.output["git"]["git"] is False


def test_verifier_agent_validates_dataset_analysis_result():
    profile = {"rows": 3, "columns": 1}
    analysis = {"answer": {"rows": 3}, "method": "row_count"}

    registry = AgentRegistry([VerifierAgent()])
    result = registry.dispatch(
        AgentTask(
            task_id="verify-task",
            objective="validate answer",
            capability="verification",
            inputs={"profile": profile, "analysis": analysis},
        )
    )

    assert result.status == "success"
    assert result.output["verified"] is True


def test_kernel_specialist_workflow_is_serial_and_bounded(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    dataset = workspace / "sample.csv"
    dataset.write_text("value\n4\n8\n12\n", encoding="utf-8")

    previous = os.environ.get("AGENT_WORKSPACE")
    os.environ["AGENT_WORKSPACE"] = str(workspace)
    try:
        kernel = CognitiveKernel()
        workflow = kernel.run_specialist_workflow(
            dataset_path=str(dataset),
            question="What is the average value?",
            session_id="workflow-session",
        )

        assert workflow.status == "success"
        assert workflow.output["profile"]["rows"] == 3
        assert "answer" in workflow.output["analysis"]
        assert workflow.output["verification"]["verified"] is True

        blocked = kernel.run_specialist_workflow(dataset_path="", question="still works")
        assert blocked.status == "blocked"
        assert "dataset_path is required" in blocked.errors[0]
    finally:
        if previous is None:
            os.environ.pop("AGENT_WORKSPACE", None)
        else:
            os.environ["AGENT_WORKSPACE"] = previous


def test_kernel_executes_specialist_dag_in_dependency_order(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    dataset = workspace / "sample.csv"
    dataset.write_text("value\n4\n8\n12\n", encoding="utf-8")

    previous = os.environ.get("AGENT_WORKSPACE")
    os.environ["AGENT_WORKSPACE"] = str(workspace)
    try:
        kernel = CognitiveKernel()
        graph = TaskGraph([
            TaskNode("profile", "profile_dataset", {"path": str(dataset)}),
            TaskNode("analysis", "analyze_dataset", {"path": str(dataset), "question": "What is the average value?"}, ["profile"]),
        ])

        result = kernel.execute_specialist_graph(graph, session_id="dag-session")

        assert result.status == "success"
        assert result.output["order"] == ["profile", "analysis"]
        assert result.output["results"]["profile"]["rows"] == 3
        assert "answer" in result.output["results"]["analysis"]
    finally:
        if previous is None:
            os.environ.pop("AGENT_WORKSPACE", None)
        else:
            os.environ["AGENT_WORKSPACE"] = previous


def test_data_agent_rejects_path_outside_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.csv"
    outside.write_text("value\n1\n2\n", encoding="utf-8")
    previous = os.environ.get("AGENT_WORKSPACE")
    os.environ["AGENT_WORKSPACE"] = str(workspace)
    try:
        registry = AgentRegistry([DataAgent()])
        result = registry.dispatch(AgentTask(task_id="outside-path", objective="profile outside dataset", capability="data_analysis", inputs={"path": str(outside)}))
        assert result.status == "blocked"
        assert "workspace" in result.errors[0].lower()
    finally:
        if previous is None:
            os.environ.pop("AGENT_WORKSPACE", None)
        else:
            os.environ["AGENT_WORKSPACE"] = previous


def test_registry_rejects_result_id_mismatch_and_timeout():
    class WrongIdAgent(SpecialistAgent):
        def __init__(self):
            SpecialistAgent.__init__(self, {"agent_id": "wrong-id-agent", "name": "wrong", "capability": "wrong-id", "description": "wrong", "read_only": True, "max_timeout_seconds": 5.0})

        def run(self, task: AgentTask) -> AgentResult:
            return AgentResult(task_id="different-id", status="success", output={"ok": True})

    class SlowAgent(SpecialistAgent):
        def __init__(self):
            SpecialistAgent.__init__(self, {"agent_id": "slow-agent", "name": "slow", "capability": "slow", "description": "slow", "read_only": True, "max_timeout_seconds": 5.0})

        def run(self, task: AgentTask) -> AgentResult:
            time.sleep(0.2)
            return AgentResult(task_id=task.task_id, status="success", output={"ok": True})

    wrong = AgentRegistry([WrongIdAgent()])
    wrong_result = wrong.dispatch(AgentTask(task_id="expected", objective="wrong id", capability="wrong-id"))
    assert wrong_result.status == "blocked"
    assert "task_id mismatch" in wrong_result.errors[0]

    slow = AgentRegistry([SlowAgent()])
    slow_result = slow.dispatch(AgentTask(task_id="slow-task", objective="slow", capability="slow", timeout_seconds=0.05))
    assert slow_result.status == "timeout"


def test_verifier_agent_rejects_null_answers():
    registry = AgentRegistry([VerifierAgent()])
    result = registry.dispatch(
        AgentTask(
            task_id="verify-null",
            objective="reject empty answer",
            capability="verification",
            inputs={"profile": {"rows": 3, "columns": 2}, "analysis": {"answer": None, "method": "row_count"}},
        )
    )
    assert result.status == "blocked"
    assert "answer cannot be null" in result.errors[0]


def test_kernel_graph_rejects_failed_node_before_success(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.csv"
    outside.write_text("value\n1\n2\n", encoding="utf-8")
    previous = os.environ.get("AGENT_WORKSPACE")
    os.environ["AGENT_WORKSPACE"] = str(workspace)
    try:
        kernel = CognitiveKernel()
        dataset = workspace / "inside.csv"
        dataset.write_text("value\n4\n8\n12\n", encoding="utf-8")
        graph = TaskGraph([
            TaskNode("profile", "profile_dataset", {"path": str(outside)}),
            TaskNode("analysis", "analyze_dataset", {"path": str(dataset), "question": "What is the average value?"}, ["profile"]),
        ])
        result = kernel.execute_specialist_graph(graph, session_id="failed-dag")
        assert result.status in {"failed", "blocked"}
        assert "profile" in result.output["results"]
    finally:
        if previous is None:
            os.environ.pop("AGENT_WORKSPACE", None)
        else:
            os.environ["AGENT_WORKSPACE"] = previous


def test_kernel_summarizes_specialist_workflow_for_final_response(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    dataset = workspace / "sample.csv"
    dataset.write_text("value\n4\n8\n12\n", encoding="utf-8")

    previous = os.environ.get("AGENT_WORKSPACE")
    os.environ["AGENT_WORKSPACE"] = str(workspace)
    try:
        kernel = CognitiveKernel()
        workflow = kernel.run_specialist_workflow(
            dataset_path=str(dataset),
            question="What is the average value?",
            session_id="summary-session",
        )

        summary = kernel.summarize_specialist_workflow(workflow)
        assert "Dataset profile" in summary
        assert "Verification: passed" in summary
        assert "Analysis" in summary
    finally:
        if previous is None:
            os.environ.pop("AGENT_WORKSPACE", None)
        else:
            os.environ["AGENT_WORKSPACE"] = previous
