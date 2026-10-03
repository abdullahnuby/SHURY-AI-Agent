"""Small deterministic benchmark modeled after 2026 memory-agent evaluation themes."""
from app.knowledge.memory import Memory


def run_memory_benchmark(path):
    m = Memory(path)
    results = {}

    m.set_fact("project", "نخيل")
    results["factual_recall"] = m.get_fact("project") == "نخيل"

    m.set_fact("project", "نخيل-الجديد")
    results["conflict_resolution_latest_wins"] = m.get_fact("project") == "نخيل-الجديد"

    m.add_note("اجتماع احمد بخصوص المشروع")
    m.add_note("موعد تسليم التقرير")
    results["retrieval"] = m.search_notes("احمد") == ["اجتماع احمد بخصوص المشروع"]

    m.delete_fact("project")
    results["selective_forgetting"] = m.get_fact("project") is None

    second = Memory(path)
    results["cross_session_persistence"] = second.search_notes("التقرير") == ["موعد تسليم التقرير"]
    passed = sum(results.values())
    return {"passed": passed, "total": len(results), "accuracy": passed / len(results), "details": results}
