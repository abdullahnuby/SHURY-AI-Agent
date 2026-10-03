from app.runtime.registry import tool
import re
from app.services.skill_supply_service import discover_skills, install_skill, refresh_skill, installed_skills, skill_supply_status, skill_routes


def _tail(goal: str, markers=()):
    quoted = re.findall(r'["\']([^"\']+)["\']', goal)
    if quoted:
        return quoted[-1].strip()
    low = goal.casefold()
    for marker in markers:
        pos = low.find(marker.casefold())
        if pos >= 0:
            return goal[pos + len(marker):].strip()
    return goal.strip()


def _repo_and_skill(goal: str):
    quoted = [x.strip() for x in re.findall(r'["\']([^"\']+)["\']', goal)]
    repo = ""
    skill = "SKILL.md"
    for token in quoted:
        if re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', token):
            repo = token
        elif token.casefold().endswith("skill.md"):
            skill = token.replace("\\", "/").strip("/")
    pairs = re.findall(r'\b[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\b', goal)
    if not repo:
        repo = next((x for x in pairs if not x.casefold().startswith(("skills/", "skill/"))), pairs[0] if pairs else "")
    if skill == "SKILL.md" and repo:
        idx = goal.casefold().find(repo.casefold())
        if idx >= 0:
            tail = goal[idx + len(repo):].strip(" :=,-")
            m = re.search(r'([A-Za-z0-9_.\-/]+SKILL\.md)', tail, re.I)
            if m:
                skill = m.group(1).replace("\\", "/").strip("/")
    if skill == "SKILL.md":
        marker = goal.casefold().find("skill path")
        if marker >= 0:
            tail = goal[marker + len("skill path"):].strip(" :=")
            if tail:
                skill = tail.split()[0].strip("\"'").replace("\\", "/")
    return repo, skill


def _skill_key_arg(goal: str) -> str:
    if "remote:" in goal.casefold():
        m = re.search(r'(remote:[a-f0-9]{8,64})', goal.casefold())
        if m:
            return m.group(1)
    return _tail(goal, ("refresh skill ", "update skill ", "حدّث المهارة ", "حدّث skill ")).strip().split()[0] if _tail(goal, ("refresh skill ", "update skill ", "حدّث المهارة ", "حدّث skill ")).strip() else ""


@tool(
    "اكتشاف Skills فعلية من مستودعات Agent Skills العامة، بفحص SKILL.md وmetadata فقط أولًا، ثم عرض candidates بدون تفعيل",
    {"query": "str"}, name="discover_skills", capability="skill_discovery",
    triggers=("discover skills", "find skills", "find a skill", "search skills", "skills for", "اكتشف المهارات", "اكتشف مهارات", "ابحث عن مهارات", "دور على skills"),
    match=lambda g: (not re.search(r"\bmatch\s+skills?\b", g, re.I)) and any(x in g.casefold() for x in ("discover skills", "find skills", "find a skill", "search skills", "skills for", "اكتشف المهارات", "اكتشف مهارات", "ابحث عن مهارات", "دور على skills")),
    build_args=lambda g: {"query": _tail(g, ("discover skills ", "find skills ", "search skills ", "اكتشف المهارات ", "ابحث عن مهارات ", "دور على skills "))},
    produces=("skill_catalog_discovered",), cost=3.5, duration=4.0, parallel_safe=False,
    idempotent=True, verification_level="strong", intent_priority=13,
)
def discover_skills_tool(query: str):
    return discover_skills(query)


@tool(
    "توجيه Progressive-Disclosure للـSkills المثبتة: request ثم area ثم family ثم skill root بدون تحميل المحتوى الكامل",
    {"query": "str"}, name="route_skills", capability="skill_routing",
    triggers=("route skills", "skill router", "route skill", "وجه المهارات", "روتر المهارات"),
    match=lambda g: any(x in g.casefold() for x in ("route skills", "skill router", "route skill", "وجه المهارات", "روتر المهارات")),
    build_args=lambda g: {"query": _tail(g, ("route skills ", "route skill ", "وجه المهارات "))},
    produces=("skill_routes",), cost=0.4, duration=0.05, parallel_safe=True,
    idempotent=True, verification_level="strong", intent_priority=12,
)
def route_skills_tool(query: str):
    return skill_routes(query)


