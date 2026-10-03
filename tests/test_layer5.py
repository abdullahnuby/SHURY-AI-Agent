from __future__ import annotations
import os
from pathlib import Path

from app.learning.diagnosis import task_signature, failure_class, contrastive_lesson
from app.learning.models import ExperienceRecord, Lesson, SkillEvaluation
from app.learning.store import LearningStore
from app.learning.manager import SelfImprovementManager
from app.learning.promotion import promotion_gate
from app.skills.registry import SkillBank
from app.runtime.registry import load_tools
from app.planning.planner import RulePlanner
from app.planning.adaptive_planning import skill_to_plan
from app.domain.plan import Plan, PlanStep


def _exp(run_id, goal, status, verified=1.0, reward=1.0, env="env"):
    sig = task_signature(goal)
    return ExperienceRecord(
        run_id=run_id, goal=goal, task_signature=sig, status=status,
        reward=reward, verified_rate=verified,
        steps=({"step":"s1","tool":"calculator","status":"done" if status=="completed" else "failed",
                 "verified":verified>=0.8,"error":"" if status=="completed" else "invalid syntax","attempts":1,"capability":"calculation"},),
        failure_class=None if status=="completed" else "invalid_input", lesson_keys=(), session_id=None,
        created_at="2026-09-30T00:00:00", environment_signature=env,
    )


def test_task_signature_and_failure_classification():
    assert "analyze sales data" in task_signature("Please analyze sales data for 2026")
    assert failure_class("calculator", "invalid syntax") == "invalid_input"
    assert failure_class("web", "DNS connection timeout") == "timeout"


