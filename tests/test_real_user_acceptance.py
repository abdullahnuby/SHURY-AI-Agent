import app.knowledge.memory as memory_mod
from app.knowledge.memory import get_memory
from app.runtime.cognitive_agent import run_cognitive


def _setup(tmp_path, monkeypatch):
    memory_mod.configure(tmp_path / "memory.db")
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "sample.py").write_text("print(\'hello\')\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_WORKSPACE", str(ws))
    monkeypatch.setenv("AGENT_LEARNING_DB", str(tmp_path / "learning.db"))
    monkeypatch.setenv("AGENT_SKILLS_DB", str(tmp_path / "skills.db"))
    monkeypatch.setenv("SHURY_NLP_MODE", "off")
    return ws


def test_real_user_calculation_journey(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    s = run_cognitive("calculate 17*6", approve=lambda *a, **k: True, max_steps=3)
    assert s.status == "completed"
    assert s.plan.steps[0].tool == "calculator"
    assert s.plan.steps[0].output == 102


def test_real_user_memory_save_then_recall(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    s1 = run_cognitive("my name is Abdullah", approve=lambda *a, **k: True, max_steps=2)
    s2 = run_cognitive("what's my name?", approve=lambda *a, **k: True, max_steps=2)
    assert s1.status == "completed" and s2.status == "completed"
    assert s2.plan.steps[0].output == "Abdullah"


def test_real_user_arabic_memory_journey(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    s1 = run_cognitive("أنا اسمي عبدالله", approve=lambda *a, **k: True, max_steps=2)
    s2 = run_cognitive("ما اسمي؟", approve=lambda *a, **k: True, max_steps=2)
    assert s1.status == "completed" and s2.status == "completed"
    assert s2.plan.steps[0].output == "عبدالله"


def test_real_user_ambiguous_request_gets_clarification(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    s = run_cognitive("analyze the file and find anomalies")
    assert s.status == "needs_user"
    assert s.final_message
    assert not s.plan.steps


def test_real_user_project_inspection_journey(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    s = run_cognitive("inspect the project and tell me what stack it uses", approve=lambda *a, **k: True, max_steps=2)
    assert s.status == "completed"
    assert s.plan.steps[0].tool == "inspect_project"
    assert s.plan.steps[0].output["metadata"]["files"] == ["sample.py"]


def test_real_user_multi_step_calculation_and_explicit_result_save(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    s = run_cognitive("calculate 12*7 and save result as total", approve=lambda *a, **k: True, max_steps=4)
    assert s.status == "completed"
    assert [x.tool for x in s.plan.steps] == ["calculator", "remember_result"]
    assert get_memory().get_fact("total") == "84"


def test_real_user_dataset_profile_journey(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    (tmp_path / "workspace" / "sales.csv").write_text("amount,region\n10,A\n20,B\n30,A\n", encoding="utf-8")
    s = run_cognitive("profile the dataset", approve=lambda *a, **k: True, max_steps=2)
    assert s.status == "completed"
    assert s.plan.steps[0].tool == "profile_dataset"


def test_real_user_time_question_does_not_route_to_memory(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    s = run_cognitive("what's the time?", approve=lambda *a, **k: True, max_steps=2)
    assert s.status == "completed"
    assert s.plan.steps[0].tool == "get_time"


def test_real_user_final_claim_without_support_is_rejected(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    s = run_cognitive("give me an unsupported answer", max_steps=1)
    assert s.status == "needs_user"
    assert "goal" in s.final_message.lower() or "support" in s.final_message.lower()


def test_semantic_route_is_deterministic_and_retrieval_native(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    s = run_cognitive("calculate 2+2", approve=lambda *a, **k: True, max_steps=2)
    assert s.status == "completed"
    assert s.plan.diagnostics["semantic_engine"] == "arabic-retrieval-v1.0"


def test_last_result_is_isolated_between_sessions(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    first = run_cognitive("calculate 9*9", approve=lambda *a, **k: True, max_steps=2, session_id="session-a")
    second = run_cognitive("what was the last result", approve=lambda *a, **k: True, max_steps=2, session_id="session-b")
    assert first.status == "completed"
    assert second.status == "completed"
    assert second.plan.steps[0].status == "done"
    assert "81" not in str(second.plan.steps[0].output)
    assert get_memory().last_completed_output(session_id="session-b") is None
    assert get_memory().last_completed_output(session_id="session-a")["output"] == 81


def test_last_result_is_available_in_same_canonical_session(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    first = run_cognitive("calculate 25 * 4", approve=lambda *a, **k: True, max_steps=2, session_id="session-a")
    second = run_cognitive("what was the last result", approve=lambda *a, **k: True, max_steps=2, session_id="session-a")

    assert first.status == "completed"
    assert first.plan.steps[0].output == 100
    assert second.status == "completed"
    assert "100" in str(second.final_message) or any(step.output == 100 for step in second.plan.steps)


def test_saved_calculation_remains_the_last_meaningful_result(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    first = run_cognitive(
        "calculate 12 * 7 and save result as total",
        approve=lambda *a, **k: True,
        max_steps=4,
        session_id="session-a",
    )
    second = run_cognitive(
        "what was the last result",
        approve=lambda *a, **k: True,
        max_steps=2,
        session_id="session-a",
    )

    assert first.status == "completed"
    assert second.status == "completed"
    assert "84" in str(second.final_message) or any(step.output == 84 for step in second.plan.steps)


def test_session_memory_is_visible_to_same_session_only(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    mem = get_memory()
    mem.remember("Cairo", kind="fact", key="city", session_id="session-a", source="user", reason="test")
    assert mem.recall_context("city", session_id="session-a")["semantic"]
    assert not mem.recall_context("city", session_id="session-b")["working"]
