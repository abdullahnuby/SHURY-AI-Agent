import csv
from pathlib import Path
from app.knowledge.data_analysis import answer_question
from app.knowledge.statistics.statistics_v12 import bootstrap_ci, theil_sen, robust_z_scores, mutual_information, page_hinkley
from app.services.data_analysis_service import comprehensive_analysis
from app.evaluation.versions.v12 import run_v12_benchmark


def _csv(path: Path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(["x","group"]); w.writerows(rows)


def test_v12_bootstrap_is_reproducible():
    a=bootstrap_ci([1,2,3,4,5], seed_text="same")
    b=bootstrap_ci([1,2,3,4,5], seed_text="same")
    assert a == b and a["lower"] <= a["estimate"] <= a["upper"]


def test_v12_theil_sen_resists_outlier():
    out=theil_sen([1,2,100,4,5])
    assert abs(out["slope"]-1.0) < 1e-9


def test_v12_robust_z_and_mi():
    z=robust_z_scores([1,2,3,4,100])
    assert max(z) > 5
    assert mutual_information(["a","a","b","b"],["x","x","y","y"]) > 0


def test_v12_page_hinkley_detects_shift():
    out=page_hinkley([0.0]*10+[2.0]*10, threshold=1.0)
    assert out["change"]


def test_v12_answer_question_confidence_interval(tmp_path):
    p=tmp_path/"a.csv"; _csv(p, [[1,"a"],[2,"a"],[3,"b"],[4,"b"],[5,"b"]])
    out=answer_question(p,"احسب فاصل ثقة المتوسط x")
    assert out["answer"]["mean_ci95"]["lower"] <= 3.0 <= out["answer"]["mean_ci95"]["upper"]


def test_v12_answer_question_uses_robust_trend(tmp_path):
    p=tmp_path/"a.csv"; _csv(p, [[1,"a"],[2,"a"],[100,"a"],[4,"b"],[5,"b"],[6,"b"],[7,"b"],[8,"b"]])
    out=answer_question(p,"ما اتجاه x؟")
    assert out["method"] == "theil_sen_robust_trend"


def test_v12_comprehensive_contains_methodology(tmp_path):
    p=tmp_path/"a.csv"; _csv(p, [[1,"a"],[2,"a"],[3,"a"],[4,"b"],[100,"b"],[6,"b"],[7,"b"],[8,"b"]])
    out=comprehensive_analysis(p)
    assert out["verified"] and out["methodology"] and out["quality"]["ranked_findings"]


def test_v12_benchmark_green():
    out=run_v12_benchmark()
    assert out["passed"] == out["total"] == 5


def test_v12_agent_routes_comprehensive_goal_to_diagnose(tmp_path):
    from app.knowledge.memory import configure
    from app.runtime.agent import run_agent
    p=tmp_path/"d.csv"; _csv(p, [[1,"a"],[2,"a"],[3,"b"],[4,"b"],[100,"b"],[6,"b"],[7,"b"],[8,"b"]])
    configure(tmp_path/"agent.db")
    state=run_agent(f"حلل البيانات بالكامل في {p}")
    assert state.status == "completed"
    assert state.plan.steps[0].tool == "diagnose_dataset"
    assert state.plan.steps[0].output["verified"] is True


def test_v12_verification_certificate_is_real(tmp_path):
    p=tmp_path/"d.csv"; _csv(p, [[1,"a"],[2,"a"],[3,"b"],[4,"b"],[5,"b"],[6,"b"],[7,"b"],[8,"b"]])
    out=comprehensive_analysis(p)
    assert out["verification"]["ok"] is True
    assert out["verification"]["checks"]["fingerprint_matches"] is True


def test_v12_feature_screening_uses_aligned_rows(tmp_path):
    p=tmp_path/"d.csv"; _csv(p, [[1,"a"],[2,"a"],[3,"a"],[4,"b"],[5,"b"],[6,"b"],[7,"b"],[8,"b"]])
    out=answer_question(p,"ما العوامل المرتبطة بـ x؟")
    assert out["method"] == "aligned_feature_screening_mutual_information"
    assert out["answer"]["target"] == "x"


def test_v12_comprehensive_evidence_verifier_is_not_hardcoded(tmp_path):
    p=tmp_path/"d.csv"; _csv(p, [[1,"a"],[2,"a"],[3,"b"],[4,"b"],[5,"b"],[6,"b"],[7,"b"],[8,"b"]])
    out=comprehensive_analysis(p)
    assert out["verification"]["method"] == "deterministic_evidence_certificate"
    assert out["verified"] is True


def test_v12_tool_posteriors_are_exposed(tmp_path):
    from app.knowledge.memory import Memory
    from app.observability.agent_analytics import analyze_runtime
    m=Memory(tmp_path/"m.db")
    for _ in range(3): m.record_tool_outcome("t", True)
    report=analyze_runtime(m)
    assert "t" in report["tool_posteriors"]
    assert report["tool_posteriors"]["t"]["posterior_mean"] > 0.5
