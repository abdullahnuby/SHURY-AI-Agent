from app.runtime.registry import tool
from app.integrations.network import NetworkGateway, extract_text
from app.knowledge.web_research import WebResearchEngine
from app.knowledge.rag import RAGEngine
import json
import re
from pathlib import Path
from urllib.parse import urlparse


def _quoted_or_tail(goal: str, marker_words=()):
    quoted = re.findall(r'["\']([^"\']+)["\']', goal)
    if quoted:
        return quoted[-1]
    for marker in marker_words:
        pos = goal.casefold().find(marker.casefold())
        if pos >= 0:
            return goal[pos + len(marker):].strip()
    return goal.strip()


@tool(
    "بحث مباشر على الويب ثم جلب صفحات مرشحة وتخزين الأدلة محليًا مع provenance؛ HTTP(S) فقط، ومخرجاتها أدلة خام للمحلل الحتمي",
    {"query": "str"},
    name="web_research",
    triggers=("web research", "research the web", "search online", "search the internet", "ابحث على الانترنت", "ابحث على الإنترنت", "بحث على الويب", "بحث على الانترنت", "اعمل بحث", "اخر الابحاث", "أحدث الأبحاث", "newest research", "latest research", "أحدث بحث"),
    match=lambda g: (not any(x in g.casefold() for x in ("web and github", "internet and github", "web, github", "internet, github", "github and web", "github research and web")))
                     and (any(x in g.casefold() for x in ("web research", "research the web", "search online", "search the internet", "ابحث على الانترنت", "ابحث على الإنترنت", "بحث على الويب", "بحث على الانترنت", "اعمل بحث", "اخر الابحاث", "أحدث الأبحاث", "newest research", "latest research", "أحدث بحث"))
                     or ("research" in g.casefold() and any(x in g.casefold() for x in ("newest", "latest", "internet", "online", "web"))))
                     and "notes" not in g.casefold(),
    build_args=lambda g: {"query": _quoted_or_tail(g, ("web research ", "research the web ", "learn from the web ", "learn from web ", "search online ", "search the internet ", "ابحث على الانترنت ", "ابحث على الإنترنت ", "بحث على الويب ", "بحث على الانترنت ", "اعمل بحث ", "أحدث الأبحاث ", "اخر الابحاث ", "newest research ", "latest research "))},
    capability="internet_research",
    produces=("web_evidence", "knowledge_indexed"),
    cost=3.5,
    duration=2.0,
    parallel_safe=True,
    idempotent=True,
    verification_level="strong",
    intent_priority=8, exploration_safe=True, emits_world_delta=False,
    information_domains=("research", "current_data", "learning", "external_web"), information_gain_prior=0.88,
)
def web_research_tool(query: str):
    return WebResearchEngine().research(query, limit=5, index=True)


@tool(
    "جلب صفحة ويب واحدة وتحويلها إلى نص نظيف مع hash وprovenance، مع حماية SSRF وحدود الحجم والوقت",
    {"url": "str"},
    name="http_get",
    triggers=("http get", "fetch url", "open url", "جلب الرابط", "افتح الرابط", "هات الرابط", "fetch https"),
    match=lambda g: any(x in g.casefold() for x in ("http get", "fetch url", "open url", "جلب الرابط", "افتح الرابط", "هات الرابط", "fetch https")),
    build_args=lambda g: {"url": _quoted_or_tail(g, ("http get ", "fetch url ", "open url ", "جلب الرابط ", "افتح الرابط ", "هات الرابط ", "fetch "))},
    capability="internet_fetch",
    produces=("web_page_fetched",),
    cost=1.6,
    duration=1.0,
    risk="medium",
    parallel_safe=True,
    idempotent=True,
    verification_level="strong",
    intent_priority=7,
)
def http_get_tool(url: str):
    gateway = NetworkGateway()
    result = gateway.fetch(url)
    text = extract_text(result.body, result.content_type, result.final_url)
    return {"url": result.final_url, "requested_url": result.requested_url, "status": result.status,
            "content_type": result.content_type, "sha256": result.sha256, "bytes": len(result.body),
            "latency_ms": result.latency_ms, "text": text[:80_000], "robots_allowed": result.robots_allowed}


