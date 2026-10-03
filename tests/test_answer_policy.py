from __future__ import annotations

from types import SimpleNamespace

from app.intelligence.answer_policy import classify_question, is_generic_question
from app.tools.knowledge.answer import answer_question
from app.intelligence.semantic import semantic_understand
from app.intelligence.task_compiler import compile_task_ir
from app.runtime.response import compose_final_response


class FakeRAG:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def query(self, query, top_k=6, max_hops=3):
        self.calls.append((query, top_k, max_hops))
        return self.result


def test_adaptive_answer_falls_back_to_web_when_rag_is_not_grounded():
    rag = FakeRAG({"grounded": False, "answer": "", "evidence": []})
    web = FakeWeb({"count": 1, "sources": [{"title": "Source", "url": "https://example.test", "score": 0.9, "text": "A black hole is a region from which light cannot escape. It is extremely compact."}]})
    result = answer_question("What is a black hole?", rag=rag, web=web)
    assert result["status"] == "answered"
    assert result["route"] == "web_extractive"
    assert result["grounded"] is True
    assert web.calls == [("What is a black hole?", 5, True)]


class FakeWeb:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def research(self, query, limit=5, index=True):
        self.calls.append((query, limit, index))
        return self.result


def test_generic_question_is_detected_without_stealing_known_intents():
    parse = semantic_understand("What is a black hole?", mem=None, world=None, registry={})
    assert parse.top_intent is not None
    assert parse.top_intent.name == "knowledge_query"
    assert parse.slots["question"] == "What is a black hole?"
    assert is_generic_question("What is a black hole?")


def test_action_question_does_not_get_stolen_by_knowledge_route():
    parse = semantic_understand("Can you run the tests?", mem=None, world=None, registry={})
    assert parse.top_intent is not None
    assert parse.top_intent.name != "knowledge_query"


def test_question_plans_to_question_answering_capability():
    parse = semantic_understand("What is a black hole?", mem=None, world=None, registry={})
    ir = compile_task_ir(parse)
    assert ir.nodes[0].intent == "knowledge_query"
    assert ir.nodes[0].capability == "question_answering"


def test_answer_policy_prefers_local_rag_for_non_fresh_question():
    decision = classify_question("What is a black hole?", "knowledge_query", 0.72)
    assert decision.mode == "adaptive"
    assert decision.requires_fresh_data is False


def test_answer_policy_routes_fresh_question_to_web():
    decision = classify_question("What is the latest price of X?", "knowledge_query", 0.72)
    assert decision.mode == "web"
    assert decision.requires_fresh_data is True


def test_answer_response_is_grounded_and_not_raw_runtime_dump():
    plan = SimpleNamespace(steps=[SimpleNamespace(
        tool="answer_question",
        output={
            "status": "answered",
            "answer": "A black hole is a region of spacetime from which light cannot escape. [S1]",
            "evidence": [{"title": "NASA", "url": "https://example.test/nasa"}],
        },
        args={"query": "What is a black hole?"},
        status="done",
    )])
    semantic = SimpleNamespace(language="en", top_intent=SimpleNamespace(name="knowledge_query"))
    text = compose_final_response("What is a black hole?", semantic, plan, "completed")
    assert "A black hole" in text
    assert "Sources:" in text
    assert "answer_question:" not in text
