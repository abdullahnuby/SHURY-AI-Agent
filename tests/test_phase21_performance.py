from __future__ import annotations

import sys
import types


def test_model_constructor_is_cached_once(monkeypatch):
    import app.intelligence.semantic.retrieval as retrieval

    class FakeModel:
        max_seq_length = 512

        def encode(self, items, **kwargs):
            return [[1.0, 0.0, 0.0] for _ in items]

        def get_sentence_embedding_dimension(self):
            return 3

    calls = []

    def ctor(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeModel()

    fake_st = types.ModuleType("sentence_transformers")
    fake_st.SentenceTransformer = ctor
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_st)
    monkeypatch.setenv("SHURY_NLP_MODE", "required")
    monkeypatch.setenv("SHURY_NLP_MODEL", "omarelshehy/Arabic-Retrieval-v1.0")
    retrieval._model = None
    retrieval._load_error = None

    first = retrieval.get_model()
    for _ in range(20):
        assert retrieval.get_model() is first
    retrieval.encode_queries(["one"])
    retrieval.encode_queries(["two"])

    assert len(calls) == 1


def test_phase21_measurement_is_strict_about_real_model(monkeypatch):
    monkeypatch.setenv("SHURY_NLP_MODE", "required")
    import app.evaluation.performance as performance

    monkeypatch.setattr(
        performance,
        "measure_model_preflight",
        lambda: {"status": "blocked", "error": "test blocker"},
    )
    result = performance.collect()
    assert result["real_model"]["status"] == "blocked"
    assert result["gate"]["real_measurements_complete"] is False
