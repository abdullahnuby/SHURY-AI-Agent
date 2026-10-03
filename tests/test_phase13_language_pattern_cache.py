from __future__ import annotations

from app.intelligence.semantic.models import IntentCandidate, SemanticParse
from app.intelligence.semantic.pattern_cache import LanguagePatternCache
from app.intelligence.semantic import parser as semantic_parser
from app.learning.store import LearningStore


def parse_time(text: str, confidence: float = 0.95, source: str = "hybrid-model") -> SemanticParse:
    return SemanticParse(
        original=text,
        normalized=text.casefold(),
        language="en",
        domain="time",
        canonical_goal="query_time",
        intent_candidates=[IntentCandidate("query_time", confidence, ("time-pattern",), "time", source=source)],
        entities=[], references=[], temporal=[], constraints=[], slots={}, required_information=[],
        ambiguity_reasons=[], safety_signals=[], needs_clarification=False, clarification_question="",
        confidence=confidence, speech_act="question", actionability="information", requires_fresh_data=False,
        source=source,
    )


def parse_caps(text: str, confidence: float = 0.95) -> SemanticParse:
    p=parse_time(text, confidence=confidence)
    return SemanticParse(**{**p.__dict__, "domain":"capability", "canonical_goal":"query_capabilities",
        "intent_candidates":[IntentCandidate("query_capabilities", confidence, ("capability-pattern",), "capability", source="hybrid-model")]})


def test_single_verified_use_is_not_promoted(tmp_path):
    store=LearningStore(tmp_path/"learning.db")
    cache=LanguagePatternCache(store)
    p=parse_time("What time is it?")
    result=cache.observe(p, run_id="r1", success=True, verified=True)
    assert result["eligible"] is True and result["promoted"] is False
    assert cache.lookup(p) is None


def test_repeated_verified_uses_promote_and_lookup(tmp_path):
    store=LearningStore(tmp_path/"learning.db")
    cache=LanguagePatternCache(store)
    for i in range(3):
        result=cache.observe(parse_time("What time is it?"), run_id=f"r{i}", success=True, verified=True)
    assert result["promoted"] is True
    hit=cache.lookup(parse_time("What time is it?"))
    assert hit is not None and hit["status"]=="promoted" and hit["successes"]==3
    materialized=cache.materialize(parse_time("WHAT TIME IS IT?"), hit)
    assert materialized.original == "WHAT TIME IS IT?"
    assert materialized.top_intent is not None and materialized.top_intent.name == "query_time"
    assert materialized.source == "language-pattern-cache"


def test_failed_use_prevents_future_promotion(tmp_path):
    store=LearningStore(tmp_path/"learning.db")
    cache=LanguagePatternCache(store)
    assert cache.observe(parse_time("What time is it?"), run_id="r1", success=True, verified=True)["promoted"] is False
    assert cache.observe(parse_time("What time is it?"), run_id="r2", success=True, verified=True)["promoted"] is False
    failed=cache.observe(parse_time("What time is it?"), run_id="r3", success=False, verified=False)
    assert failed["status"]=="revoked"
    assert cache.lookup(parse_time("What time is it?")) is None
    assert cache.observe(parse_time("What time is it?"), run_id="r4", success=True, verified=True)["promoted"] is False


def test_conflicting_mapping_revokes_promotion(tmp_path):
    store=LearningStore(tmp_path/"learning.db")
    cache=LanguagePatternCache(store)
    for i in range(3):
        cache.observe(parse_time("What time is it?"), run_id=f"a{i}", success=True, verified=True)
    assert cache.lookup(parse_time("What time is it?")) is not None
    conflict=cache.observe(parse_caps("What time is it?"), run_id="conflict", success=True, verified=True)
    assert conflict["promoted"] is False
    assert cache.lookup(parse_time("What time is it?")) is None
    assert any(x["status"]=="revoked" and x["contradiction_count"]>0 for x in cache.snapshot()["mappings"])


def test_uncertain_or_dynamic_semantics_never_enter_static_cache(tmp_path):
    store=LearningStore(tmp_path/"learning.db")
    cache=LanguagePatternCache(store)
    dynamic=parse_time("What time is it for Cairo?")
    dynamic=SemanticParse(**{**dynamic.__dict__, "entities": [] , "slots":{"location":"Cairo"}})
    uncertain=parse_time("What time is it?", confidence=0.60)
    assert cache.observe(dynamic, run_id="d1", success=True, verified=True)["eligible"] is False
    assert cache.observe(uncertain, run_id="u1", success=True, verified=True)["eligible"] is False
    assert cache.stats()["observations"] == 0


def test_parser_uses_promoted_cache_before_repeated_semantic_inference(monkeypatch, tmp_path):
    store=LearningStore(tmp_path/"learning.db")
    cache=LanguagePatternCache(store)
    for i in range(3):
        cache.observe(parse_time("What time is it?", source="retrieval-nlp"), run_id=f"r{i}", success=True, verified=True)

    calls={"count": 0}
    import app.intelligence.semantic.parser as parser_module
    original = parser_module.candidates
    def counted(text):
        calls["count"] += 1
        return original(text)
    monkeypatch.setattr(parser_module, "candidates", counted)
    result=parser_module.SemanticInterpreter(pattern_cache=cache).parse("What time is it?", mem=None, world=None, registry={})
    assert result.source=="language-pattern-cache"
    assert result.top_intent is not None and result.top_intent.name=="query_time"
    assert calls["count"] == 1
