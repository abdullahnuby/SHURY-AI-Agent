from pathlib import Path

from app.learning.procedures import task_family_signature, build_procedure_evidence
from app.learning.store import LearningStore


def _procedure(goal: str, run_id: str, *, tool: str = "calculate") -> dict:
    return build_procedure_evidence(
        goal=goal,
        operation="calculate",
        capability="calculate",
        steps=[{"tool": tool, "capability": "calculate", "depends_on": []}],
        status="completed",
        verified_rate=1.0,
        failure_class=None,
        environment_signature="calc-v1",
        run_id=run_id,
    )


def test_value_slots_share_one_canonical_procedure_family(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    first = _procedure("calculate 20+30", "run-2030")
    second = _procedure("calculate 40+50", "run-4050")

    assert first["task_family_signature"] == second["task_family_signature"]

    stored1 = store.upsert_procedural_memory(**first, key="proc:calculate-family")
    stored2 = store.upsert_procedural_memory(**second, key="proc:calculate-family")

    assert stored1["stored"] is True
    assert stored2["successes"] == 2

    matches = store.match_procedural_memory(
        task_family_signature=task_family_signature("calculate 70+80"),
        operation="calculate",
        capability="calculate",
    )
    assert len(matches) == 1
    assert matches[0]["status"] == "promoted"
    assert matches[0]["successes"] == 2
    assert set(matches[0]["evidence_run_ids"]) == {"run-2030", "run-4050"}
