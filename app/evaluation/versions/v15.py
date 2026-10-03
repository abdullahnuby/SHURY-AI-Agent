"""Focused V15 benchmark for deterministic RAG."""
from pathlib import Path
import tempfile

from app.knowledge.rag import RAGEngine


def run_v15_benchmark() -> dict:
    tests = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "policy.md").write_text(
            "# Safety Policy\n\nAll production changes require explicit approval.\n\n"
            "# Data Retention\n\nArchived records remain searchable for thirty days.\n",
            encoding="utf-8",
        )
        (root / "ops.md").write_text(
            "# Operations\n\nProduction changes require approval from an operator.\n"
            "Critical incidents must be recorded in the operations log.\n",
            encoding="utf-8",
        )
        (root / "data.csv").write_text(
            "id,amount,customer\n1,100,A\n2,250,B\n3,100,C\n", encoding="utf-8"
        )
        engine = RAGEngine(root / "rag.db")
        out = engine.index(root)
        tests.append(("index_sources", out["files"] == 3 and out["chunks"] >= 6))
        repeat = engine.index(root)
        tests.append(("incremental_skip", repeat["skipped"] == 3 and repeat["added"] == 0))
        q1 = engine.query("what requires operator approval for production deployment?")
        tests.append(("grounded_query", q1["grounded"] and q1["evidence"] and "[S1]" in q1["answer"]))
        q2a = engine.query("approval changes and incident log")
        q2b = engine.query("approval changes and incident log")
        tests.append(("deterministic_retrieval", q2a["retrieval"] == q2b["retrieval"] and q2a["trace"] == q2b["trace"]))
        q3 = engine.query("zebra quantum glacier nobody mentions")
        tests.append(("fail_closed_abstention", q3["abstained"] and not q3["evidence"]))
        # Memory decay remains a measurable signal rather than destructive eviction.
        decay = engine.decay_report()
        tests.append(("memory_decay_report", decay["chunks"] >= 6 and "half_life_days" in decay))
    passed = sum(1 for _, ok in tests if ok)
    return {"passed": passed, "total": len(tests), "cases": [{"name": n, "passed": ok} for n, ok in tests]}
