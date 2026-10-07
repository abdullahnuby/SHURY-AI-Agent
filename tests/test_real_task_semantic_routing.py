from app.intelligence.semantic import parser as semantic_parser


def test_data_report_capability_is_selected_from_typed_task_structure(monkeypatch):
    monkeypatch.setattr(semantic_parser, "apply_brain_priors", lambda *args, **kwargs: args[1])
    import app.intelligence.semantic.intents as intents
    monkeypatch.setattr(intents, "rank_query_against_texts", lambda *args, **kwargs: [])

    text = (
        "حلل ملف workspace/sales.csv تحليلاً كاملاً. اكتشف شكل البيانات، الأعمدة وأنواعها، "
        "القيم المفقودة، التكرارات، والقيم الشاذة. حدد أهم الأنماط والنتائج المهمة، ثم "
        "أنشئ تقريرًا منظمًا واحفظه في workspace/sales_report.md. بعد ذلك راجع التقرير."
    )
    parsed = semantic_parser.SemanticInterpreter().parse(text, world={"last_goal": "", "last_outputs": {}}, registry={})
    assert parsed.needs_clarification is False
    assert parsed.top_intent is not None
    assert parsed.top_intent.name == "data_analysis_report"
    assert parsed.top_intent.capability == "data_analysis_report"
