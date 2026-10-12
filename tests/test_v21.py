from app.evaluation.versions.v21 import run_v21_benchmark


def test_v21_benchmark_green():
    out = run_v21_benchmark()
    assert out["passed"] == out["total"]


from app.runtime.registry import load_tools

def test_v21_skill_tool_contracts():
    tools = load_tools()
    assert tools["approve_remote_skill"].requires_approval
    assert tools["approve_remote_skill"].risk == "high"
    args = tools["install_remote_skill"].args_for("install skill from vercel-labs/agent-skills skills/react-best-practices/SKILL.md")
    assert args["repo"] == "vercel-labs/agent-skills"
    assert args["skill_path"] == "skills/react-best-practices/SKILL.md"

