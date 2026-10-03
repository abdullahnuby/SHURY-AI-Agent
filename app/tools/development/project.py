from app.runtime.registry import tool
from app.runtime.security import safe_workspace_path
from app.integrations.devops import inspect_project, git_status, check_project
import re


def _path(goal: str) -> str:
    quoted = re.findall(r'["\']([^"\']+)["\']', goal)
    if quoted:
        return quoted[-1]
    m = re.search(r'((?:[A-Za-z]:[\\/]|/)[^\n]+?)(?:\s+(?:عن|for|ثم|and)\s+|$)', goal)
    if m:
        return m.group(1).strip().rstrip('.,')
    # No explicit path: use the current workspace. Passing the whole natural-language
    # request as a filesystem path was a real routing bug.
    return "."


def _check_names(goal: str):
    g = goal.casefold()
    names = []
    if "git" in g:
        names.append("git-diff-check")
    for k in ("test", "tests", "اختبارات"):
        if k in g:
            names.append("pytest")
            names.append("test")
    if "compile" in g or "compileall" in g or "ترجمة" in g or "فحص" in g:
        names.append("compile")
    if not names:
        names = ["git-diff-check", "compile"]
    # de-dupe while preserving order
    out=[]
    for n in names:
        if n not in out: out.append(n)
    return out


@tool(
    "فحص مشروع برمجي محلي: يكتشف Python/Node/Rust/Go/Maven/Gradle والـmanifests وأوامر build/test الآمنة",
    {"path": "str"},
    name="inspect_project",
    triggers=("inspect project", "analyze project", "inspect repository", "حلل المشروع", "افحص المشروع", "حلل الريبو"),
    match=lambda g: any(x in g.casefold() for x in ("inspect project", "analyze project", "inspect repository", "حلل المشروع", "افحص المشروع", "حلل الريبو")),
    build_args=lambda g: {"path": _path(g)},
    capability="development_inspection",
    produces=("project_inspected",),
    cost=1.0,
    duration=0.2,
    parallel_safe=True,
    idempotent=True,
    verification_level="strong",
    intent_priority=7, exploration_safe=True, emits_world_delta=False,
    information_domains=("development", "workspace"), information_gain_prior=0.88,
)
def inspect_project_tool(path: str):
    return inspect_project(safe_workspace_path(path))


@tool(
    "فحص حالة Git المحلية والفرع والـworking tree وآخر 5 commits بدون أي تعديل",
    {"path": "str"},
    name="git_status",
    triggers=("git status", "repository status", "حالة git", "حالة المستودع"),
    match=lambda g: any(x in g.casefold() for x in ("git status", "repository status", "حالة git", "حالة المستودع")),
    build_args=lambda g: {"path": _path(g)},
    capability="development_git",
    produces=("git_status_observed",),
    cost=0.6,
    duration=0.1,
    parallel_safe=True,
    idempotent=True,
    verification_level="strong",
    intent_priority=6, exploration_safe=True, emits_world_delta=False,
    information_domains=("development", "workspace"), information_gain_prior=0.76,
)
def git_status_tool(path: str):
    return git_status(safe_workspace_path(path))


@tool(
    "تنفيذ فحوصات build/test المكتشفة من project manifest وgit diff --check بدون shell ومع timeout",
    {"path": "str", "checks": "list[str]"},
    name="check_project",
    triggers=("check project", "build project", "build the project", "test project", "run project tests", "run the tests", "build and test", "ابني المشروع", "اختبر المشروع", "افحص build", "شغل الاختبارات"),
    match=lambda g: any(x in g.casefold() for x in ("check project", "build project", "build the project", "test project", "run project tests", "run the tests", "build and test", "ابني المشروع", "اختبر المشروع", "افحص build", "شغل الاختبارات")),
    build_args=lambda g: {"path": _path(g), "checks": _check_names(g)},
    capability="development_validation",
    produces=("project_checked",),
    cost=2.5,
    duration=10.0,
    requires_approval=True,
    risk="medium",
    parallel_safe=False,
    idempotent=True,
    verification_level="strong",
    intent_priority=7,
)
def check_project_tool(path: str, checks=None):
    return check_project(safe_workspace_path(path), tuple(checks or ("git-diff-check", "compile")))
