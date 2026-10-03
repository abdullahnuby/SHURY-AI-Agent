import csv
from pathlib import Path

from app.knowledge.memory import configure
from app.runtime.agent import run_agent
from app.knowledge.data_analysis import profile_dataset, answer_question, compare_datasets
from app.observability.agent_analytics import analyze_runtime
from app.knowledge.memory import Memory
from app.runtime.registry import load_tools


def _csv(path: Path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "value", "group", "date"])
        w.writerows(rows)


def test_profile_infers_types_and_quality(tmp_path):
    p = tmp_path / "a.csv"
    _csv(p, [["a",1,"x","2026-01-01"],["b",2,"x","2026-01-02"],["c",3,"y","2026-01-03"],["d",100,"y","2026-01-04"],["",5,"y","2026-01-05"]])
    prof = profile_dataset(p)
    kinds = {c.name:c.inferred_type for c in prof.column_profiles}
    assert prof.rows == 5 and kinds["value"] == "numeric" and kinds["date"] == "datetime"
    assert prof.duplicate_rows == 0 and prof.quality_score < 100 and prof.warnings


def test_robust_outlier_and_correlation(tmp_path):
    p = tmp_path / "a.csv"
    _csv(p, [["a",1,"x","2026-01-01"],["b",2,"x","2026-01-02"],["c",3,"y","2026-01-03"],["d",100,"y","2026-01-04"],["e",5,"y","2026-01-05"]])
    out = answer_question(p, "اكتشف الشذوذ في value")
    assert out["answer"]["outliers"] >= 1 and out["method"] == "tukey_iqr_with_mad"


def test_aggregation_is_exact_and_evidence_fingerprinted(tmp_path):
    p = tmp_path / "a.csv"
    _csv(p, [["a",1,"x","2026-01-01"],["b",2,"x","2026-01-02"],["c",3,"y","2026-01-03"],["d",4,"y","2026-01-04"]])
    out = answer_question(p, "ما متوسط value؟")
    assert out["answer"]["value"] == 2.5
    assert len(out["fingerprint"]) == 64 and out["method"] == "deterministic_scalar_aggregation"


def test_compare_detects_schema_and_distribution_change(tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    _csv(a, [["a",1,"x","2026-01-01"],["b",2,"x","2026-01-02"],["c",3,"y","2026-01-03"]])
    _csv(b, [["a",2,"x","2026-01-01"],["b",4,"z","2026-01-02"],["c",6,"z","2026-01-03"]])
    report = compare_datasets(a, b)
    assert "z" in report["columns"]["group"]["new_categories"]
    assert report["columns"]["value"]["mean_relative_change"] > 0


def test_data_capability_dispatch_does_not_confuse_profile_with_question(tmp_path):
    configure(tmp_path / "m.db")
    p = tmp_path / "a.csv"
    _csv(p, [["a",1,"x","2026-01-01"],["b",3,"x","2026-01-02"]])
    state = run_agent(f"حلل {p} عن متوسط value")
    assert state.status == "completed"
    assert state.plan.steps[0].tool == "analyze_dataset"
    assert state.plan.steps[0].output["answer"]["value"] == 2.0


def test_runtime_analytics_empty_state_is_well_formed(tmp_path):
    m = Memory(tmp_path / "m.db")
    report = analyze_runtime(m)
    assert report["runs"] == 0 and report["effects"] == 0 and report["alerts"] == []


def test_data_tools_are_discoverable():
    tools = load_tools()
    assert {"profile_dataset", "analyze_dataset", "analyze_runtime"} <= set(tools)


def test_compare_reports_psi_drift(tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    _csv(a, [[str(i),1,"x","2026-01-01"] for i in range(20)])
    _csv(b, [[str(i),100,"x","2026-01-01"] for i in range(20)])
    report = compare_datasets(a, b)
    assert report["columns"]["value"]["psi"] is not None
    assert report["columns"]["value"]["drift_alert"] is True


def test_runtime_analytics_exposes_ewma_and_cusum(tmp_path):
    m = Memory(tmp_path / "m.db")
    report = analyze_runtime(m)
    assert report["recent_outcome_ewma"] is None
    assert report["negative_cusum"] == 0.0


def test_rank_findings_prioritizes_material_issues(tmp_path):
    p = tmp_path / "a.csv"
    _csv(p, [["a",1,"x","2026-01-01"],["b",2,"x","2026-01-02"],["c",3,"y","2026-01-03"],["d",100,"y","2026-01-04"],["e",5,"y","2026-01-05"]])
    profile = profile_dataset(p)
    findings = __import__('app.knowledge.data_analysis', fromlist=['rank_findings']).rank_findings(profile)
    assert findings and any(f['type'] == 'outliers' for f in findings)


def test_trend_and_group_analysis(tmp_path):
    p = tmp_path / "a.csv"
    _csv(p, [["a",1,"x","2026-01-01"],["b",2,"x","2026-01-02"],["c",3,"y","2026-01-03"],["d",4,"y","2026-01-04"]])
    tr = answer_question(p, "ما اتجاه value؟")
    assert tr['method'] == 'ordinary_least_squares_trend' and tr['answer']['slope'] > 0
    gr = answer_question(p, "متوسط value حسب group")
    assert gr['method'] == 'deterministic_group_aggregation'
    assert {x['group'] for x in gr['answer']['groups']} == {'x','y'}
