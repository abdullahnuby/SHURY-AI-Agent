from pathlib import Path
from tempfile import TemporaryDirectory

from app.integrations.network import _validate_connected_peer, validate_public_url
from app.planning.planner import RulePlanner
from app.skills.discovery import SkillDiscovery
from app.skills.research import import_package
from app.skills.standard import validate_skill_package
from app.skills.registry import SkillBank
from app.intelligence.understanding import understand
from app.evaluation.versions.v21 import FakeGateway


def test_natural_language_routing():
    planner = RulePlanner()
    assert planner.plan("Learn from the internet how to improve RAG").steps[0].tool == "research_and_learn"
    assert planner.plan("Build the project and run the tests").steps[0].tool == "check_project"
    assert planner.plan("Find skills for data analysis").steps[0].tool == "discover_skills"


def test_remote_skill_identity_approval_refresh():
    with TemporaryDirectory(prefix="v22-skill-") as td:
        root = Path(td)
        gateway = FakeGateway(root)
        discovery = SkillDiscovery(gateway=gateway, root=root / "external", manifest=root / "external" / "registry.json")
        installed = discovery.install("demo/skills", "skills/data-quality/SKILL.md", bank_path=root / "skills.db")
        remote_key = installed["materialized"]["key"]
        bank = SkillBank(root / "skills.db")
        assert remote_key in {x.key for x in bank.list()}
        assert discovery.approve_and_trust(remote_key, bank_path=root / "skills.db")["status"] == "approved"
        gateway.repos["demo/skills"]["files"]["skills/data-quality/SKILL.md"] = "---\nname: data-quality\ndescription: Changed upstream\nlicense: MIT\n---\n# v2\n"
        refreshed = discovery.refresh(remote_key)
        assert refreshed["changed"] and refreshed["reapproval_required"]
        bank_after = SkillBank(root / "skills.db")
        assert bank_after.get(remote_key).status == "candidate"
        assert bank_after.trust(remote_key) == "quarantined"


def test_external_skill_cannot_auto_promote_from_outcomes():
    with TemporaryDirectory(prefix="v22-lifecycle-") as td:
        db = Path(td) / "skills.db"
        bank = SkillBank(db)
        skill = bank.upsert(key="remote:test", name="remote", source="github", status="candidate")
        bank.set_trust(skill.key, "quarantined")
        for _ in range(3):
            bank.record_outcome(skill.key, True)
        refreshed = bank.get(skill.key)
        assert refreshed.status == "candidate"
        assert bank.trust(skill.key) == "quarantined"
        try:
            bank.set_status(skill.key, "active")
        except PermissionError:
            pass
        else:
            raise AssertionError("quarantined skill was activated")


def test_trust_downgrade_revokes_activation():
    with TemporaryDirectory(prefix="v22-trust-") as td:
        bank = SkillBank(Path(td) / "skills.db")
        skill = bank.upsert(key="local:test", name="local", source="runtime", status="candidate")
        bank.set_trust(skill.key, "trusted")
        bank.set_status(skill.key, "approved")
        bank.set_status(skill.key, "active")
        bank.set_trust(skill.key, "quarantined")
        assert bank.get(skill.key).status == "candidate"


def test_connected_peer_must_match_public_dns():
    import ipaddress
    public = {ipaddress.ip_address("93.184.216.34")}
    _validate_connected_peer("example.com", "93.184.216.34", public)
    try:
        _validate_connected_peer("example.com", "10.0.0.1", public)
    except ValueError:
        pass
    else:
        raise AssertionError("private peer was accepted")
    try:
        _validate_connected_peer("example.com", "93.184.216.35", public)
    except ValueError:
        pass
    else:
        raise AssertionError("unvalidated DNS peer was accepted")


def test_ipv6_url_is_canonicalized_correctly():
    # validate_public_url performs DNS lookup, so use loopback only to assert rejection;
    # it must fail for the correct reason rather than producing an invalid netloc.
    try:
        validate_public_url("http://[::1]/")
    except ValueError as exc:
        assert "private" in str(exc).lower() or "blocked" in str(exc).lower()
    else:
        raise AssertionError("loopback IPv6 was accepted")


def test_contextual_intent_precedence():
    assert understand("remember that the meeting: tomorrow at 6").top_intent.name == "remember_fact"
    assert understand("Search the internet for the newest RAG research").top_intent.name == "web_research"
    assert understand("Learn from the internet how to improve RAG").top_intent.name == "open_world_learning"
    assert understand("هات أحدث الأوراق العلمية عن الوكلاء").top_intent.name == "scientific_research"


def test_natural_bilingual_tool_matches():
    from app.runtime.registry import load_tools
    registry = load_tools()
    assert registry["analyze_dataset"].matches("حلل data.csv واكتشف القيم الشاذة")
    assert registry["profile_dataset"].matches("اعمل بروفايل للـdataset.csv")
    assert registry["discover_skills"].matches("اكتشف مهارات لتحليل البيانات")
    assert registry["arxiv_research"].matches("هات أحدث الأوراق العلمية عن الوكلاء")



def test_name_memory_natural_language_routing():
    planner = RulePlanner()
    cases = [
        ("save me name abdullah", "remember_fact", {"key": "name", "value": "abdullah"}),
        ("save my name as Abdullah", "remember_fact", {"key": "name", "value": "Abdullah"}),
        ("my name is Abdullah", "remember_fact", {"key": "name", "value": "Abdullah"}),
        ("remember my name Abdullah", "remember_fact", {"key": "name", "value": "Abdullah"}),
        ("what's my name ?", "recall_fact", {"key": "name"}),
        ("what is my name", "recall_fact", {"key": "name"}),
        ("who am I?", "recall_fact", {"key": "name"}),
        ("ما اسمي؟", "recall_fact", {"key": "name"}),
    ]
    for goal, tool, args in cases:
        plan = planner.plan(goal)
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == tool
        assert plan.steps[0].args == args


def test_name_is_not_saved_as_a_free_form_note():
    from app.runtime.registry import load_tools
    registry = load_tools()
    assert not registry["save_note"].matches("save me name abdullah")
    assert registry["remember_fact"].matches("save me name abdullah")


def test_name_fact_persists_and_can_be_recalled(tmp_path):
    import app.knowledge.memory as memory_module
    import app.runtime.agent as agent_module
    memory_module.configure(tmp_path / "memory.db")
    agent_module.LOG_FILE = tmp_path / "agent.jsonl"
    save_state = agent_module.run_agent("save me name abdullah", approve=lambda *_: True)
    assert save_state.status == "completed"
    assert [s.tool for s in save_state.plan.steps] == ["remember_fact"]
    recall_state = agent_module.run_agent("what's my name ?")
    assert recall_state.status == "completed"
    assert [s.tool for s in recall_state.plan.steps] == ["recall_fact"]
    assert recall_state.plan.steps[0].output == "abdullah"
