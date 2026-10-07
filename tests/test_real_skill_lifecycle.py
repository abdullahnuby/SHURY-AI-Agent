from pathlib import Path

from app.brain.capabilities import discover_skill_candidates
from app.brain.kernel import CognitiveKernel
from app.brain.models import GoalSpec, SemanticFrame
from app.brain.store import BrainStateStore
from app.knowledge.memory import Memory
from app.brain.learning import BrainExperienceStore
from app.skills.registry import SkillBank
from app.skills.verification import verify_skill_contract
from app.runtime.registry import load_tools


def test_persisted_builtin_skill_survives_fresh_skillbank(tmp_path):
    db = tmp_path / "skills.db"
    first = SkillBank(db, bootstrap=True)
    active = first.list(status="active")
    assert active
    assert any(skill.key == "builtin:calculate" for skill in active)

    second = SkillBank(db, bootstrap=True)
    assert second.get("builtin:calculate").status == "active"
    assert second.get("builtin:calculate").verification


def test_capability_matching_does_not_depend_on_skill_trigger_text(tmp_path):
    bank = SkillBank(tmp_path / "skills.db")
    bank.upsert(
        key="capability-only",
        name="Math Workflow",
        triggers=("irrelevant phrase",),
        workflow=({"step_id": "s1", "tool": "calculator", "capability": "calculate", "args_policy": "derive-from-live-goal"},),
        verification=({"type": "all_steps_verified"},),
        status="active",
    )
    goal = GoalSpec("perform_calculation", "25 * 4", required_capability="calculate")
    frame = SemanticFrame("25 * 4", "en", "command", requested_operation="calculate",
                          slots=(("expression", "25 * 4"),))
    matches = discover_skill_candidates(goal, frame, bank)
    assert matches and matches[0].key == "capability-only"


def test_real_kernel_uses_persisted_skill_after_fresh_runtime(tmp_path):
    db = tmp_path / "skills.db"
    SkillBank(db, bootstrap=True)
    kernel = CognitiveKernel(
        memory=Memory(tmp_path / "memory.db"),
        state_store=BrainStateStore(tmp_path / "state.db"),
        experience_store=BrainExperienceStore(tmp_path / "experience.db"),
        skill_bank=SkillBank(db),
    )
    result = kernel.act_structured({
        "goal": "Calculate 25 * 4",
        "operation": "calculate",
        "capability": "calculate",
        "slots": {"expression": "25 * 4"},
    })
    assert result.status == "completed"
    assert result.state.selected_skill is not None
    assert result.state.selected_skill.key == "builtin:calculate"
    execution = [e for e in result.state.trace if e.get("kind") == "execution_record"]
    assert execution and execution[-1]["skill_verification"]["verified"] is True
    assert result.state.plan[0].skill_key == "builtin:calculate"


def test_skill_level_verification_detects_missing_required_effect(tmp_path):
    bank = SkillBank(tmp_path / "skills.db")
    skill = bank.upsert(
        key="verify-required-effect",
        name="Verification Skill",
        triggers=("calculate",),
        workflow=({"step_id": "s1", "tool": "calculator", "capability": "calculate"},),
        outputs=("required_effect",),
        verification=({"type": "all_steps_verified"}, {"type": "expected_effects_observed"}),
        status="active",
    )
    # Tool-level success is present, but the Skill-level contract requires an effect
    # that was never observed. The Skill must therefore fail closed.
    class State:
        plan = [type("Step", (), {"step_id": "s1", "skill_key": skill.key})()]
        observations = [{"step_id": "s1", "ok": True, "verified": True, "effects": []}]

    verdict = verify_skill_contract(skill, State(), {"s1": 100})
    assert verdict["verified"] is False
    assert any("effects" in error for error in verdict["errors"])
