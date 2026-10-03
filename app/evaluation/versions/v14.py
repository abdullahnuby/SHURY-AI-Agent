"""Small deterministic V14 regression benchmark."""
from __future__ import annotations
import csv
import tempfile
from pathlib import Path
from app.knowledge.statistics.statistics_v14 import wasserstein_1d, sliced_wasserstein_distance, multivariate_drift
from app.integrations.workspace import catalog_workspace, join_candidates, deterministic_join


def _csv(path: Path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(["id","value"]); w.writerows(rows)


def run_v14_benchmark():
    results=[]
    results.append(("wasserstein_identity", wasserstein_1d([1,2,3],[1,2,3]) == 0.0))
    results.append(("sliced_identity", sliced_wasserstein_distance([[1,0],[0,1]], [[1,0],[0,1]], seed_text="x")["distance"] == 0.0))
    drift=multivariate_drift([[0,0],[0,0],[1,1],[1,1],[0,1]], [[5,5],[5,5],[6,6],[6,6],[5,6]], ["a","b"], seed_text="x")
    results.append(("multivariate_drift_alert", drift["alert"]))
    with tempfile.TemporaryDirectory() as td:
        root=Path(td); a=root/"customers.csv"; b=root/"orders.csv"
        with a.open("w", newline="", encoding="utf-8") as f:
            w=csv.writer(f); w.writerow(["customer_id","name"]); w.writerows([[1,"A"],[2,"B"],[3,"C"]])
        with b.open("w", newline="", encoding="utf-8") as f:
            w=csv.writer(f); w.writerow(["customer_id","amount"]); w.writerows([[1,10],[2,20],[2,5],[3,7]])
        cat=catalog_workspace(root)
        results.append(("workspace_catalog", cat["source_count"] == 2 and cat["data_sources"] == 2))
        cands=join_candidates(a,b)
        results.append(("join_candidate", bool(cands) and cands[0]["left_column"] == "customer_id"))
        joined=deterministic_join(a,b)
        results.append(("deterministic_join", joined["joined_rows"] == 4 and joined["key"]["normalized_key"] == "customer_id"))
    passed=sum(ok for _,ok in results)
    return {"passed": passed, "total": len(results), "results": [{"name":n,"ok":ok} for n,ok in results]}
