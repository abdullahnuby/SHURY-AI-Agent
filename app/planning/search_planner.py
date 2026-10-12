"""V8 bounded state-space planner.

The planner is deterministic and model-free. It searches over explicit capability
operators, can insert missing precondition-producers, supports partial-order
execution for independent `and` clauses, and scores plans using cost, duration,
risk and empirical reliability.
"""
from dataclasses import dataclass, field
import heapq
import math
from app.domain.goal import GoalModel, GoalClause
from app.domain.operators import Operator, OperatorRegistry
from app.domain.plan import Plan, PlanStep
from app.intelligence.keywords import PIPE_KW, has


@dataclass(order=True)
class _Node:
    score: float
    serial: int
    completed: frozenset[int] = field(compare=False)
    state: tuple[str, ...] = field(compare=False, default=())
    resources: tuple[tuple[str, float], ...] = field(compare=False, default=())
    elapsed: float = field(compare=False, default=0.0)
    path_cost: float = field(compare=False, default=0.0)
    selected: tuple[tuple[int, str, bool], ...] = field(compare=False, default=())


def _resources_dict(node: _Node) -> dict[str, float]:
    return {k: v for k, v in node.resources}


def _apply(op: Operator, state: set[str], resources: dict[str, float]) -> tuple[set[str], dict[str, float]]:
    new_state = set(state)
    new_state.update(op.produces)
    new_state.difference_update(op.removes)
    new_resources = dict(resources)
    for key, cost in op.resource_costs:
        new_resources[key] = new_resources.get(key, 0.0) - cost
    return new_state, new_resources


def _relation_ready(idx: int, goal: GoalModel, completed: frozenset[int]) -> bool:
    clause = goal.clauses[idx]
    if clause.relation == "then" and idx > 0:
        return (idx - 1) in completed
    return True


def _remaining_clause_count(goal: GoalModel, completed: frozenset[int]) -> int:
    return len(goal.clauses) - len(completed)


def _heuristic(goal: GoalModel, completed: frozenset[int], missing_preconditions: int = 0) -> float:
    # Admissibility is intentionally not claimed because risk/reliability are soft penalties.
    return float(_remaining_clause_count(goal, completed)) + missing_preconditions * 0.25


def _candidate_with_support(clause: GoalClause, opreg: OperatorRegistry, state: set[str], resources: dict[str, float]):
    direct = opreg.candidates(clause.text, state, resources)
    if direct:
        return [(o, False) for o in direct]
    missing = set()
    for op in opreg.items:
        if op.matches(clause.text):
            missing.update(set(op.preconditions) - state)
    supporters = []
    for fact in sorted(missing):
        supporters.extend((o, True) for o in opreg.producers(fact) if o.applicable(state, resources))
    # Supporters are intentionally capped to prevent combinatorial explosion.
    return supporters[:4]


def _make_steps(selected: tuple[tuple[int, str, bool], ...], goal: GoalModel, registry: dict, operators: OperatorRegistry) -> list[PlanStep]:
    steps: list[PlanStep] = []
    clause_last: dict[int, str] = {}
    support_last: dict[int, str] = {}
    prior_pipe_source: str | None = None
    prior_pipe_tool = None
    for idx, tool_name, is_support in selected:
        clause = goal.clauses[idx] if idx >= 0 else GoalClause("", "root", -1)
        tool = registry[tool_name]
        args = tool.args_for(clause.text)
        depends: list[str] = []
        # Sequential relation: explicit `then` depends on previous clause's final step.
        if idx in support_last and not is_support:
            depends.append(support_last[idx])
        if idx > 0 and clause.relation == "then" and (idx - 1) in clause_last:
            depends.append(clause_last[idx - 1])
        # Pipe references are stronger than textual ordering.
        if tool.pipe_param and prior_pipe_source and (has(clause.text, PIPE_KW) or not args.get(tool.pipe_param)):
            source_tool = registry[prior_pipe_tool]
            source_args = source_tool.args_for(goal.clauses[max(0, idx - 1)].text) if idx >= 0 else {}
            label = source_tool.pipe_label(source_args) if source_tool.pipe_label else ""
            args[tool.pipe_param] = f"{label}{{{{{prior_pipe_source}}}}}"
            if prior_pipe_source not in depends:
                depends.append(prior_pipe_source)
        step_id = f"s{len(steps) + 1}"
        step = PlanStep(
            id=step_id, tool=tool_name, args=args,
            clause_index=idx, clause_text=clause.text, capability=tool.capability or tool.name,
            depends_on=list(dict.fromkeys(depends)),
        )
        if is_support:
            step.clause_text = ""
            support_last[idx] = step_id
        else:
            clause_last[idx] = step_id
        steps.append(step)
        if tool.pipe_source:
            prior_pipe_source, prior_pipe_tool = step_id, tool_name
    return steps


