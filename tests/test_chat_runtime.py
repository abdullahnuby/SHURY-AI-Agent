from __future__ import annotations

from uuid import uuid4
from types import SimpleNamespace

from app.runtime.response import compose_final_response
from app.runtime.agent import run_agent
from app.intelligence.semantic.references import resolve_references


def _step(tool, output, args=None):
    return SimpleNamespace(tool=tool, output=output, args=args or {}, status="done")


def test_expletive_it_does_not_force_clarification():
    refs = resolve_references("what time is it?", world={}, recent_episodes=[])
    assert not any(r.text.casefold() == "it" and not r.resolved for r in refs)


def test_this_task_is_current_turn_reference():
    refs = resolve_references("discover skills for this task", world={}, recent_episodes=[])
    assert any(r.text.casefold() == "this" and r.resolved and r.target == "current_task" for r in refs)


def test_time_response_is_human_not_raw_tool_dump():
    plan = SimpleNamespace(steps=[_step("get_time", "2026-09-30 02:22")])
    semantic = SimpleNamespace(language="en", top_intent=SimpleNamespace(name="time"))
    text = compose_final_response("what time is it?", semantic, plan, "completed")
    assert "current time is" in text
    assert "get_time:" not in text


def test_calculation_response_is_human():
    plan = SimpleNamespace(steps=[_step("calculator", 400)])
    semantic = SimpleNamespace(language="en", top_intent=SimpleNamespace(name="calculate"))
    text = compose_final_response("calculate 25*16", semantic, plan, "completed")
    assert "400" in text
    assert "calculator:" not in text


def test_social_turns_respond_without_planning(monkeypatch):
    monkeypatch.setenv("SHURY_NLP_MODE", "off")
    expected = {
        "hello": "أهلًا بيك 👋 أنا شوري.",
        "how are you?": "أنا شغال كويس 😄 وإنت عامل إيه؟",
        "thanks": "العفو!",
        "goodbye": "مع السلامة!",
        "okay": "تمام.",
    }
    for text, response in expected.items():
        state = run_agent(text)
        assert state.status == "completed"
        assert not state.plan.steps
        assert state.final_message == response


def test_social_turns_are_not_swallowed_by_generic_question_routing(monkeypatch):
    monkeypatch.setenv("SHURY_NLP_MODE", "required")
    monkeypatch.setenv("SHURY_NLP_MODEL", "omarelshehy/Arabic-Retrieval-v1.0")
    monkeypatch.setenv("SHURY_NLP_DEVICE", "cpu")

    for text in ["hello", "how are you?", "thanks", "مع السلامة"]:
        state = run_agent(text, session_id=f"required-social-{text[:8]}")
        assert state.status == "completed", text
        assert not state.plan.steps, (text, state.final_message)
        assert state.final_message.strip(), text


def test_social_phrase_inside_request_does_not_shadow_task(monkeypatch):
    monkeypatch.setenv("SHURY_NLP_MODE", "off")
    state = run_agent("calculate 25*16, thanks")
    assert state.status == "completed"
    assert state.plan.steps[0].tool == "calculator"


def test_personal_memory_turns_have_conversational_replies(monkeypatch):
    monkeypatch.setenv("SHURY_NLP_MODE", "off")
    session_id = f"chat-memory-{uuid4().hex}"
    saved_name = run_agent("أنا اسمي عبدالله", session_id=session_id)
    saved_origin = run_agent("أنا من الأقصر", session_id=session_id)
    recalled_name = run_agent("فاكر اسمي؟", session_id=session_id)
    assert saved_name.final_message == "تشرفت يا عبدالله."
    assert saved_origin.final_message == "تمام، هفتكر إنك من الأقصر."
    assert recalled_name.final_message == "أيوه، فاكر إن اسمك عبدالله."

def test_generic_fact_is_saved_and_recalled_as_a_logical_reply():
    save = run_agent("افتكر اسم المشروع: نخيل")
    assert save.status == "completed"
    assert save.plan.steps[0].tool == "remember_fact"
    assert "تم حفظ" in save.final_message

    recall = run_agent("فاكر ايه عن اسم المشروع")
    assert recall.status == "completed"
    assert recall.plan.steps[0].tool == "recall_fact"
    assert recall.plan.steps[0].output == "نخيل"
    assert recall.final_message == "أفتكر إن اسم المشروع = نخيل"
