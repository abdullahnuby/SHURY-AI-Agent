from pathlib import Path

from app.brain.kernel import CognitiveKernel
from app.brain.learning import BrainExperienceStore
from app.brain.store import BrainStateStore
from app.knowledge.memory import Memory
from app.skills.builtin import BUILTIN_SKILLS
from app.skills.registry import SkillBank


def _install_builtin(skill_bank: SkillBank, key: str):
    spec = next(x for x in BUILTIN_SKILLS if x["key"] == key)
    skill_bank.upsert(**spec)


def test_real_data_report_task_executes_end_to_end(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    csv = workspace / "sales.csv"
    csv.write_text("date,region,sales\n2026-01-01,Cairo,100\n2026-01-02,Cairo,120\n2026-01-03,Alex,1000\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_WORKSPACE", str(workspace))

    skill_db = tmp_path / "skills.db"
    skill_bank = SkillBank(path=skill_db, bootstrap=False)
    _install_builtin(skill_bank, "builtin:data-analysis-report")

    kernel = CognitiveKernel(
        memory=Memory(tmp_path / "memory.db"),
        state_store=BrainStateStore(tmp_path / "brain.db"),
        experience_store=BrainExperienceStore(tmp_path / "experience.db"),
        skill_bank=skill_bank,
    )

    result = kernel.act_structured({
        "goal": "حلل ملف workspace/sales.csv وأنشئ تقريرًا في workspace/sales_report.md ثم راجع التقرير",
        "operation": "data_analysis_report",
        "capability": "data_analysis_report",
        "target": "workspace/sales.csv",
        "slots": {
            "path": "workspace/sales.csv",
            "output_path": "workspace/sales_report.md",
        },
    }, approve=lambda _tool, _args: True, session_id="real-task", max_steps=3)

    report = workspace / "sales_report.md"
    assert result.status == "completed"
    assert "Analysis report created and verified" in result.response or "تم تحليل الملف وإنشاء التقرير والتحقق منه" in result.response
    assert not any(e.get('kind') == 'episodic_memory_error' for e in result.state.trace)
    assert any(e.get('kind') == 'episodic_memory_recorded' for e in result.state.trace)
    assert result.state.selected_skill is not None
    assert result.state.selected_skill.key == "builtin:data-analysis-report"
    assert result.state.plan
    assert result.state.plan[0].skill_key == "builtin:data-analysis-report"
    assert report.is_file()
    content = report.read_text(encoding="utf-8")
    assert "# Data Analysis Report" in content
    assert "## Key Findings" in content

