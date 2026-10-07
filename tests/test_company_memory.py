from pathlib import Path

import pytest

from app.knowledge.memory import Memory
from app.knowledge.memory_types import COMPANY, COMPANY_MEMORY, USER, FACT
from app.organization import CompanyMemory


def test_company_memory_uses_canonical_store_and_explicit_scope(tmp_path: Path):
    mem = Memory(tmp_path / "memory.db", owner_id="user-a")
    company = CompanyMemory(mem, company_id="org-a")
    mid = company.remember_decision(
        decision_key="data-analysis-team",
        decision={"departments": ["data"], "members": ["data:data-analyst"]},
        evidence=["company-run:r1"],
        run_id="r1",
    )
    row = mem.get_memory(mid, scope=COMPANY, owner_id="org-a")
    assert row is not None
    assert row["kind"] == COMPANY_MEMORY
    assert row["scope"] == COMPANY
    assert row["owner_id"] == "org-a"


def test_company_memory_isolated_from_user_memory(tmp_path: Path):
    mem = Memory(tmp_path / "memory.db", owner_id="user-a")
    mem.remember("user-only secret", kind=FACT, key="note", scope=USER, owner_id="user-a")
    company = CompanyMemory(mem, company_id="org-a")
    company.remember_procedure(
        capability="data_analysis", skill="builtin:data-analysis", tool="analyze_dataset",
        procedure={"method": "verified"}, evidence=["run:r1"], run_id="r1",
    )

    company_hits = company.recall("data analysis")
    assert company_hits
    assert all(hit.metadata.get("company_id") == "org-a" for hit in company_hits)
    assert all("user-only secret" not in hit.value for hit in company_hits)

    user_hits = mem.retrieve("data analysis", scope=USER, owner_id="user-a", kinds={FACT})
    assert user_hits == []


def test_company_memory_verified_only(tmp_path: Path):
    mem = Memory(tmp_path / "memory.db", owner_id="user-a")
    company = CompanyMemory(mem, company_id="org-a")
    mem.remember(
        '{"unverified": true}', kind=COMPANY_MEMORY, key="lesson:unverified", scope=COMPANY,
        owner_id="org-a", source="system", metadata={"category": "lesson", "verified": False},
    )
    company.remember_failure_lesson(
        capability="file_move", failure_class="path_mismatch", lesson={"cause": "separator mismatch"},
        evidence=["run:r2"], run_id="r2",
    )
    hits = company.recall("path mismatch")
    assert hits
    assert all(hit.metadata.get("verified") for hit in hits)
    assert all("unverified" not in hit.value for hit in hits)


def test_company_procedure_requires_evidence(tmp_path: Path):
    company = CompanyMemory(Memory(tmp_path / "memory.db"), company_id="org-a")
    with pytest.raises(ValueError, match="verification evidence"):
        company.remember_procedure(
            capability="x", skill="s", tool="t", procedure={"x": 1}, evidence=(),
        )


def test_company_memory_company_owner_is_not_tied_to_active_user_owner(tmp_path: Path):
    mem = Memory(tmp_path / "memory.db", owner_id="user-a")
    company = CompanyMemory(mem, company_id="org-b")
    company.remember_ownership(
        subject="analyze_dataset", department="data", role="data:data-analyst",
        capability="data_analysis", tool="analyze_dataset", evidence=["registry:v1"],
    )
    assert company.stats()["total"] == 1
    assert mem.list_memories(scope=COMPANY, owner_id="org-b", kind=COMPANY_MEMORY, limit=10)
    assert not mem.list_memories(scope=COMPANY, owner_id="org-a", kind=COMPANY_MEMORY, limit=10)


def test_company_stats_categories(tmp_path: Path):
    company = CompanyMemory(Memory(tmp_path / "memory.db"), company_id="org-a")
    company.remember_ownership(subject="x", department="data", role="data:analyst", evidence=["registry"])
    company.remember_decision(decision_key="x", decision={"selected": "data"}, evidence=["run:r1"], run_id="r1")
    stats = company.stats()
    assert stats["total"] == 2
    assert stats["verified"] == 2
    assert stats["categories"]["ownership"] == 1
    assert stats["categories"]["decision"] == 1


def test_structured_brain_retrieves_prior_company_memory_without_user_context(tmp_path: Path):
    mem = Memory(tmp_path / "memory.db")
    company = CompanyMemory(mem, company_id="org-a")
    company.remember_decision(
        decision_key="dataset-analysis",
        decision={"preferred_department": "data", "preferred_role": "data:data-analyst"},
        evidence=["verified-run:r1"],
        run_id="r1",
    )
    company.remember_procedure(
        capability="data_analysis", skill="builtin:data-analysis", tool="analyze_dataset",
        procedure={"verification": "source_fingerprint"}, evidence=["verified-run:r1"], run_id="r1",
    )
    from app.brain import CognitiveKernel
    from app.brain.learning import BrainExperienceStore
    from app.brain.store import BrainStateStore
    kernel = CognitiveKernel(
        memory=mem,
        state_store=BrainStateStore(tmp_path / "brain.db"),
        experience_store=BrainExperienceStore(tmp_path / "experience.db"),
    )
    kernel.company_memory = CompanyMemory(mem, company_id="org-a")
    payload = {
        "goal": "analyze dataset",
        "operation": "data_analysis",
        "capability": "data_analysis",
        "target": "",
        "target_type": "",
        "slots": {"path": "workspace/sales.csv"},
        "constraints": [],
        "temporal_requirements": [],
        "required_evidence": [],
        "priority": 0.5,
        "language": "en",
    }
    result = kernel.think_structured(payload)
    categories = {item["category"] for item in result.state.company_memory}
    assert "decision" in categories or "procedure" in categories
    assert all(item["metadata"].get("company_id") == "shury-company" for item in result.state.company_memory) is False


def test_company_memory_does_not_store_raw_task_output(tmp_path: Path):
    mem = Memory(tmp_path / "memory.db")
    company = CompanyMemory(mem, company_id="org-a")
    company.remember_outcome(
        run_id="r-secret", status="completed",
        summary={"tool": "analyze_dataset", "verified": True}, verified=True,
    )
    hits = company.recall("analyze_dataset")
    assert hits
    assert all("raw task output" not in hit.value for hit in hits)


def test_company_memory_rejects_user_provenance(tmp_path: Path):
    mem = Memory(tmp_path / "memory.db")
    with pytest.raises(ValueError):
        mem.remember(
            "user-provenance-company-record",
            kind=COMPANY_MEMORY,
            key="decision:user-provenance",
            scope=COMPANY,
            owner_id="org-a",
            source="user",
        )
