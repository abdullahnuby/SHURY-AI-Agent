import tempfile
from pathlib import Path
import pytest

from app.brain.kernel import CognitiveKernel
from app.skills.registry import SkillBank
from app.knowledge.memory import Memory
from app.brain.store import BrainStateStore
from app.brain.learning import BrainExperienceStore


def test_execution_contract_record_fields():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_skills.db"
        skill_bank = SkillBank(path=db_path)

        skill_bank.upsert(
            key="calc_skill_contract",
            name="Calculator Skill Contract",
            triggers=("calculate", "math"),
            workflow=(
                {
                    "step_id": "s1",
                    "tool": "calculator",
                    "capability": "calculate",
                    "args": {"expression": "50 * 2"},
                },
            ),
            status="active",
        )

        kernel = CognitiveKernel(
            memory=Memory(Path(tmpdir) / "m.db"),
            state_store=BrainStateStore(Path(tmpdir) / "s.db"),
            experience_store=BrainExperienceStore(Path(tmpdir) / "e.db"),
            skill_bank=skill_bank,
        )

        result = kernel.act_structured(
            {
                "goal": "Calculate 50 * 2",
                "operation": "calculate",
                "capability": "calculate",
                "slots": {"expression": "50 * 2"},
            }
        )

        state = result.state
        assert result.status == "completed"

        records = [e for e in state.trace if e.get("kind") == "execution_record"]
        assert len(records) == 1
        record = records[0]

        # Verify all 8 contract fields are present
        assert "selected_skill" in record
        assert "inputs" in record
        assert "tools_invoked" in record
        assert "tool_outputs" in record
        assert "execution_status" in record
        assert "errors" in record
        assert "elapsed_execution" in record
        assert "verification_result" in record

        # Verify specific values
        assert record["selected_skill"] == "calc_skill_contract"
        assert record["tools_invoked"] == ["calculator"]
        assert record["execution_status"] == "completed"
        assert record["verification_result"] is True
        assert record["errors"] == []
        assert "s1" in record["tool_outputs"]
        assert record["tool_outputs"]["s1"] == "100"
