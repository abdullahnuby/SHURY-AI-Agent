from app.evaluation.simulations import run_real_user_simulation

def test_layer6_real_user_simulation(tmp_path):
    report = run_real_user_simulation(tmp_path / "sim")
    assert report["pass_rate"] == 1.0
    assert report["safety_violations"] == 0
    assert report["reproducible"] is True
