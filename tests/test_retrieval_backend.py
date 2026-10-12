from __future__ import annotations

import numpy as np

import app.intelligence.semantic.retrieval as retrieval


class FakeSentenceTransformer:
    max_seq_length = 1024

    def __init__(self):
        self.calls = []

    def encode(self, texts, **kwargs):
        self.calls.append((list(texts), dict(kwargs)))
        vectors = []
        for text in texts:
            if text.startswith("<query>:"):
                vectors.append([1.0, 0.0, 0.0])
            elif "preferred passage" in text:
                vectors.append([1.0, 0.0, 0.0])
            else:
                vectors.append([0.0, 1.0, 0.0])
        return np.asarray(vectors, dtype=np.float32)


def test_arabic_retrieval_uses_explicit_query_and_passage_prefixes(monkeypatch):
    fake = FakeSentenceTransformer()
    monkeypatch.setattr(retrieval, "_model", fake)
    monkeypatch.setenv("SHURY_NLP_MODE", "auto")

    q = retrieval.encode_queries(["احسب التكلفة"])
    p = retrieval.encode_passages(["preferred passage", "other passage"])

    assert q.shape == (1, 3)
    assert p.shape == (2, 3)
    assert fake.calls[0][0] == ["<query>: احسب التكلفة"]
    assert fake.calls[1][0] == ["<passage>: preferred passage", "<passage>: other passage"]
    assert fake.calls[0][1]["normalize_embeddings"] is True


def test_arabic_retrieval_ranking_is_semantic(monkeypatch):
    fake = FakeSentenceTransformer()
    monkeypatch.setattr(retrieval, "_model", fake)
    monkeypatch.setenv("SHURY_NLP_MODE", "auto")

    rows = [("close", "preferred passage"), ("far", "other passage")]
    matches = retrieval.rank_query_against_texts("احسب", rows, top_k=2)

    assert [x.name for x in matches] == ["close", "far"]
    assert matches[0].score > matches[1].score
    assert "arabic-retrieval-v1.0" in matches[0].evidence
