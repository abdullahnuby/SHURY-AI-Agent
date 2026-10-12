from __future__ import annotations

from app.intelligence.semantic import SemanticContract, semantic_understand


def test_unified_contract_has_typed_core_fields_across_languages(monkeypatch):
    monkeypatch.setenv("SHURY_NLP_MODE", "off")
    parses = [
        semantic_understand("احسب 20*5"),
        semantic_understand("calculate 20*5"),
        semantic_understand("احسب 20*5 please"),
    ]
    contracts = [SemanticContract.from_parse(item) for item in parses]

    assert contracts[0].language == "ar"
    assert contracts[1].language == "en"
    assert contracts[2].language == "mixed"
    assert {item.intent for item in contracts} == {"calculate"}
    assert {item.operation for item in contracts} == {"calculate"}
    assert {item.expression for item in contracts} == {"20*5"}
    for item in contracts:
        payload = item.to_dict()
        for field in ("intent", "operation", "target", "key", "value", "expression", "reference", "language", "speech_act", "conversation_class"):
            assert field in payload


def test_memory_and_reference_fields_are_canonical(monkeypatch, tmp_path):
    monkeypatch.setenv("SHURY_NLP_MODE", "off")
    from app.knowledge.memory import Memory
    mem = Memory(tmp_path / "memory.db")
    first = semantic_understand("أنا من الأقصر", mem=mem, session_id="s1")
    contract = SemanticContract.from_parse(first)
    assert contract.operation == "remember_fact"
    assert contract.key in {"origin", ""}
    assert contract.value in {"الأقصر", "الاقصر"}


def test_canonical_expression_slot_is_not_overwritten_by_generic_mixed_language_capture(monkeypatch):
    monkeypatch.setenv("SHURY_NLP_MODE", "off")
    for text in ("احسب 20*5 please", "calculate 20*5 please"):
        contract = SemanticContract.from_parse(semantic_understand(text))
        assert contract.expression == "20*5"
        assert dict(contract.slots)["operation:expression"] == "20*5"
