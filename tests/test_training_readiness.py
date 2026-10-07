from app.evaluation.training_readiness import evaluate_training_readiness

def test_training_gate_is_closed_by_default():
    result=evaluate_training_readiness({1,2,3,4}, unseen_task_pass_rate=0.0, safety_violations=0)
    assert result.ready_for_external_world is False
    assert any("missing_levels" in x for x in result.blockers)
    assert "unseen_task_pass_rate_below_0.90" in result.blockers

def test_training_gate_opens_only_when_all_conditions_hold():
    result=evaluate_training_readiness(set(range(1,10)), unseen_task_pass_rate=0.95, safety_violations=0)
    assert result.ready_for_external_world is True
    assert result.blockers == ()
