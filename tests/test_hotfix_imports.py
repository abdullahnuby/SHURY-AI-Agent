from app.domain.task_ir import TaskCondition, TaskIR, TaskNode
from app.planning.capabilities import CapabilityMatch, INTENT_TO_CAPABILITY, grounded_args


def test_task_ir_contract():
    ir = TaskIR(
        original="calculate and save",
        objective="calculate",
        nodes=[TaskNode("t1", "calculate", planner_goal="calculate 2+2", capability="calculate")],
    )
    assert ir.executable is True
    assert ir.compound is False
    assert ir.to_dict()["nodes"][0]["id"] == "t1"


def test_condition_serialization():
    assert TaskCondition("if", "x", "y").to_dict() == {"kind": "if", "expression": "x", "consequence": "y"}


def test_capability_import_contract():
    assert INTENT_TO_CAPABILITY["calculate"] == "calculate"
    assert CapabilityMatch("calculator", 1.0).tool == "calculator"
