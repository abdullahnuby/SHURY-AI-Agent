from app.runtime.registry import tool
from app.runtime.security import safe_workspace_path
from app.skills.registry import SkillBank
import re


def _tail(goal: str, marker: str):
    pos = goal.casefold().find(marker.casefold())
    return goal[pos + len(marker):].strip() if pos >= 0 else goal.strip()


@tool(
    "عرض الـSkills النشطة/المعتمدة التي تعلمها الـAgent واستخداماتها وسجل نجاحها",
    {"status": "str"}, name="list_skills",
    triggers=("list skills", "show skills", "الskills", "المهارات", "عرض المهارات"),
    match=lambda g: any(x in g.casefold() for x in ("list skills", "show skills", "المهارات", "عرض المهارات")),
    build_args=lambda g: {"status": "approved"}, capability="skill_management",
    produces=("skills_observed",), cost=0.4, duration=0.05, parallel_safe=True,
    idempotent=True, verification_level="strong", intent_priority=6,
)
def list_skills_tool(status="approved"):
    return [x.__dict__ | {"utility": x.utility} for x in SkillBank().list(status)]


@tool(
    "اقتراح Skills مناسبة لهدف حالي اعتمادًا على triggers وutility؛ لا ينفذ Skill وحده",
    {"goal": "str"}, name="match_skills",
    triggers=("match skills", "skill for", "ما المهارة", "مهارة مناسبة"),
    match=lambda g: bool(re.search(r"\bmatch\s+skills?\b", g, re.I)) or any(x in g.casefold() for x in ("ما المهارة", "مهارة مناسبة")),
    build_args=lambda g: {"goal": _tail(g, "match skills ")}, capability="skill_selection",
    produces=("skill_candidates_observed",), cost=0.5, duration=0.05, parallel_safe=True,
    idempotent=True, verification_level="strong", intent_priority=14,
)
def match_skills_tool(goal: str):
    return [x.__dict__ | {"utility": x.utility} for x in SkillBank().match(goal)]


@tool(
    "اعتماد Skill مرشح أو تفعيله أو إيقافه؛ requires approval دائمًا",
    {"key": "str", "status": "str"}, name="manage_skill",
    triggers=("approve skill", "activate skill", "retire skill", "اعتمد المهارة", "فعّل المهارة", "أوقف المهارة"),
    match=lambda g: any(x in g.casefold() for x in ("approve skill", "activate skill", "retire skill", "اعتمد المهارة", "فعّل المهارة", "أوقف المهارة")),
    build_args=lambda g: {"key": re.findall(r"(?:skill|مهارة)\s+([\w.-]+)", g.casefold())[-1] if re.findall(r"(?:skill|مهارة)\s+([\w.-]+)", g.casefold()) else "",
                          "status": "approved" if "approve" in g.casefold() or "اعتمد" in g.casefold() else ("active" if "activate" in g.casefold() or "فعّل" in g.casefold() else "deprecated")},
    capability="skill_lifecycle", produces=("skill_lifecycle_changed",), cost=0.6, duration=0.05,
    requires_approval=True, risk="medium", parallel_safe=False, idempotent=True,
    verification_level="strong", intent_priority=8,
)
def manage_skill_tool(key: str, status: str):
    SkillBank().set_status(key, status)
    return {"key": key, "status": status, "verified": True}

@tool(
    "إنشاء Skill مرشح من project manifest: inspection ثم git status ثم build/test الحالي؛ لا يفعل شيئًا تنفيذيًا",
    {"path": "str"}, name="learn_project_skill",
    triggers=("learn project skill", "learn development skill", "تعلم من المشروع", "تعلم تطوير المشروع", "استخرج مهارة المشروع"),
    match=lambda g: any(x in g.casefold() for x in ("learn project skill", "learn development skill", "تعلم من المشروع", "تعلم تطوير المشروع", "استخرج مهارة المشروع")),
    build_args=lambda g: {"path": (re.findall(r'["\']([^"\']+)["\']', g) or [g.strip()])[-1]},
    capability="skill_compilation", produces=("skill_candidate_created",), cost=1.0, duration=0.2,
    parallel_safe=True, idempotent=True, verification_level="strong", intent_priority=7,
)
def learn_project_skill_tool(path: str):
    from app.integrations.devops import inspect_project
    from app.skills.compiler import compile_project_skill
    safe_path = safe_workspace_path(path)
    inspection = inspect_project(safe_path)
    skill = compile_project_skill(str(safe_path), inspection)
    return {"skill": skill.__dict__ | {"utility": skill.utility}, "inspection": inspection,
            "policy": "candidate only; requires explicit approval/activation before adaptive reuse"}
