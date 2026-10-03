"""V21 skill supply-chain facade."""
from app.skills.discovery import SkillDiscovery, discovery_snapshot, CURATED_REPOSITORIES
from app.knowledge.research_memory import ResearchMemory
from app.skills.registry import SkillBank


def discover_skills(query: str):
    return SkillDiscovery().discover(query)


def install_skill(repo: str, skill_path: str):
    return SkillDiscovery().install(repo, skill_path)


def refresh_skill(key: str):
    return SkillDiscovery().refresh(key)


def installed_skills():
    return SkillDiscovery().list_installed()


def skill_routes(query: str = "", limit: int = 20):
    return SkillDiscovery().route(query, limit=limit)


def skill_supply_status():
    bank = SkillBank()
    lifecycle = {}
    for skill in bank.list():
        lifecycle[skill.status] = lifecycle.get(skill.status, 0) + 1
    return {"skills": discovery_snapshot(), "research": ResearchMemory().stats(),
            "skill_bank": {"total": len(bank.list()), "by_status": lifecycle}}


def _candidate_score(query: str, item: dict, curated: tuple[str, ...]) -> float:
    import re
    def toks(v):
        return set(re.findall(r"[\w\u0600-\u06ff]+", str(v).casefold(), re.UNICODE))
    q = toks(query)
    text = toks(" ".join((item.get("name", ""), item.get("description", ""), item.get("skill_path", ""))))
    overlap = len(q & text) / max(1, len(q))
    repo_bonus = 0.22 if item.get("repository") in curated else 0.0
    desc_bonus = min(0.12, len(str(item.get("description", ""))) / 900.0)
    return 0.66 * overlap + repo_bonus + desc_bonus


def learn_skills(query: str, *, max_installs: int = 3) -> dict:
    """Research a topic, discover real Agent Skills, and quarantine the best bounded packages."""
    from app.knowledge.open_world import OpenWorldResearchEngine
    discovery = SkillDiscovery()
    research = OpenWorldResearchEngine().learn(query)
    found = discovery.discover(query, max_skills=max(10, max_installs * 4))
    ranked = sorted(found.get("skills", []), key=lambda x: (-_candidate_score(query, x, CURATED_REPOSITORIES), x.get("repository", ""), x.get("skill_path", "")))
    installed = []
    errors = []
    seen = set()
    used_families = set()
    budget = max(1, min(10, max_installs))
    for pass_no in (0, 1):
        for item in ranked:
            if len(installed) >= budget:
                break
            ident = (item.get("repository"), item.get("skill_path"))
            family = (item.get("repository"), item.get("skill_path", "").split("/")[-2] if "/" in item.get("skill_path", "") else "root")
            if ident in seen or (pass_no == 0 and family in used_families):
                continue
            seen.add(ident)
            try:
                installed.append(discovery.install(item["repository"], item["skill_path"]))
                used_families.add(family)
            except Exception as exc:
                errors.append({"repository": item.get("repository"), "skill_path": item.get("skill_path"), "error": str(exc)})
        if len(installed) >= budget:
            break
    return {"query": query, "research_run": research.get("run_id"), "discovered": found,
            "installed_count": len(installed), "installed": installed, "errors": errors,
            "policy": "skills are acquired as audited, quarantined candidates; no remote package is activated automatically"}


def approve_remote_skill(key: str):
    return SkillDiscovery().approve_and_trust(key)
