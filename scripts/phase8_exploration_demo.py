"""Reproducible Phase-8 exploration demonstration using only local synthetic tools.

The environment here is intentionally tiny and deterministic.  It demonstrates that the
actual ExplorationPolicy prefers an unseen safe information source when the current model
is uncertain, then reduces its novelty after evidence accumulates and can select the other
source.  It does not write synthetic transitions into the production runtime.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.learning.manager import SelfImprovementManager
from app.learning.store import LearningStore
from app.runtime.registry import Tool
from app.domain.world import WorldState


def safe_tool(name: str, prior: float) -> Tool:
    return Tool(
        name=name,
        description=f"safe information probe: {name}",
        params={"query": "str"},
        fn=lambda query: {"evidence": [{"title": name, "snippet": query}]},
        capability=name,
        produces=("information_observed",),
        cost=0.5,
        risk="low",
        idempotent=True,
        verification_level="strong",
        exploration_safe=True,
        emits_world_delta=False,
        information_domains=("research", "learning"),
        information_gain_prior=prior,
        build_args=lambda goal: {"query": goal},
    )


def action(name: str, query: str) -> dict:
    return {
        "tool": name,
        "capability": name,
        "parameters": {"query": query},
        "preconditions": (),
        "expected_effects": ("information_observed",),
        "risk": "low",
        "cost": 0.5,
        "reversible": True,
    }


def transition(state: str, act: dict, next_state: str) -> dict:
    return {
        "state_before": state,
        "action": act,
        "predicted_state": next_state,
        "state_after": next_state,
        "outcome": {"ok": True, "verified": True},
        "verified": True,
        "reward": 1.0,
        "timestamp": "2026-09-30T00:00:00+00:00",
        "metadata": (),
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="shury-phase8-") as temp:
        store = LearningStore(Path(temp) / "learning.db")
        manager = SelfImprovementManager(store=store)
        registry = {
            "probe_a": safe_tool("probe_a", 0.82),
            "probe_b": safe_tool("probe_b", 0.94),
        }
        state = WorldState(capabilities={"research"}).fingerprint()
        a = action("probe_a", "topic")
        b = action("probe_b", "topic")
        before = manager.exploration_policy.decide(state, "research this topic", [a, b], registry)
        next_state = WorldState(capabilities={"research", "observed"}).fingerprint()
        # Real observations would normally arrive through the governed runtime.  Here
        # the transitions are local synthetic evidence solely for this demonstration.
        for _ in range(25):
            manager.transition_model.learn_episode([transition(state, b, next_state)])
        after = manager.exploration_policy.decide(state, "research this topic", [a, b], registry)
        payload = {
            "cold_start": {
                "selected": before.selected_tool if before else None,
                "mode": before.mode if before else None,
                "information_gain": round(before.information_gain, 3) if before else None,
            },
            "after_evidence": {
                "selected": after.selected_tool if after else None,
                "mode": after.mode if after else None,
                "information_gain": round(after.information_gain, 3) if after else None,
            },
            "behavior_changed": bool(before and after and before.selected_tool != after.selected_tool),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
