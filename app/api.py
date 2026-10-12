"""Stable public API for embedding or integrating the Personal Agent.

Internal implementation modules live under responsibility-oriented packages.
Prefer importing public orchestration entry points from this module.
"""

from app.runtime.agent import (
    plan_only,
    replay_run,
    reliability_report,
    resume_agent,
    run_agent,
)
from app.runtime.registry import Tool, load_tools, manifest, register
from app.intelligence.semantic import SemanticParse, SemanticInterpreter, semantic_understand
from app.learning import SelfImprovementManager
from app.knowledge.seed_scenarios import SeedScenarioStore, SeedScenario
from app.world import (WorldModel, EntityState, Observation, PredictedTransition, RelationState, StateDiff, WorldAssessment, load_session_world, save_session_world)
from app.evaluation import EvaluationLab, EvalScenario, ExpectedOutcome, release_gate, render_report_markdown
from app.identity import AgentIdentity, get_identity, identity_context
from app.brain import BrainResult, CognitiveKernel


def run_cognitive(*args, **kwargs):
    from app.runtime.cognitive_agent import run_cognitive as _run_cognitive
    return _run_cognitive(*args, **kwargs)


def run_structured_goal(payload: dict, *, approve=None, session_id: str | None = None, max_steps: int = 8,
                       kernel: CognitiveKernel | None = None, execution_guard=None):
    """Canonical entry point for a structured GoalSpec request."""
    engine = kernel or CognitiveKernel()
    return engine.act_structured(payload, approve=approve, session_id=session_id, max_steps=max_steps, execution_guard=execution_guard)


def run_brain(message: str, *, approve=None, session_id: str | None = None, max_steps: int = 8,
              kernel: CognitiveKernel | None = None, execution_guard=None):
    """V23 cognitive entry point using the canonical Brain → Learning stack."""
    engine = kernel or CognitiveKernel()
    return engine.act(message, approve=approve, session_id=session_id, max_steps=max_steps, execution_guard=execution_guard)

__all__ = [
    "Tool",
    "load_tools",
    "manifest",
    "register",
    "plan_only",
    "replay_run",
    "reliability_report",
    "resume_agent",
    "run_agent",
    "run_cognitive",
    "run_structured_goal",
    "SemanticParse", "SemanticInterpreter", "semantic_understand",
    "SelfImprovementManager",
    "SeedScenarioStore", "SeedScenario",
    "WorldModel", "EntityState", "Observation", "PredictedTransition", "RelationState", "StateDiff", "WorldAssessment", "load_session_world", "save_session_world",
    "EvaluationLab", "EvalScenario", "ExpectedOutcome", "release_gate", "render_report_markdown",
    "AgentIdentity", "get_identity", "identity_context",
    "BrainResult", "CognitiveKernel", "run_brain",
]
