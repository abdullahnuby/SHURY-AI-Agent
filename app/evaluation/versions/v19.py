from __future__ import annotations
from pathlib import Path
import tempfile
import textwrap

from app.skills.standard import validate_skill_package, load_skill
from app.skills.governance import assess_skill
from app.skills.research import import_package, research_to_candidate
from app.skills.evaluation import record_differential, lifecycle_recommendation, compare_plans
from app.skills.registry import SkillBank
from app.domain.plan import Plan, PlanStep
from app.runtime.registry import load_tools
from app.planning.adaptive_planning import choose_adaptive_plan


def run_v19_benchmark():
    cases=[]
    with tempfile.TemporaryDirectory(prefix="agent-v19-bench-") as td:
        root=Path(td)
        skilldir=root/"safe-build"
        skilldir.mkdir()
        (skilldir/"SKILL.md").write_text(textwrap.dedent("""\
        ---
        name: safe-build
        description: Build and validate a project safely when the user asks to build or test the project.
        license: MIT
        compatibility: Requires Python and local project access.
        metadata:
          author: benchmark
          version: "1.0"
        allowed-tools: inspect_project git_status check_project
        ---
        # Safe Build\n\n        1. Inspect the project.\n        2. Inspect Git state.\n        3. Run approved project checks.\n        """), encoding="utf-8")
        (skilldir/"workflow.json").write_text('{"steps":[{"tool":"inspect_project"},{"tool":"git_status","depends_on":["s1"]},{"tool":"check_project","depends_on":["s2"]}]}', encoding="utf-8")
        info=validate_skill_package(skilldir)
        cases.append(("skill_format_validation", info["valid"] and info["name"]=="safe-build" and info["workflow_present"]))
        meta=load_skill(skilldir, level="metadata")
        full=load_skill(skilldir, level="resources")
        cases.append(("progressive_disclosure", meta.body=="" and len(full.body)>0 and full.workflow and len(full.scripts)==0))
        admission=assess_skill(info, source="github")
        cases.append(("external_skill_quarantine", admission.allowed and admission.trust=="quarantined" and admission.requires_approval))
        imported=import_package(skilldir, bank_path=root/"skills.db", source="github")
        cases.append(("safe_import_candidate", imported["imported"] and imported["skill"]["status"]=="candidate" and imported["skill"].get("source")=="github" and imported["workflow_errors"]==[]))
        bank=SkillBank(root/"skills.db")
        key=imported["skill"]["key"]
        cases.append(("quarantine_persists", bank.trust(key)=="quarantined"))
        blocked=False
        try: bank.set_status(key,"active")
        except PermissionError: blocked=True
        cases.append(("activation_gate", blocked))
        # Differential evidence must promote only after repeated positive evidence.
        for _ in range(3): record_differential(key,"build project",0.35,0.48,baseline_verified=True,skill_verified=True,path=bank.path)
        rec=lifecycle_recommendation(key,path=bank.path)
        cases.append(("differential_promotion_signal", rec["recommendation"]=="promote" and rec["mean_delta"]>0.05))
        for _ in range(3): record_differential(key,"build project",0.50,0.30,baseline_verified=True,skill_verified=False,path=bank.path)
        rec2=lifecycle_recommendation(key,path=bank.path)
        cases.append(("negative_differential_signal", rec2["recommendation"]=="demote"))
        bank2=SkillBank(root/"local.db")
        local=bank2.upsert(key="local-evo",name="Local Evo",triggers=("evolve",),workflow=(),status="candidate",confidence=0.9,source="runtime")
        for _ in range(3): record_differential(local.key,"evolve",0.2,0.4,baseline_verified=True,skill_verified=True,path=bank2.path)
        action=bank2.apply_differential_lifecycle(local.key)
        cases.append(("local_auto_promotion", action["action"]=="promote" and action["after"]=="active"))
        registry=load_tools()
        b=Plan([PlanStep("s1","inspect_project",{"path":str(root)})], estimated_cost=2.5, estimated_duration=1.0, score=2.5)
        s=Plan([PlanStep("s1","inspect_project",{"path":str(root)}),PlanStep("s2","git_status",{"path":str(root)},depends_on=["s1"])], estimated_cost=1.6, estimated_duration=0.3, score=1.6)
        cmp=compare_plans(b,s,registry,baseline_verified=True,skill_verified=True)
        cases.append(("plan_differential", isinstance(cmp["delta"],float)))
        demo=bank.upsert(key="local-demo",name="Local Build",triggers=("build","project"),workflow=({"tool":"inspect_project"},),status="active",confidence=1.0,source="runtime")
        for _ in range(3): bank.record_outcome("local-demo", True)
        demo=bank.get("local-demo")
        selected=choose_adaptive_plan(f'build project "{root}"', b, [demo], registry)
        cases.append(("adaptive_selection_contract", selected.planner in {"generic","v18-adaptive-skill"}))
        research=research_to_candidate("adaptive build testing", [{"url":"https://example.org/paper","title":"Adaptive build","sha256":"abc","source":"web"}], bank_path=bank.path)
        cases.append(("research_candidate_safe", research["candidate"]["status"]=="candidate" and research["candidate"]["workflow"]==()))
    passed=sum(1 for _,ok in cases if ok)
    return {"passed":passed,"total":len(cases),"cases":[{"name":n,"passed":bool(ok)} for n,ok in cases]}