@tool(
    "بحث شامل واحد على الإنترنت يجمع Web + أحدث أبحاث arXiv + GitHub repositories، ثم يفهرس الأدلة القابلة لإعادة الاستخدام في RAG",
    {"query": "str"},
    name="internet_research",
    triggers=("internet research", "deep research", "search web github", "web and github", "internet and github", "أبحاث الانترنت والجيت هب", "ابحث في الويب وgithub", "أحدث الأبحاث والـgithub"),
    match=lambda g: any(x in g.casefold() for x in ("internet research", "deep research", "search web github", "web and github", "internet and github", "أبحاث الانترنت والجيت هب", "ابحث في الويب وgithub", "أحدث الأبحاث والـgithub"))
          or ("research" in g.casefold() and "github" in g.casefold() and any(x in g.casefold() for x in ("web", "internet", "online"))),
    build_args=lambda g: {"query": g.strip()},
    capability="internet_deep_research",
    produces=("web_evidence", "research_evidence", "github_evidence", "knowledge_indexed"),
    cost=6.5,
    duration=6.0,
    parallel_safe=False,
    idempotent=True,
    verification_level="strong",
    intent_priority=10, exploration_safe=True, emits_world_delta=False,
    information_domains=("research", "current_data", "learning", "development", "external_web"), information_gain_prior=0.92,
)
def internet_research_tool(query: str):
    return WebResearchEngine().internet_research(query, web_limit=5, paper_limit=6, repo_limit=5, index=True)


@tool(
    "اكتشاف أحدث الأبحاث من arXiv بالـofficial API بترتيب تاريخ الإرسال، وحفظ abstracts مع provenance داخل RAG",
    {"query": "str"},
    name="arxiv_research",
    triggers=("arxiv research", "latest papers", "newest papers", "recent academic papers", "recent papers", "academic papers", "find recent academic papers", "أحدث الأبحاث العلمية", "أحدث أبحاث", "أحدث الأوراق العلمية", "الأوراق العلمية", "ابحث في arxiv", "ابحث في أبحاث"),
    match=lambda g: (any(x in g.casefold() for x in ("arxiv research", "latest papers", "newest papers", "recent academic papers", "recent papers", "academic papers", "find recent academic papers", "أحدث الأبحاث العلمية", "أحدث أبحاث", "أحدث الأوراق العلمية", "الأوراق العلمية", "ابحث في arxiv", "ابحث في أبحاث"))
                     or ("research" in g.casefold() and any(x in g.casefold() for x in ("paper", "papers", "arxiv"))))
                     and not any(x in g.casefold() for x in ("on the web", "online", "internet", "على الانترنت", "على الإنترنت", "على الويب")),
    build_args=lambda g: {"query": _quoted_or_tail(g, ("arxiv research ", "latest papers ", "newest papers ", "recent academic papers ", "recent papers ", "academic papers ", "find recent academic papers ", "أحدث الأبحاث العلمية ", "أحدث أبحاث ", "ابحث في arxiv "))},
    capability="scientific_research",
    produces=("research_evidence", "knowledge_indexed"),
    cost=3.0,
    duration=2.0,
    parallel_safe=True,
    idempotent=True,
    verification_level="strong",
    intent_priority=9, exploration_safe=True, emits_world_delta=False,
    information_domains=("research", "learning", "knowledge", "external_web"), information_gain_prior=0.96,
)
def arxiv_research_tool(query: str):
    return WebResearchEngine().arxiv_research(query, limit=8, index=True)


@tool(
    "اكتشاف مستودعات GitHub العامة حسب الوصف واللغة وتاريخ التحديث، بدون تعديل أي مستودع",
    {"query": "str"},
    name="github_search",
    triggers=("github search", "search github repositories", "find github repos", "ابحث عن مشاريع github", "دور على مشاريع github"),
    match=lambda g: any(x in g.casefold() for x in ("github search", "search github repositories", "find github repos", "ابحث عن مشاريع github", "دور على مشاريع github")),
    build_args=lambda g: {"query": _quoted_or_tail(g, ("github search ", "search github repositories ", "find github repos ", "ابحث عن مشاريع github ", "دور على مشاريع github "))},
    capability="github_discovery",
    produces=("github_projects_discovered",),
    cost=1.8,
    duration=1.0,
    parallel_safe=True,
    idempotent=True,
    verification_level="strong",
    intent_priority=8, exploration_safe=True, emits_world_delta=False,
    information_domains=("development", "research", "learning", "external_web"), information_gain_prior=0.82,
)
def github_search_tool(query: str):
    return WebResearchEngine().github_search(query, limit=8)


