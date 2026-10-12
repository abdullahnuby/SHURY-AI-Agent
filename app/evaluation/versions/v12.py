"""Focused V12 benchmark for statistical rigor and agent self-analysis."""
from pathlib import Path
import tempfile
import csv
from app.services.data_analysis_service import comprehensive_analysis
from app.knowledge.statistics.statistics_v12 import bootstrap_ci, theil_sen, mutual_information, page_hinkley


def run_v12_benchmark() -> dict:
    tests = []
    tests.append(("bootstrap_reproducible", bootstrap_ci([1,2,3,4,5], seed_text="x")==bootstrap_ci([1,2,3,4,5], seed_text="x")))
    tests.append(("theil_sen_robust_slope", abs(theil_sen([1,2,100,4,5])["slope"] - 1.0) < 1e-9))
    tests.append(("mutual_information_positive", mutual_information(["a","a","b","b"],["x","x","y","y"]) > 0.0))
    ph = page_hinkley([0.0]*10 + [2.0]*10, threshold=1.0)
    tests.append(("change_point_detected", ph["change"]))
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)/"d.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            w=csv.writer(f); w.writerow(["x","g"]); w.writerows([[1,"a"],[2,"a"],[3,"a"],[4,"b"],[100,"b"],[6,"b"],[7,"b"],[8,"b"]])
        rep=comprehensive_analysis(p)
        tests.append(("comprehensive_evidence", rep["verified"] and bool(rep["methodology"])))
    passed=sum(1 for _,ok in tests if ok)
    return {"passed": passed, "total": len(tests), "cases": [{"name":n,"passed":ok} for n,ok in tests]}
