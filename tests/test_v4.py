from app.intelligence.understanding import understand, normalize
from app.intelligence.evaluate import run
from app.runtime.agent import run_agent

def test_arabic_normalization_preserves_meaning():
    assert normalize("إحسِب ١٢") == "احسب 12"

def test_intent_scoring():
    u = understand("احسب ١٢ ضرب ٤")
    assert u.top_intent and u.top_intent.name == "calculate"
    assert "12" in u.entities["number"]

def test_original_note_entity_is_not_normalized():
    u = understand("سجل عندي ملاحظة دائمة")
    assert u.entities["note"] == ["ملاحظة دائمة"]

def test_evaluation_suite():
    r = run(); assert r["accuracy"] == 1.0

def test_runtime_still_executes():
    s = run_agent("احسب 12*4")
    assert s.status == "completed" and s.plan.steps[0].output == 48
