"""Focused V13 benchmark: adaptive selection + dependence-aware inference + learning."""
from pathlib import Path
import csv
import tempfile
from app.knowledge.statistics.statistics_v13 import (
    autocorrelation, choose_confidence_interval_method, moving_block_bootstrap_ci, rolling_origin_mae
)
from app.planning.adaptive_portfolio import select_trend_method, learned_ucb
from app.knowledge.memory import Memory
from app.services.adaptive_analysis_service import adaptive_analyze


def run_v13_benchmark() -> dict:
    tests = []
    seq = [i * 0.8 + (0.2 if i % 3 == 0 else 0.0) for i in range(30)]
    tests.append(("autocorrelation_detected", autocorrelation(seq) is not None and autocorrelation(seq) > 0.9))
    ci_choice = choose_confidence_interval_method(seq)
    tests.append(("dependence_aware_ci", ci_choice["method"] == "moving_block_bootstrap"))
    a = moving_block_bootstrap_ci(seq, seed_text="v13")
    b = moving_block_bootstrap_ci(seq, seed_text="v13")
    tests.append(("block_bootstrap_reproducible", a == b and a["lower"] <= a["estimate"] <= a["upper"]))
    outlier = [1,2,3,4,100,6,7,8,9,10,11,12]
    tests.append(("robust_trend_selection", select_trend_method(outlier, 0.10).method == "theil_sen"))
    tests.append(("rolling_origin_available", rolling_origin_mae(seq, "ols") is not None))
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "memory.db"
        m = Memory(db)
        c = select_trend_method(seq, 0.0, memory=m)
        m.record_algorithm_observation(c.context, "ols", 0.95, True, {"case": "bench"})
        u = learned_ucb(m, c.context, "ols")
        tests.append(("learned_ucb_updates", u["count"] == 1 and u["mean"] > 0.5))
        p = Path(td) / "data.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["x", "y"]); w.writerows([[i, i*i] for i in range(1, 15)])
        rep = adaptive_analyze(p, memory=m)
        tests.append(("adaptive_report", rep["verified"] and bool(rep["adaptive_learning"])))
    passed = sum(1 for _, ok in tests if ok)
    return {"passed": passed, "total": len(tests), "cases": [{"name": n, "passed": ok} for n, ok in tests]}
