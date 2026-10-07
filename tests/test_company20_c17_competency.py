from __future__ import annotations

import pytest

from app.learning.store import LearningStore
from app.organization import CompanyCompetencyCalibrator, ExecutiveTeamFormer
from app.organization.capability_planning import CapabilityCandidate


def _seed(learning, *, capability: str, specialist: str, department: str, tool: str, successes: int, failures: int):
    for index in range(successes):
        learning.record_company_delegation_outcome(
            capability=capability,
            department=department,
            specialist=specialist,
            skill_key="",
            tool=tool,
            verified=True,
            run_id=f"{specialist}-ok-{index}",
        )
    for index in range(failures):
        learning.record_company_delegation_outcome(
            capability=capability,
            department=department,
            specialist=specialist,
            skill_key="",
            tool=tool,
            verified=False,
            run_id=f"{specialist}-fail-{index}",
            failure_class="execution",
        )


def test_c17_calibration_is_conservative_and_uses_canonical_evidence(tmp_path):
    learning = LearningStore(tmp_path / "learning.db")
    _seed(learning, capability="c17-cap", specialist="data:data-analyst", department="data", tool="tool-a", successes=1, failures=0)
    calibrator = CompanyCompetencyCalibrator(learning)
    profile = calibrator.profile_for(capability="c17-cap", specialist="data:data-analyst", tool="tool-a")
    assert profile is not None
    assert profile.observed_rate == 1.0
    assert profile.conservative_rate < profile.observed_rate
    assert profile.evidence_state == "insufficient_evidence"


def test_c17_supported_competency_requires_repeated_verified_success(tmp_path):
    learning = LearningStore(tmp_path / "learning.db")
    _seed(learning, capability="c17-cap", specialist="data:data-analyst", department="data", tool="tool-a", successes=20, failures=0)
    calibrator = CompanyCompetencyCalibrator(learning)
    profile = calibrator.profile_for(capability="c17-cap", specialist="data:data-analyst", tool="tool-a")
    assert profile is not None
    assert profile.attempts == 20
    assert profile.conservative_rate >= 0.75
    assert profile.evidence_state == "proven"


def test_c17_team_history_score_blends_canonical_competency_evidence_after_skill_history():
    class Skill:
        success_count = 4
        failure_count = 0
        confidence = 0.5

    class SkillBank:
        def get(self, key):
            assert key == "skill:c17"
            return Skill()

    class Competency:
        def score(self, **kwargs):
            return 0.9

    candidate = CapabilityCandidate(
        requirement_key="r1", tool="tool-a", skill_key="skill:c17", capability="c17-cap",
        department="data", specialist="data:data-analyst", fit=1.0, cost=1.0,
        risk="low", verification_level="standard", reason="test",
    )
    base = ExecutiveTeamFormer._history_score(candidate, SkillBank())
    calibrated = ExecutiveTeamFormer._history_score(candidate, SkillBank(), Competency())
    assert calibrated > base


def test_c17_calibrator_fails_closed_without_canonical_learning_store():
    with pytest.raises(TypeError):
        CompanyCompetencyCalibrator(None)


def test_c17_cli_reports_calibrated_profiles(monkeypatch, capsys, tmp_path):
    import app.interfaces.cli as cli
    from app.organization import CompanyCompetencyCalibrator

    monkeypatch.chdir(tmp_path)
    inputs = iter(["/company-competency c17-cap|data:data-analyst", "exit"])
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))
    learning = LearningStore(tmp_path / "learning.db")
    _seed(learning, capability="c17-cap", specialist="data:data-analyst", department="data", tool="tool-a", successes=4, failures=1)
    monkeypatch.setenv("AGENT_LEARNING_DB", str(tmp_path / "learning.db"))
    # The CLI resolves its canonical LearningStore from the environment.
    cli.main()
    out = capsys.readouterr().out
    assert '"capability": "c17-cap"' in out
    assert '"specialist": "data:data-analyst"' in out
    assert '"conservative_rate"' in out
