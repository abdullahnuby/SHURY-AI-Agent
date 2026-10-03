"""V9 deterministic hierarchical AND/OR planner.

The planner treats a goal as an AND tree of clauses. Each clause is an OR node
whose alternatives are registered operators. Every operator's preconditions are
an AND set of facts, and each missing fact is another OR search over producer
operators. The search therefore finds complete operator chains instead of
binding one tool to one phrase.

No generative model, embeddings, network calls, or hidden planner state are required.
"""
from dataclasses import dataclass
from typing import Iterable

from app.domain.goal import GoalModel
from app.domain.operators import Operator, OperatorRegistry
from app.domain.plan import Plan, PlanStep
from app.runtime.registry import Tool
from app.planning.scheduler import critical_path
from app.planning.algorithms import goal_heuristic, expected_plan_failure, pareto_dominates


@dataclass(frozen=True)
class _Branch:
    facts: frozenset[str]
    resources: tuple[tuple[str, float], ...]
    selected: tuple[tuple[str, int, tuple[str, ...]], ...]
    used_nonidempotent: frozenset[str]
    actual_cost: float
    search_cost: float
    failure_probability: float = 0.0

    def resources_dict(self) -> dict[str, float]:
        return dict(self.resources)


@dataclass(frozen=True)
class PlanCandidate:
    plan: Plan
    actual_cost: float
    search_cost: float
    makespan: float
    failure_probability: float = 0.0


def _apply(op: Operator, facts: Iterable[str], resources: dict[str, float]):
    next_facts = set(facts)
    next_facts.update(op.produces)
    next_facts.difference_update(op.removes)
    next_resources = dict(resources)
    for key, amount in op.resource_costs:
        next_resources[key] = next_resources.get(key, 0.0) - float(amount)
    return next_facts, next_resources


def _groups(goal: GoalModel) -> list[list[int]]:
    """Split clauses on explicit `then`; clauses joined by `and` form an AND set."""
    result: list[list[int]] = []
    current: list[int] = []
    for idx, clause in enumerate(goal.clauses):
        if idx > 0 and clause.relation == "then" and current:
            result.append(current)
            current = []
        current.append(idx)
    if current:
        result.append(current)
    return result


def _matching(opreg: OperatorRegistry, text: str) -> list[Operator]:
    return sorted(
        (op for op in opreg.items if op.matches(text)),
        key=lambda op: (-op.intent_priority, op.search_cost(), op.duration_cost(), op.risk_penalty, op.name),
    )


def _producer_candidates(opreg: OperatorRegistry, fact: str) -> list[Operator]:
    return opreg.producers(fact)


