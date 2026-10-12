from pathlib import Path

from app.knowledge.memory import Memory


def test_episode_keeps_structured_experience_separate_from_facts(tmp_path: Path):
    m = Memory(tmp_path / "memory.db", owner_id="u1")
    episode_id = m.record_episode(
        "We fixed the import issue",
        "The migration was corrected successfully",
        outcome="completed",
        tool_events=[{"tool": "pytest", "ok": True, "verified": True, "output": "12 passed"}],
        entities=[{"type": "project", "text": "SHURY"}],
        experience_kind="task",
        session_id="s1",
        run_id="r1",
    )
    assert m.profile(owner_id="u1") == []
    episode = m.get_episode(episode_id, owner_id="u1", session_id="s1", run_id="r1")
    assert episode["episode_id"] == episode_id
    assert episode["user_message"] == "We fixed the import issue"
    assert episode["assistant_response"].startswith("The migration")
    assert episode["tool_events"][0]["tool"] == "pytest"
    assert episode["entities"][0]["text"] == "SHURY"
    assert episode["experience_kind"] == "task"


def test_experience_retrieval_matches_tool_and_outcome_not_fact_memory(tmp_path: Path):
    m = Memory(tmp_path / "memory.db", owner_id="u1")
    m.record_episode("We investigated the broken tests", "pytest showed the import error", outcome="failed",
                     tool_events=[{"tool": "pytest", "ok": False, "error": "import error"}], session_id="s1", run_id="r1")
    m.record_episode("We prepared the release", "Everything passed", outcome="completed",
                     tool_events=[{"tool": "zip", "ok": True, "verified": True, "output": "archive ready"}], session_id="s2", run_id="r2")
    hits = m.retrieve_experience("pytest import error", owner_id="u1", top_k=5)
    assert hits
    assert hits[0]["outcome"] == "failed"
    assert hits[0]["tool_events"][0]["tool"] == "pytest"
    assert hits[0]["episode_id"] != hits[-1]["episode_id"] or len(hits) == 1


def test_empty_experience_query_is_recent_deterministically(tmp_path: Path):
    m = Memory(tmp_path / "memory.db", owner_id="u1")
    first = m.record_episode("older task", session_id="s1")
    second = m.record_episode("newer task", session_id="s2")
    hits = m.experience_timeline(owner_id="u1", limit=2)
    assert [h["episode_id"] for h in hits] == [second, first]


def test_episode_owner_isolation_applies_to_get_and_search(tmp_path: Path):
    m = Memory(tmp_path / "memory.db")
    episode_id = m.record_episode("private user A task", owner_id="user-a", session_id="a")
    m.record_episode("private user B task", owner_id="user-b", session_id="b")
    assert m.get_episode(episode_id, owner_id="user-b") is None
    hits = m.retrieve_experience("private task", owner_id="user-b", top_k=10)
    assert all(item["owner_id"] == "user-b" for item in hits)
    assert all(item["episode_id"] != episode_id for item in hits)


def test_episode_session_and_run_isolation(tmp_path: Path):
    m = Memory(tmp_path / "memory.db")
    r1 = m.record_episode("session alpha run one", owner_id="u1", session_id="s1", run_id="r1")
    r2 = m.record_episode("session alpha run two", owner_id="u1", session_id="s1", run_id="r2")
    r3 = m.record_episode("session beta run three", owner_id="u1", session_id="s2", run_id="r3")
    assert [x["episode_id"] for x in m.retrieve_experience("run", owner_id="u1", session_id="s1")] == [r2, r1]
    assert [x["episode_id"] for x in m.retrieve_experience("run", owner_id="u1", run_id="r1")] == [r1]
    assert r3 not in [x["episode_id"] for x in m.retrieve_experience("run", owner_id="u1", session_id="s1")]


def test_episode_secret_redaction_is_recursive(tmp_path: Path):
    m = Memory(tmp_path / "memory.db", owner_id="u1")
    episode_id = m.record_episode(
        "we did a task",
        tool_events=[{"tool": "deploy", "args": {"api_key": "SUPERSECRET", "region": "eg"}, "output": "token=TOPSECRET"}],
        metadata={"access_token": "NO_STORE"},
        owner_id="u1",
    )
    e = m.get_episode(episode_id, owner_id="u1")
    raw = str(e)
    assert "SUPERSECRET" not in raw
    assert "NO_STORE" not in raw
    assert "<redacted>" in raw or "<redacted>" in str(e["tool_events"])


