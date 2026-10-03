import tempfile
import time
from pathlib import Path
import app.knowledge.memory as memory
import app.runtime.agent as agent_mod
tmp = Path(tempfile.mkdtemp())
MEM_PATH = tmp / "m.db"
memory.configure(MEM_PATH)
agent_mod.LOG_FILE = tmp / "agent.jsonl"
from app.runtime.agent import run_agent, plan_only
from app.domain.plan import Plan, PlanStep
from app.runtime.registry import Tool, register, REGISTRY, load_tools, manifest


def tools_of(s): return [x.tool for x in s.plan.steps]
def statuses(s): return [x.status for x in s.plan.steps]

class Fixed:
    def __init__(self, steps): self.steps = steps
    def plan(self, goal, memory=None): return Plan(list(self.steps))


def test_autodiscovery():
    assert {"calculator", "get_time", "save_note", "list_notes", "search_notes",
            "remember_fact", "recall_fact", "recent_runs"} <= set(load_tools())

def test_manifest():
    m = {t["name"]: t for t in manifest()}
    assert m["save_note"]["requires_approval"] and "text" in m["save_note"]["params"]

def test_calc():
    s = run_agent("احسب 5*3+2"); assert s.status == "completed" and s.plan.steps[0].output == 17

def test_time():
    s = run_agent("الساعة كام"); assert tools_of(s) == ["get_time"] and s.status == "completed"

def test_note_saved_in_memory():
    s = run_agent("سجل عندي اجتماع الساعة 6")
    assert s.status == "completed" and tools_of(s) == ["save_note"]
    assert "اجتماع الساعة 6" in memory.get_memory().list_notes()

def test_note_with_numbers_not_calc():
    assert tools_of(run_agent("سجل اجتماع 6-7")) == ["save_note"]

def test_phone_fact_not_calc():
    s = run_agent("افتكر التليفون: 0100-1234"); assert tools_of(s) == ["remember_fact"]

def test_note_denied():
    n = len(memory.get_memory().list_notes())
    s = run_agent("سجل اجتماع مرفوض", approve=lambda t, a: False)
    assert s.status == "cancelled" and statuses(s) == ["skipped"] and len(memory.get_memory().list_notes()) == n

def test_plan_is_data_with_pipeline():
    plan, errors = plan_only("احسب 12*4 واحفظ النتيجة")
    assert not errors and [s.tool for s in plan.steps] == ["calculator", "save_note"]
    assert plan.steps[1].args == {"text": "12*4 = {{s1}}"}

def test_pipeline_executes_and_approval_sees_real_args():
    seen = []
    s = run_agent("احسب 12*4 واحفظ النتيجة", approve=lambda t, a: seen.append((t, a)) or True)
    assert s.status == "completed" and seen == [("save_note", {"text": "12*4 = 48"})]
    assert "12*4 = 48" in memory.get_memory().list_notes()

def test_pipe_when_text_empty():
    plan, _ = plan_only("احسب 7*6 واحفظ"); assert plan.steps[1].args["text"] == "7*6 = {{s1}}"

def test_failure_skips_rest_and_saves_nothing():
    n = len(memory.get_memory().list_notes())
    s = run_agent("احسب 5/0 واحفظ النتيجة")
    assert s.status == "failed" and statuses(s) == ["failed", "skipped"]
    assert len(memory.get_memory().list_notes()) == n

def test_unknown_goal():
    assert run_agent("ايه الأخبار").status == "needs_user"

def test_search_and_list():
    run_agent("سجل مقابلة المهندس احمد")
    assert "مقابلة المهندس احمد" in run_agent("اعرض الملاحظات").plan.steps[0].output
    assert any("احمد" in x for x in run_agent("دور على احمد").plan.steps[0].output)
    assert run_agent("دور على xyz").plan.steps[0].output == []

def test_facts():
    run_agent("افتكر اسم المشروع: نخيل")
    assert run_agent("فاكر ايه عن اسم المشروع").plan.steps[0].output == "نخيل"
    assert "مفيش" in run_agent("فاكر ايه عن حاجة_مجهولة").plan.steps[0].output

def test_run_history_recorded():
    run_agent("احسب 99*99")
    out = run_agent("آخر الأهداف").plan.steps[0].output
    assert any("احسب 99*99" in x and "completed" in x for x in out)

def test_memory_persists_across_instances():
    run_agent("سجل ملاحظة دائمة")
    assert "ملاحظة دائمة" in memory.Memory(MEM_PATH).list_notes()

def test_max_steps_guard():
    s = run_agent("x", planner=Fixed([PlanStep(f"s{i}", "get_time", {}) for i in range(1, 11)]), max_steps=4)
    assert s.status == "max_steps" and statuses(s).count("done") == 4 and statuses(s).count("skipped") == 6

def test_timeout_guard():
    register(Tool("sleepy", "t", {}, lambda: time.sleep(0.05) or "ok"))
    try:
        s = run_agent("x", planner=Fixed([PlanStep("s1", "sleepy", {}), PlanStep("s2", "sleepy", {})]), max_seconds=0.01)
        assert s.status == "timeout" and statuses(s) == ["done", "skipped"]
    finally:
        REGISTRY.pop("sleepy")

def test_retry_flaky():
    calls = {"n": 0}
    def flaky():
        calls["n"] += 1
        if calls["n"] < 2: raise IOError("مؤقت")
        return "تمام"
    register(Tool("flaky", "t", {}, flaky, retries=1, triggers=("flakytest",)))
    try:
        s = run_agent("flakytest"); assert s.status == "completed" and s.plan.steps[0].attempts == 2
    finally:
        REGISTRY.pop("flaky")

def test_retry_exhausted():
    def broken(): raise IOError("دايمًا")
    register(Tool("broken", "t", {}, broken, retries=2, triggers=("brokentest",)))
    try:
        s = run_agent("brokentest"); assert s.status == "failed" and s.plan.steps[0].attempts == 3
    finally:
        REGISTRY.pop("broken")

def _invalid(steps):
    s = run_agent("x", planner=Fixed(steps))
    assert s.status == "failed" and "خطة غير صالحة" in s.final_message
    assert all(x.status == "pending" for x in s.plan.steps)   # ولا خطوة اتنفذت

def test_validation_unknown_tool(): _invalid([PlanStep("s1", "rm_rf", {})])
def test_validation_bad_args(): _invalid([PlanStep("s1", "calculator", {"wrong": 1})])
def test_validation_forward_ref():
    _invalid([PlanStep("s1", "save_note", {"text": "{{s2}}"}), PlanStep("s2", "get_time", {})])

if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("PASS", n)
