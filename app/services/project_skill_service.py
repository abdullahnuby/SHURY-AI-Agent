"""V18 adaptive skills and execution facade."""
from app.skills.registry import SkillBank
from app.planning.adaptive_execution import AdaptiveExecutionController
from app.skills.compiler import compile_project_skill


def skill_snapshot(status=None):
    bank = SkillBank()
    return [x.__dict__ | {"utility": x.utility} for x in (bank.list(status) if status else bank.list())]


def matching_skills(goal: str, limit: int = 5):
    return [x.__dict__ | {"utility": x.utility} for x in SkillBank().match(goal, limit)]


def set_skill_status(key: str, status: str):
    SkillBank().set_status(key, status)
    return SkillBank().get(key).__dict__


def adaptive_score(tool_name: str):
    from app.runtime.registry import load_tools
    tool = load_tools()[tool_name]
    return AdaptiveExecutionController().score_tool(tool)


def learn_project(path: str):
    from app.integrations.devops import inspect_project
    inspection = inspect_project(path)
    skill = compile_project_skill(path, inspection)
    return {"skill": skill.__dict__ | {"utility": skill.utility}, "inspection": inspection}
