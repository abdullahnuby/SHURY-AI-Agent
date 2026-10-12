"""Planning facade for the V9 hierarchical deterministic runtime."""
from typing import Protocol

from app.domain.plan import Plan, validate
from app.domain.world import WorldState
from app.runtime.registry import load_tools
from app.domain.goal import parse_goal
from app.domain.operators import build_operators
from app.planning.portfolio import portfolio_plan
from app.planning.stn import validate_plan_temporal
from app.runtime.certificate import certify_plan
from app.intelligence.understanding import normalize
from app.skills.registry import SkillBank
from app.planning.adaptive_planning import choose_adaptive_plan
from app.planning.task_planner import plan_task_ir
from app.planning.methods import expand_task_ir
from app.learning.meta_strategy import MetaStrategyController


class Planner(Protocol):
    def plan(self, goal: str, memory=None, world=None) -> Plan: ...


class RulePlanner:
    """Backward-compatible facade; implementation is V9 hierarchical AND/OR search."""
    last_constraints: dict = {}

    def plan(self, goal: str, memory=None, world=None, task_ir=None, learning=None, registry=None) -> Plan:
        registry = dict(registry or load_tools())
        reliability = {name: memory.tool_reliability_posterior(name) for name in registry} if memory else {}
        model = parse_goal(goal)
        self.last_constraints = dict(model.constraints)
        initial_facts = set(world.capabilities) if world else set()
        initial_resources = dict(world.resources) if world else {}

        # Reuse the canonical Phase-2..7 learning stack when the caller provides one.
        # Otherwise lazily open the same AGENT_LEARNING_DB-backed store for explicit
        # learning operations; the mature legacy runtime remains deterministic unless
        # a learning manager is deliberately injected.
        learning_was_provided = learning is not None
        meta_controller = None
        meta_decision = None
        try:
            meta_store = getattr(learning, "store", learning) if learning is not None else None
            if meta_store is not None and hasattr(meta_store, "meta_strategy_observation"):
                meta_controller = MetaStrategyController(meta_store)
                state_type = "compound" if getattr(task_ir, "compound", False) else ("conditional" if getattr(task_ir, "conditions", None) else "atomic")
                available_strategies = (
                    ("sequential", "search", "verification-first", "recovery-first") if state_type == "compound"
                    else ("direct", "search", "information-first", "exploration", "verification-first")
                )
                meta_decision = meta_controller.recommend(state_type, available=available_strategies)
        except Exception:
            meta_controller = None
            meta_decision = None
        if learning is None:
            try:
                from app.learning.manager import SelfImprovementManager
                learning = SelfImprovementManager()
            except Exception:
                learning = None

        # TaskIR is the intelligence-facing entry point. The legacy portfolio remains
        # available as a certified fallback, so a malformed semantic compilation can
        # never silently replace a valid legacy plan.
        task_ir_candidate = None
        method_preview = []
        if task_ir is not None:
            try:
                _preview_nodes, method_preview = expand_task_ir(task_ir)
            except Exception:
                method_preview = []
        task_ir_eligible = bool(
            task_ir is not None
            and getattr(task_ir, "executable", False)
            and (
                getattr(task_ir, "compound", False)
                or float(getattr(task_ir, "confidence", 0.0)) >= 0.72
                or bool(method_preview)
            )
            and not getattr(task_ir, "conditions", None)
        )
        if task_ir_eligible:
            try:
                task_ir_candidate = plan_task_ir(task_ir, registry, memory=memory, world=world, max_nodes=12000)
            except Exception:
                task_ir_candidate = None

        fresh = portfolio_plan(
            model,
            build_operators(registry, reliability),
            registry,
            initial_facts=initial_facts,
            initial_resources=initial_resources,
            max_nodes=20000,
        )
        # Skills are candidates, not authorities. Re-materialize their workflow against
        # the live goal and only keep a skill plan when it is certified and near-tied
        # with the current planner output.
        # TaskIR is an alternative planning route, not an authority. Prefer it only when
        # it demonstrably expands task coverage beyond the legacy portfolio. A tie stays
        # with the mature planner, which preserves subtle dataflow behavior accumulated
        # in existing operators (for example the historical calculate -> save-note pipe).
        if task_ir_candidate is not None and task_ir_candidate.steps:
            node_diag = task_ir_candidate.diagnostics.get("nodes", []) if isinstance(task_ir_candidate.diagnostics, dict) else []
            planned_nodes = sum(1 for item in node_diag if item.get("status") == "planned")
            legacy_steps = len(fresh.steps)
            task_edges = sum(len(s.depends_on) for s in task_ir_candidate.steps)
            legacy_edges = sum(len(s.depends_on) for s in fresh.steps)
            structural_gain = task_edges > legacy_edges or bool(task_ir_candidate.diagnostics.get("methods"))
            materially_better = planned_nodes >= len(getattr(task_ir, "nodes", [])) and (
                legacy_steps == 0
                or structural_gain
                or len(task_ir_candidate.steps) > legacy_steps
                or (len(task_ir_candidate.steps) == legacy_steps and task_ir_candidate.estimated_cost < fresh.estimated_cost * 0.90)
            )
            if materially_better:
                fresh = task_ir_candidate
                self.last_constraints = dict(getattr(task_ir, "constraints", {}) or {})
                fresh.diagnostics = dict(fresh.diagnostics)
                fresh.diagnostics["task_ir_planner"] = True

        try:
            matched_skills = (SkillBank().match_task_ir(task_ir, limit=5)
                              if task_ir is not None and getattr(task_ir, "compound", False)
                              else SkillBank().match(goal, limit=5))
            fresh = choose_adaptive_plan(
                model.original, fresh, matched_skills, registry,
                initial_facts=initial_facts, initial_resources=initial_resources,
                max_duration=model.constraints.get("max_duration"),
                task_ir=task_ir,
            )
        except Exception as exc:
            fresh.diagnostics = dict(fresh.diagnostics)
            fresh.diagnostics["skill_selection_error"] = str(exc)
        # Phase-7 model-based search is the default learned candidate. It is conservative:
        # no learned edge -> no learned plan; failed/uncertified search -> keep the mature
        # deterministic candidate. Runtime policy/approval/verification remain authoritative.
        if learning_was_provided and learning is not None and world is not None and not fresh.diagnostics.get("model_based_attempted"):
            try:
                from app.planning.model_based_planner import ModelBasedPlanner
                learned_candidate = ModelBasedPlanner(
                    learning.transition_model, learning.value_model,
                    registry=registry, max_depth=min(5, max(1, len(fresh.steps) or 5)),
                ).plan(
                    model.original, world,
                    initial_facts=initial_facts, initial_resources=initial_resources,
                )
                fresh.diagnostics = dict(fresh.diagnostics)
                fresh.diagnostics["model_based_attempted"] = True
                learned_errors = validate(learned_candidate, registry)
                if learned_candidate.steps and not learned_errors and learned_candidate.diagnostics.get("certificate", {}).get("ok"):
                    learned_candidate.diagnostics = dict(learned_candidate.diagnostics)
                    learned_candidate.diagnostics["precedence"] = "phase7-learned-default"
                    learned_candidate.diagnostics["deterministic_fallback_cost"] = fresh.estimated_cost
                    preferred = str(getattr(meta_decision, "preferred_strategy", "") or "") if meta_decision else ""
                    evidence_count = int(getattr(meta_decision, "evidence_count", 0) or 0) if meta_decision else 0
                    # Meta-strategy is a route selector, not a new planner authority. During
                    # cold-start it must not disable an already-supported learned route that was
                    # the pre-controller behavior; once evidence exists, the learned preference
                    # controls route selection explicitly.
                    if not meta_decision or evidence_count == 0 or preferred == "search":
                        fresh = learned_candidate
            except Exception as exc:
                fresh.diagnostics = dict(fresh.diagnostics)
                fresh.diagnostics["model_based_attempted"] = True
                fresh.diagnostics["model_based_error"] = str(exc)[:300]

        if meta_decision is not None:
            fresh.diagnostics = dict(fresh.diagnostics)
            fresh.diagnostics["meta_strategy"] = meta_decision.to_dict()
            fresh.diagnostics["meta_strategy"] = {**fresh.diagnostics["meta_strategy"], "selected": getattr(meta_decision, "preferred_strategy", "direct")}
        errors = validate(fresh, registry)
        temporal_ok, temporal_reason = validate_plan_temporal(fresh, registry, model.constraints.get("max_duration"))
        if not temporal_ok:
            fresh.diagnostics["temporal_error"] = temporal_reason
            fresh = Plan([], planner="v10-temporal-reject", diagnostics=dict(fresh.diagnostics))
        if not errors and fresh.steps:
            fresh.diagnostics.setdefault("experience", "not_checked")
            if not str(fresh.planner).startswith(("v23-model-based", "v18-adaptive-skill", "v10-portfolio")):
                fresh.planner = "v10-search-stn"
            fresh.diagnostics["algorithm"] = "hierarchical-and-or-v9"
            fresh.diagnostics["algorithm_v10"] = "v10-portfolio+relaxed-heuristic+pareto+stn"

        # Verified procedural memory is treated as a candidate, never a bypass.
        if memory and not errors:
            cached = memory.cached_plan(normalize(goal))
            if cached and cached.get("success_count", 0) > 0:
                try:
                    cached_plan = Plan.from_dict(cached["plan"])
                    cached_errors = validate(cached_plan, registry)
                    cached_cert = certify_plan(cached_plan, registry, initial_facts, initial_resources, model.constraints.get("max_duration"))
                    if not cached_errors and cached_cert.ok:
                        # Cache is a candidate only after re-certifying against the live world.
                        if (cached_cert.estimated_cost, cached_cert.estimated_duration, len(cached_plan.steps)) <= \
                           (fresh.estimated_cost, fresh.estimated_duration, len(fresh.steps)):
                            cached_plan.planner = "v8-experience-reuse"
                            cached_plan.diagnostics = dict(cached_plan.diagnostics)
                            cached_plan.diagnostics["experience"] = "verified-cache"
                            cached_plan.diagnostics["fresh_candidate_cost"] = fresh.estimated_cost
                            cached_plan.diagnostics["certificate"] = {"ok": True, "states": len(cached_cert.states)}
                            # Reuse the verified plan structure, never the old execution state/output.
                            # Data-dependent tools (including RAG and analytics) must execute again
                            # against current inputs; otherwise plan-cache reuse can surface stale evidence.
                            for step in cached_plan.steps:
                                step.status = "pending"
                                step.resolved = None
                                step.output = None
                                step.error = None
                                step.attempts = 0
                            return cached_plan
                except Exception:
                    pass
        return fresh

    def model_based_plan(self, goal: str, memory=None, world=None, *, max_depth: int = 5, registry=None, learning=None) -> Plan:
        """Explicit diagnostic entry point for the same Phase-7 learned strategy used by :meth:`plan`.

        It does not bypass normal validation or certification.
        """
        from app.planning.model_based_planner import ModelBasedPlanner
        from app.learning.manager import SelfImprovementManager
        from app.runtime.registry import load_tools

        manager = learning or SelfImprovementManager()
        active_registry = dict(registry or load_tools())
        return ModelBasedPlanner(
            manager.transition_model, manager.value_model, registry=active_registry, max_depth=max_depth
        ).plan(goal, world or WorldState())
