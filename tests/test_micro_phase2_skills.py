import pytest
import tempfile
from pathlib import Path

from app.brain.kernel import CognitiveKernel
from app.skills.registry import SkillBank
from app.brain.models import GoalSpec


def test_first_class_skill_selection_and_binding():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_skills.db"
        skill_bank = SkillBank(path=db_path)
        
        # Register a test skill with contract metadata
        skill_bank.upsert(
            key="calc_skill",
            name="Calculator Skill",
            triggers=("calculate", "math"),
            preconditions=("valid_expression",),
            workflow=(
                {
                    "step_id": "step1",
                    "tool": "calculator",
                    "capability": "calculate",
                    "args": {"expression": "10 + 20"},
                },
            ),
            outputs=("calculation_completed",),
            status="active",
            confidence=0.9,
        )

        kernel = CognitiveKernel(skill_bank=skill_bank)

        # Execute structured goal requiring calculate capability
        result = kernel.act_structured(
            {
                "goal": "Calculate 10 + 20",
                "operation": "calculate",
                "capability": "calculate",
                "slots": {"expression": "10 + 20"},
            }
        )

        state = result.state

        # 1. Verify Skill selection is explicit in CognitiveState
        assert state.selected_skill is not None
        assert state.selected_skill.key == "calc_skill"

        # 2. Verify selected Skill is recorded in event trace
        selected_events = [e for e in state.trace if e.get("kind") == "skill_selected"]
        assert len(selected_events) == 1
        assert selected_events[0]["key"] == "calc_skill"

        # 3. Verify execution plan steps carry skill_key explicitly
        assert len(state.plan) >= 1
        assert state.plan[0].skill_key == "calc_skill"
        assert state.plan[0].tool == "calculator"

        # 4. Verify execution outcome
        assert result.status == "completed"
