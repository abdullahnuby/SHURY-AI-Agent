from app.runtime.registry import tool
from app.runtime.security import safe_workspace_path
from app.skills.standard import validate_skill_package, load_skill
from app.skills.research import import_package, research_to_candidate
from app.skills.evaluation import summary as eval_summary, lifecycle_recommendation
from app.skills.registry import SkillBank
import re


def _path(goal: str) -> str:
    q = re.findall(r'["\']([^"\']+)["\']', goal)
    if q: return q[-1]
    return goal.strip()

@tool(
    "فحص Skill package وفق Agent Skills specification مع progressive disclosure وsecurity findings؛ لا يستوردها",
    {"path":"str"}, name="inspect_skill_package",
    triggers=("inspect skill package", "validate skill", "فحص المهارة", "تحقق من skill", "تحقق المهارة"),
    match=lambda g: any(x in g.casefold() for x in ("inspect skill package", "validate skill", "فحص المهارة", "تحقق من skill", "تحقق المهارة")),
    build_args=lambda g:{"path":_path(g)}, capability="skill_governance",
    produces=("skill_package_inspected",), cost=0.7, duration=0.1, parallel_safe=True,
    idempotent=True, verification_level="strong", intent_priority=8,
)
def inspect_skill_package_tool(path: str):
    return validate_skill_package(str(safe_workspace_path(path)))

@tool(
    "استيراد Skill package خارجي إلى SkillBank كمرشح quarantine؛ لا يفعله إلا بعد approval",
    {"path":"str"}, name="import_skill_package",
    triggers=("import skill", "install skill", "استورد المهارة", "ثبت المهارة"),
    match=lambda g: any(x in g.casefold() for x in ("import skill", "استورد المهارة", "ثبت المهارة")) or ("install skill" in g.casefold() and not any(x in g.casefold() for x in ("github", "remote", "owner/repo"))),
    build_args=lambda g:{"path":_path(g)}, capability="skill_acquisition",
    produces=("skill_candidate_imported",), cost=1.0, duration=0.2, requires_approval=True,
    risk="medium", parallel_safe=False, idempotent=True, verification_level="strong", intent_priority=8,
)
def import_skill_package_tool(path: str):
    return import_package(str(safe_workspace_path(path)))

@tool(
    "عرض الدليل التفريقي بين Skill وخطة baseline وعدد التجارب ومتوسط التحسن؛ لا يغير lifecycle",
    {"key":"str"}, name="evaluate_skill",
    triggers=("evaluate skill", "skill evaluation", "قيّم المهارة", "تقييم المهارة", "اختبر المهارة"),
    match=lambda g: any(x in g.casefold() for x in ("evaluate skill", "skill evaluation", "قيّم المهارة", "تقييم المهارة", "اختبر المهارة")),
    build_args=lambda g:{"key":(re.findall(r'(?:skill|مهارة)\s+([\w:.-]+)', g.casefold()) or [""])[-1]},
    capability="skill_evaluation", produces=("skill_evaluated",), cost=0.5, duration=0.05,
    parallel_safe=True, idempotent=True, verification_level="strong", intent_priority=7,
)
def evaluate_skill_tool(key: str):
    return lifecycle_recommendation(key)

@tool(
    "تطبيق توصية lifecycle المبنية على differential evidence؛ يسمح بالترقية التلقائية للـlocal/trusted فقط ويمنع الخارجية quarantine من bypass approval",
    {"key":"str"}, name="adapt_skill_lifecycle",
    triggers=("adapt skill lifecycle", "promote skill", "demote skill", "تكيف المهارة", "رقّي المهارة", "خفض المهارة"),
    match=lambda g: any(x in g.casefold() for x in ("adapt skill lifecycle", "promote skill", "demote skill", "تكيف المهارة", "رقّي المهارة", "خفض المهارة")),
    build_args=lambda g:{"key":(re.findall(r'(?:skill|مهارة)\s+([\w:.-]+)', g.casefold()) or [""])[-1]},
    capability="skill_lifecycle_adaptation", produces=("skill_lifecycle_adapted",), cost=0.6, duration=0.05,
    requires_approval=True, risk="medium", parallel_safe=False, idempotent=True, verification_level="strong", intent_priority=8,
)
def adapt_skill_lifecycle_tool(key: str):
    return SkillBank().apply_differential_lifecycle(key)

@tool(
    "إنشاء Skill knowledge candidate من نتائج البحث الخارجية مع provenance؛ لا يحول نص الويب إلى خطوات تنفيذية",
    {"query":"str"}, name="compile_research_skill",
    triggers=("compile research skill", "learn from research", "تعلم مهارة من البحث", "استخرج مهارة من البحث"),
    match=lambda g: any(x in g.casefold() for x in ("compile research skill", "learn from research", "تعلم مهارة من البحث", "استخرج مهارة من البحث")),
    build_args=lambda g:{"query":g}, capability="skill_acquisition",
    produces=("research_skill_candidate",), cost=1.2, duration=0.2, parallel_safe=False,
    idempotent=True, verification_level="strong", intent_priority=7,
)
def compile_research_skill_tool(query: str):
    # Deliberately create an empty-workflow candidate. Actual procedure must be learned
    # from a verified run or imported machine-readable workflow.json.
    from app.knowledge.web_research import WebResearchEngine
    result = WebResearchEngine().internet_research(query, web_limit=3, paper_limit=3, repo_limit=3, index=True)
    sources=[]
    sources += [{"url":x.get("url"),"title":x.get("title"),"sha256":x.get("sha256"),"source":"web","score":x.get("score")} for x in result.get("web",{}).get("sources",[])]
    sources += [{"url":x.get("url"),"title":x.get("title"),"sha256":x.get("sha256"),"source":"arxiv"} for x in result.get("arxiv",{}).get("papers",[])]
    return research_to_candidate(query, sources)
