"""Simple Temporal Network utilities.

Nodes are event times. Constraints are difference bounds of the form
x_j - x_i <= c.  Floyd-Warshall gives deterministic consistency checking and
all-pairs shortest bounds; no external solver is required.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class TemporalConstraint:
    before: str
    after: str
    minimum: float = 0.0
    maximum: float | None = None


class SimpleTemporalNetwork:
    def __init__(self, nodes: list[str]):
        self.nodes = list(dict.fromkeys(["ZERO", *nodes]))
        self.index = {n: i for i, n in enumerate(self.nodes)}
        n = len(self.nodes)
        self.dist = [[float("inf")] * n for _ in range(n)]
        for i in range(n):
            self.dist[i][i] = 0.0

    def add_constraint(self, before: str, after: str, minimum: float = 0.0, maximum: float | None = None) -> None:
        if before not in self.index or after not in self.index:
            raise KeyError("unknown temporal node")
        i, j = self.index[before], self.index[after]
        # after - before >= minimum  => before - after <= -minimum
        self.dist[j][i] = min(self.dist[j][i], -float(minimum))
        if maximum is not None:
            # after - before <= maximum
            self.dist[i][j] = min(self.dist[i][j], float(maximum))

    def close(self) -> bool:
        n = len(self.nodes)
        d = [row[:] for row in self.dist]
        for k in range(n):
            dk = d[k]
            for i in range(n):
                dik = d[i][k]
                if dik == float("inf"):
                    continue
                di = d[i]
                for j in range(n):
                    alt = dik + dk[j]
                    if alt < di[j]:
                        di[j] = alt
        self.dist = d
        return all(self.dist[i][i] >= -1e-9 for i in range(n))

    def upper_bound(self, before: str, after: str) -> float:
        return self.dist[self.index[before]][self.index[after]]

    def lower_bound(self, before: str, after: str) -> float:
        ub = self.upper_bound(after, before)
        return -ub if ub != float("inf") else float("-inf")


def build_plan_stn(plan, registry, max_duration: float | None = None):
    nodes = [s.id for s in plan.steps]
    stn = SimpleTemporalNetwork(nodes)
    for step in plan.steps:
        tool = registry[step.tool]
        stn.add_constraint("ZERO", step.id, minimum=0.0)
        stn.add_constraint(step.id, step.id, minimum=0.0, maximum=max(0.0, float(tool.duration)))
        # Explicit finish event is represented by the difference from ZERO below.
        for dep in step.depends_on:
            stn.add_constraint(dep, step.id, minimum=registry[dep].duration if dep in registry else 0.0)
    if max_duration is not None and nodes:
        # Every step must start early enough that its duration fits the horizon.
        for step in plan.steps:
            stn.add_constraint("ZERO", step.id, maximum=max_duration)
    consistent = stn.close()
    return stn, consistent


def validate_plan_temporal(plan, registry, max_duration: float | None = None) -> tuple[bool, str]:
    if not plan.steps:
        return True, "empty plan"
    stn = SimpleTemporalNetwork([s.id for s in plan.steps])
    for step in plan.steps:
        stn.add_constraint("ZERO", step.id, minimum=0.0)
        for dep in step.depends_on:
            dep_tool = registry.get(next((x.tool for x in plan.steps if x.id == dep), ""))
            stn.add_constraint(dep, step.id, minimum=float(dep_tool.duration) if dep_tool else 0.0)
        if max_duration is not None:
            stn.add_constraint("ZERO", step.id, maximum=float(max_duration) - float(registry[step.tool].duration))
    if not stn.close():
        return False, "temporal network inconsistent"
    # Earliest feasible completion = max earliest start + duration.
    earliest = 0.0
    for step in plan.steps:
        lb = stn.lower_bound("ZERO", step.id)
        if lb == float("-inf"):
            lb = 0.0
        earliest = max(earliest, lb + float(registry[step.tool].duration))
    if max_duration is not None and earliest > float(max_duration) + 1e-9:
        return False, f"estimated completion {earliest:.3f} exceeds horizon {max_duration}"
    return True, "ok"
