"""V19 Skill standard, governance, differential evaluation and adaptive-selection facade."""
from app.skills.standard import validate_skill_package, load_skill
from app.skills.research import import_package, research_to_candidate
from app.skills.evaluation import lifecycle_recommendation, summary as evaluation_summary
from app.skills.registry import SkillBank


def inspect_skill(path: str):
    return validate_skill_package(path)


def skill_metadata(path: str):
    p = load_skill(path, level="metadata")
    return {
        "name": p.name, "description": p.description, "license": p.license,
        "compatibility": p.compatibility, "metadata": p.metadata,
        "allowed_tools": list(p.allowed_tools), "sha256": p.sha256,
        "references": list(p.references), "scripts": list(p.scripts), "assets": list(p.assets),
        "policy": "metadata-only progressive disclosure",
    }


def activate_skill_view(path: str):
    p = load_skill(path, level="resources")
    return {
        "name": p.name, "description": p.description, "body": p.body,
        "allowed_tools": list(p.allowed_tools), "workflow": p.workflow,
        "references": list(p.references), "scripts": list(p.scripts), "assets": list(p.assets),
        "sha256": p.sha256,
    }


def skill_evidence(key: str):
    bank = SkillBank()
    return {"key": key, "trust": bank.trust(key), "evaluation": evaluation_summary(key),
            "lifecycle": lifecycle_recommendation(key)}
