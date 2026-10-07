import tempfile
from pathlib import Path

from app.brain.kernel import CognitiveKernel
from app.brain.store import BrainStateStore
from app.brain.models import GoalSpec, SemanticFrame
from app.brain.planner import plan
from app.knowledge.memory import Memory
from app.brain.learning import BrainExperienceStore
from app.skills.registry import SkillBank
from app.skills.verification import verify_skill_contract
import app.intelligence.semantic.intents as intents


def test_calculation_skill_plan_projects_namespaced_expression_slot():
    with tempfile.TemporaryDirectory() as tmpdir:
        bank = SkillBank(Path(tmpdir) / "skills.db", bootstrap=True)
        skill = bank.get("builtin:calculate")
        frame = SemanticFrame(
            "احسب 25 * 4", "ar", "command", requested_operation="calculate",
            slots=(("operation:expression", "25 * 4"),),
        )
        goal = GoalSpec("perform_calculation", frame.text, required_capability="calculate")
        from app.brain.models import CognitiveState
        state = CognitiveState(frame.text, session_id="s1", semantic=frame)
        state.selected_skill = skill
        actions = plan(goal, frame, [], state=state, registry=__import__('app.runtime.registry', fromlist=['load_tools']).load_tools())
        assert actions
        assert actions[0].skill_key == "builtin:calculate"
        assert actions[0].args == {"expression": "25 * 4"}


def test_skill_verification_uses_skill_workflow_steps_even_without_skill_key_on_plan():
    class Skill:
        key = "skill-x"
        outputs = ("done_effect",)
        workflow = ({"step_id": "s1", "tool": "calculator", "capability": "calculate"},)
        verification = ({"type": "all_steps_verified"}, {"type": "expected_effects_observed"})

    class State:
        plan = [type("Step", (), {"step_id": "s1", "skill_key": ""})()]
        observations = [{"step_id": "s1", "ok": True, "verified": True, "effects": ["done_effect"]}]

    verdict = verify_skill_contract(Skill(), State(), {"s1": 100})
    assert verdict["verified"] is True


def test_numeric_calculation_semantics_win_over_result_memory(monkeypatch):
    monkeypatch.setattr(intents, "rank_query_against_texts", lambda *args, **kwargs: [])
    result = intents.candidates("احسب 1250 / 25 ثم قل لي النتيجة")
    assert result
    assert result[0].name == "calculate"
    assert result[0].capability == "calculate"


def test_structured_calculation_executes_builtin_skill_and_verifies():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        kernel = CognitiveKernel(
            memory=Memory(base / "memory.db"),
            state_store=BrainStateStore(base / "state.db"),
            experience_store=BrainExperienceStore(base / "experience.db"),
            skill_bank=SkillBank(base / "skills.db", bootstrap=True),
        )
        result = kernel.act_structured({
            "goal": "احسب 1250 / 25 ثم قل لي النتيجة",
            "operation": "calculate",
            "capability": "calculate",
            "slots": {"operation:expression": "1250 / 25", "expression": "1250 / 25"},
        })
        assert result.status == "completed"
        assert "50.0" in result.response
        assert result.state.selected_skill.key == "builtin:calculate"
        execution = [e for e in result.state.trace if e.get("kind") == "execution_record"][-1]
        assert execution["skill_verification"]["verified"] is True
