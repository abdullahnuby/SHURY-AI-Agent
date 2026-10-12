"""Explicit task DAG used for deterministic planning and replanning."""
from dataclasses import dataclass, field


@dataclass
class TaskNode:
    id: str
    tool: str
    args: dict
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"
    attempts: int = 0
    output: object = None
    error: str | None = None


@dataclass
class TaskGraph:
    nodes: list[TaskNode] = field(default_factory=list)

    def ready(self) -> list[TaskNode]:
        done = {n.id for n in self.nodes if n.status == "done"}
        return [n for n in self.nodes if n.status == "pending" and all(d in done for d in n.depends_on)]

    def validate(self) -> list[str]:
        ids = set()
        errors: list[str] = []

        for n in self.nodes:
            if n.id in ids:
                errors.append(f"duplicate:{n.id}")
            ids.add(n.id)

        node_map = {n.id: n for n in self.nodes}

        for n in self.nodes:
            for d in n.depends_on:
                if d == n.id:
                    errors.append(f"self_dependency:{n.id}")
                elif d not in node_map:
                    errors.append(f"missing_dependency:{n.id}->{d}")

        visiting: set[str] = set()
        visited: set[str] = set()

        def dfs(node_id: str) -> None:
            if node_id in visiting:
                errors.append(f"cycle:{node_id}")
                return
            if node_id in visited or node_id not in node_map:
                return
            visiting.add(node_id)
            for dependency in node_map[node_id].depends_on:
                if dependency not in node_map:
                    continue
                dfs(dependency)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in node_map:
            dfs(node_id)

        return errors

    def to_dict(self):
        return {"nodes": [n.__dict__.copy() for n in self.nodes]}
