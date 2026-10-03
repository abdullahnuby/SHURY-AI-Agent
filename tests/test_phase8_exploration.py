from __future__ import annotations

from pathlib import Path

from app.interfaces.web.server import _cognitive_summary
from app.brain.kernel import CognitiveKernel
from app.brain.store import BrainStateStore
from app.knowledge.memory import Memory
from app.learning.exploration import ExplorationPolicy, build_exploration_actions, is_safe_exploration_tool
from app.learning.manager import SelfImprovementManager
from app.learning.store import LearningStore
from app.learning.transition_model import action_signature
from app.runtime.registry import Tool
from app.world.model import WorldModel
from app.domain.world import WorldState


def _transition(state: str, action: dict, *, success: bool, next_state: str) -> dict:
    return {
        "state_before": state,
        "action": action,
        "predicted_state": next_state,
        "state_after": next_state if success else state,
        "outcome": {"ok": success, "verified": success, "output": {"ok": success}},
        "verified": success,
        "reward": 1.0 if success else 0.0,
        "timestamp": "2026-09-30T00:00:00+00:00",
        "metadata": (),
    }


def _action(name: str, *, effect: str = "observed", parameters: dict | None = None) -> dict:
    return {
        "action_id": f"{name}:1",
        "capability": name,
        "tool": name,
        "parameters": dict(parameters or {}),
        "preconditions": [],
        "expected_effects": [effect],
        "risk": "low",
        "cost": 0.5,
        "reversible": True,
    }


def _safe_tool(name: str, *, domain: tuple[str, ...] = ("research",), prior: float = 0.9) -> Tool:
    return Tool(
        name=name,
        description=f"safe information tool for {domain}",
        params={"query": "str"},
        fn=lambda query: {"answer": query, "evidence": [{"title": "observed evidence", "snippet": query}]},
        capability=name,
        produces=("information_observed",),
        risk="low",
        idempotent=True,
        verification_level="strong",
        exploration_safe=True,
        emits_world_delta=False,
        information_domains=domain,
        information_gain_prior=prior,
        build_args=lambda goal: {"query": str(goal)},
    )


