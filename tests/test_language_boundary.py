from __future__ import annotations

from app.intelligence.language import detect_language, normalize_text, prepare
from app.intelligence.semantic.contract import SemanticContract
from app.intelligence.semantic.models import IntentCandidate, SemanticParse


def test_language_profiles_are_general_not_capability_specific():
    assert detect_language("هذا ملف") == "ar"
    assert detect_language("Analyze the file") == "en"
    assert detect_language("حلل file") == "mixed"


def test_arabic_normalization_collapses_common_orthographic_variants():
    assert normalize_text("إختبارٌ") == "اختبار"
    assert normalize_text("كیف؟") == "كيف?"


def test_language_envelope_exposes_variant_without_leaking_it_downstream():
    envelope = prepare("احنا عايزين نحلل الملف")
    assert envelope.language == "ar"
    assert envelope.variant == "ar-eg"
    assert envelope.token_count > 0


def test_semantic_contract_is_language_neutral():
    for language in ("ar", "en", "mixed"):
        parse = SemanticParse(
            original="language-specific surface",
            normalized="language neutral semantic content",
            language=language,
            canonical_goal="analyze data",
            intent_candidates=[IntentCandidate("data_analysis", 0.9, (), "data_analysis")],
        )
        contract = SemanticContract.from_parse(parse)
        assert contract.capability == "data_analysis"
        assert contract.executable_operation == "data_analysis"
        assert contract.to_dict()["language"] == language
        assert "language_variant" in contract.to_dict()
