from pathlib import Path

from app.knowledge.rag_v16 import AdaptiveRAGEngine
from app.evaluation.versions.v16 import run_v16_benchmark


def _fixture(root: Path):
    (root / "guide.md").write_text(
        "# Deployment\n\nProduction deployment requires operator approval.\n\n"
        "# Incident\n\nCritical incidents must be written to the operations log.\n",
        encoding="utf-8",
    )
    (root / "owners.md").write_text(
        "# Ownership\n\nAlice owns deployment approvals.\nBob owns incident logging.\n",
        encoding="utf-8",
    )
    (root / "facts.csv").write_text(
        "id,owner,status\n1,Alice,active\n2,Bob,closed\n3,Alice,active\n",
        encoding="utf-8",
    )


def test_v16_profile_and_portfolio_learning(tmp_path):
    _fixture(tmp_path)
    e = AdaptiveRAGEngine(tmp_path / "rag.db")
    e.index(tmp_path)
    first = e.query("what requires operator approval for production deployment?")
    second = e.query("what requires operator approval for production deployment?")
    assert first["grounded"]
    assert first["trace"]
    assert first["profile"]["complexity"] >= 0
    assert second["strategy_portfolio"]
    assert any(row["observations"] > 0 for row in second["strategy_portfolio"])


def test_v16_adaptive_escalation_for_multihop(tmp_path):
    _fixture(tmp_path)
    e = AdaptiveRAGEngine(tmp_path / "rag.db")
    e.index(tmp_path)
    out = e.query("deployment approval and incident log")
    assert out["profile"]["subqueries"] == 2
    assert out["grounded"]
    assert len(out["strategies"]) <= 3
    assert any(row["marginal_gain"] >= 0 for row in out["trace"])


def test_v16_safe_abstention(tmp_path):
    _fixture(tmp_path)
    e = AdaptiveRAGEngine(tmp_path / "rag.db")
    e.index(tmp_path)
    out = e.query("zebra quantum glacier nobody mentions")
    assert out["abstained"]
    assert not out["evidence"]
    assert out["reason"] == "adaptive_evidence_gate_failed"


def test_v16_repeatability_same_corpus(tmp_path):
    _fixture(tmp_path)
    e = AdaptiveRAGEngine(tmp_path / "rag.db")
    e.index(tmp_path)
    a = e.query("what requires operator approval for production deployment?")
    b = e.query("what requires operator approval for production deployment?")
    assert a["retrieval"] == b["retrieval"]
    assert a["answer"] == b["answer"]


def test_v16_benchmark_green():
    out = run_v16_benchmark()
    assert out["passed"] == out["total"] == 6
