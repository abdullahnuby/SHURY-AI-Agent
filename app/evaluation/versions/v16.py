"""Focused V16 benchmark for adaptive RAG routing and evidence-aware escalation."""
from pathlib import Path
import tempfile

from app.knowledge.rag_v16 import AdaptiveRAGEngine


def run_v16_benchmark() -> dict:
    cases = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "policy.md").write_text(
            "# Production\n\nProduction deployment requires explicit operator approval.\n\n"
            "# Incidents\n\nCritical incidents must be recorded in the operations log.\n",
            encoding="utf-8",
        )
        (root / "owners.md").write_text(
            "# Ownership\n\nAlice owns deployment approvals.\nBob owns incident logging.\n",
            encoding="utf-8",
        )
        (root / "records.csv").write_text(
            "id,status,owner\n1,approved,Alice\n2,pending,Bob\n3,approved,Alice\n",
            encoding="utf-8",
        )
        engine = AdaptiveRAGEngine(root / "rag.db")
        indexed = engine.index(root)
        cases.append(("index", indexed["files"] == 3 and indexed["chunks"] >= 7))

        direct = engine.query("what requires operator approval for production deployment?")
        cases.append(("focused_grounding", direct["grounded"] and direct["strategies"]))
        cases.append(("portfolio_trace", all("marginal_gain" in row and "evidence" in row for row in direct["trace"])))

        multi = engine.query("deployment approval and incident log")
        cases.append(("adaptive_multihop", multi["grounded"] and multi["profile"]["subqueries"] == 2))
        cases.append(("evidence_stop", len(multi["strategies"]) <= 3))

        unknown = engine.query("unicorn glacier quantum nobody mentions")
        cases.append(("safe_abstention", unknown["abstained"] and not unknown["evidence"]))

    passed = sum(1 for _, ok in cases if ok)
    return {"passed": passed, "total": len(cases), "cases": [{"name": n, "passed": bool(ok)} for n, ok in cases]}
