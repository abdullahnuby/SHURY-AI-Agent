from __future__ import annotations
from app.brain.self_model import SelfModel
from app.learning.models import ExperienceRecord
from app.learning.store import LearningStore
from app.learning.self_model import PersistentSelfModel
from app.runtime.registry import Tool
from app.brain.models import CandidateAction
from app.brain.planner import _learning_adjusted_candidates


def exp(run_id: str, *, failed_first=False):
    ts=[]
    if failed_first:
        ts += [
            {"transition_id":f"{run_id}-1","state_before":"s0","action":{"capability":"calculator","tool":"calculator","cost":1},"state_after":"s1","outcome":{"ok":False,"verified":False,"duration_ms":100},"verified":False,"reward":-0.25,"prediction_error":0.8,"metadata":(("prediction_confidence_before",0.85),("world_model_version",2))},
            {"transition_id":f"{run_id}-2","state_before":"s1","action":{"capability":"fallback","tool":"fallback","cost":2},"state_after":"s2","outcome":{"ok":True,"verified":True,"duration_ms":900},"verified":True,"reward":0.5,"prediction_error":0.1,"metadata":(("prediction_confidence_before",0.75),("world_model_version",3))},
        ]
    else:
        ts=[{"transition_id":f"{run_id}-1","state_before":"s0","action":{"capability":"calculator","tool":"calculator","cost":1},"state_after":"s1","outcome":{"ok":True,"verified":True,"duration_ms":200},"verified":True,"reward":0.8,"prediction_error":0.05,"metadata":(("prediction_confidence_before",0.70),("world_model_version",3))}]
    steps=tuple({"step":f"s{i+1}","tool":t["action"]["tool"],"capability":t["action"]["capability"],"status":"done" if t["verified"] else "failed","verified":t["verified"]} for i,t in enumerate(ts))
    ok=all(t["verified"] for t in ts)
    return ExperienceRecord(run_id,"calculate 6*7","calculate 6*7","calculate","completed" if ok else "failed",1.0 if ok else 0.0,1.0 if ok else 0.0,steps,None,(),"s","2026-09-30T20:00:00",transitions=tuple(ts))


def test_persistent_self_model_metrics(tmp_path):
    store=LearningStore(tmp_path/"learning.db"); sm=PersistentSelfModel(store); e=exp("r1")
    assert sm.learn(e)["inserted"]==1
    row=store.self_model_metrics(tool="calculator",context_signature=e.task_signature)[0]
    assert row["attempts"]==1 and row["average_cost"]==0.2
    assert round(row["calibration_error"],6)==0.3 and round(row["brier_error"],6)==0.09
    assert row["prediction_error_mean"]==0.05 and row["recovery_rate"]==0.0


def test_self_model_idempotency_and_recovery(tmp_path):
    store=LearningStore(tmp_path/"learning.db"); sm=PersistentSelfModel(store); e=exp("r2",failed_first=True)
    assert sm.learn(e)["inserted"]==2 and sm.learn(e)["inserted"]==0
    row=store.self_model_metrics(tool="fallback",context_signature=e.task_signature)[0]
    assert row["recovery_attempts"]==1 and row["recovery_successes"]==1 and row["recovery_rate"]==1.0
    assert store.self_model_stats()["observations"]==2


def test_unknown_is_neutral_and_repeated_failure_is_negative(tmp_path):
    store=LearningStore(tmp_path/"learning.db"); sm=PersistentSelfModel(store)
    for i in range(4):
        e=exp(f"bad-{i}"); t=dict(e.transitions[0]); t.update({"transition_id":f"bad-{i}-x","verified":False,"reward":-0.25,"outcome":{"ok":False,"verified":False,"duration_ms":200}})
        sm.learn(ExperienceRecord(e.run_id,e.goal,e.task_signature,e.operation,"failed",0.0,0.0,e.steps,None,(),e.session_id,e.created_at,transitions=(t,)))
    assert sm.assess(tool="calculator",capability="calculate",context_signature="calculate 6*7").adjustment < 0
    assert sm.assess(tool="unknown",capability="unknown").adjustment == 0.0


def test_brain_self_model_snapshot_is_persistent(tmp_path):
    store=LearningStore(tmp_path/"learning.db"); PersistentSelfModel(store).learn(exp("r3"))
    snap=SelfModel({"calculator":Tool("calculator","",{},lambda:1,capability="calculate")},store).snapshot()
    assert snap["version"]==2 and snap["reliability"] and snap["reliability"][0]["tool"]=="calculator"
    assert snap["context_metrics"]==1


def test_self_model_adjustment_changes_primary_candidate_order(tmp_path):
    store=LearningStore(tmp_path/"learning.db"); sm=PersistentSelfModel(store)
    for i in range(5):
        e=exp(f"poor-{i}")
        t=dict(e.transitions[0]); t.update({"transition_id":f"poor-{i}-x","verified":False,"reward":-0.25,"outcome":{"ok":False,"verified":False,"duration_ms":300}})
        sm.learn(ExperienceRecord(e.run_id,e.goal,e.task_signature,e.operation,"failed",0.0,0.0,e.steps,None,(),e.session_id,e.created_at,transitions=(t,)))
    candidates=[
        CandidateAction("calculate","calculator",1.0,"primary",effects=("calculation_completed",)),
        CandidateAction("calculate","backup_calculator",1.0,"backup",effects=("calculation_completed",)),
    ]
    adjusted=_learning_adjusted_candidates(candidates,"calculate",store)
    assert adjusted[0].tool == "backup_calculator"
    assert adjusted[1].tool == "calculator"
