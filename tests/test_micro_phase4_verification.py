import tempfile
from pathlib import Path
from types import SimpleNamespace
import pytest

from app.runtime.verify import verify_step
from app.brain.kernel import CognitiveKernel
from app.skills.registry import SkillBank
from app.knowledge.memory import Memory
from app.brain.store import BrainStateStore
from app.brain.learning import BrainExperienceStore


def test_verify_step_calculator_math():
    tool = SimpleNamespace(name="calculator")
    
    # 1. Correct result passes verification
    res_ok = SimpleNamespace(ok=True, data=100, error=None)
    verified, msg = verify_step(tool, {"expression": "25 * 4"}, res_ok)
    assert verified is True
    assert msg == "ok"

    # 2. Incorrect result fails verification
    res_bad = SimpleNamespace(ok=True, data=999, error=None)
    verified, msg = verify_step(tool, {"expression": "25 * 4"}, res_bad)
    assert verified is False
    assert "calculator result verification failed" in msg


def test_verify_step_read_file_and_memory():
    file_tool = SimpleNamespace(name="read_file")
    
    # None result fails verification
    verified, msg = verify_step(file_tool, {"path": "test.txt"}, SimpleNamespace(ok=True, data=None, error=None))
    assert verified is False
    assert "file read tool returned no content" in msg

    # Valid content passes verification
    verified, msg = verify_step(file_tool, {"path": "test.txt"}, SimpleNamespace(ok=True, data="file content", error=None))
    assert verified is True


def test_kernel_executes_and_verifies_state():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_skills.db"
        skill_bank = SkillBank(path=db_path)

        skill_bank.upsert(
            key="calc_skill_v4",
            name="Calculator Skill V4",
            triggers=("calculate", "math"),
            workflow=(
                {
                    "step_id": "s1",
                    "tool": "calculator",
                    "capability": "calculate",
                    "args": {"expression": "25 * 4"},
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
                "goal": "Calculate 25 * 4",
                "operation": "calculate",
                "capability": "calculate",
                "slots": {"expression": "25 * 4"},
            }
        )

        assert result.status == "completed"
        record = [e for e in result.state.trace if e.get("kind") == "execution_record"][0]
        assert record["verification_result"] is True
        assert record["tool_outputs"]["s1"] == "100"
