from app.runtime.registry import tool
from app.runtime.security import safe_workspace_path
from app.services.research_service import learn, learn_development, research_status, research_sources, research_source_learning
import re


def _tail(goal: str, markers=()):
    quoted=re.findall(r'["\']([^"\']+)["\']', goal)
    if quoted:
        return quoted[-1]
    for marker in markers:
        pos=goal.casefold().find(marker.casefold())
        if pos >= 0:
            return goal[pos+len(marker):].strip()
    return goal.strip()


@tool(
    "بحث وتعلم مفتوح العالم: يوزع السؤال على Web/arXiv/GitHub، يجمع الأدلة ويقيّم حداثتها وجودتها وnovelty ويخزنها في ذاكرة بحثية ويصدر Skill معرفية declarative",
    {"query":"str"}, name="research_and_learn",
    triggers=("research and learn","learn from the web","learn from web","learn from the internet","learn from internet","learn online","deep research learn","تعلم من الانترنت","تعلم من الإنترنت","ابحث وتعلم","تعلم من البحث","تعلم من الويب","بحث وتعلم"),
    match=lambda g: any(x in g.casefold() for x in ("research and learn","learn from the web","learn from web","learn from the internet","learn from internet","learn online","deep research learn","تعلم من الانترنت","تعلم من الإنترنت","ابحث وتعلم","تعلم من البحث","تعلم من الويب","بحث وتعلم")),
    build_args=lambda g:{"query":_tail(g,("research and learn ","learn from the web ","learn from web ","learn from the internet ","learn from internet ","learn online ","deep research learn ","تعلم من الانترنت ","تعلم من الإنترنت ","ابحث وتعلم ","تعلم من البحث ","تعلم من الويب ","بحث وتعلم "))},
    capability="open_world_learning", produces=("research_evidence","knowledge_indexed","learning_candidate"),
    cost=7.0,duration=7.0,parallel_safe=False,idempotent=True,verification_level="strong",intent_priority=12, exploration_safe=True, emits_world_delta=False,
    information_domains=("research", "learning", "knowledge", "external_web"), information_gain_prior=0.95,
)
def research_and_learn_tool(query: str):
    return learn(query)


@tool(
    "تعلم من مشروع برمجي فعلي: يفحص الـstack والـgit ثم يجمع معرفة تطوير وبناء واختبار وإدارة مرتبطة بالـstack ويصدر candidate skill بدون تعديل المشروع",
    {"path":"str"}, name="learn_development",
    triggers=("learn development","learn project","learn to build manage","تعلم تطوير","تعلم من المشروع","تعلم بناء المشروع","تعلم ادارة المشروع"),
    match=lambda g:any(x in g.casefold() for x in ("learn development","learn project","learn to build manage","تعلم تطوير","تعلم من المشروع","تعلم بناء المشروع","تعلم ادارة المشروع")),
    build_args=lambda g:{"path":_tail(g,("learn development ","learn project ","learn to build manage ","تعلم تطوير ","تعلم من المشروع ","تعلم بناء المشروع ","تعلم ادارة المشروع "))},
    capability="development_learning", produces=("project_knowledge_learned","learning_candidate"), cost=8.0,duration=8.0,
    parallel_safe=False,idempotent=True,verification_level="strong",intent_priority=11,
)
def learn_development_tool(path: str):
    return learn_development(str(safe_workspace_path(path)))


@tool(
    "عرض ذاكرة البحث المتراكمة وعدد عمليات التعلم والأدلة المفهرسة وتوزيع مصادرها",
    {}, name="research_status",
    triggers=("research status","learning status","حالة البحث","حالة التعلم","ذاكرة البحث"),
    match=lambda g:any(x in g.casefold() for x in ("research status","learning status","حالة البحث","حالة التعلم","ذاكرة البحث")),
    capability="research_memory_observability", produces=("research_memory_observed",), cost=0.3,duration=0.05, exploration_safe=True, emits_world_delta=False,
    information_domains=("memory",), information_gain_prior=0.52,
    parallel_safe=True,idempotent=True,verification_level="strong",intent_priority=8,
)
def research_status_tool():
    return research_status()


@tool(
    "استرجاع الأدلة البحثية السابقة ذات الصلة مع provenance ودرجة novelty/quality؛ لا يعد ذلك حقيقة نهائية",
    {"query":"str"}, name="research_memory_search",
    triggers=("research memory search","recall research","استرجع البحث","ابحث في ذاكرة البحث","استرجع أدلة البحث"),
    match=lambda g:any(x in g.casefold() for x in ("research memory search","recall research","استرجع البحث","ابحث في ذاكرة البحث","استرجع أدلة البحث")),
    build_args=lambda g:{"query":_tail(g,("research memory search ","recall research ","استرجع البحث ","ابحث في ذاكرة البحث ","استرجع أدلة البحث "))},
    capability="research_memory_retrieval", produces=("historical_research_evidence",), cost=0.6,duration=0.1, exploration_safe=True, emits_world_delta=False,
    information_domains=("research", "learning", "memory"), information_gain_prior=0.92,
    parallel_safe=True,idempotent=True,verification_level="strong",intent_priority=8,
)
def research_memory_search_tool(query: str):
    return research_sources(query,limit=20)


@tool(
    "عرض كيف توزعت فائدة Web/arXiv/GitHub سابقًا لهذا السياق لمساعدة قرار المصدر التالي",
    {"query":"str"}, name="research_source_learning",
    triggers=("source learning","source portfolio","خبرة المصادر","تعلم المصادر","سياسة المصادر"),
    match=lambda g:any(x in g.casefold() for x in ("source learning","source portfolio","خبرة المصادر","تعلم المصادر","سياسة المصادر")),
    build_args=lambda g:{"query":_tail(g,("source learning ","source portfolio ","خبرة المصادر ","تعلم المصادر ","سياسة المصادر "))},
    capability="research_source_policy", produces=("source_policy_observed",), cost=0.4,duration=0.05, exploration_safe=True, emits_world_delta=False,
    information_domains=("source_policy",), information_gain_prior=0.48,
    parallel_safe=True,idempotent=True,verification_level="strong",intent_priority=8,
)
def research_source_learning_tool(query: str):
    return research_source_learning(query)
