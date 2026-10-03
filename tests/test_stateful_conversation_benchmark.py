from app.evaluation.stateful_conversation_benchmark import ARABIC_TRANSLATIONS, CONVERSATION_TEMPLATES, generate_sessions, run_stateful_benchmark
from collections import Counter


def test_generate_sessions_is_seeded_and_reproducible():
    first = generate_sessions(12, seed=7)
    second = generate_sessions(12, seed=7)
    smaller_batch = generate_sessions(2, seed=7)
    assert len(first) == 12
    assert len(second) == 12
    assert first == second
    assert smaller_batch == first[:2]
    assert all("turns" in session for session in first)
    assert any(session["category"] for session in first)
    category_counts = Counter(session["category"] for session in first)
    assert max(category_counts.values()) - min(category_counts.values()) <= 1
    for session in first:
        template = CONVERSATION_TEMPLATES[session["category"]]
        assert len(session["turns"]) == len(template)
        assert all(
            generated in {english, ARABIC_TRANSLATIONS.get(english, english)}
            for generated, (english, _) in zip(session["turns"], template)
        )
        if session["language"] == "mixed":
            assert any("\u0600" <= char <= "\u06ff" for turn in session["turns"] for char in turn)
            assert any(char.isascii() and char.isalpha() for turn in session["turns"] for char in turn)


def test_stateful_benchmark_produces_report_shape():
    report = run_stateful_benchmark(count=8, seed=3, rounds=1)
    assert report["dialogs"] == 8
    assert report["turns_total"] >= 8
    assert report["categories"]
    assert "summary" in report
    assert report["summary"]["evaluated_turns"] == 0
    assert report["summary"]["pass_rate"] is None
    assert all(category["pass_rate"] is None for category in report["categories"].values())
