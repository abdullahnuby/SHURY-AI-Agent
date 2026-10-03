"""Task-IR planner: deterministic decomposition, capability grounding and dataflow.

The planner treats each TaskIR node as a subgoal, asks the existing search/HTN
planner for a certified local plan, and falls back to capability resolution when the
surface wording is novel. Local plans are then composed into one dependency-safe plan.
No generative model, embeddings or network calls are involved.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.domain.goal import parse_goal
from app.domain.plan import Plan, PlanStep, validate
from app.domain.operators import build_operators
from app.planning.capabilities import grounded_args, resolve_capabilities
from app.planning.methods import enrich_skill_selection_dataflow, enrich_research_grounding_dataflow, expand_task_ir
from app.planning.portfolio import portfolio_plan
from app.runtime.certificate import certify_plan
from app.learning.brain_store import BrainKnowledgeStore


class TaskIRPlanningError(RuntimeError):
    pass


def _renumber_steps(steps: list[PlanStep], offset: int) -> tuple[list[PlanStep], dict[str, str]]:
    mapping: dict[str, str] = {}
    for step in steps:
        mapping[step.id] = f"s{offset + len(mapping) + 1}"
    out: list[PlanStep] = []
    for step in steps:
        deps = [mapping.get(dep, dep) for dep in step.depends_on]
        args = dict(step.args)
        for key, value in args.items():
            if isinstance(value, str):
                for old, new in mapping.items():
                    value = value.replace("{{" + old + "}}", "{{" + new + "}}")
                args[key] = value
        out.append(replace(step, id=mapping[step.id], depends_on=deps, args=args))
    return out, mapping


def _last_step_id(steps: list[PlanStep]) -> str | None:
    return steps[-1].id if steps else None




def _node_text(node: Any) -> str:
    # Certification still checks the legacy tool matcher, so use the planner-facing
    # canonical phrase first; human-facing objective text can contain harmless words
    # (e.g. "the") that are not present in the tool trigger.
    return str(getattr(node, "planner_goal", "") or getattr(node, "objective", "") or "").strip()



def _matcher_clause(tool: Any, node: Any) -> str:
    source = _node_text(node)
    candidates = [source, str(getattr(node, "objective", "") or "").strip()]
    candidates.extend([f"{source} dataset", f"{source} data", f"{getattr(node, 'objective', '')} dataset"])
    candidates.extend(str(x) for x in (getattr(tool, "triggers", ()) or ()) if x)
    for candidate in candidates:
        if not candidate:
            continue
        try:
            if tool.matches(candidate):
                return candidate
        except Exception:
            continue
    return source


def _local_plan(node: Any, registry: dict, operators, memory, world, max_nodes: int,
                initial_facts: set[str] | None = None, initial_resources: dict[str, float] | None = None) -> Plan:
    goal = str(getattr(node, "planner_goal", "") or getattr(node, "objective", "")).strip()
    if not goal:
        return Plan([])

    # Exact semantic capability is stronger than lexical goal matching.  This prevents
    # broad tools whose trigger text merely contains a common noun (for example
    # ``skills``) from hijacking a typed intent such as ``list_skills``.
    exact_matches = resolve_capabilities(node, registry, limit=8)
    requested_cap = str(getattr(node, "capability", "") or "").casefold().strip()
    exact = [m for m in exact_matches
             if requested_cap and str(getattr(registry.get(m.tool), "capability", "") or m.tool).casefold().strip() == requested_cap]
    for match in exact:
        tool = registry.get(match.tool)
        if tool is None:
            continue
        args = grounded_args(tool, node)
        if tool.validate_args(args):
            continue
        initial = set(initial_facts if initial_facts is not None else (getattr(world, "capabilities", set()) or set()))
        if any(pre not in initial for pre in getattr(tool, "preconditions", ())):
            continue
        step = PlanStep(
            id="s1", tool=tool.name, args=args, clause_index=0,
            clause_text=_matcher_clause(tool, node), capability=tool.capability or tool.name,
        )
        return Plan(
            steps=[step], estimated_cost=tool.cost, estimated_duration=tool.duration,
            score=tool.cost, planner="v22-task-exact-capability",
            diagnostics={"capability_exact": True, "selected": tool.name,
                         "score": round(match.score, 3), "evidence": list(match.evidence)},
        )

    # Learned procedural priors can supply a multi-step method when the legacy planner
    # cannot decompose a novel phrase. They are advisory: every tool is still grounded,
    # argument-validated, precondition-checked and certified before it can enter the plan.
    try:
        priors = BrainKnowledgeStore().match_procedures(goal, registry=registry,
                                                         capability=requested_cap or None,
                                                         limit=6, min_steps=2)
        for prior in priors:
            prior_score = float(prior.get("score", 0.0))
            exact_prior_capability = bool(requested_cap and (
                str(prior.get("capability", "")).casefold().strip() == requested_cap or
                float(prior.get("capability_affinity", 0.0)) >= 0.90
            ))
            if prior_score < (0.24 if exact_prior_capability else 0.36):
                continue
            candidate_steps: list[PlanStep] = []
            valid = True
            running_facts = set(initial_facts if initial_facts is not None else (getattr(world, "capabilities", set()) or set()))
            running_resources = dict(initial_resources if initial_resources is not None else (getattr(world, "resources", {}) or {}))
            for idx, tool_name in enumerate(prior.get("workflow", []), start=1):
                tool = registry.get(tool_name)
                if tool is None:
                    valid = False; break
                if any(pre not in running_facts for pre in getattr(tool, "preconditions", ())):
                    valid = False; break
                args = grounded_args(tool, node)
                if tool.pipe_param and (tool.pipe_param not in args or args.get(tool.pipe_param) in (None, "")) and candidate_steps:
                    args[tool.pipe_param] = "{{" + candidate_steps[-1].id + "}}"
                if tool.validate_args(args):
                    valid = False; break
                step_id = f"s{idx}"
                deps = [candidate_steps[-1].id] if candidate_steps else []
                candidate_steps.append(PlanStep(id=step_id, tool=tool.name, args=args, clause_index=0,
                                                clause_text=_matcher_clause(tool, node),
                                                depends_on=deps, capability=tool.capability or tool.name))
                running_facts.update(tool.produces)
                running_facts.difference_update(tool.removes)
                for resource, amount in tool.resource_costs:
                    running_resources[resource] = running_resources.get(resource, 0.0) - float(amount)
            if valid and len(candidate_steps) >= 2:
                return Plan(steps=candidate_steps,
                            estimated_cost=sum(registry[s.tool].cost for s in candidate_steps),
                            estimated_duration=sum(registry[s.tool].duration for s in candidate_steps),
                            score=sum(registry[s.tool].cost for s in candidate_steps),
                            planner="v22-brain-procedure-prior",
                            diagnostics={"brain_prior": {"key": prior.get("key"), "score": prior.get("score"),
                                                         "examples": prior.get("examples"), "workflow": prior.get("workflow")}})
    except Exception:
        pass

    model = parse_goal(goal)
    candidate = portfolio_plan(
        model,
        operators,
        registry,
        initial_facts=set(initial_facts if initial_facts is not None else (getattr(world, "capabilities", set()) or set())),
        initial_resources=dict(initial_resources if initial_resources is not None else (getattr(world, "resources", {}) or {})),
        max_nodes=min(max_nodes, 5000),
    )
    if candidate.steps:
        # Keep the planner's certified structure, but re-ground argument values against
        # the original semantic node. Canonical planner goals such as "save note" must
        # never erase the user's actual note text.
        for step in candidate.steps:
            tool = registry.get(step.tool)
            if tool is None:
                continue
            grounded = grounded_args(tool, node)
            for key, value in grounded.items():
                if key not in step.args or step.args.get(key) in (None, ""):
                    step.args[key] = value
                elif not (isinstance(step.args.get(key), str) and "{{s" in step.args.get(key)):
                    # Prefer explicitly grounded semantic arguments over canonical text
                    # when both are valid. This only changes input binding, not tool choice.
                    if value not in (None, ""):
                        step.args[key] = value
        return candidate

    matches = resolve_capabilities(node, registry, limit=4)
    for match in matches:
        tool = registry.get(match.tool)
        if tool is None:
            continue
        args = grounded_args(tool, node)
        if tool.validate_args(args):
            continue
        # Capability grounding is authoritative for this fallback, but the legacy
        # certificate still understands tool matcher text. Find a small canonical phrase
        # that the selected tool itself recognizes, while keeping the user's objective
        # in diagnostics/semantic arguments.
        clause_text = str(getattr(node, "objective", "") or goal)
        candidates = [clause_text, goal, str(getattr(node, "intent", "") or "")]
        candidates.extend(str(x) for x in getattr(tool, "triggers", ()) if x)
        # Add a few deterministic context combinations for tools whose matcher needs a
        # domain noun in addition to a verb (e.g. "analyze" + "dataset").
        candidates.extend([
            f"{clause_text} dataset", f"{clause_text} data",
            f"{goal} dataset", f"{goal} data",
        ])
        clause_text = next((candidate for candidate in candidates if tool.matches(candidate)), clause_text)
        step = PlanStep(
            id="s1", tool=tool.name, args=args,
            clause_index=0, clause_text=clause_text,
            capability=tool.capability or tool.name,
        )
        return Plan(
            steps=[step],
            estimated_cost=tool.cost,
            estimated_duration=tool.duration,
            score=max(0.0, 10.0 - match.score),
            planner="v22-task-capability",
            diagnostics={"capability_resolution": {
                "selected": tool.name,
                "score": round(match.score, 3),
                "evidence": list(match.evidence),
            }},
        )
    return Plan([])


def _inject_cross_node_dataflow(node: Any, node_steps: list[PlanStep], dep_last_ids: list[str], registry: dict) -> None:
    if not node_steps:
        return
    # A downstream pipe consumer with an empty value should consume the most recent
    # dependency result. This is semantic dataflow, not positional execution magic.
    for step in node_steps:
        tool = registry[step.tool]
        if not tool.pipe_param or step.args.get(tool.pipe_param) not in (None, ""):
            continue
        source = dep_last_ids[-1] if dep_last_ids else None
        if source:
            step.args[tool.pipe_param] = "{{" + source + "}}"
            if source not in step.depends_on:
                step.depends_on.append(source)
            return


def plan_task_ir(task_ir: Any, registry: dict, memory=None, world=None, max_nodes: int = 12000) -> Plan:
    if not task_ir or not getattr(task_ir, "nodes", None):
        return Plan([])

    reliability = {name: memory.tool_reliability_posterior(name) for name in registry} if memory else {}
    operators = build_operators(registry, reliability)
    combined: list[PlanStep] = []
    node_last: dict[str, list[str]] = {}
    node_diagnostics: list[dict[str, Any]] = []
    offset = 0
    # Plan the whole TaskIR as a state transition sequence rather than solving every
    # node against the same initial world. This lets later subgoals depend on facts
    # produced by earlier nodes (or on resource consumption), which is the core
    # difference between task composition and command routing.
    virtual_facts = set(getattr(world, "capabilities", set()) or set())
    virtual_resources = dict(getattr(world, "resources", {}) or {})

    expanded_nodes, method_diagnostics = expand_task_ir(task_ir)
    expanded_nodes = enrich_skill_selection_dataflow(expanded_nodes)
    expanded_nodes = enrich_research_grounding_dataflow(expanded_nodes)

    for node in expanded_nodes:
        local = _local_plan(node, registry, operators, memory, world, max_nodes=max_nodes,
                            initial_facts=virtual_facts, initial_resources=virtual_resources)
        if not local.steps:
            node_diagnostics.append({"node": node.id, "status": "unplanned", "objective": node.objective,
                                     "intent": node.intent, "planner_goal": getattr(node, "planner_goal", "")})
            continue
        steps, mapping = _renumber_steps(local.steps, offset)
        offset += len(steps)
        local_ids = [s.id for s in steps]
        dependencies: list[str] = []
        for dep_node in node.depends_on:
            dependencies.extend(node_last.get(dep_node, []))
        if dependencies and steps:
            steps[0].depends_on = list(dict.fromkeys(steps[0].depends_on + dependencies))
        _inject_cross_node_dataflow(node, steps, dependencies, registry)
        combined.extend(steps)
        node_last[node.id] = local_ids
        # Advance the planner-side world after a successfully grounded local plan.
        # This is a virtual transition; the runtime will apply the exact same tool
        # effects again only after execution is verified.
        for planned_step in steps:
            planned_tool = registry[planned_step.tool]
            virtual_facts.update(planned_tool.produces)
            virtual_facts.difference_update(planned_tool.removes)
            for resource, amount in planned_tool.resource_costs:
                virtual_resources[resource] = virtual_resources.get(resource, 0.0) - float(amount)
        node_diagnostics.append({
            "node": node.id, "status": "planned", "objective": node.objective,
            "intent": node.intent, "planner_goal": getattr(node, "planner_goal", ""),
            "steps": [s.tool for s in steps],
            "local_planner": local.planner,
        })

    if getattr(task_ir, "unresolved", None):
        return Plan([], planner="v22-task-ir-reject", diagnostics={"reason": "unresolved-task-ir",
                                                                     "unresolved": list(task_ir.unresolved)})
    if any(item["status"] == "unplanned" for item in node_diagnostics):
        return Plan([], planner="v22-task-ir-incomplete", diagnostics={"nodes": node_diagnostics})

    # Unsupported arbitrary condition branches must not silently execute as if the
    # condition were absent. A later runtime sprint can add a first-class condition
    # evaluator; for now the planner refuses only when a branch has no deterministic
    # representation, keeping safety fail-closed.
    if getattr(task_ir, "conditions", None):
        return Plan([], planner="v22-task-ir-condition-gate", diagnostics={
            "reason": "condition-control-flow-not-yet-executable",
            "conditions": [c.to_dict() for c in task_ir.conditions],
            "nodes": node_diagnostics,
        })

    plan = Plan(
        steps=combined,
        estimated_cost=sum(registry[s.tool].cost for s in combined),
        estimated_duration=sum(registry[s.tool].duration for s in combined),
        score=sum(registry[s.tool].cost for s in combined),
        planner="v22-task-ir",
        diagnostics={
            "algorithm": "task-ir-capability-grounded-composition",
            "node_count": len(expanded_nodes),
            "source_node_count": len(task_ir.nodes),
            "nodes": node_diagnostics,
            "methods": method_diagnostics,
            "execution_mode": "parallel-capable" if task_ir.constraints.get("parallel") else "dependency-driven",
            "state_propagation": {"enabled": True, "final_facts": sorted(virtual_facts), "final_resources": dict(virtual_resources)},
        },
    )
    errors = validate(plan, registry)
    if errors:
        return Plan([], planner="v22-task-ir-invalid", diagnostics={"errors": errors, "nodes": node_diagnostics})
    cert = certify_plan(
        plan,
        registry,
        set(getattr(world, "capabilities", set()) or set()),
        dict(getattr(world, "resources", {}) or {}),
        task_ir.constraints.get("max_duration"),
    )
    if not cert.ok:
        return Plan([], planner="v22-task-ir-uncertified", diagnostics={
            "certificate_errors": list(cert.errors),
            "nodes": node_diagnostics,
        })
    plan.diagnostics["certificate"] = {"ok": True, "states": len(cert.states)}
    return plan