def best_first_plan(goal: GoalModel, operators: OperatorRegistry, registry: dict,
                    reliability: dict[str, float] | None = None, max_candidates: int = 5,
                    initial_state: set[str] | None = None, initial_resources: dict[str, float] | None = None,
                    max_search_nodes: int = 5000) -> Plan:
    if not goal.clauses:
        return Plan([])
    initial_state = set(initial_state or set())
    initial_resources = dict(initial_resources or {})
    frontier: list[_Node] = []
    serial = 0
    start = _Node(0.0, serial, frozenset(), tuple(sorted(initial_state)), tuple(sorted(initial_resources.items())), 0.0, 0.0, tuple())
    heapq.heappush(frontier, start)
    best_seen: dict[tuple[frozenset[int], tuple[str, ...], tuple[tuple[str, float], ...], int], float] = {
        (frozenset(), tuple(sorted(initial_state)), tuple(sorted(initial_resources.items())), 0): 0.0
    }
    expanded = 0

    while frontier and expanded < max_search_nodes:
        node = heapq.heappop(frontier)
        expanded += 1
        if len(node.completed) == len(goal.clauses):
            steps = _make_steps(node.selected, goal, registry, operators)
            # Estimates account for dependency structure: critical-path duration rather than sum.
            duration_by_step = {s.id: registry[s.tool].duration for s in steps}
            finish = {}
            for s in steps:
                finish[s.id] = duration_by_step[s.id] + max((finish.get(d, 0.0) for d in s.depends_on), default=0.0)
            est_duration = max(finish.values(), default=0.0)
            est_cost = node.path_cost
            return Plan(steps, est_cost, est_duration, node.score, "v8-search")

        state = set(node.state)
        resources = _resources_dict(node)
        # Prefer ready clauses with fewer candidates first; this reduces branching.
        ready = [i for i in range(len(goal.clauses)) if i not in node.completed and _relation_ready(i, goal, node.completed)]
        if not ready:
            continue
        ready.sort(key=lambda i: (len(_candidate_with_support(goal.clauses[i], operators, state, resources)), i))
        idx = ready[0]
        clause = goal.clauses[idx]
        options = _candidate_with_support(clause, operators, state, resources)[:max_candidates]
        if not options:
            continue
        for op, is_support in options:
            if op.tool in [tool for _, tool, _ in node.selected] and not op.idempotent and not is_support:
                continue
            if op.tool in [tool for _, tool, _ in node.selected] and is_support:
                continue
            next_state, next_resources = _apply(op, state, resources)
            next_elapsed = node.elapsed + op.duration
            c = goal.constraints
            if c.get("max_duration") is not None and next_elapsed > float(c["max_duration"]):
                continue
            path_cost = node.path_cost + op.search_cost()
            if c.get("max_cost") is not None and path_cost > float(c["max_cost"]):
                continue
            completed = node.completed if is_support else frozenset(set(node.completed) | {idx})
            selected = node.selected + ((idx, op.tool, is_support),)
            heuristic_missing = len(set(op.preconditions) - state)
            # Penalize support insertions, but still permit them to satisfy real prerequisites.
            support_penalty = 0.75 if is_support else 0.0
            score = path_cost + support_penalty + op.duration * 0.02 + _heuristic(goal, completed, heuristic_missing)
            serial += 1
            key = (completed, tuple(sorted(next_state)), tuple(sorted(next_resources.items())), len(selected))
            if score + 1e-9 >= best_seen.get(key, math.inf):
                continue
            best_seen[key] = score
            heapq.heappush(frontier, _Node(score, serial, completed, tuple(sorted(next_state)),
                                            tuple(sorted(next_resources.items())), next_elapsed, path_cost, selected))
    return Plan([])
