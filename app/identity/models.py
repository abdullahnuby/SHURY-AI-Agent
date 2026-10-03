from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class AgentIdentity:
    name: str
    short_name: str
    role: str
    mission: str
    background: tuple[str, ...]
    principles: tuple[str, ...]
    interaction_style: tuple[str, ...]
    capabilities: tuple[str, ...]
    boundaries: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
