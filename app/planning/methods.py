"""Deterministic high-level task methods for SHURY's model-free planner.

Methods are domain procedures, not language generation.  They turn a known semantic
objective into smaller, explicit subgoals when the user's request contains enough
cues to justify the decomposition.  Every generated node still goes through normal
capability grounding, operator preconditions, plan validation and certification.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any, Callable, Iterable

from app.domain.task_ir import TaskIR, TaskNode
from app.intelligence.understanding import normalize


@dataclass(frozen=True)
class MethodApplication:
    name: str
    reason: str
    nodes: tuple[TaskNode, ...]


class TaskMethod:
    def __init__(self, name: str, matcher: Callable[[TaskNode], bool], expand: Callable[[TaskNode], Iterable[TaskNode]], reason: str):
        self.name = name
        self.matcher = matcher
        self.expand = expand
        self.reason = reason

    def apply(self, node: TaskNode) -> MethodApplication | None:
        if not self.matcher(node):
            return None
        expanded = tuple(self.expand(node))
        return MethodApplication(self.name, self.reason, expanded) if expanded else None


def _norm(node: TaskNode) -> str:
    return normalize(f"{node.objective} {node.planner_goal}").strip()


def _make(base: TaskNode, suffix: str, *, objective: str, planner_goal: str, intent: str, capability: str,
          depends_on: tuple[str, ...], relation: str = "then", confidence_delta: float = 0.0) -> TaskNode:
    return replace(
        base,
        id=f"{base.id}{suffix}",
        objective=objective,
        planner_goal=planner_goal,
        kind="action",
        intent=intent,
        capability=capability,
        depends_on=depends_on,
        relation=relation,
        success_conditions=(f"intent:{intent}",),
        confidence=max(0.0, min(1.0, base.confidence + confidence_delta)),
    )


def _is_release_readiness(node: TaskNode) -> bool:
    if node.intent not in {"development_validation", "development_inspection", "workspace_reasoning"}:
        return False
    text = _norm(node)
    markers = (
        "release readiness", "ready for release", "ready to release", "production readiness",
        "ready for production", "ready to deploy", "deployment readiness", "launch readiness",
        "جاهز للاطلاق", "جاهز للإطلاق", "جاهز للنشر", "جاهز للانتاج", "جاهز للإنتاج", "جاهزية الاطلاق",
    )
    return any(marker in text for marker in markers)


def _release_readiness(node: TaskNode) -> Iterable[TaskNode]:
    pfx = node.id
    t1 = _make(node, ".inspect", objective="inspect the project", planner_goal="inspect project",
               intent="development_inspection", capability="development_inspection", depends_on=())
    t2 = _make(node, ".git", objective="inspect repository state", planner_goal="git status",
               intent="development_git", capability="development_git", depends_on=(t1.id,))
    t3 = _make(node, ".check", objective="run the project's build and tests", planner_goal="check project build and test",
               intent="development_validation", capability="development_validation", depends_on=(t2.id,))
    return (t1, t2, t3)


def _is_research_grounding(node: TaskNode) -> bool:
    if node.intent not in {"web_research", "scientific_research", "open_world_learning", "rag_reasoning"}:
        return False
    text = _norm(node)
    search_terms = ("search", "research", "latest", "recent", "find papers", "ابحث", "أحدث الأبحاث", "الأبحاث")
    evidence_terms = ("knowledge base", "retrieve evidence", "indexed", "evidence", "المعرفة", "الأدلة", "المصادر")
    return any(x in text for x in search_terms) and any(x in text for x in evidence_terms)


def _research_grounding(node: TaskNode) -> Iterable[TaskNode]:
    text = node.objective.strip()
    marker = re.search(r"(?:and|then|بعدها|ثم|و)", text, re.I)
    query = text
    if marker:
        query = text[:marker.start()].strip(" ,؛") or text
    retrieval = node.objective
    t1 = _make(node, ".research", objective=query, planner_goal="search online " + query,
               intent="web_research", capability="internet_research", depends_on=())
    t2 = _make(node, ".rag", objective=retrieval, planner_goal="retrieve evidence from the knowledge base",
               intent="rag_reasoning", capability="rag_reasoning", depends_on=(t1.id,))
    return (t1, t2)


def _is_skill_discovery_followed_by_selection(nodes: list[TaskNode]) -> bool:
    return len(nodes) >= 2 and nodes[-2].intent == "skill_discovery" and nodes[-1].intent == "skill_selection"


def _methods() -> tuple[TaskMethod, ...]:
    return (
        TaskMethod(
            "release_readiness_audit",
            _is_release_readiness,
            _release_readiness,
            "Explicit release/production readiness requests require inspection, repository state, and build/test evidence.",
        ),
        TaskMethod(
            "research_then_ground",
            _is_research_grounding,
            _research_grounding,
            "Explicit online research plus knowledge-base/evidence wording is a two-source workflow, not one search action.",
        ),
    )




def enrich_research_grounding_dataflow(nodes: list[TaskNode]) -> list[TaskNode]:
    """Turn an adjacent research -> evidence request into an ordered evidence flow.

    Natural language often omits ``then`` here ("search ... and retrieve evidence").
    The dependency is nevertheless semantic: the retrieval step should consume a
    knowledge state that the research step may have just created.
    """
    result = list(nodes)
    for i, node in enumerate(result):
        if node.intent != "rag_reasoning" or i == 0:
            continue
        prev = result[i - 1]
        if prev.intent not in {"web_research", "scientific_research", "github_learning", "github_discovery"}:
            continue
        result[i] = replace(node, depends_on=tuple(dict.fromkeys(node.depends_on + (prev.id,))))
    return result


def expand_task_ir(task_ir: TaskIR) -> tuple[list[TaskNode], list[dict[str, Any]]]:
    """Apply conservative high-level methods and return a rewritten task DAG."""
    methods = _methods()
    original_nodes = list(task_ir.nodes)
    expanded: list[TaskNode] = []
    diagnostics: list[dict[str, Any]] = []
    id_map: dict[str, tuple[str, ...]] = {}

    for node in original_nodes:
        application = next((m.apply(node) for m in methods if m.matcher(node)), None)
        if application is None:
            expanded.append(node)
            id_map[node.id] = (node.id,)
            continue
        new_nodes = list(application.nodes)
        # Preserve dependencies entering the expanded method and make the generated
        # chain explicit.  The last generated node is the replacement for the original id.
        incoming = tuple(node.depends_on)
        if incoming:
            new_nodes[0] = replace(new_nodes[0], depends_on=incoming)
        new_nodes[-1] = replace(new_nodes[-1], relation=node.relation)
        expanded.extend(new_nodes)
        id_map[node.id] = tuple(n.id for n in new_nodes)
        diagnostics.append({
            "method": application.name,
            "source_node": node.id,
            "generated_nodes": [n.id for n in new_nodes],
            "reason": application.reason,
        })

    # Rewrite dependencies that pointed at a replaced high-level node to its final step.
    final_for_original = {old: ids[-1] for old, ids in id_map.items()}
    rewritten: list[TaskNode] = []
    for node in expanded:
        deps = tuple(dict.fromkeys(final_for_original.get(dep, dep) for dep in node.depends_on))
        # Generated nodes already have meaningful internal dependencies that must not be
        # rewritten. Only original node ids can be remapped here.
        rewritten.append(replace(node, depends_on=deps))

    # Normalize a common implicit procedure that the language layer often expresses as
    # two clauses: research first, then retrieve the resulting evidence. This is a method
    # application even when the legacy clause parser already separated the text.
    for i, node in enumerate(rewritten):
        if node.intent != "rag_reasoning" or i == 0:
            continue
        prev = rewritten[i - 1]
        if prev.intent not in {"web_research", "scientific_research", "github_learning", "github_discovery"}:
            continue
        rewritten[i] = replace(node, depends_on=tuple(dict.fromkeys(node.depends_on + (prev.id,))))
        diagnostics.append({
            "method": "research_then_ground",
            "source_node": f"{prev.id}+{node.id}",
            "generated_nodes": [prev.id, node.id],
            "reason": "Evidence retrieval depends on the preceding research/indexing state.",
        })

    return rewritten, diagnostics


def enrich_skill_selection_dataflow(nodes: list[TaskNode]) -> list[TaskNode]:
    """Pass the discovery topic into an immediately following skill-selection task."""
    result = list(nodes)
    for i, node in enumerate(result):
        if node.intent != "skill_selection" or i == 0 or result[i - 1].intent != "skill_discovery":
            continue
        prev = result[i - 1]
        args = dict(node.arguments)
        # Prefer the explicit query from the discovery step when the selection request
        # says only "pick the right skill". This is deterministic semantic dataflow.
        if not args.get("skill:query") and not args.get("query"):
            for key in ("skill:query", "research:query", "query"):
                if prev.arguments.get(key):
                    args[key] = prev.arguments[key]
                    break
        result[i] = replace(
            node,
            arguments=args,
            depends_on=tuple(dict.fromkeys(node.depends_on + (prev.id,))),
        )
    return result
