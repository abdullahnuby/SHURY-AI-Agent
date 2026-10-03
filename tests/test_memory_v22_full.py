from app.knowledge.memory import Memory
from app.runtime.agent import run_agent
from app.intelligence.understanding import understand


def test_memory_observes_episode_and_promotes_explicit_fact(tmp_path):
    m = Memory(tmp_path / "m.db")
    out = m.observe("my favorite editor is VS Code", assistant_text="saved", outcome="completed", session_id="s1", run_id="r1")
    assert out["promoted"]
    assert m.get_fact("favorite editor") == "VS Code"
    assert m.recent_episodes("s1", 2)


def test_memory_updates_fact_without_losing_history(tmp_path):
    m = Memory(tmp_path / "m.db")
    m.set_fact("city", "Luxor")
    m.set_fact("city", "Cairo")
    assert m.get_fact("city") == "Cairo"
    hist = m.memory_history(key="city")
    assert any(h["action"] == "SUPERSEDE" and h["old_value"] == "Luxor" for h in hist)


def test_memory_search_finds_episode_and_fact(tmp_path):
    m = Memory(tmp_path / "m.db")
    m.set_fact("project", "KEMEX")
    m.add_episode("we discussed KEMEX architecture", "done", session_id="s1")
    hits = m.search_memory("KEMEX", top_k=10)
    assert any(h["kind"] == "fact" for h in hits)
    assert any(h["kind"] == "episode" for h in hits)


def test_memory_temporal_expiry_hides_fact(tmp_path):
    m = Memory(tmp_path / "m.db")
    m.remember("temporary", kind="fact", key="status", expires_at="2000-01-01T00:00:00")
    assert m.get_fact("status") is None
    assert m.search_memory("status") == []


def test_memory_working_scope(tmp_path):
    m = Memory(tmp_path / "m.db")
    m.working_put("session-a", "current project is KEMEX", priority=5)
    assert m.working_recall("session-a")
    assert m.working_recall("session-b") == []


def test_memory_graph_and_provenance(tmp_path):
    m = Memory(tmp_path / "m.db")
    mid = m.remember("KEMEX", kind="fact", key="project", source_ref="episode:1")
    m.relate("project", "name", "KEMEX", source_memory_id=mid)
    rel = m.graph("project")
    assert rel and rel[0]["object"] == "KEMEX"
    assert rel[0]["source_memory_id"] == mid


def test_memory_forget_all(tmp_path):
    m = Memory(tmp_path / "m.db")
    m.set_fact("name", "Abdullah")
    m.add_note("private note")
    m.add_episode("hello", "hi", session_id="global")
    result = m.forget_all()
    assert result["deleted_memory_items"] >= 2
    assert m.get_fact("name") is None
    assert m.profile() == []
    assert m.recent_episodes() == []


def test_natural_memory_profile_and_specific_recall():
    assert understand("what do you remember about me?").top_intent.name == "memory_profile"
    assert understand("do you remember my name?").top_intent.name == "recall_fact"


