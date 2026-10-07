from __future__ import annotations

from app.domain.world import WorldState
from app.intelligence.semantic import semantic_understand
import app.knowledge.memory as memory


def _setup(tmp_path):
    memory.configure(tmp_path / "memory.db")
    return memory.get_memory()


def test_real_user_multiturn_identity_and_correction(tmp_path):
    mem = _setup(tmp_path)
    sid = "real-user-identity"
    p1 = semantic_understand("my name is Abdullah", mem=mem, session_id=sid)
    assert p1.top_intent and p1.top_intent.name == "remember_fact"
    mem.observe("my name is Abdullah", session_id=sid, outcome="completed")
    p2 = semantic_understand("what is my name?", mem=mem, session_id=sid)
    assert p2.top_intent and p2.top_intent.name == "recall_fact"
    assert p2.slots.get("recall:key") == "name"
    p3 = semantic_understand("No, I mean Ahmed", mem=mem, session_id=sid)
    assert p3.canonical_goal == "correct name to ahmed"
    assert p3.slots.get("correction:previous_value") == "abdullah"


def test_real_user_ambiguous_reference_does_not_guess(tmp_path):
    mem = _setup(tmp_path)
    sid = "real-user-ambiguity"
    p = semantic_understand("update it", mem=mem, session_id=sid)
    assert p.needs_clarification is True
    assert any(not r.resolved for r in p.references)


def test_real_user_forward_reference_is_grounded(tmp_path):
    mem = _setup(tmp_path)
    p = semantic_understand("analyze this github repository for architecture", mem=mem)
    ref = next(r for r in p.references if r.text.casefold() == "this")
    assert ref.resolved
    assert ref.target == "github repository"


def test_real_user_polite_request_is_actionable(tmp_path):
    _setup(tmp_path)
    p = semantic_understand("Could you verify the repo still passes its checks before we touch it?")
    assert p.speech_act == "request"
    assert p.actionability == "action"
    assert p.top_intent and p.top_intent.name == "development_validation"


def test_real_user_fresh_web_question_is_not_memory(tmp_path):
    _setup(tmp_path)
    p = semantic_understand("what is the weather today?")
    assert p.top_intent and p.top_intent.name == "web_research"
    assert p.requires_fresh_data is True
    assert p.actionability == "information"


def test_real_user_arabic_with_opaque_identifier_keeps_language(tmp_path):
    _setup(tmp_path)
    p = semantic_understand("احفظ النتيجة باسم total")
    assert p.language == "ar"
    assert p.slots.get("result:key") == "total"


def test_real_user_compound_pipeline_is_actionable(tmp_path):
    _setup(tmp_path)
    world = WorldState()
    p = semantic_understand("calculate 25*16 then save the result as total", world=world)
    assert p.needs_clarification is False
    assert p.top_intent and p.top_intent.name == "remember_result"
    assert p.slots.get("operation:expression") == "25*16"
    assert p.slots.get("result:key") == "total"


def test_real_user_academic_search_is_scientific_and_fresh(tmp_path):
    _setup(tmp_path)
    p = semantic_understand("find recent academic papers about agent memory")
    assert p.top_intent and p.top_intent.name == "scientific_research"
    assert p.requires_fresh_data is True


def test_real_user_rag_question_stays_inside_knowledge_base(tmp_path):
    _setup(tmp_path)
    p = semantic_understand("answer using the indexed documents about agent memory")
    assert p.top_intent and p.top_intent.name == "rag_reasoning"
    assert p.requires_fresh_data is False


def test_real_user_preference_is_write_not_recall(tmp_path):
    _setup(tmp_path)
    p = semantic_understand("I prefer dark mode")
    assert p.speech_act == "statement"
    assert p.top_intent and p.top_intent.name == "remember_memory"
    assert p.slots.get("preference:theme") == "dark"


def test_real_user_origin_statement_is_memory_write(tmp_path):
    mem = _setup(tmp_path)
    p = semantic_understand("I'm from Luxor", mem=mem, session_id="origin")
    assert p.top_intent and p.top_intent.name == "remember_fact"
    assert p.slots.get("fact:origin") == "luxor"
    assert p.speech_act == "statement"
    assert p.canonical_goal == "remember origin = luxor"


def test_real_user_origin_question_is_memory_read(tmp_path):
    mem = _setup(tmp_path)
    mem.set_fact("origin", "luxor")
    p = semantic_understand("where do I come from?", mem=mem, session_id="origin")
    assert p.top_intent and p.top_intent.name == "recall_fact"
    assert p.slots.get("recall:key") == "origin"
    assert p.confidence >= 0.70


