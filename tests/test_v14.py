import csv
from pathlib import Path
from app.knowledge.statistics.statistics_v14 import wasserstein_1d, sliced_wasserstein_distance, multivariate_drift, adaptive_distribution_signal
from app.integrations.workspace import catalog_workspace, join_candidates, deterministic_join
from app.evaluation.versions.v14 import run_v14_benchmark


def test_v14_wasserstein_identity():
    assert wasserstein_1d([1,2,3], [1,2,3]) == 0.0


def test_v14_sliced_identity_deterministic():
    a=[[1,0],[0,1],[2,1]]
    assert sliced_wasserstein_distance(a,a,seed_text="same")==sliced_wasserstein_distance(a,a,seed_text="same")
    assert sliced_wasserstein_distance(a,a,seed_text="same")["distance"] == 0.0


def test_v14_multivariate_drift_detects_shift():
    d=multivariate_drift([[0,0],[0,0],[1,1],[1,1],[0,1]], [[5,5],[5,5],[6,6],[6,6],[5,6]], ["a","b"], seed_text="x")
    assert d["alert"] and d["global_alert"]


def test_v14_adaptive_distribution_signal():
    s=adaptive_distribution_signal(list(range(30))+[100,101,102], window=8)
    assert s["alert"]


def test_v14_workspace_catalog_and_join(tmp_path):
    a=tmp_path/"customers.csv"; b=tmp_path/"orders.csv"
    with a.open("w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(["customer_id","name"]); w.writerows([[1,"A"],[2,"B"],[3,"C"]])
    with b.open("w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(["customer_id","amount"]); w.writerows([[1,10],[2,20],[2,5],[3,7]])
    c=catalog_workspace(tmp_path)
    assert c["source_count"]==2
    assert join_candidates(a,b)[0]["normalized_key"]=="customer_id"
    j=deterministic_join(a,b)
    assert j["joined_rows"]==4


def test_v14_benchmark_green():
    out=run_v14_benchmark(); assert out["passed"]==out["total"]==6