def _serialize(selected, goal: GoalModel, registry: dict[str, Tool], diagnostics: dict) -> Plan:
    steps: list[PlanStep] = []
    position_to_id: dict[int, str] = {}
    clause_last: dict[int, list[str]] = {}

    for pos, (tool_name, clause_idx, dep_positions) in enumerate(selected):
        tool = registry[tool_name]
        clause = goal.clauses[clause_idx] if clause_idx >= 0 else None
        args = tool.args_for(clause.text if clause else "")
        deps = [position_to_id[int(p)] for p in dep_positions if int(p) in position_to_id]
        steps.append(
            PlanStep(
                id=f"s{pos + 1}", tool=tool_name, args=args,
                clause_index=clause_idx,
                clause_text=clause.text if clause else "",
                capability=tool.capability or tool.name,
                depends_on=list(dict.fromkeys(deps)),
            )
        )
        position_to_id[pos] = f"s{pos + 1}"
        if clause_idx >= 0:
            clause_last.setdefault(clause_idx, []).append(f"s{pos + 1}")

    groups = _groups(goal)
    for group_idx in range(1, len(groups)):
        prior_ids = [sid for clause_idx in groups[group_idx - 1] for sid in clause_last.get(clause_idx, [])]
        for step in steps:
            if step.clause_index in groups[group_idx]:
                step.depends_on = list(dict.fromkeys(step.depends_on + prior_ids))

    # Preserve the intuitive pipeline behavior for explicit result/numeric references.
    previous_pipe_id: str | None = None
    previous_pipe_clause: int | None = None
    for step in steps:
        tool = registry[step.tool]
        clause_text = goal.clauses[step.clause_index].text if step.clause_index >= 0 else ""
        if tool.pipe_param and previous_pipe_id:
            raw_arg = str(step.args.get(tool.pipe_param, ""))
            explicit_ref = any(token in clause_text.casefold() for token in ("النتيجة", "النتيجه", "الناتج", "اللي فات", "المحسوبة", "result", "output", "previous"))
            # A downstream tool with a pipe parameter and no concrete user value may consume
            # the previous step output. This makes the dataflow semantic, not merely positional.
            empty_arg = (not raw_arg.strip()) or (step.clause_index >= 0 and raw_arg.strip() == goal.clauses[step.clause_index].text.strip())
            if "{{s" not in raw_arg and (explicit_ref or empty_arg):
                source_tool = registry[position_tool_name(steps, previous_pipe_id)]
                label = ""
                if source_tool.pipe_label and previous_pipe_clause is not None:
                    source_args = source_tool.args_for(goal.clauses[previous_pipe_clause].text)
                    label = source_tool.pipe_label(source_args)
                step.args[tool.pipe_param] = f"{label}{{{{{previous_pipe_id}}}}}"
                if previous_pipe_id not in step.depends_on:
                    step.depends_on.append(previous_pipe_id)
        if tool.pipe_source:
            previous_pipe_id = step.id
            previous_pipe_clause = step.clause_index

    return Plan(
        steps=steps,
        estimated_cost=sum(registry[s.tool].cost for s in steps),
        estimated_duration=critical_path(Plan(steps), registry),
        score=0.0,
        planner="v9-hierarchical",
        diagnostics=dict(diagnostics),
    )


def position_tool_name(steps: list[PlanStep], step_id: str) -> str:
    for step in steps:
        if step.id == step_id:
            return step.tool
    raise KeyError(step_id)


def _candidate_key(candidate: PlanCandidate):
    expected_loss = candidate.actual_cost + candidate.failure_probability * 8.0
    return (expected_loss, candidate.makespan, len(candidate.plan.steps), candidate.search_cost)


