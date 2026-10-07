from app.intelligence.semantic.parser import semantic_understand


GOAL = "حلل ملفات CSV الموجودة داخل workspace بشكل recursive. لكل ملف CSV قابل للتحليل، احسب عدد الصفوف والأعمدة وإجمالي القيم في الأعمدة الرقمية، ثم قارن الملفات وحدد الملف الذي يحتوي على أكبر إجمالي رقمي. بعد ذلك انقل ملف CSV صاحب أكبر إجمالي إلى workspace/processed_data مع الحفاظ على محتواه وعدم استبدال أي ملف موجود، وأنشئ workspace/company_data_report.md يحتوي على نتائج التحليل والملف الذي تم اختياره ومساره الجديد. ثم اقرأ التقرير مرة أخرى وتحقق من أن نتائج التحليل مطابقة للملفات الأصلية، وأن الملف المنقول موجود في المسار الجديد وأن بصمة محتواه قبل النقل وبعده متطابقة، وأن الملفات الأخرى لم تتغير."


def test_cross_department_goal_is_typed_before_planning(monkeypatch):
    import app.intelligence.semantic.parser as parser
    monkeypatch.setattr(parser, "candidates", lambda _text: [])
    monkeypatch.setattr(parser, "apply_brain_priors", lambda _original, base, _registry, speech_act: base)
    parsed = semantic_understand(GOAL, mem=None, world={}, registry={})
    assert parsed.top_intent is not None
    assert parsed.top_intent.name == "cross_department_data_move"
    assert not parsed.needs_clarification


def test_cross_department_capability_maps_to_executable_contract():
    from app.planning.capabilities import INTENT_TO_CAPABILITY
    assert INTENT_TO_CAPABILITY["cross_department_data_move"] == "cross_department_data_move"


def test_canonical_brain_structured_goal_plans_cross_department_workflow():
    from app.brain import CognitiveKernel
    kernel = CognitiveKernel()
    payload = {
        "goal": "analyze csv collection, choose the largest, move it, and verify the report",
        "operation": "cross_department_data_move",
        "capability": "cross_department_data_move",
        "target": "workspace",
        "target_type": "directory",
        "slots": {"output_path": "workspace/company_data_report.md"},
        "constraints": [],
        "temporal_requirements": [],
        "required_evidence": [],
        "priority": 0.8,
        "language": "en",
    }
    result = kernel.think_structured(payload)
    tools = [step.tool for step in result.state.plan]
    assert tools == [
        "list_files_recursive", "analyze_csv_collection", "move_workspace_file",
        "create_company_data_report", "read_file"
    ]
    assert [item["department"] for item in result.state.company_assignments] == [
        "operations", "data", "operations", "data", "operations"
    ]
    assert result.state.decision.kind == "execute"
