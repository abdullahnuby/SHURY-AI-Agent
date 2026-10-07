"""Deterministic semantic capability resolution and argument grounding.

This module deliberately knows nothing about language generation. It bridges the
semantic/task IR vocabulary to the executable Tool contracts already present in the
runtime registry.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


INTENT_TO_CAPABILITY: dict[str, str] = {
    "time": "time",
    "project_audit": "project_audit",
    "development_validation": "development_validation",
    "development_inspection": "development_inspection",
    "development_git": "development_git",
    "workspace_reasoning": "workspace_reasoning",
    "workspace_files": "workspace_files",
    "skill_discovery": "skill_discovery",
    "skill_selection": "skill_selection",
    "skill_inventory": "skill_inventory",
    "skill_routing": "skill_routing",
    "list_skills": "skill_management",
    "github_discovery": "github_discovery",
    "github_learning": "github_learning",
    "scientific_research": "scientific_research",
    "web_research": "internet_research",
    "open_world_learning": "open_world_learning",
    "data_analysis": "data_analysis",
    "cross_department_data_move": "cross_department_data_move",
    "cross_department_sales_report_move": "cross_department_sales_report_move",
    "agentic_rag": "agentic_rag",
    "rag_reasoning": "rag_reasoning",
    "memory_search": "memory_search",
    "memory_profile": "memory_profile",
    "memory_stats": "memory_stats",
    "memory_history": "memory_history",
    "list_notes": "list_notes",
    "search_notes": "search_notes",
    "calculate": "calculate",
    "save_note": "save_note",
    "remember_fact": "remember_fact",
    "recall_fact": "recall_fact",
    "remember_result": "remember_result",
    "remember_last_result": "remember_last_result",
    "history": "recent_runs",
    "knowledge_query": "question_answering",
}


@dataclass(frozen=True)
class CapabilityMatch:
    tool: str
    score: float
    evidence: tuple[str, ...] = ()


def _norm(value: Any) -> str:
    return str(value or "").casefold().strip()


def _tokens(value: Any) -> set[str]:
    return {x for x in re.findall(r"[\w\u0600-\u06ff]+", _norm(value)) if len(x) > 1}


def _node_source(node: Any) -> str:
    return str(getattr(node, "objective", "") or getattr(node, "planner_goal", "") or "").strip()


def _semantic_values(node: Any) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, value in (getattr(node, "arguments", {}) or {}).items():
        if value in (None, ""):
            continue
        values[str(key)] = str(value).strip()
    return values


def grounded_args(tool: Any, node: Any) -> dict[str, Any]:
    """Build tool arguments from tool-native parsers first, then typed semantic slots."""
    source = _node_source(node)
    args: dict[str, Any] = {}
    try:
        candidate = tool.args_for(source)
        if isinstance(candidate, dict):
            args.update(candidate)
    except Exception:
        pass

    values = _semantic_values(node)
    aliases: dict[str, tuple[str, ...]] = {
        "expression": ("expression", "operation:expression"),
        "key": ("key", "remember:key", "recall:key", "result:key", "correction:key", "memory:key", "theme:key"),
        "value": ("value", "remember:value", "remember_result:value", "remember_memory:value", "correction:value"),
        "text": ("text", "note:text", "save_note:text"),
        "query": ("query", "research:query", "skill:query", "search:query", "memory:query", "question"),
        "question": ("question", "analysis:question", "query"),
        "path": ("path", "file:path", "repository:path", "workspace:path", "project:path", "data:path"),
        "repo": ("repo", "repository", "github:repo"),
        "url": ("url", "source:url"),
        "subject": ("subject", "memory:subject"),
        "goal": ("goal", "task:goal"),
        "status": ("status", "skill:status"),
        "skill_path": ("skill_path", "skill:path"),
        "content": ("content", "file:content"),
        "checks": ("checks", "validation:checks"),
    }

    # Exact parameter-name matches first.
    for key in list(tool.params):
        if key in values and key not in args:
            args[key] = values[key]

    # Namespaced semantic slots and conservative heuristics second.
    for param, candidates in aliases.items():
        if param not in tool.params:
            continue
        for candidate in candidates:
            if candidate in values and values[candidate]:
                # Typed semantic slots are higher-quality evidence than a legacy
                # tool parser operating on the original natural-language surface.
                # This matters for questions such as "متى الاجتماع؟": the semantic
                # layer has already reduced the memory query to "اجتماع" and the tool
                # must not overwrite it with the full question.
                args[param] = values[candidate]
                break

    # Generic entity grounding for common workspace/research objects.
    if "path" in tool.params and args.get("path") in (None, ""):
        for entity in getattr(node, "entities", ()) or ():
            etype = _norm(getattr(entity, "type", ""))
            if etype in {"file", "repository", "directory", "path"}:
                args["path"] = str(getattr(entity, "canonical", "") or getattr(entity, "text", ""))
                break

    # Keep fallback grounding conservative; never emit keys outside the Tool contract.
    return {k: v for k, v in args.items() if k in tool.params and v not in (None, "")}


def resolve_capabilities(node: Any, registry: dict[str, Any], limit: int = 4) -> list[CapabilityMatch]:
    source = _node_source(node)
    intent = _norm(getattr(node, "intent", ""))
    requested_cap = _norm(getattr(node, "capability", "")) or _norm(INTENT_TO_CAPABILITY.get(intent, ""))
    source_tokens = _tokens(source)
    matches: list[CapabilityMatch] = []

    for name, tool in registry.items():
        tool_cap = _norm(getattr(tool, "capability", "") or name)
        desc = _norm(getattr(tool, "description", ""))
        trigger_text = " ".join(str(x) for x in (getattr(tool, "triggers", ()) or ()))
        trigger_tokens = _tokens(trigger_text)
        evidence: list[str] = []
        score = 0.0

        if requested_cap and tool_cap == requested_cap:
            score += 8.0
            evidence.append("capability-exact")
        elif requested_cap and requested_cap in tool_cap:
            score += 3.0
            evidence.append("capability-family")

        if intent and tool_cap == _norm(INTENT_TO_CAPABILITY.get(intent, "")):
            score += 2.5
            evidence.append("intent-capability")

        overlap = len(source_tokens & trigger_tokens) / max(1, len(source_tokens))
        if overlap:
            score += 3.0 * overlap
            evidence.append(f"trigger-overlap={overlap:.2f}")

        # A matching tool is strong evidence, but a custom matcher returning False is a
        # hard negative and must never be revived by semantic capability similarity.
        try:
            matched = bool(tool.matches(source))
        except Exception:
            matched = False
        exact_capability = bool(requested_cap and tool_cap == requested_cap)
        if matched:
            score += 2.5
            evidence.append("tool-match")
        elif getattr(tool, "match", None) is not None and not exact_capability:
            # A custom matcher is still a hard negative during fuzzy resolution.
            # A typed semantic capability, however, is stronger evidence than a matcher
            # that simply lacks a paraphrase such as "list my skills".
            continue
        elif exact_capability:
            score += 1.5
            evidence.append("semantic-capability-override")

        ground = grounded_args(tool, node)
        validation_errors = tool.validate_args(ground)
        if not validation_errors:
            score += 0.75
            evidence.append("arguments-grounded")
        elif getattr(tool, "params", None):
            # Do not discard a strong capability match just because an argument must be
            # filled by a later pipe. Penalize it instead.
            score -= 0.60
            evidence.append("arguments-incomplete")

        if score <= 0:
            continue
        matches.append(CapabilityMatch(name, score, tuple(evidence)))

    matches.sort(key=lambda m: (-m.score, m.tool))
    return matches[: max(1, int(limit))]