def test_agent_cross_run_memory(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    s1 = run_agent("my favorite color is blue", approve=lambda *_: True)
    assert s1.status == "completed"
    s2 = run_agent("what do you remember about me?")
    assert s2.status == "completed"
    assert s2.plan.steps[0].tool == "memory_profile"


def test_preference_dedup_and_profile(tmp_path):
    m = Memory(tmp_path / "m.db")
    a = m.observe("I prefer dark mode", session_id="s1")
    b = m.observe("I prefer dark mode", session_id="s1")
    assert a["promoted"] and b["promoted"]
    rows = [r for r in m.profile() if r["kind"] == "preference"]
    assert len(rows) == 1


def test_recall_fact_falls_back_to_hybrid_memory_search(tmp_path):
    m = Memory(tmp_path / "m.db")
    m.add_note("KEMEX architecture decision: use modular memory")
    result = m.search_memory("KEMEX", top_k=5)
    assert result and result[0]["kind"] == "note"


def test_agent_natural_preference_and_profile_flow(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    saved = run_agent("I prefer dark mode", approve=lambda *_: True)
    assert saved.status == "completed"
    assert saved.plan.steps[0].tool == "remember_memory"
    profile = run_agent("what do you remember about me?")
    assert profile.status == "completed"
    assert profile.plan.steps[0].tool == "memory_profile"
    assert any(x["kind"] == "preference" for x in profile.plan.steps[0].output)


def test_agent_full_memory_forget_requires_approval(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    run_agent("my name is Abdullah", approve=lambda *_: True)
    denied = run_agent("forget everything about me", approve=lambda *_: False)
    assert denied.status == "cancelled"
    allowed = run_agent("forget everything about me", approve=lambda *_: True)
    assert allowed.status == "completed"
    assert mm.get_memory().profile() == []


def test_question_never_becomes_name_save(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    run_agent("my name is Abdullah", approve=lambda *_: True)
    s = run_agent("do you remember my name?")
    assert s.status == "completed"
    assert s.plan.steps[0].tool == "recall_fact"
    assert s.plan.steps[0].output == "Abdullah"


def test_search_my_memory_does_not_route_to_profile(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    run_agent("my project is KEMEX", approve=lambda *_: True)
    s = run_agent("search my memory KEMEX")
    assert s.status == "completed"
    assert s.plan.steps[0].tool == "search_memory"


def test_user_provenance_survives_automatic_confirmation(tmp_path):
    m = Memory(tmp_path / "m.db")
    m.set_fact("name", "Abdullah", source="user")
    m.observe("my name is Abdullah", session_id="s1", run_id="r1")
    rows = [r for r in m.profile() if r["key"] == "name"]
    assert rows and rows[0]["source"] == "user"


def test_memory_stats_is_operational(tmp_path):
    m = Memory(tmp_path / "m.db")
    m.set_fact("name", "Abdullah")
    stats = m.memory_stats()
    assert stats["episodes"] == 0
    assert stats["items"]["fact:active"] >= 1


def test_memory_procedure_promotes_after_repeated_success(tmp_path):
    m = Memory(tmp_path / "m.db")
    meta = {"goal_key": "analyze kemex", "plan_steps": ["data_profile", "rag"]}
    first = m.observe("Analyze KEMEX", outcome="completed", metadata=meta)
    assert first["procedural"] is None
    second = m.observe("Analyze KEMEX", outcome="completed", metadata=meta)
    assert second["procedural"]
    hits = m.procedural_memory("Analyze KEMEX")
    assert hits and hits[0]["metadata"]["tool_sequence"] == ["data_profile", "rag"]


def test_memory_profile_excludes_notes_and_procedures(tmp_path):
    m = Memory(tmp_path / "m.db")
    m.set_fact("name", "Abdullah")
    m.add_note("KEMEX architecture note")
    m.remember("calculator -> save_note", kind="procedural", key="test workflow")
    kinds = {row["kind"] for row in m.profile()}
    assert kinds <= {"fact", "preference", "goal", "profile"}


def test_memory_blocks_secret_persistence(tmp_path):
    m = Memory(tmp_path / "m.db")
    import pytest
    with pytest.raises(ValueError):
        m.set_fact("api_key", "secret=abcd")
    with pytest.raises(ValueError):
        m.add_note("my password is supersecret")
    assert m.search_memory("supersecret") == []


def test_memory_valid_at_future_is_not_recalled(tmp_path):
    m = Memory(tmp_path / "m.db")
    m.remember("future value", kind="fact", key="state", valid_at="2999-01-01T00:00:00")
    assert m.get_fact("state") is None
    assert m.search_memory("state") == []


def test_memory_benchmark_is_green():
    from app.evaluation.memory_benchmark import run_memory_benchmark
    result = run_memory_benchmark()
    assert result["passed"] == result["total"]


def test_memory_export_restore_round_trip(tmp_path):
    source = Memory(tmp_path / "source.db")
    source.set_fact("name", "Abdullah")
    source.add_episode("we discussed KEMEX", "done", session_id="s1")
    payload = source.export_memory(include_history=True, include_episodes=True)
    target = Memory(tmp_path / "target.db")
    result = target.restore_memory(payload, include_episodes=True)
    assert result["imported_items"] >= 1
    assert target.get_fact("name") == "Abdullah"
    assert target.recent_episodes("s1")


def test_memory_profile_hides_future_and_invalid_items(tmp_path):
    m = Memory(tmp_path / "m.db")
    m.remember("future", kind="fact", key="future", valid_at="2999-01-01T00:00:00")
    m.remember("old", kind="fact", key="old", invalid_at="2000-01-01T00:00:00")
    assert all(r["key"] not in {"future", "old"} for r in m.profile())


def test_memory_health_tool_is_registered():
    from app.runtime.registry import load_tools
    assert "memory_health" in load_tools()


def test_forget_my_name_canonicalizes_key(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    run_agent("my name is Abdullah", approve=lambda *_: True)
    forgotten = run_agent("forget my name", approve=lambda *_: True)
    assert forgotten.status == "completed"
    assert mm.get_memory().get_fact("name") is None


def test_natural_preference_question_recalls_saved_preference(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    run_agent("my favorite programming language is Python", approve=lambda *_: True)
    out = run_agent("what programming language do I prefer?")
    assert out.status == "completed"
    assert out.plan.steps[0].tool == "recall_fact"
    assert out.plan.steps[0].output == "Python"


def test_generic_natural_fact_question_recalls_key(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    run_agent("my city is Cairo", approve=lambda *_: True)
    out = run_agent("what is my city?")
    assert out.status == "completed"
    assert out.plan.steps[0].tool == "recall_fact"
    assert out.plan.steps[0].output == "Cairo"


def test_forget_my_generic_key_uses_same_canonical_key(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    run_agent("my city is Cairo", approve=lambda *_: True)
    out = run_agent("forget my city", approve=lambda *_: True)
    assert out.status == "completed"
    assert mm.get_memory().get_fact("city") is None


def test_recall_after_forget_does_not_surface_stale_episode_as_fact(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    run_agent("my city is Cairo", approve=lambda *_: True)
    run_agent("forget my city", approve=lambda *_: True)
    out = run_agent("what is my city?")
    assert out.status == "completed"
    assert out.plan.steps[0].tool == "recall_fact"
    assert isinstance(out.plan.steps[0].output, str)
    assert "مفيش معلومة" in out.plan.steps[0].output


def test_save_result_as_key_persists_calculation_output(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    out = run_agent("calculate 25*16 then save the result as total", approve=lambda *_: True)
    assert out.status == "completed"
    assert [s.tool for s in out.plan.steps] == ["calculator", "remember_result"]
    assert mm.get_memory().get_fact("total") == "400"


def test_trivial_single_step_retrieval_is_not_procedural_memory(tmp_path):
    m = Memory(tmp_path / "m.db")
    meta = {"goal_key": "what is my city?", "plan_steps": ["recall_fact"]}
    m.observe("what is my city?", outcome="completed", metadata=meta)
    m.observe("what is my city?", outcome="completed", metadata=meta)
    assert m.procedural_memory("what is my city?") == []


def test_cross_turn_save_previous_result_uses_last_completed_output(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    run_agent("calculate 7*8")
    out = run_agent("I meant save the result as total", approve=lambda *_: True)
    assert out.status == "completed"
    assert out.plan.steps[0].tool == "remember_result" or out.plan.steps[0].tool == "remember_last_result"
    assert mm.get_memory().get_fact("total") == "56"


def test_generic_fact_question_and_preference_question(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    run_agent("my city is Cairo", approve=lambda *_: True)
    run_agent("my preferred report format is Excel", approve=lambda *_: True)
    assert run_agent("what is my city?").plan.steps[0].output == "Cairo"
    assert run_agent("what report format do I prefer?").plan.steps[0].output == "Excel"


def test_explicit_human_correction_reuses_previous_assignment_key(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    run_agent("my city is Luxor", approve=lambda *_: True)
    out = run_agent("No, I mean Cairo", approve=lambda *_: True)
    assert out.status == "completed"
    assert mm.get_memory().get_fact("city") == "Cairo"


def test_cross_turn_previous_result_uses_dedicated_tool(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    run_agent("calculate 7*8")
    out = run_agent("I meant save the previous result as total", approve=lambda *_: True)
    assert out.status == "completed"
    assert out.plan.steps[0].tool == "remember_last_result"
    assert mm.get_memory().get_fact("total") == "56"


def test_correction_after_recall_question_uses_previous_key(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    run_agent("my city is Luxor", approve=lambda *_: True)
    run_agent("what is my city?")
    out = run_agent("No, I mean Cairo", approve=lambda *_: True)
    assert out.status == "completed"
    assert mm.get_memory().get_fact("city") == "Cairo"


def test_memory_search_hides_failed_or_needs_user_episodes(tmp_path):
    m = Memory(tmp_path / "m.db")
    m.add_episode("failed topic", "no", outcome="failed")
    m.add_episode("needs topic", "clarify", outcome="needs_user")
    m.add_episode("successful topic", "done", outcome="completed")
    hits = m.search_memory("topic", top_k=10)
    values = [h["value"] for h in hits if h["kind"] == "episode"]
    assert "successful topic" in values
    assert "failed topic" not in values
    assert "needs topic" not in values


def test_forget_preferred_alias_finds_stored_preferred_key(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    run_agent("my preferred report format is Excel", approve=lambda *_: True)
    out = run_agent("forget my report format", approve=lambda *_: True)
    assert out.status == "completed"
    assert mm.get_memory().get_fact("preferred report format") is None


def test_arabic_name_is_extracted_as_name(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    out = run_agent("اسمي عبدالله", approve=lambda *_: True)
    assert out.status == "completed"
    assert mm.get_memory().get_fact("name") == "عبدالله"


def test_arabic_preference_is_remembered(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    out = run_agent("أنا بفضل الوضع الداكن", approve=lambda *_: True)
    assert out.status == "completed"
    assert out.plan.steps[0].tool == "remember_memory"
    assert any(row["kind"] == "preference" and row["value"] == "الوضع الداكن" for row in mm.get_memory().profile())


def test_last_result_is_recalled_in_arabic(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    run_agent("احسب 12 * 7", session_id="last-result-session")
    out = run_agent("ما هو الناتج؟", session_id="last-result-session")
    assert out.status == "completed"
    assert out.plan.steps[0].tool == "recall_last_result"
    assert out.plan.steps[0].output == 84


def test_arabic_name_and_preference_end_to_end(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    a = run_agent("اسمي عبدالله", approve=lambda *_: True)
    b = run_agent("أنا بفضل الوضع الداكن", approve=lambda *_: True)
    c = run_agent("ما اسمي؟")
    assert a.status == "completed"
    assert b.status == "completed"
    assert c.plan.steps[0].tool == "recall_fact"
    assert c.plan.steps[0].output == "عبدالله"


def test_arabic_last_result_end_to_end(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    run_agent("احسب 12 * 7", session_id="last-result-session")
    out = run_agent("ما هو الناتج؟", session_id="last-result-session")
    assert out.status == "completed"
    assert out.plan.steps[0].tool == "recall_last_result"
    assert out.plan.steps[0].output == 84


def test_origin_alias_supports_city_recall_and_forget(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    run_agent("I'm from Luxor", approve=lambda *_: True)
    recalled = run_agent("what is my city?")
    assert recalled.status == "completed"
    assert recalled.plan.steps[0].output == "luxor"
    forgotten = run_agent("forget my city", approve=lambda *_: True)
    assert forgotten.status == "completed"
    assert mm.get_memory().get_fact("origin") is None


def test_last_result_does_not_use_memory_query_output(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    run_agent("what is my name?")
    out = run_agent("remember the last result as wrong")
    assert out.status == "needs_user"
    assert mm.get_memory().get_fact("wrong") is None


def test_correction_uses_last_turn_without_last_result_channel(tmp_path):
    import app.knowledge.memory as mm
    mm.configure(tmp_path / "m.db")
    run_agent("my city is Luxor", approve=lambda *_: True)
    run_agent("what is my city?")
    out = run_agent("No, I mean Cairo", approve=lambda *_: True)
    assert out.status == "completed"
    assert mm.get_memory().get_fact("city") == "Cairo"
