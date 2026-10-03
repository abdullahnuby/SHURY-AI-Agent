from __future__ import annotations

import uuid

from app.brain.kernel import CognitiveKernel


def test_brain_consumes_retrieval_native_arabic_memory_statements():
    session_id = f"arabic-nlp-{uuid.uuid4().hex}"
    brain = CognitiveKernel()

    first = brain.act("انا اسمي عبدالله", session_id=session_id, max_steps=4)
    assert first.status == "completed"
    assert first.state.semantic is not None
    assert first.state.semantic.requested_operation == "remember"
    assert first.state.semantic.slot("predicate") == "name"
    assert first.state.semantic.slot("value") == "عبدالله"
    assert "clarify" != (first.state.decision.kind if first.state.decision else "")
    assert "عبدالله" in first.response

    second = brain.act("أنا من الأقصر", session_id=session_id, max_steps=4)
    assert second.status == "completed"
    assert second.state.semantic.requested_operation == "remember"
    assert second.state.semantic.slot("predicate") == "origin"
    assert second.state.semantic.slot("value") == "الاقصر"
    assert "الأقصر" in second.response or "الاقصر" in second.response

    name = brain.act("ما اسمي؟", session_id=session_id, max_steps=4)
    assert name.status == "completed"
    assert name.state.semantic.requested_operation == "query_identity"
    assert "عبدالله" in name.response

    origin = brain.act("أنا من فين؟", session_id=session_id, max_steps=4)
    assert origin.state.semantic.requested_operation == "query_memory"
    assert origin.state.semantic.slot("key") == "origin"
    assert "الاقصر" in origin.response or "الأقصر" in origin.response


def test_web_cognition_is_debug_only():
    source = open("app/interfaces/web/static/app.js", "r", encoding="utf-8").read()
    assert "SHOW_COGNITION" in source
    assert "cognitive && SHOW_COGNITION" in source
