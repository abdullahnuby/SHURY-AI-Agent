from app.brain.deliberation import deliberate
from app.brain.models import CognitiveState, PlannedAction, SemanticFrame, GoalSpec


def test_data_analysis_report_is_an_executable_capability():
    text = "حلل ملف workspace/sales.csv وأنشئ تقريرًا في workspace/sales_report.md ثم راجع التقرير"
    frame = SemanticFrame(
        text=text,
        language="ar",
        speech_act="command",
        requested_operation="data_analysis_report",
        slots=(
            ("path", "workspace/sales.csv"),
            ("output_path", "workspace/sales_report.md"),
        ),
        uncertainty=(),
    )
    state = CognitiveState(
        user_text=text,
        session_id="test-session",
        semantic=frame,
        goal=GoalSpec(
            name="data_analysis_report",
            objective=text,
            required_capability="data_analysis_report",
        ),
        plan=(PlannedAction(
            "s1", "data_analysis_report", "create_data_analysis_report",
            {"path": "workspace/sales.csv", "output_path": "workspace/sales_report.md"},
        ),),
    )
    decision = deliberate(state)
    assert decision.kind == "execute"
    assert decision.tool == "create_data_analysis_report"
    assert decision.capability == "data_analysis_report"
