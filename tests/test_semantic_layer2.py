from datetime import datetime

import app.knowledge.memory as memory
from app.core.time import get_timezone, now_in_timezone
from app.domain.world import WorldState
from app.intelligence.semantic import semantic_understand
from app.intelligence.semantic.intents import candidates
from app.intelligence.semantic.slots import extract_slots


def _setup(tmp_path):
    memory.configure(tmp_path / "semantic.db")
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


def test_semantic_temporal_grounding_and_constraints(tmp_path):
    _setup(tmp_path)
    now = datetime(2026, 9, 29, 20, 0, tzinfo=get_timezone("Africa/Cairo"))
    p = semantic_understand(
        "tomorrow at 10:30, run the tests before deploy and finish within 15 minutes, max 4 steps",
        now=now,
    )
    assert any(t.kind == "date" and t.start == "2026-09-30" for t in p.temporal)
    assert any(t.kind == "time" and t.start == "10:30:00" for t in p.temporal)
    assert any(c.key == "deadline" and c.value == "15 minutes" for c in p.constraints)
    assert any(c.key == "max_steps" and c.operator == "lte" and c.value == "4" for c in p.constraints)
    assert any(c.key == "ordering" and c.operator == "before" for c in p.constraints)


def test_semantic_same_utterance_coreference_beats_old_session_output(tmp_path):
    _setup(tmp_path)
    world = WorldState(last_goal="calculate 9*9", last_outputs={"last_result": 81})
    p = semantic_understand("find the latest papers about agent memory and compare them", world=world)
    refs = [r for r in p.references if r.text.casefold() == "them"]
    assert refs and refs[0].resolved
    assert refs[0].target.lower() in {"papers", "latest papers"}
    assert refs[0].basis == "same-utterance antecedent"


def test_semantic_does_not_resolve_unrelated_definite_entity(tmp_path):
    _setup(tmp_path)
    world = WorldState(last_goal="calculate 9*9", last_outputs={"last_result": 81})
    p = semantic_understand("take the report we made last week and update it", world=world)
    report = [r for r in p.references if r.kind == "definite_entity"]
    assert report and not report[0].resolved


def test_semantic_distinguishes_question_from_memory_and_marks_fresh_data(tmp_path):
    _setup(tmp_path)
    p = semantic_understand("What is the weather today?")
    assert p.speech_act == "question"
    assert p.requires_fresh_data is True
    assert all(i.name not in {"memory_profile", "recall_fact", "memory_search"} for i in p.intent_candidates)
    assert any(t.kind == "date" and t.start == now_in_timezone("Africa/Cairo").date().isoformat() for t in p.temporal)


def test_semantic_profile_and_preference_slots(tmp_path):
    _setup(tmp_path)
    p = semantic_understand("أنا بفضل الوضع الداكن")
    assert p.language == "ar"
    assert p.slots.get("preference:theme") == "الداكن"
    assert any(e.type == "preference_value" for e in p.entities)


def test_semantic_engine_has_retrieval_native_source(tmp_path, monkeypatch):
    _setup(tmp_path)
    monkeypatch.setenv("SHURY_NLP_MODE", "off")
    p = semantic_understand("calculate 4*6")
    assert p.source == "retrieval-nlp"
    assert p.top_intent and p.top_intent.name == "calculate"


def test_semantic_retrieval_can_route_a_known_intent(tmp_path, monkeypatch):
    _setup(tmp_path)
    import app.intelligence.semantic.intents as intents
    from app.intelligence.semantic.retrieval import SemanticMatch
    monkeypatch.setattr(
        intents,
        "rank_query_against_texts",
        lambda query, rows, top_k=10: [
            SemanticMatch("calculate::0", 0.94, ("arabic-retrieval-v1.0",)),
        ],
    )
    p = semantic_understand("محتاج احسب 25 على 5")
    assert p.top_intent is not None
    assert p.top_intent.name == "calculate"
    assert any("arabic-retrieval-v1.0" in e for e in p.top_intent.evidence)


def test_semantic_question_is_information_even_when_it_has_a_recall_slot(tmp_path):
    _setup(tmp_path)
    p = semantic_understand("what's my name?")
    assert p.speech_act == "question"
    assert p.actionability == "information"
    assert p.slots.get("recall:key") == "name"


def test_semantic_preference_statement_is_not_recall(tmp_path):
    _setup(tmp_path)
    p = semantic_understand("I prefer dark mode")
    assert p.speech_act == "statement"
    assert p.top_intent and p.top_intent.name == "remember_memory"


def test_semantic_declarative_fact_is_memory_write(tmp_path):
    _setup(tmp_path)
    p = semantic_understand("my city is Luxor")
    assert p.speech_act == "statement"
    assert p.top_intent and p.top_intent.name == "remember_fact"
    assert p.canonical_goal == "remember city = luxor"


def test_semantic_unresolved_pronoun_requires_clarification(tmp_path):
    _setup(tmp_path)
    p = semantic_understand("update it")
    assert p.needs_clarification is True
    assert any(r.kind == "pronoun" and not r.resolved for r in p.references)


def test_semantic_forward_demonstrative_uses_following_entity(tmp_path):
    _setup(tmp_path)
    p = semantic_understand("analyze this repository")
    ref = next(r for r in p.references if r.text.casefold() == "this")
    assert ref.resolved and ref.target == "repository"


def test_semantic_cross_turn_correction_is_grounded(tmp_path):
    _setup(tmp_path)
    m = memory.get_memory(); sid = "semantic-correction"
    m.observe("my city is Luxor", session_id=sid, outcome="completed")
    p = semantic_understand("No, I mean Cairo", mem=m, session_id=sid)
    assert p.slots.get("correction:key") == "city"
    assert p.slots.get("correction:previous_value") == "luxor"
    assert p.slots.get("correction:value") == "cairo"
    assert p.canonical_goal == "correct city to cairo"


def test_phase6_normalized_arabic_memory_slots():
    assert extract_slots("أنا أعيش في مدينة الأقصر").get("fact:city") == "الاقصر"
    assert extract_slots("أنا شغال دكتور").get("fact:job") == "دكتور"
    assert extract_slots("أنا أفضل لغة بايثون").get("preference:general") == "لغة بايثون"
    assert extract_slots("أين أعيش؟").get("recall:key") == "city"
    assert extract_slots("بشتغل ايه؟").get("recall:key") == "job"
    assert extract_slots("ما هي لغتي المفضلة؟").get("recall:key") == "preference"
    assert extract_slots("أنا منين يا شوري؟").get("recall:key") == "origin"
    assert extract_slots("اسم مين المسجل عندك؟").get("recall:key") == "name"


def test_phase6_specialized_intents_and_underspecified_command(tmp_path):
    _setup(tmp_path)
    assert semantic_understand("كم معلومة مسجلة عندك؟").top_intent.name == "memory_stats"
    previous = semantic_understand(
        "ما هي النتيجة السابقة؟",
        world=WorldState(last_goal="احسب 20 * 5", last_outputs={"last_result": 100}),
    )
    assert previous.top_intent.name == "recall_last_result"
    assert not previous.needs_clarification
    assert semantic_understand("نفذ الأمر").needs_clarification


def test_project_name_does_not_imply_github_learning():
    assert all(item.name != "github_learning" for item in candidates("أنا اعمل على مشروع SHURY"))