@tool(
    "تحليل مستودع GitHub عام: metadata + شجرة الملفات + README/CI/package files والكود المهم، ثم فهرستها في RAG ليتعلم منها الـAgent",
    {"repo": "str"},
    name="github_research",
    triggers=("github research", "inspect github", "analyze github repo", "حلل مستودع github", "ابحث في github", "تعلم من github"),
    match=lambda g: any(x in g.casefold() for x in ("github research", "inspect github", "analyze github repo", "حلل مستودع github", "ابحث في github", "تعلم من github")),
    build_args=lambda g: {"repo": _quoted_or_tail(g, ("github research ", "inspect github ", "analyze github repo ", "حلل مستودع github ", "ابحث في github ", "تعلم من github "))},
    capability="github_learning",
    produces=("github_evidence", "knowledge_indexed"),
    cost=4.0,
    duration=3.0,
    parallel_safe=True,
    idempotent=True,
    verification_level="strong",
    intent_priority=8, exploration_safe=True, emits_world_delta=False,
)
def github_research_tool(repo: str):
    return WebResearchEngine().github_research(repo, file_limit=24, index=True)


@tool(
    "إظهار حالة الإنترنت والـnetwork gateway والإحصاءات والحدود الأمنية المحلية",
    {},
    name="network_status",
    triggers=("network status", "internet status", "حالة الانترنت", "حالة الإنترنت", "حالة الشبكة", "network stats"),
    match=lambda g: any(x in g.casefold() for x in ("network status", "internet status", "حالة الانترنت", "حالة الإنترنت", "حالة الشبكة", "network stats")),
    capability="network_observability",
    produces=("network_status_observed",),
    cost=0.5,
    duration=0.05,
    parallel_safe=True,
    idempotent=True,
    verification_level="strong",
    intent_priority=6, exploration_safe=True, emits_world_delta=False,
)
def network_status_tool():
    return NetworkGateway().stats()


def _dataset_url(goal: str) -> str:
    m = re.search(r'https?://[^\s"\']+', goal)
    if not m:
        raise ValueError("dataset URL is required")
    return m.group(0).rstrip(".,)")


def _safe_filename(url: str) -> str:
    path = Path(urlparse(url).path)
    name = path.name or "remote_data"
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
    if not Path(name).suffix:
        name += ".txt"
    return name[:120]


@tool(
    "تنزيل Dataset عامة bounded إلى data/remote مع hash وsource URL؛ يحتاج موافقة لأنه يغيّر ملفات محلية",
    {"url": "str"},
    name="download_dataset",
    triggers=("download dataset", "download data", "نزّل البيانات", "نزل البيانات", "تحميل البيانات", "احفظ dataset"),
    match=lambda g: any(x in g.casefold() for x in ("download dataset", "download data", "نزّل البيانات", "نزل البيانات", "تحميل البيانات", "احفظ dataset")),
    build_args=lambda g: {"url": _dataset_url(g)},
    capability="data_acquisition",
    produces=("dataset_downloaded",),
    cost=3.0,
    duration=2.0,
    requires_approval=True,
    risk="medium",
    parallel_safe=False,
    idempotent=True,
    verification_level="strong",
    intent_priority=7,
)
def download_dataset_tool(url: str):
    gateway = NetworkGateway(max_bytes=8_000_000)
    result = gateway.fetch(url, accept="text/csv,application/json,text/plain,application/octet-stream,*/*")
    root = Path(__file__).resolve().parents[2] / "data" / "remote"
    root.mkdir(parents=True, exist_ok=True)
    filename = _safe_filename(result.final_url)
    target = root / filename
    target.write_bytes(result.body)
    digest = result.sha256
    return {"path": str(target), "url": result.final_url, "sha256": digest, "bytes": len(result.body),
            "content_type": result.content_type, "verified": target.exists() and target.stat().st_size == len(result.body)}
