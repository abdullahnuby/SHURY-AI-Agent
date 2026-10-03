from app.evaluation.lab_models import ExpectedOutcome, StepTrace, Trajectory
from app.evaluation.scorers import score_trajectory, horizon_survival


def _t(ok=True):
    return Trajectory("r", "t", "goal", "completed" if ok else "failed", "done", [StepTrace(1,"s1","calculator",{},"done" if ok else "failed",ok,1,output=4)])


def test_safety_forbidden_tool():
    t = _t(True)
    t.steps.append(StepTrace(2,"s2","memory_forget_all",{},"done",True,1))
    scores, failure = score_trajectory(t, ExpectedOutcome(forbidden_tools=("memory_forget_all",)))
    assert any(s.name == "safety" and not s.passed for s in scores)
    assert failure is not None
    assert failure.category == "safety_or_scope"


def test_horizon_survival():
    a = Trajectory("a","a","g","completed","",[
        StepTrace(1,"s1","a",{},"done",True,1), StepTrace(2,"s2","b",{},"done",True,1)])
    b = Trajectory("b","b","g","completed","",[
        StepTrace(1,"s1","a",{},"done",True,1), StepTrace(2,"s2","b",{},"failed",False,1)])
    assert horizon_survival([a,b], 2)[1] == 1.0
    assert horizon_survival([a,b], 2)[2] == 0.5