def test_information_gain_is_evidence_sensitive(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    manager = SelfImprovementManager(store=store)
    state = "state-x"
    action = _action("probe")
    cold = manager.exploration_policy._metrics(state, action)

    next_a = "state-a"
    for _ in range(30):
        manager.transition_model.learn_episode([_transition(state, action, success=True, next_state=next_a)])
    warm = manager.exploration_policy._metrics(state, action)

    assert float(cold["information_gain"]) > float(warm["information_gain"])
    assert float(cold["novelty"]) > float(warm["novelty"])


def test_phase8_ucb_can_select_an_unseen_safe_action(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    manager = SelfImprovementManager(store=store)
    registry = {
        "known": _safe_tool("known", domain=("research",), prior=0.10),
        "probe": _safe_tool("probe", domain=("research",), prior=0.99),
    }
    state = WorldState(capabilities={"research"}).fingerprint()
    known = _action("known", parameters={"query": "topic"})
    next_state = WorldState(capabilities={"research", "observed"}).fingerprint()
    for _ in range(20):
        manager.transition_model.learn_episode([_transition(state, known, success=True, next_state=next_state)])

    decision = manager.exploration_policy.decide(
        state,
        "research this topic",
        [known, _action("probe", parameters={"query": "topic"})],
        registry,
    )
    assert decision is not None
    assert decision.selected_tool == "probe"
    assert decision.mode in {"information", "explore"}
    assert decision.evidence_count == 0
    assert decision.information_gain > 0.55


def test_unsafe_actions_are_not_exploration_candidates(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    safe = _safe_tool("safe_probe")
    unsafe = Tool(
        name="dangerous_probe", description="unsafe", params={"query": "str"}, fn=lambda query: query,
        capability="dangerous_probe", risk="medium", idempotent=True,
        exploration_safe=True, emits_world_delta=False,
        information_domains=("research",), information_gain_prior=1.0,
        build_args=lambda goal: {"query": str(goal)},
    )
    registry = {"safe_probe": safe, "dangerous_probe": unsafe}
    actions = build_exploration_actions("research this topic", registry)
    assert [a["tool"] for a in actions] == ["safe_probe"]
    assert is_safe_exploration_tool(safe)
    assert not is_safe_exploration_tool(unsafe)


def test_seed_action_is_preferred_over_rebuilt_duplicate(tmp_path: Path):
    tool = _safe_tool("web_research", domain=("research", "learning"), prior=0.95)
    registry = {"web_research": tool}
    seed = {
        "tool": "web_research",
        "capability": "web_research",
        "parameters": {"query": "specific topic"},
        "preconditions": (),
        "expected_effects": ("information_observed",),
        "risk": "low",
        "reversible": True,
    }
    actions = build_exploration_actions("learn from web specific topic", registry, seed_actions=[seed])
    assert len(actions) == 1
    assert actions[0]["parameters"] == {"query": "specific topic"}


def test_learning_from_web_keeps_the_topic_and_uses_open_world_learning(tmp_path: Path):
    kernel = CognitiveKernel(
        memory=Memory(tmp_path / "memory.db"),
        state_store=BrainStateStore(tmp_path / "brain_state.db"),
        experience_store=LearningStore(tmp_path / "learning.db"),
    )
    result = kernel.think("learn from web how to be smarter", session_id="phase8-web")
    assert result.state.semantic is not None
    assert result.state.semantic.requested_operation == "research"
    assert result.state.semantic.slot("query") == "how to be smarter"
    assert result.state.plan
    first = result.state.plan[0]
    assert first.tool == "research_and_learn"
    assert first.args["query"] == "how to be smarter"
    assert first.exploration_mode in {"", "information", "explore", "relearn"}


def test_learning_intent_can_take_an_information_first_step(tmp_path: Path):
    kernel = CognitiveKernel(
        memory=Memory(tmp_path / "memory.db"),
        state_store=BrainStateStore(tmp_path / "brain_state.db"),
        experience_store=LearningStore(tmp_path / "learning.db"),
    )
    result = kernel.think("learn how to improve", session_id="phase8-learning")
    assert result.state.semantic is not None
    assert result.state.semantic.requested_operation == "learning_intent"
    assert result.state.plan
    assert result.state.plan[0].exploration_mode == "information"
    assert result.state.plan[0].tool == "research_memory_search"
    decisions = [e for e in result.state.trace if e.get("kind") == "exploration_decision"]
    assert decisions
    assert decisions[-1]["information_gain"] > 0.55


def test_exploration_then_replan_is_side_effect_free_for_learning_until_observation(tmp_path: Path):
    calls: list[tuple[str, dict]] = []
    registry = {
        "research_memory_search": Tool(
            "research_memory_search", "memory search", {"query": "str"},
            lambda query: calls.append(("research_memory_search", {"query": query})) or {
                "evidence": [{"title": "memory result", "snippet": query}]
            },
            capability="research_memory_retrieval", produces=("historical_research_evidence",),
            cost=0.5, duration=0.1, risk="low", idempotent=True, verification_level="strong",
            exploration_safe=True, emits_world_delta=False,
            information_domains=("research", "learning", "memory"), information_gain_prior=0.9,
            build_args=lambda goal: {"query": str(goal)},
        ),
        "research_and_learn": Tool(
            "research_and_learn", "learning search", {"query": "str"},
            lambda query: calls.append(("research_and_learn", {"query": query})) or {
                "query": query, "evidence_count": 1, "new_evidence_count": 1,
                "route": [{"source": "test"}],
                "evidence": [{"title": "learned result", "url": "https://example.test", "snippet": query}],
            },
            capability="open_world_learning", produces=("research_evidence", "learning_candidate"),
            cost=1.0, duration=0.2, risk="low", idempotent=True, verification_level="strong",
            exploration_safe=True, emits_world_delta=False,
            information_domains=("research", "learning"), information_gain_prior=0.95,
            triggers=("never-match-direct",),
            match=lambda g: False,
            build_args=lambda goal: {"query": "how to improve"},
        ),
    }
    kernel = CognitiveKernel(
        memory=Memory(tmp_path / "memory.db"),
        registry=registry,
        state_store=BrainStateStore(tmp_path / "brain_state.db"),
        experience_store=LearningStore(tmp_path / "learning.db"),
    )
    result = kernel.act("learn how to improve", session_id="phase8-exec")
    assert result.status == "completed"
    assert [name for name, _ in calls] == ["research_memory_search", "research_and_learn"]
    events = result.learning_events if hasattr(result, "learning_events") else []
    # The persisted exploration row is the authoritative execution audit.
    rows = kernel.learning.store.recent_exploration_events(run_id=result.run_id, limit=10)
    assert rows and rows[0]["executed"] == 1 and rows[0]["ok"] == 1
    assert rows[0]["mode"] == "information"


def test_bare_learning_request_does_not_create_fake_exploration_plan(tmp_path: Path):
    kernel = CognitiveKernel(
        memory=Memory(tmp_path / "memory.db"),
        state_store=BrainStateStore(tmp_path / "brain_state.db"),
        experience_store=LearningStore(tmp_path / "learning.db"),
    )
    result = kernel.think("learn", session_id="phase8-bare-learn")
    assert result.state.semantic is not None
    assert result.state.semantic.requested_operation == "learning_intent"
    assert "learning_topic_required" in result.state.semantic.uncertainty
    assert result.state.plan == []
    assert result.state.decision is not None
    assert result.state.decision.kind == "clarify"
    assert "learning_topic" in result.state.decision.missing_information
    assert "What should I learn" in result.response


def test_explicit_web_learning_honors_user_source_constraint(tmp_path: Path):
    kernel = CognitiveKernel(
        memory=Memory(tmp_path / "memory.db"),
        state_store=BrainStateStore(tmp_path / "brain_state.db"),
        experience_store=LearningStore(tmp_path / "learning.db"),
    )
    result = kernel.think("learn from web how to be smarter", session_id="phase8-explicit-web")
    assert result.state.plan
    assert result.state.plan[0].tool == "research_and_learn"
    assert result.state.plan[0].args["query"] == "how to be smarter"
    assert result.state.plan[0].exploration_mode in {"", "information", "explore", "relearn"}


def test_realized_information_gain_is_persisted_and_reused(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    safe = _safe_tool("memory_probe", domain=("research", "learning", "memory"), prior=0.9)
    registry = {"memory_probe": safe}
    kernel = CognitiveKernel(
        memory=Memory(tmp_path / "memory.db"),
        registry=registry,
        state_store=BrainStateStore(tmp_path / "brain_state.db"),
        experience_store=store,
    )
    result = kernel.think("research this topic", session_id="phase8-feedback")
    # Exercise the persistence API directly here with a controlled before/after uncertainty;
    # the runtime path is covered by the integration test above.
    event_id = store.record_exploration_event(
        run_id=result.run_id,
        state_signature="state-feedback",
        action_signature="sig-feedback",
        tool="memory_probe",
        action=_action("memory_probe", parameters={"query": "topic"}),
        mode="information",
        score=1.0,
        goal_alignment=1.0,
        exploitation=0.5,
        ucb_bonus=0.5,
        information_gain=0.8,
        novelty=1.0,
        relearning_pressure=0.0,
        risk_penalty=0.0,
        evidence_count=0,
        uncertainty_before=0.9,
        selected=True,
        executed=True,
    )
    store.complete_exploration_event(
        event_id,
        executed=True,
        ok=True,
        verified=True,
        reward=0.5,
        uncertainty_after=0.2,
        realized_information_gain=0.7,
    )
    assert store.exploration_information_gain("memory_probe", "sig-feedback") == 0.7
    assert store.exploration_information_gain("memory_probe", "different-context-signature") == 0.7

    metrics = kernel.learning.exploration_policy._metrics("state-feedback", _action("memory_probe", parameters={"query": "topic"}))
    decision = kernel.learning.exploration_policy.decide(
        "state-feedback", "research this topic", [_action("memory_probe", parameters={"query": "topic"})], registry
    )
    assert decision is not None
    assert decision.historical_information_gain == 0.7
    assert float(decision.information_gain) < 1.0


def test_web_cognitive_summary_exposes_real_phase8_evidence(tmp_path: Path):
    kernel = CognitiveKernel(
        memory=Memory(tmp_path / "memory.db"),
        state_store=BrainStateStore(tmp_path / "brain_state.db"),
        experience_store=LearningStore(tmp_path / "learning.db"),
    )
    result = kernel.think("learn how to improve", session_id="phase8-ui")
    summary = _cognitive_summary(result.state)
    assert summary["planning_mode"] == "exploration"
    assert summary["exploration"]["tool"] == "research_memory_search"
    assert summary["exploration"]["information_value"] > 0
    assert summary["exploration"]["expected_failure_cost"] >= 0
    assert any(stage["name"] == "state" and stage["complete"] for stage in summary["stages"])
    assert summary["alternatives"]