def test_legacy_episode_api_preserves_phase8_fields(tmp_path: Path):
    m = Memory(tmp_path / "memory.db", owner_id="u1")
    eid = m.add_episode("done this before", "yes", outcome="completed", session_id="s1", run_id="r1",
                        metadata={"topic": "migration"}, tool_events=[{"tool": "pytest", "ok": True}])
    e = m.get_episode(eid, owner_id="u1", session_id="s1", run_id="r1")
    assert e["episode_id"] == eid
    assert e["tool_events"]
    assert e["metadata"]["topic"] == "migration"


def test_restore_export_round_trip_keeps_episode_evidence(tmp_path: Path):
    source = Memory(tmp_path / "source.db", owner_id="u1")
    source.record_episode("we solved the parser issue", "done", outcome="completed",
                          tool_events=[{"tool": "pytest", "ok": True, "output": "green"}],
                          entities=[{"type": "module", "text": "parser"}], owner_id="u1", session_id="s1", run_id="r1")
    payload = source.export(owner_id="u1", scope="user", include_episodes=True)
    target = Memory(tmp_path / "target.db", owner_id="u1")
    result = target.restore_memory(payload, owner_id="u1", include_episodes=True)
    assert result["imported_episodes"] == 1
    restored = target.retrieve_experience("parser", owner_id="u1")
    assert restored and restored[0]["tool_events"][0]["tool"] == "pytest"


def test_recall_context_uses_dedicated_experience_retrieval(tmp_path: Path):
    m = Memory(tmp_path / "memory.db", owner_id="u1")
    m.record_episode("we fixed database migration", "migration completed", outcome="completed",
                     tool_events=[{"tool": "pytest", "ok": True}], owner_id="u1", session_id="s1")
    ctx = m.recall_context("database migration", owner_id="u1", session_id="s1")
    assert ctx["episodic"]
    assert ctx["episodic"][0]["episode_id"]
    assert ctx["semantic"] == []


def test_brain_canonical_runtime_records_an_episode(tmp_path: Path):
    from app.brain.kernel import CognitiveKernel
    from app.runtime.registry import Tool

    m = Memory(tmp_path / "memory.db", owner_id="u1")
    registry = {
        "calculator": Tool(
            "calculator", "calculate an expression", {"expression": "str"}, lambda expression: 5,
            triggers=("calculate",), capability="calculate", produces=("calculation_completed",),
        )
    }
    kernel = CognitiveKernel(memory=m, registry=registry)
    result = kernel.act_structured(
        {"goal": "calculate 2+3", "operation": "calculate", "parameters": {"expression": "2+3"}},
        session_id="s1",
        approve=lambda *_: True,
    )
    assert result.status in {"completed", "failed"}
    episodes = m.retrieve_experience("calculate 2+3", owner_id="u1", session_id="s1")
    assert episodes
    assert episodes[0]["run_id"] == result.run_id
    assert episodes[0]["tool_events"]
    assert episodes[0]["tool_events"][0]["tool"] == "calculator"


def test_generic_memory_search_tolerates_structured_episode_metadata(tmp_path: Path):
    m = Memory(tmp_path / "memory.db", owner_id="u1")
    m.set_fact("project", "KEMEX")
    m.record_episode(
        "we worked on KEMEX",
        "pytest passed",
        outcome="completed",
        entities=[{"type": "project", "text": "KEMEX"}],
        tool_events=[{"tool": "pytest", "ok": True}],
        owner_id="u1",
        session_id="s1",
        run_id="r1",
    )
    hits = m.search_memory("KEMEX", owner_id="u1", session_id="s1", top_k=5)
    assert hits
    assert any(item["kind"] == "episode" for item in hits)


def test_legacy_episode_schema_migrates_without_losing_rows(tmp_path: Path):
    import sqlite3

    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE memory_episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id TEXT NOT NULL,
            session_id TEXT,
            run_id TEXT,
            user_text TEXT NOT NULL,
            assistant_text TEXT,
            outcome TEXT,
            summary TEXT,
            ts TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX idx_memory_episodes_owner_session ON memory_episodes(owner_id, session_id, id);
    """)
    conn.execute(
        "INSERT INTO memory_episodes(owner_id,session_id,run_id,user_text,assistant_text,outcome,summary,ts,metadata) VALUES(?,?,?,?,?,?,?,?,?)",
        ("u1", "s1", "r1", "legacy interaction", "done", "completed", None, "2026-10-01T10:00:00", '{"topic":"legacy"}')
    )
    conn.commit()
    conn.close()

    m = Memory(path, owner_id="u1")
    episode = m.retrieve_episodes("legacy interaction", owner_id="u1", session_id="s1", top_k=5)
    assert episode and episode[0]["user_message"] == "legacy interaction"
    assert episode[0]["tool_events"] == []
    assert episode[0]["entities"] == []
    assert episode[0]["experience_kind"] == "interaction"

