import app.knowledge.memory as memory_mod
import app.runtime.agent as agent_mod
from app.evaluation import EvaluationLab, EvalScenario, ExpectedOutcome


def test_lab_scores_real_agent_trajectory_and_writes_report(tmp_path, monkeypatch):
    memory_mod.configure(tmp_path / "memory.db")
    agent_mod.LOG_FILE = tmp_path / "agent.jsonl"
    monkeypatch.setenv("SHURY_NLP_MODE", "off")
    scenario = EvalScenario("x", "calc", "calculate 17*6", expected=ExpectedOutcome(required_tools=("calculator",), final_contains=("102",), max_steps=2))
    report = EvaluationLab(output_dir=tmp_path / "evals").run([scenario])
    assert report.pass_count == 1
    assert report.pass_rate == 1.0
    assert list((tmp_path / "evals").glob("*.json"))


def test_regression_gate_blocks_score_drop():
    baseline = {"scenario_results": [{"scenario_id": "x", "mean_score": 0.95, "pass_rate": 1.0}], "safety_violations": 0, "pass_rate": 1.0, "mean_score": 0.95}
    candidate = {"scenario_results": [{"scenario_id": "x", "mean_score": 0.85, "pass_rate": 0.9}], "safety_violations": 0, "pass_rate": 0.9, "mean_score": 0.85}
    result = EvaluationLab().compare(baseline, candidate, max_regression=0.03)
    assert result["blocked"] is True