def hierarchical_plan(
    goal: GoalModel,
    operators: OperatorRegistry,
    registry: dict,
    initial_facts: set[str] | None = None,
    initial_resources: dict[str, float] | None = None,
    max_nodes: int = 20000,
) -> Plan:
    groups = _groups(goal)
    diagnostics = {
        "algorithm": "hierarchical-and-or-v9",
        "groups": len(groups),
        "expanded_nodes": 0,
        "candidate_branches": 0,
        "alternative_operator_count": 0,
        "unsatisfied_facts": [],
        "search_complete": False,
        "pruned_by_cost": 0,
        "pruned_by_steps": 0,
        "pruned_by_duration": 0,
        "pruned_by_dominance": 0,
        "heuristic_calls": 0,
        "landmark_estimates": 0,
    }
    if not groups:
        return Plan([], 0.0, 0.0, 0.0, "v9-hierarchical", diagnostics)

    best: PlanCandidate | None = None
    frontier: list[PlanCandidate] = []
    seen_plan_signatures: set[tuple] = set()
    initial = _Branch(
        frozenset(initial_facts or set()),
        tuple(sorted((initial_resources or {}).items())),
        tuple(), frozenset(), 0.0, 0.0,
    )
    node_counter = [0]
    active_fact_stack: list[str] = []
    dominance: dict[tuple, list[tuple[float, float, int, float]]] = {}

    def violates_limits(branch: _Branch, plan_steps: int) -> bool:
        constraints = goal.constraints
        if constraints.get("max_cost") is not None and branch.actual_cost > float(constraints["max_cost"]):
            diagnostics["pruned_by_cost"] += 1
            return True
        if constraints.get("max_steps") is not None and plan_steps > int(constraints["max_steps"]):
            diagnostics["pruned_by_steps"] += 1
            return True
        return False

    def ensure_operator(op: Operator, clause_idx: int, branch: _Branch) -> list[tuple[_Branch, str]]:
        """Return all bounded variants that make op executable; result includes op position."""
        node_counter[0] += 1
        diagnostics["expanded_nodes"] = node_counter[0]
        if node_counter[0] > max_nodes:
            return []
        if (not op.idempotent) and op.tool in branch.used_nonidempotent:
            return []

        base_resources = branch.resources_dict()
        if any(pre in active_fact_stack for pre in op.preconditions):
            return []

        variants: list[tuple[_Branch, list[str]]] = [(branch, [])]
        for fact in op.preconditions:
            next_variants: list[tuple[_Branch, list[str]]] = []
            for current, dep_positions in variants:
                if fact in current.facts:
                    next_variants.append((current, dep_positions))
                    continue
                if fact in active_fact_stack:
                    continue
                active_fact_stack.append(fact)
                producers = _producer_candidates(operators, fact)
                if not producers:
                    diagnostics["unsatisfied_facts"].append(fact)
                for producer in producers[:4]:
                    for produced_branch, produced_last in ensure_operator(producer, -1, current):
                        next_variants.append((produced_branch, dep_positions + [produced_last]))
                        diagnostics["candidate_branches"] += 1
                active_fact_stack.pop()
            variants = next_variants[:8]
            if not variants:
                return []

        out: list[tuple[_Branch, str]] = []
        for current, dep_positions in variants:
            current_resources = current.resources_dict()
            if not op.applicable(set(current.facts), current_resources):
                continue
            facts, resources = _apply(op, current.facts, current_resources)
            selected = list(current.selected)
            position = len(selected)
            selected.append((op.tool, clause_idx, tuple(dep_positions)))
            actual_cost = current.actual_cost + registry[op.tool].cost
            search_cost = current.search_cost + op.search_cost()
            used = set(current.used_nonidempotent)
            if not op.idempotent:
                used.add(op.tool)
            next_branch = _Branch(
                frozenset(facts), tuple(sorted(resources.items())), tuple(selected),
                frozenset(used), actual_cost, search_cost,
                1.0 - (1.0 - current.failure_probability) * max(0.0, min(1.0, op.reliability)),
            )
            if violates_limits(next_branch, len(selected)):
                continue
            out.append((next_branch, str(position)))
        return out[:8]

    def solve_clause(idx: int, branch: _Branch) -> list[_Branch]:
        text = goal.clauses[idx].text
        candidates = _matching(operators, text)
        diagnostics["alternative_operator_count"] += max(0, len(candidates) - 1)
        branches: list[_Branch] = []
        for op in candidates[:6]:
            # If a branch already has a cheaper complete competitor, use it as a bound.
            min_possible = branch.actual_cost + op.search_cost()
            if best is not None and min_possible > _candidate_key(best)[0] + 1e-9:
                continue
            variants = ensure_operator(op, idx, branch)
            for next_branch, _last in variants:
                branches.append(next_branch)
                diagnostics["candidate_branches"] += 1
        return branches[:12]

    def solve_group(group: list[int], remaining: frozenset[int], branch: _Branch, group_idx: int):
        nonlocal best
        if node_counter[0] > max_nodes:
            return
        dom_key = (group_idx, tuple(sorted(remaining)), tuple(sorted(branch.facts)), tuple(sorted(branch.resources)), tuple(sorted(branch.used_nonidempotent)))
        metrics = (branch.actual_cost, branch.search_cost, len(branch.selected), branch.failure_probability)
        bucket = dominance.setdefault(dom_key, [])
        if any(a <= metrics[0] + 1e-9 and b <= metrics[1] + 1e-9 and c <= metrics[2] and d <= metrics[3] + 1e-9
               for a, b, c, d in bucket):
            diagnostics["pruned_by_dominance"] += 1
            return
        bucket[:] = [x for x in bucket if not (metrics[0] <= x[0] + 1e-9 and metrics[1] <= x[1] + 1e-9 and metrics[2] <= x[2] and metrics[3] <= x[3] + 1e-9)]
        bucket.append(metrics)
        if not remaining:
            if group_idx == len(groups) - 1:
                plan = _serialize(list(branch.selected), goal, registry, diagnostics)
                constraints = goal.constraints
                if constraints.get("max_duration") is not None and plan.estimated_duration > float(constraints["max_duration"]):
                    diagnostics["pruned_by_duration"] += 1
                    return
                candidate = PlanCandidate(plan, branch.actual_cost, branch.search_cost, plan.estimated_duration, branch.failure_probability)
                signature = tuple((s.tool, tuple(sorted(s.depends_on))) for s in plan.steps)
                if signature not in seen_plan_signatures:
                    seen_plan_signatures.add(signature)
                    frontier.append(candidate)
                    frontier.sort(key=_candidate_key)
                    del frontier[8:]
                if best is None or _candidate_key(candidate) < _candidate_key(best):
                    best = candidate
                diagnostics["search_complete"] = True
                return
            next_idx = group_idx + 1
            solve_group(groups[next_idx], frozenset(groups[next_idx]), branch, next_idx)
            return

        # AND node: branch on which remaining clause to solve first.
        pending_all = set(remaining)
        for future in groups[group_idx + 1:]:
            pending_all.update(future)
        completed_for_heuristic = set(range(len(goal.clauses))) - pending_all
        relaxed_h, missing_landmarks, _ = goal_heuristic(
            goal.clauses, completed_for_heuristic, operators, set(branch.facts)
        )
        diagnostics["heuristic_calls"] += 1
        diagnostics["landmark_estimates"] += missing_landmarks

        def clause_order(i):
            candidates = _matching(operators, goal.clauses[i].text)
            if not candidates:
                return (float("inf"), i)
            pre_missing = min(len([p for p in op.preconditions if p not in branch.facts]) for op in candidates)
            best_cost = min(op.search_cost() for op in candidates)
            # The relaxed global estimate is a tie-breaker; it is deliberately
            # not treated as an admissible bound because h_add can double-count.
            h_tiebreak = 0.0 if relaxed_h == float("inf") else min(relaxed_h, 1000.0) * 0.001
            return (pre_missing * 10.0 + best_cost + h_tiebreak, i)
        ordered = sorted(remaining, key=clause_order)
        for idx in ordered:
            for next_branch in solve_clause(idx, branch):
                solve_group(group, remaining - {idx}, next_branch, group_idx)

    solve_group(groups[0], frozenset(groups[0]), initial, 0)

    if best is None:
        diagnostics["search_complete"] = True
        return Plan([], 0.0, 0.0, float("inf"), "v9-hierarchical", diagnostics)

    best.plan.score = best.search_cost + best.makespan * 0.02
    diagnostics["frontier_size"] = len(frontier)
    diagnostics["alternatives"] = [
        {
            "tools": [s.tool for s in c.plan.steps],
            "cost": c.actual_cost,
            "makespan": c.makespan,
            "steps": len(c.plan.steps),
            "failure_probability": c.failure_probability,
            "expected_loss": c.actual_cost + c.failure_probability * 8.0,
        }
        for c in frontier if c is not best
    ][:5]
    best.plan.diagnostics.update({
        "selected_cost": best.actual_cost,
        "selected_search_cost": best.search_cost,
        "selected_makespan": best.makespan,
        "selected_steps": len(best.plan.steps),
        "selected_failure_probability": best.failure_probability,
        "selected_expected_loss": best.actual_cost + best.failure_probability * 8.0,
        "pruned_by_dominance": diagnostics["pruned_by_dominance"],
    })
    return best.plan