def test_real_user_origin_persists_end_to_end(tmp_path):
    mem = _setup(tmp_path)
    import app.runtime.agent as agent
    agent.LOG_FILE = tmp_path / "agent.jsonl"
    saved = agent.run_agent("I'm from Luxor", approve=lambda *_: True, session_id="origin")
    assert saved.status == "completed"
    assert saved.plan.steps[0].tool == "remember_fact"
    assert saved.plan.steps[0].args == {"key": "origin", "value": "luxor"}
    recalled = agent.run_agent("where am I from?", session_id="origin")
    assert recalled.status == "completed"
    assert recalled.plan.steps[0].tool == "recall_fact"
    assert recalled.plan.steps[0].output == "luxor"


def test_real_user_origin_extraction_handles_originally_from(tmp_path):
    _setup(tmp_path)
    p = semantic_understand("I'm originally from Aswan")
    assert p.top_intent and p.top_intent.name == "remember_fact"
    assert p.slots.get("fact:origin") == "aswan"


def test_real_user_arabic_origin_statement(tmp_path):
    _setup(tmp_path)
    p = semantic_understand("أنا من الأقصر")
    assert p.top_intent and p.top_intent.name == "remember_fact"
    assert p.slots.get("fact:origin") == "الاقصر"



def test_arabic_origin_question_overrides_declarative_origin_pattern():
    p = semantic_understand("أنا من فين?")
    assert p.intent_candidates
    assert p.intent_candidates[0].name == "recall_fact"
    assert p.slots.get("recall:key") == "origin"
    assert "fact:origin" not in p.slots


def test_colloquial_arabic_memory_questions_route_to_recall(tmp_path):
    _setup(tmp_path)
    origin = semantic_understand("فاكر أنا منين؟")
    name = semantic_understand("فاكر اسمي؟")

    assert origin.top_intent and origin.top_intent.name == "recall_fact"
    assert origin.slots.get("recall:key") == "origin"
    assert "fact:origin" not in origin.slots
    assert name.top_intent and name.top_intent.name == "recall_fact"
    assert name.slots.get("recall:key") == "name"


def test_natural_fact_statements_get_typed_memory_slots(tmp_path, monkeypatch):
    mem = _setup(tmp_path)
    monkeypatch.setenv("SHURY_NLP_MODE", "off")
    cases = (
        ("iam from luxor", "fact:origin", "luxor", "remember origin = luxor"),
        ("انا سني 30 سنه", "fact:age", "30", "remember age = 30"),
        ("انا عمري 30 سنه احفظ عندك", "fact:age", "30", "remember age = 30"),
        ("احفظ أن اسم المشروع SHURY", "fact:اسم المشروع", "shury", "remember اسم المشروع = shury"),
    )

    for text, slot, value, canonical in cases:
        parsed = semantic_understand(text, mem=mem)
        assert parsed.top_intent and parsed.top_intent.name == "remember_fact", text
        assert parsed.slots.get(slot) == value, text
        assert parsed.canonical_goal == canonical, text


def test_arabic_age_save_does_not_fall_through_to_note(tmp_path, monkeypatch):
    _setup(tmp_path)
    monkeypatch.setenv("SHURY_NLP_MODE", "off")
    import app.runtime.agent as agent
    agent.LOG_FILE = tmp_path / "agent.jsonl"

    state = agent.run_agent(
        "انا عمري 30 سنه احفظ عندك",
        approve=lambda *_: True,
        session_id="arabic-age-memory",
    )

    assert state.status == "completed"
    assert state.plan.steps[0].tool == "remember_fact"
    assert state.plan.steps[0].args == {"key": "age", "value": "30"}


def test_real_user_prospective_report_reference_is_not_unresolved():
    from app.intelligence.semantic.references import resolve_references

    text = (
        "حلل ملف workspace/sales.csv ثم أنشئ تقريرًا منظمًا واحفظه في "
        "workspace/sales_report.md وبعد ذلك راجع التقرير وتأكد من أن الملف تم إنشاؤه."
    )
    refs = resolve_references(text, {}, [])
    report = next(ref for ref in refs if ref.text.casefold() == "التقرير")
    assert report.resolved is True
    assert report.target == "workspace/sales_report.md"
    assert "prospective artifact" in report.basis


def test_real_user_compound_goal_with_prospective_report_is_not_blocked_by_reference_resolution():
    from app.intelligence.semantic.references import resolve_references

    text = (
        "حلل ملف workspace/sales.csv ثم أنشئ تقريرًا منظمًا واحفظه في "
        "workspace/sales_report.md وبعد ذلك راجع التقرير وتأكد أن الملف تم إنشاؤه."
    )
    refs = resolve_references(text, {}, [])
    assert not any(ref.text.casefold() in {"ذلك", "ها"} for ref in refs)
    assert not any(ref.text.casefold() == "ه" and not ref.resolved for ref in refs)
    report = next(ref for ref in refs if ref.text.casefold() == "التقرير")
    assert report.resolved is True
    assert report.target == "workspace/sales_report.md"
