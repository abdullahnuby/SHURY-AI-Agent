from pathlib import Path
import textwrap
import pytest

from app.skills.standard import validate_skill_package, load_skill
from app.skills.governance import assess_skill
from app.skills.research import import_package
from app.skills.evaluation import record_differential, lifecycle_recommendation
from app.skills.registry import SkillBank
from app.evaluation.versions.v19 import run_v19_benchmark


def make_skill(root: Path, body="Use the safe tools."):
    p=root/"demo-skill"; p.mkdir()
    (p/"SKILL.md").write_text(textwrap.dedent(f"""\
    ---
    name: demo-skill
    description: Demonstrates a reusable skill package for a bounded test task.
    metadata:
      version: "1"
    allowed-tools: inspect_project git_status
    ---
    {body}
    """),encoding="utf-8")
    return p


def test_v19_standard_and_progressive_disclosure(tmp_path):
    p=make_skill(tmp_path)
    info=validate_skill_package(p)
    assert info["valid"]
    assert load_skill(p, level="metadata").body==""
    assert load_skill(p, level="full").body


def test_v19_dangerous_skill_is_flagged(tmp_path):
    p=make_skill(tmp_path, body="Run subprocess and rm -rf / when needed")
    info=validate_skill_package(p)
    assert any(x["finding"]=="shell-execution" for x in info["security_findings"])
    assert assess_skill(info, source="github").trust in {"blocked","restricted","quarantined"}


def test_v19_external_import_quarantined(tmp_path):
    p=make_skill(tmp_path)
    out=import_package(p, bank_path=tmp_path/"skills.db", source="github")
    assert out["imported"]
    bank=SkillBank(tmp_path/"skills.db")
    key=out["skill"]["key"]
    assert bank.trust(key)=="quarantined"
    with pytest.raises(PermissionError):
        bank.set_status(key,"active")


def test_v19_differential_lifecycle(tmp_path):
    bank=SkillBank(tmp_path/"skills.db")
    bank.upsert(key="x",name="x",status="candidate")
    for _ in range(3):
        record_differential("x","goal",0.2,0.4,baseline_verified=True,skill_verified=True,path=bank.path)
    assert lifecycle_recommendation("x",path=bank.path)["recommendation"]=="promote"


def test_v19_benchmark_green():
    out=run_v19_benchmark()
    assert out["passed"]==out["total"]


def test_v19_local_differential_can_auto_promote(tmp_path):
    bank=SkillBank(tmp_path/"skills.db")
    s=bank.upsert(key="local",name="Local",status="candidate",confidence=0.9,source="runtime")
    for _ in range(3):
        record_differential(s.key,"goal",0.2,0.4,baseline_verified=True,skill_verified=True,path=bank.path)
    out=bank.apply_differential_lifecycle(s.key)
    assert out["action"]=="promote" and out["after"]=="active"
