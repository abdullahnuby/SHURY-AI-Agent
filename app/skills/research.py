"""Turn trusted research discoveries into skill candidates without executing prose.

A research result can install declarative procedural knowledge only when it comes from
an Agent Skills package or a machine-readable workflow contract. Plain web text is kept
as evidence, not converted into executable steps.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from app.skills.registry import SkillBank
from app.skills.standard import validate_skill_package, load_skill
from app.skills.governance import assess_skill


def import_package(path: str | Path, *, bank_path=None, source="external", skill_key: str | None = None) -> dict:
    info = validate_skill_package(path)
    admission = assess_skill(info, source=source)
    if not admission.allowed:
        return {"imported": False, "admission": admission.__dict__, "validation": info}
    package = load_skill(path, level="resources")
    workflow = package.workflow or {}
    steps = workflow.get("steps", []) if isinstance(workflow, dict) else []
    workflow_errors = []
    if steps:
        # Only import machine-readable steps, never infer workflow from Markdown prose.
        normalized = []
        allowed_tools = set(package.allowed_tools)
        seen_ids = set()
        try:
            from app.runtime.registry import load_tools
            registry = load_tools()
        except Exception:
            registry = {}
        for i, item in enumerate(steps, 1):
            if not isinstance(item, dict) or not item.get("tool"):
                workflow_errors.append("workflow step must contain a tool")
                continue
            step_id = f"s{i}"
            tool_name = str(item["tool"])
            if tool_name not in registry:
                workflow_errors.append(f"unknown tool: {tool_name}")
            if allowed_tools and tool_name not in allowed_tools:
                workflow_errors.append(f"tool not in allowed-tools: {tool_name}")
            deps = []
            for dep in list(item.get("depends_on", [])):
                dep_id = f"s{dep}" if isinstance(dep, int) else str(dep)
                if dep_id not in seen_ids:
                    workflow_errors.append(f"dependency {dep_id} is not a prior step")
                deps.append(dep_id)
            normalized.append({"tool": tool_name, "depends_on": deps,
                               "capability": item.get("capability", ""), "args_policy": "derive-from-live-goal"})
            seen_ids.add(step_id)
        workflow_tuple = tuple(normalized) if not workflow_errors else ()
    else:
        workflow_tuple = ()
    # External supply-chain entries must retain their manifest identity. Older callers
    # that do not provide it keep the historical pkg:<hash> key for compatibility.
    key = skill_key or ("pkg:" + hashlib.sha256((package.name + "|" + package.sha256).encode()).hexdigest()[:16])
    evidence = [{"kind":"skill-package", "path": package.root, "sha256": package.sha256,
                 "source": source, "security": info.get("security_findings", [])}]
    bank = SkillBank(bank_path) if bank_path else SkillBank()
    skill = bank.upsert(key=key, name=package.name, triggers=(package.name, package.description),
                        contraindications=("untrusted package",), preconditions=(), workflow=workflow_tuple,
                        termination="verify outputs or replan on failed postcondition", outputs=(), evidence=evidence,
                        confidence=0.35 if admission.trust != "local" else 0.55, source=source,
                        status="candidate")
    bank.set_trust(key, admission.trust)
    skill = bank.get(key)
    return {"imported": True, "admission": admission.__dict__, "validation": info,
            "workflow_errors": workflow_errors,
            "skill": skill.__dict__ | {"utility": skill.utility}, "executable_workflow": bool(workflow_tuple),
            "policy": "external prose is evidence; only validated workflow.json may supply executable steps"}


def research_to_candidate(query: str, sources: list[dict], *, bank_path=None) -> dict:
    # Declarative candidate only; a human/verified run must supply procedural steps.
    key = "research:" + hashlib.sha256(query.casefold().encode()).hexdigest()[:16]
    evidence = []
    for src in sources[:10]:
        evidence.append({"url": src.get("url"), "title": src.get("title"), "sha256": src.get("sha256"),
                         "source": src.get("source") or src.get("source_kind"), "score": src.get("score")})
    skill = SkillBank(bank_path).upsert(key=key, name=f"Research knowledge: {query[:72]}",
        triggers=tuple(query.split()[:10]), workflow=(), evidence=evidence, confidence=0.25,
        source="research", status="candidate") if bank_path else SkillBank().upsert(
        key=key, name=f"Research knowledge: {query[:72]}", triggers=tuple(query.split()[:10]), workflow=(), evidence=evidence,
        confidence=0.25, source="research", status="candidate")
    return {"candidate": skill.__dict__ | {"utility": skill.utility}, "evidence_count": len(evidence),
            "policy": "knowledge candidate only; executable skill requires machine-readable workflow or verified runtime"}