@tool(
    "تنزيل Skill محددة من GitHub بعد اكتشافها، مع حدود حجم/عدد ملفات وفحص schema/security؛ تبقى quarantined ولا تتفعل تلقائيًا",
    {"repo": "str", "skill_path": "str"}, name="install_remote_skill", capability="skill_acquisition",
    triggers=("install skill", "install remote skill", "ثبت مهارة", "نزّل skill", "ثبت skill من github"),
    match=lambda g: any(x in g.casefold() for x in ("install skill", "install remote skill", "ثبت مهارة", "نزّل skill", "ثبت skill من github")),
    build_args=lambda g: dict(zip(("repo", "skill_path"), _repo_and_skill(g))),
    produces=("skill_materialized", "skill_audited"), cost=5.0, duration=5.0, parallel_safe=False,
    idempotent=True, verification_level="strong", intent_priority=12,
)
def install_remote_skill_tool(repo: str, skill_path: str):
    return install_skill(repo, skill_path)


@tool(
    "عرض Skills التي تم جلبها من المصادر الخارجية وحالتها والـhash ونتيجة الفحص",
    {}, name="installed_remote_skills", capability="skill_inventory",
    triggers=("installed skills", "remote skills", "skills inventory", "المهارات المثبتة", "المهارات الخارجية"),
    match=lambda g: any(x in g.casefold() for x in ("installed skills", "remote skills", "skills inventory", "المهارات المثبتة", "المهارات الخارجية")),
    produces=("skill_inventory",), cost=0.3, duration=0.05, parallel_safe=True,
    idempotent=True, verification_level="strong", intent_priority=7,
)
def installed_remote_skills_tool():
    return installed_skills()


@tool(
    "تحديث Skill خارجية وفق upstream provenance وإظهار هل تغير المحتوى؛ التحديث لا يغير activation lifecycle وحده",
    {"key": "str"}, name="refresh_remote_skill", capability="skill_refresh",
    triggers=("refresh skill", "update skill", "حدّث المهارة", "حدّث skill"),
    match=lambda g: any(x in g.casefold() for x in ("refresh skill", "update skill", "حدّث المهارة", "حدّث skill")),
    build_args=lambda g: {"key": _skill_key_arg(g)},
    produces=("skill_refresh_checked",), cost=3.0, duration=3.0, parallel_safe=False,
    idempotent=True, verification_level="strong", intent_priority=6,
)
def refresh_remote_skill_tool(key: str):
    return refresh_skill(key)


@tool(
    "مراقبة supply chain للـSkills: عدد external packages وحالاتها مع Research Memory",
    {}, name="skill_supply_status", capability="skill_supply_observability",
    triggers=("skill supply status", "skills status", "حالة منظومة المهارات", "حالة skills"),
    match=lambda g: any(x in g.casefold() for x in ("skill supply status", "skills status", "حالة منظومة المهارات", "حالة skills")),
    produces=("skill_supply_status",), cost=0.3, duration=0.05, parallel_safe=True,
    idempotent=True, verification_level="strong", intent_priority=5,
)
def skill_supply_status_tool():
    return skill_supply_status()

@tool(
    "نقل Skill خارجية من quarantined إلى trusted بعد موافقة بشرية صريحة؛ لا يتم ذلك ضمن الاكتشاف التلقائي",
    {"key": "str"}, name="approve_remote_skill", capability="skill_trust",
    triggers=("approve skill", "trust skill", "activate trusted skill", "اعتمد المهارة", "ثق في المهارة"),
    match=lambda g: any(x in g.casefold() for x in ("approve skill", "trust skill", "activate trusted skill", "اعتمد المهارة", "ثق في المهارة")),
    build_args=lambda g: {"key": _skill_key_arg(g)},
    produces=("skill_trusted",), cost=0.8, duration=0.2, parallel_safe=False,
    idempotent=True, verification_level="strong", intent_priority=14,
    requires_approval=True, risk="high",
)
def approve_remote_skill_tool(key: str):
    from app.services.skill_supply_service import approve_remote_skill
    return approve_remote_skill(key)



@tool(
    "استخلاص Failure Skill Card من فشل تشغيل سابق: يحفظ pattern وtriggers كمرشح تعلمي بدون أي workflow تنفيذي",
    {"goal": "str", "tool": "str", "error": "str"}, name="distill_failure_skill", capability="skill_evolution",
    triggers=("distill failure", "learn from failure", "تعلم من الفشل", "استخلص مهارة من الفشل"),
    match=lambda g: any(x in g.casefold() for x in ("distill failure", "learn from failure", "تعلم من الفشل", "استخلص مهارة من الفشل")),
    build_args=lambda g: {"goal": g, "tool": "unknown", "error": g},
    produces=("failure_skill_candidate",), cost=0.6, duration=0.1, parallel_safe=True,
    idempotent=True, verification_level="strong", intent_priority=9,
)
def distill_failure_skill_tool(goal: str, tool: str, error: str):
    from app.skills.evolution import distill_failure
    return distill_failure(goal, tool, error)
