import csv
from pathlib import Path

from app.knowledge.statistics.statistics_v13 import (autocorrelation, choose_confidence_interval_method, moving_block_bootstrap_ci)
from app.planning.adaptive_portfolio import select_trend_method, learned_ucb
from app.services.adaptive_analysis_service import adaptive_analyze
from app.knowledge.memory import Memory
from app.evaluation.versions.v13 import run_v13_benchmark


def _csv(path: Path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["x", "y"]); w.writerows(rows)


def test_v13_autocorrelation_and_block_selection():
    xs = list(range(30))
    assert autocorrelation(xs) > 0.9
    assert choose_confidence_interval_method(xs)["method"] == "moving_block_bootstrap"


def test_v13_block_bootstrap_reproducible():
    xs = list(range(20))
    a = moving_block_bootstrap_ci(xs, seed_text="same")
    b = moving_block_bootstrap_ci(xs, seed_text="same")
    assert a == b
    assert a["lower"] <= a["estimate"] <= a["upper"]


def test_v13_adaptive_trend_prefers_ols_on_clean_linear_data():
    choice = select_trend_method([1,2,3,4,5,6,7,8,9,10,11,12])
    assert choice.method == "ols"


def test_v13_adaptive_trend_prefers_theil_sen_on_outlier():
    choice = select_trend_method([1,2,3,4,100,6,7,8,9,10,11,12], 0.10)
    assert choice.method == "theil_sen"


def test_v13_learning_updates_posterior(tmp_path):
    m = Memory(tmp_path / "memory.db")
    choice = select_trend_method([1,2,3,4,5,6,7,8,9,10], memory=m)
    before = learned_ucb(m, choice.context, "ols")
    m.record_algorithm_observation(choice.context, "ols", 1.0, True)
    after = learned_ucb(m, choice.context, "ols")
    assert before["count"] == 0 and after["count"] == 1 and after["mean"] >= before["mean"]


def test_v13_adaptive_report_contains_selection(tmp_path):
    p = tmp_path / "d.csv"
    _csv(p, [[1,1],[2,4],[3,9],[4,16],[5,25],[6,36],[7,49],[8,64],[9,81],[10,100],[11,121],[12,144]])
    m = Memory(tmp_path / "memory.db")
    rep = adaptive_analyze(p, memory=m)
    assert rep["verified"]
    assert rep["adaptive_learning"]
    assert rep["methodology"][0]["trend_selection"]["method"] == "ols"


def test_v13_memory_snapshot(tmp_path):
    m = Memory(tmp_path / "memory.db")
    m.record_algorithm_observation("ctx", "ols", 0.8, True)
    snap = m.algorithm_portfolio_snapshot()
    assert snap[0]["method"] == "ols" and snap[0]["observations"] == 1


def test_v13_benchmark_green():
    out = run_v13_benchmark()
    assert out["passed"] == out["total"] == 7


def test_v13_diagnose_tool_persists_algorithm_experience(tmp_path):
    from app.knowledge.memory import configure
    from app.runtime.registry import load_tools
    configure(tmp_path / "memory.db")
    p = tmp_path / "d.csv"
    _csv(p, [[1,1],[2,4],[3,9],[4,16],[5,25],[6,36],[7,49],[8,64],[9,81],[10,100],[11,121],[12,144]])
    tool = load_tools()["diagnose_dataset"]
    result = tool.run(path=str(p))
    assert result.ok and result.data["verified"]
    assert result.data["adaptive_learning"]
    assert configure(tmp_path / "memory.db").algorithm_portfolio_snapshot()


def test_v13_agent_uses_adaptive_diagnosis_tool(tmp_path):
    from app.knowledge.memory import configure
    from app.runtime.agent import run_agent
    configure(tmp_path / "memory.db")
    p = tmp_path / "d.csv"
    _csv(p, [[1,1],[2,4],[3,9],[4,16],[5,25],[6,36],[7,49],[8,64],[9,81],[10,100],[11,121],[12,144]])
    state = run_agent(f"حلل البيانات بالكامل في {p}")
    assert state.status == "completed"
    assert state.plan.steps[0].tool == "diagnose_dataset"
    assert configure(tmp_path / "memory.db").algorithm_portfolio_snapshot()


def test_v13_runtime_exposes_algorithm_portfolio(tmp_path):
    from app.observability.agent_analytics import analyze_runtime
    m = Memory(tmp_path / "memory.db")
    m.record_algorithm_observation("ctx", "ols", 0.9, True)
    report = analyze_runtime(m)
    assert report["algorithm_portfolio"][0]["method"] == "ols"
