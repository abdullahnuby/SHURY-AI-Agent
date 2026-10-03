from app.evaluation.semantic_benchmark import CASES, run_semantic_benchmark


def test_semantic_benchmark_has_50_cases():
    assert len(CASES) == 50


def test_semantic_benchmark_gate():
    result = run_semantic_benchmark()
    assert result["passed"] == result["total"], result
    assert result["score"] >= 0.98, result
