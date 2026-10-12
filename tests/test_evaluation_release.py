import json
from pathlib import Path

from app.evaluation import EvaluationLab, EvalScenario, ExpectedOutcome, release_gate
from app.evaluation.lab_models import StepTrace, Trajectory
from app.evaluation.regression import wilson_interval
from app.evaluation.scorers import score_trajectory


def test_release_gate_requires_reproducible_and_zero_safety():
    report={"pass_count": 3,"run_count":3,"pass_rate":1.0,"mean_score":1.0,"safety_violations":1,"reproducible":True}
    gate=release_gate(report)
    assert gate["release_allowed"] is False
    assert "safety violations detected" in gate["reasons"]


def test_wilson_interval_is_bounded():
    lo,hi=wilson_interval(3,3)
    assert 0 <= lo <= hi <= 1
    assert hi == 1.0


def test_frame_condition_detects_unexpected_workspace_change():
    t=Trajectory("r","t","g","completed","done",[] ,world_before={},world_after={},changed_paths=("keep.txt",))
    scores,failure=score_trajectory(t, ExpectedOutcome(allowed_paths=("output.txt",)))
    safety=next(x for x in scores if x.name=="safety")
    assert safety.passed is False
    assert failure.category=="safety_or_scope"


def test_repeated_trials_track_pass_at_n_and_all_n(tmp_path):
    from app.domain.state import AgentState
    from app.domain.plan import Plan, PlanStep
    from app.evaluation.lab_models import EvalScenario, ExpectedOutcome
    calls=[]
    def agent(scenario, rep):
        state=AgentState(goal=scenario.goal, status="completed")
        state.plan=Plan([PlanStep("s1","calculator",{"expression":"1+1"},status="done",output=2,attempts=1)])
        calls.append(rep)
        return state
    import app.knowledge.memory as memory_mod
    memory_mod.configure(tmp_path/'memory.db')
    scenario=EvalScenario("repeat","repeat","calculate 1+1",expected=ExpectedOutcome(status="completed",required_tools=("calculator",)),repetitions=3)
    report=EvaluationLab(output_dir=tmp_path/'evals').run([scenario],agent=agent)
    agg=report.scenario_results[0]
    assert agg.pass_at_n == 1.0 and agg.all_n == 1.0 and agg.repetitions == 3
    assert calls == [1,2,3]


def test_markdown_report_rendering():
    from app.evaluation.reporting.markdown import render_report_markdown
    text = render_report_markdown({
        "run_id":"r1","version":"22.9.0","pass_rate":1.0,"mean_score":0.99,
        "safety_violations":0,"reproducible":True,
        "scenario_results":[{"scenario_id":"x","pass_rate":1.0,"mean_score":1.0,"mean_steps":1.0,"pass_at_n":1.0,"all_n":1.0,"failure_patterns":{}}],
        "failure_patterns":{}
    })
    assert "# Agent Evaluation Report r1" in text
    assert "x" in text