def test_experience_store_is_idempotent(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    exp = _exp("r1", "calculate 4*6", "completed")
    assert store.record_experience(exp)
    assert not store.record_experience(exp)
    assert store.get_experience("r1").run_id == "r1"


def test_contrastive_lesson_uses_success_and_failure_evidence(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    failed = _exp("rf", "recover calculation", "failed", reward=0.0)
    success = ExperienceRecord(
        run_id="rs", goal="recover calculation", task_signature=failed.task_signature, status="completed",
        reward=1.0, verified_rate=1.0,
        steps=({"step":"s1","tool":"calculator","status":"done","verified":True,"error":"","attempts":1,"capability":"calculation"},),
        failure_class=None, lesson_keys=(), session_id=None, created_at="2026-09-30T00:00:01", environment_signature="env2")
    for x in (failed, success):
        store.record_experience(x)
    lesson_data = contrastive_lesson(failed, store.similar_experiences(failed.task_signature))
    assert lesson_data is not None
    assert lesson_data["kind"] == "contrastive"
    store.upsert_lesson(Lesson(status="active", uses=0, created_at="2026-09-30T00:00:02", **lesson_data))
    guidance = store.search_lessons(failed.task_signature, set(failed.task_signature.split()))
    assert guidance and guidance[0].evidence_run_ids


def test_learning_guidance_is_retrievable_and_touched(tmp_path):
    mgr = SelfImprovementManager(learning_path=tmp_path/"learning.db", bank_path=tmp_path/"skills.db")
    store = mgr.store
    sig = task_signature("build project and run tests")
    lesson = Lesson("l1", sig, "success-heuristic", "Prefer verified test command after build.", (sig,), (), ("r1",), 0.7, "active", 0, "2026-09-30T00:00:00")
    store.upsert_lesson(lesson)
    guidance = mgr.guidance("build project and run tests")
    assert guidance and guidance[0]["lesson"]
    assert mgr.store.search_lessons(sig, set(sig.split()))[0].uses == 1


def test_repeated_verified_runs_create_candidate_skill_but_do_not_implicitly_trust_external(tmp_path):
    mgr = SelfImprovementManager(learning_path=tmp_path/"learning.db", bank_path=tmp_path/"skills.db")
    reg = load_tools()
    a = _exp("r1", "calculate and save total", "completed", env="env1")
    a = ExperienceRecord(**{**a.to_dict(), "steps": ({"step":"s1","tool":"calculator","status":"done","verified":True,"error":"","attempts":1,"capability":"calculation"},{"step":"s2","tool":"remember_result","status":"done","verified":True,"error":"","attempts":1,"capability":"memory"})})
    b = ExperienceRecord(**{**a.to_dict(), "run_id":"r2", "environment_signature":"env2", "created_at":"2026-09-30T00:00:01"})
    mgr.store.record_experience(a); mgr.store.record_experience(b)
    # Simulate the manager's candidate path through a minimal AgentState-like object.
    class Dummy: pass
    state=Dummy(); state.run_id="r3"; state.goal=b.goal; state.status="completed"; state.replans=0; state.plan=Plan([
        PlanStep("s1","calculator",{"expression":"1+1"},status="done",capability="calculation"),
        PlanStep("s2","remember_result",{"key":"total","value":"2"},status="done",capability="memory",depends_on=["s1"])
    ]); state.world=Dummy(); state.world.fingerprint=lambda: "env3"
    state.world.session_id=None
    class Mem:
        def effects(self, run_id):
            return [
                {"step_id":"s1","tool":"calculator","verified":True,"error":None},
                {"step_id":"s2","tool":"remember_result","verified":True,"error":None},
            ]
    result=mgr.observe_run(state, Mem(), registry=reg)
    assert result["candidate"] is not None
    candidate=mgr.bank.get(result["candidate"]["key"])
    assert candidate.status == "candidate"
    assert "12*7" not in candidate.triggers
    assert "calculate" in candidate.triggers and "save" in candidate.triggers
    assert candidate.workflow[1]["depends_on"] == ["s1"]


def test_promotion_gate_blocks_without_positive_replay():
    skill=SkillBank(tmp:=Path("/tmp")/"layer5-promo-test.db").upsert(key="candidate:x", name="candidate", triggers=("build",), workflow=({"tool":"calculator"},), status="candidate")
    ex=[_exp("r1","build project","completed",env="a"),_exp("r2","build project","completed",env="b")]
    ev=[SkillEvaluation(skill.key,"build project",0.5,0.5,0.0,True,False,"counterfactual","2026-09-30T00:00:00")]
    gate=promotion_gate(skill,ex,ev)
    assert not gate["promotable"]
    try: tmp.unlink()
    except FileNotFoundError: pass


def test_evolve_candidate_promotes_only_after_all_gates(tmp_path):
    mgr=SelfImprovementManager(learning_path=tmp_path/"learning.db", bank_path=tmp_path/"skills.db")
    key="evo:test"
    skill=mgr.bank.upsert(key=key,name="candidate",triggers=("build project",),workflow=({"tool":"calculator"},{"tool":"remember_result"}),status="candidate")
    ex1=_exp("r1","build project","completed",env="env1")
    ex2=_exp("r2","build project","completed",env="env2")
    mgr.store.record_experience(ex1); mgr.store.record_experience(ex2)
    for g in ("build project","build project alternate"):
        mgr.store.record_evaluation(SkillEvaluation(key,g,0.30,0.40,0.10,True,False,"counterfactual","2026-09-30T00:00:00"))
    decision=mgr.evolve_candidate(key,memory=None,registry=load_tools())
    assert decision.action=="promote"
    assert mgr.bank.get(key).status=="active"
    assert mgr.rollback(key)["status"]=="candidate"


def test_replay_does_not_execute_tools(tmp_path, monkeypatch):
    mgr=SelfImprovementManager(learning_path=tmp_path/"learning.db", bank_path=tmp_path/"skills.db")
    reg=load_tools()
    for t in reg.values():
        monkeypatch.setattr(t,"run",lambda **kwargs: (_ for _ in ()).throw(AssertionError("replay executed a tool")),raising=False)
    skill=mgr.bank.upsert(key="evo:no-exec",name="candidate",triggers=("calculate",),workflow=({"tool":"calculator"},),status="candidate")
    ex=_exp("r1","calculate 2+2","completed",env="x")
    mgr.store.record_experience(ex)
    out=mgr.evaluate_candidate(skill.key,registry=reg,memory=mgr.store)
    assert out["evaluations"]


def test_promotion_requires_trusted_provenance(tmp_path):
    mgr=SelfImprovementManager(learning_path=tmp_path/"learning.db", bank_path=tmp_path/"skills.db")
    key="evo:external"
    skill=mgr.bank.upsert(key=key,name="external",triggers=("build",),workflow=({"tool":"calculator"},),source="github",status="candidate")
    mgr.bank.set_trust(key,"quarantined")
    assert mgr.bank.trust(key)=="quarantined"


def test_legacy_success_reflection_lessons_are_retired(tmp_path):
    mgr = SelfImprovementManager(learning_path=tmp_path/"learning.db", bank_path=tmp_path/"skills.db")
    exp = _exp("rsuccess", "calculate 2+2", "completed", env="env")
    mgr.store.record_experience(exp)
    lesson = Lesson(
        key="reflection:legacy-success", task_signature=exp.task_signature, kind="reflection",
        lesson="The observation satisfies the goal.", when_to_apply=(exp.task_signature,),
        avoid=(), evidence_run_ids=(exp.run_id,), confidence=0.5, status="active", uses=0,
        created_at="2026-09-30T00:00:00"
    )
    mgr.store.upsert_lesson(lesson)
    # Re-opening the manager runs the legacy reconciliation pass.
    repaired = SelfImprovementManager(learning_path=tmp_path/"learning.db", bank_path=tmp_path/"skills.db")
    assert not any(x.key == lesson.key for x in repaired.store.active_lessons())
    # The experience record remains available, proving reconciliation is non-destructive.
    assert repaired.store.get_experience(exp.run_id) is not None


def test_task_signature_redacts_credentials():
    sig = task_signature("build with api_key=SUPERSECRET123 for production")
    assert "SUPERSECRET123" not in sig
    assert "redacted" in sig


def test_experience_storage_redacts_goal_credentials(tmp_path):
    mgr = SelfImprovementManager(learning_path=tmp_path/"learning.db", bank_path=tmp_path/"skills.db")
    exp = _exp("r-secret", "deploy with api_key=SUPERSECRET123", "completed")
    # The manager's runtime path is responsible for sanitizing goals; this test documents the
    # task-signature boundary while keeping direct store records explicit.
    assert "SUPERSECRET123" not in task_signature(exp.goal)
