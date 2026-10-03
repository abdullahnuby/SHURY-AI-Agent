from __future__ import annotations
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.skills.registry import SkillBank
from app.skills.evaluation import summary as skill_eval_summary
from app.skills.compiler import _triggers
from app.learning.brain_store import BrainKnowledgeStore
from app.brain.models import ActionSpec, Transition

from .models import ExperienceRecord, Lesson, EvolutionDecision, LearningStage, LearningCycleResult
from .store import LearningStore, DEFAULT_PATH
from .diagnosis import task_signature, failure_class, summarize_steps, compute_reward, contrastive_lesson, sanitize
from .replay import PrioritizedReplayBuffer, ReplayEvaluator, ExperienceReplayLearner
from .transition_model import LearnedTransitionModel
from .value_model import RewardModel, ValueModel
from .prediction_error import PredictionErrorModel
from .exploration import ExplorationPolicy
from .self_model import PersistentSelfModel
from .invalidation import ModelInvalidation
from .meta_strategy import MetaStrategyController
from .procedures import build_procedure_evidence
from .failure_recovery import FailureRecoveryLearner
from app.intelligence.semantic.pattern_cache import LanguagePatternCache
from .promotion import promotion_gate


def _skill_key(signature: str) -> str:
    return "evo:" + hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]


def _workflow_from_state(state):
    workflow=[]
    done=[s for s in (state.plan.steps if state.plan else []) if s.status=="done"]
    for s in done:
        workflow.append({"tool":s.tool,"depends_on":list(s.depends_on),"capability":s.capability,"args_policy":"derive-from-live-goal"})
    return tuple(workflow)


class SelfImprovementManager:
    """Layer 5 control loop: observe → diagnose → replay → revise → gate → promote.

    Learning data is advisory and never bypasses runtime policy, approval, verification, or skill trust.
    """
    def __init__(self, *, learning_path=None, bank_path=None, store=None):
        if store is not None and not isinstance(store, LearningStore):
            store = getattr(store, "store", None)
        learning_path = learning_path or os.environ.get("AGENT_LEARNING_DB") or DEFAULT_PATH
        bank_path = bank_path or os.environ.get("AGENT_SKILLS_DB")
        self.store=store or LearningStore(learning_path)
        self.bank=SkillBank(bank_path) if bank_path else SkillBank()
        replay_capacity = int(os.environ.get("AGENT_REPLAY_CAPACITY", "5000"))
        self.replay = PrioritizedReplayBuffer(self.store, capacity=max(1, replay_capacity), alpha=0.70)
        self.transition_model = LearnedTransitionModel(self.store)
        self.reward_model = RewardModel()
        self.value_model = ValueModel(self.store, reward_model=self.reward_model)
        self.replay_learner = ExperienceReplayLearner(self.replay, self.store, self.value_model)
        self.prediction_error_model = PredictionErrorModel(
            self.store, transition_model=self.transition_model, value_model=self.value_model
        )
        self.exploration_policy = ExplorationPolicy(
            self.store, transition_model=self.transition_model, value_model=self.value_model
        )
        self.self_model = PersistentSelfModel(self.store)
        self.model_invalidation = ModelInvalidation(self.store)
        self.meta_strategy = MetaStrategyController(self.store)
        self.failure_recovery = FailureRecoveryLearner(self.store, self.transition_model)
        self.language_pattern_cache = LanguagePatternCache(self.store)
        self._repair_legacy_lessons()

    def _repair_legacy_lessons(self) -> None:
        """Retire legacy reflection lessons that have no failed-step evidence.

        Older Layer-5 builds allowed conservative model reflections from successful steps to
        become active lessons. They are not trustworthy learning evidence and must not guide
        future runs. Keep their rows for auditability, but remove them from retrieval.
        """
        try:
            for lesson in self.store.active_lessons(limit=500):
                if lesson.kind != "reflection" or not lesson.evidence_run_ids:
                    continue
                experiences = [self.store.get_experience(rid) for rid in lesson.evidence_run_ids[:20]]
                experiences = [x for x in experiences if x is not None]
                has_failed_step = any(
                    any(str(step.get("status")) == "failed" for step in exp.steps)
                    or bool(exp.failure_class)
                    for exp in experiences
                )
                if not has_failed_step:
                    self.store.set_lesson_status(lesson.key, "retired")
                    self.store.record_event(lesson.key, "retire", "reflection lesson has no failed-step evidence", {})
        except Exception:
            # Learning maintenance must never break the agent runtime.
            return

    @staticmethod
    def _sanitize_value(value):
        if isinstance(value, dict):
            return {str(k): SelfImprovementManager._sanitize_value(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [SelfImprovementManager._sanitize_value(v) for v in value]
        if isinstance(value, str):
            return sanitize(value, 500)
        return value

    def _build_episode_transitions(self, state, memory, registry, trajectory=None) -> tuple[dict, ...]:
        """Convert observed runtime attempts into Phase-1 transitions.

        We use the runtime's already-persisted world fingerprints rather than inventing
        missing state. A learned prediction is captured before the current observation can
        update the model, so Phase 5 can score genuine out-of-sample transition error.
        """
        if trajectory:
            normalized = []
            for item in trajectory:
                if isinstance(item, dict):
                    normalized.append(dict(item))
            return tuple(normalized)
        try:
            effects = memory.effects(state.run_id)
        except Exception:
            effects = []
        if not effects:
            return ()
        try:
            env_sig = state.world.fingerprint()
        except Exception:
            env_sig = ""
        transitions = []
        for index, effect in enumerate(effects):
            state_before = effect.get("state_before")
            if not state_before:
                continue
            tool_name = str(effect.get("tool") or "")
            tool = registry.get(tool_name) if registry else None
            capability = str((getattr(tool, "capability", None) or tool_name))
            action = ActionSpec(
                action_id=f'{effect.get("step_id") or tool_name}:attempt:{int(effect.get("attempt") or 1)}',
                capability=capability,
                tool=tool_name,
                parameters=tuple(sorted(
                    (str(k), self._sanitize_value(v))
                    for k, v in (effect.get("args") or {}).items()
                )),
                preconditions=tuple(sorted(getattr(tool, "preconditions", ()) if tool else ())),
                expected_effects=tuple(sorted(getattr(tool, "produces", ()) if tool else ())),
                risk=str(getattr(tool, "risk", "low") if tool else "low"),
                cost=float(getattr(tool, "cost", 1.0) if tool else 1.0),
                # Tool currently exposes idempotence, not true reversibility. Do not conflate
                # those concepts; remain conservatively non-reversible until the contract adds it.
                reversible=bool(getattr(tool, "reversible", False) if tool else False),
                execution_time=(float(effect.get("duration_ms") or 0.0) / 1000.0),
                uncertainty=1.0,
            )
            outcome = {
                "ok": bool(effect.get("ok")),
                "verified": bool(effect.get("verified")),
                "error": sanitize(effect.get("error") or "", 320),
                "duration_ms": float(effect.get("duration_ms") or 0.0),
                "attempt": int(effect.get("attempt") or 1),
            }
            learned_prediction = None
            learned_model_version = 1
            try:
                learned_prediction = self.transition_model.predict(str(state_before), action.to_dict())
                inspected = self.transition_model.inspect(str(state_before), action.to_dict())
                if inspected:
                    learned_model_version = max(1, int(inspected.get("model_version", 1) or 1))
            except Exception:
                learned_prediction = None
            transition = Transition(
                state_before=str(state_before),
                action=action,
                predicted_state=(learned_prediction.predicted_state if learned_prediction else None),
                state_after=str(effect.get("state_after") or "") or None,
                outcome=outcome,
                reward=None,
                prediction_error=None,
                verified=bool(effect.get("verified")),
                timestamp=str(effect.get("ts") or ""),
                metadata=(
                    ("episode_id", str(state.run_id)),
                    ("state_fingerprint_kind", "world"),
                    ("step_id", str(effect.get("step_id") or "")),
                    ("attempt", int(effect.get("attempt") or 1)),
                    ("world_model_version", learned_model_version),
                    ("context_signature", str(env_sig or "")),
                    ("replay_boundary", bool(index == 0 or index == len(effects) - 1)),
                ),
            )
            payload = transition.to_dict()
            payload["transition_id"] = transition.fingerprint()
            payload["failure_class"] = (
                failure_class(tool_name, effect.get("error")) if not effect.get("ok") else ""
            )
            transitions.append(payload)
        return tuple(transitions)

    def _learning_stage(self, run_id: str, stage: str, action, *, payload: dict | None = None):
        """Execute one learning stage and persist its observable outcome."""
        started = datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")
        self.store.record_learning_stage(
            run_id, stage, status="running", payload=payload or {}, started_at=started
        )
        try:
            value = action()
            completed = datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")
            result_payload = value.to_dict() if hasattr(value, "to_dict") else (
                value if isinstance(value, dict) else {"result": value}
            )
            self.store.record_learning_stage(
                run_id, stage, status="completed", payload=result_payload,
                started_at=started, completed_at=completed,
            )
            return value
        except Exception as exc:
            completed = datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")
            self.store.record_learning_stage(
                run_id, stage, status="failed", payload=payload or {},
                error=sanitize(f"{type(exc).__name__}: {exc}", 500),
                started_at=started, completed_at=completed,
            )
            raise

    def _cycle_result(self, run_id: str, *, status: str, duplicate: bool, transitions: int) -> LearningCycleResult:
        cycle = self.store.learning_cycle(run_id) or {}
        stages = tuple(
            LearningStage(
                run_id=run_id, stage=str(item.get("stage") or ""),
                status=str(item.get("status") or ""),
                started_at=str(item.get("started_at") or ""),
                completed_at=str(item.get("completed_at") or ""),
                payload=item.get("payload") if isinstance(item.get("payload"), dict) else {},
                error=str(item.get("error") or ""),
            )
            for item in cycle.get("stages", [])
        )
        return LearningCycleResult(
            run_id=run_id, status=status, duplicate=duplicate,
            transitions=int(cycle.get("transitions") or transitions), stages=stages,
            policy_updated=any(
                s.stage == "policy_update" and s.status == "completed"
                and int((s.payload or {}).get("action_updates", 0) or 0) > 0
                for s in stages
            ),
            self_model_refreshed=any(
                s.stage == "self_model_update" and s.status == "completed"
                for s in stages
            ) or any(
                s.stage == "self_model_refresh" and s.status == "completed"
                for s in stages
            ),
            language_patterns_updated=any(
                s.stage == "language_pattern_update" and s.status == "completed"
                for s in stages
            ),
        )

    def _duplicate_learning_result(self, run_id: str, transitions: int) -> dict:
        result = self._cycle_result(run_id, status="completed", duplicate=True, transitions=transitions)
        experience = self.store.get_experience(run_id)
        return {
            "experience": experience.to_dict() if experience else None,
            "inserted": False,
            "duplicate": True,
            "learning_cycle": result.to_dict(),
        }

    def observe_run(self, state, memory, *, trajectory=None, registry=None):
        registry=registry or {}
        steps=summarize_steps(state,memory)
        reward,verified_rate=compute_reward(state,steps)
        signature=task_signature(state.goal)
        env_sig=""
        try:
            env_sig=state.world.fingerprint()
        except Exception:
            env_sig=""
        failed=[s for s in steps if s["status"]=="failed"]
        fclass=failure_class(failed[0]["tool"],failed[0].get("error")) if failed else None
        safe_goal = sanitize(state.goal, 1200)
        timestamp = datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")
        raw_transitions = self._build_episode_transitions(state, memory, registry, trajectory=trajectory)
        transitions = self.reward_model.annotate_episode(
            raw_transitions, episode_reward=reward, episode_status=state.status,
        )
        transitions, prediction_error_learning = self.prediction_error_model.annotate_episode(transitions)
        operation = str(getattr(state, "operation", "") or getattr(getattr(state, "semantic", None), "requested_operation", "") or "")
        exp=ExperienceRecord(state.run_id,safe_goal,signature,state.status,reward,verified_rate,steps,fclass,(),
                             getattr(state.world,"session_id",None),timestamp,env_sig,transitions,operation)
        if not self.store.begin_learning_cycle(state.run_id, transitions=len(transitions), started_at=timestamp):
            return self._duplicate_learning_result(state.run_id, len(transitions))
        self.store.record_learning_stage(
            state.run_id, "reward_calculated", status="completed",
            payload={
                "episode_reward": float(reward),
                "verified_rate": float(verified_rate),
                "transition_count": len(transitions),
            },
        )
        self.store.record_learning_stage(
            state.run_id, "prediction_error_scored", status="completed",
            payload=prediction_error_learning.to_dict(),
        )
        try:
            inserted=self._learning_stage(
                state.run_id, "experience_recorded",
                lambda: self.store.record_experience(exp),
                payload={"transition_count": len(transitions)},
            )
            replay_indexed = self._learning_stage(
                state.run_id, "replay_indexed",
                lambda: self.replay.add_episode(exp),
                payload={"transition_count": len(transitions)},
            )
            model_updates = self._learning_stage(
                state.run_id, "world_model_update",
                lambda: self.transition_model.learn_episode(transitions),
                payload={"transition_count": len(transitions)},
            )
            value_learning = self._learning_stage(
                state.run_id, "value_update",
                lambda: self.value_model.learn_episode(
                    transitions, episode_reward=reward, episode_status=state.status
                ),
                payload={"transition_count": len(transitions)},
            )
            self.store.record_learning_stage(
                state.run_id, "policy_update", status="completed",
                payload={
                    "source": "action-value-policy-evidence",
                    "action_updates": int(getattr(value_learning, "action_updates", 0) or 0),
                },
            )
            invalidation = self._learning_stage(
                state.run_id, "model_invalidation",
                lambda: {
                    "evaluated": len(transitions),
                    "decisions": [self.model_invalidation.evaluate_transition(t).to_dict() for t in transitions if isinstance(t, dict)],
                    "stats": self.model_invalidation.stats(),
                },
                payload={"transition_count": len(transitions)},
            )
            replay_batch = int(os.environ.get("AGENT_REPLAY_LEARNING_BATCH", "4"))
            replay_learning = self._learning_stage(
                state.run_id, "replay_learning",
                lambda: self.replay_learner.replay(
                    replay_batch, exclude_episode_id=state.run_id,
                    seed=int(hashlib.sha256(state.run_id.encode()).hexdigest()[:8], 16),
                ),
                payload={"requested": max(0, replay_batch), "exclude_episode_id": state.run_id},
            )
            self.store.record_learning_stage(
                state.run_id, "policy_replay_update", status="completed",
                payload={
                    "source": "replayed-action-value-evidence",
                    "updates": int(getattr(replay_learning, "updates", 0) or 0),
                },
            )
            self_model_learning = self._learning_stage(
                state.run_id, "self_model_update",
                lambda: self.self_model.learn(exp),
                payload={"transition_count": len(transitions)},
            )
            semantic_parse = getattr(state, "semantic_parse", None)
            language_pattern_learning = self._learning_stage(
                state.run_id, "language_pattern_update",
                lambda: self.language_pattern_cache.observe(
                    semantic_parse, run_id=state.run_id,
                    success=state.status == "completed", verified=bool(state.status == "completed" and verified_rate >= 0.80),
                ) if semantic_parse is not None else {"eligible": False, "reason": "semantic-parse-unavailable"},
                payload={"semantic_parse_available": semantic_parse is not None},
            )
        except Exception:
            self.store.complete_learning_cycle(state.run_id, status="failed", failure="learning stage failed")
            raise
        # Meta-strategy learns from the observed route, but it never controls runtime authority.
        try:
            meta = getattr(getattr(state, "plan", None), "diagnostics", {}) or {}
            meta_info = meta.get("meta_strategy", {}) if isinstance(meta, dict) else {}
            strategy = str(meta_info.get("selected") or "")
            if not strategy:
                # The canonical Brain planner records the selected meta route as a
                # structured state-trace event because CognitiveState.plan is a list,
                # not a Plan object. Reading the trace preserves the exact route used.
                route_events = [e for e in getattr(state, "trace", ())
                                if isinstance(e, dict) and e.get("kind") == "meta_strategy_route"]
                route = route_events[-1] if route_events else {}
                strategy = str(route.get("strategy") or "") if bool(route.get("applied", True)) else ""
                route_state_type = str(route.get("state_type") or "")
            else:
                route_state_type = ""
            state_type = route_state_type or str(
                getattr(getattr(state, "semantic", None), "interaction_shape", "")
                or ("compound" if len(steps) > 1 else "atomic")
            )
            if strategy:
                meta_outcome = self.meta_strategy.record_outcome(
                    state_type=state_type, strategy=strategy,
                    reward=float(reward) if state.status == "completed" else -1.0,
                    success=bool(state.status == "completed" and verified_rate >= 0.80),
                    context={"run_id": state.run_id, "operation": operation, "verified_rate": verified_rate},
                )
                self.store.record_learning_stage(state.run_id, "meta_strategy_update", status="completed", payload=meta_outcome)
        except Exception as exc:
            self.store.record_learning_stage(state.run_id, "meta_strategy_update", status="failed", error=sanitize(f"{type(exc).__name__}: {exc}", 500))
        # Verified runtime trajectories become new procedural evidence for the Brain,
        # while remaining distinct from synthetic seed priors. Failed runs are useful too
        # because their failure mode can shape future retrieval and avoidance.
        try:
            done_steps = [step for step in steps if isinstance(step, dict) and str(step.get("status")) == "done"]
            done_tools = [str(step.get("tool") or "") for step in done_steps if str(step.get("tool") or "")]
            if len(done_steps) >= 2:
                first_cap = str(done_steps[0].get("capability") or done_tools[0])
                evidence = build_procedure_evidence(
                    goal=safe_goal, operation=operation, capability=first_cap, steps=list(steps),
                    status=state.status, verified_rate=verified_rate, failure_class=fclass,
                    environment_signature=env_sig, run_id=state.run_id,
                )
                procedure_result = self.store.upsert_procedural_memory(**evidence)
            else:
                procedure_result = {"stored": False, "reason": "less-than-two-steps"}
        except Exception as exc:
            self.store.record_learning_stage(
                state.run_id, "procedure_update", status="failed",
                error=sanitize(f"{type(exc).__name__}: {exc}", 500),
            )
        else:
            self.store.record_learning_stage(
                state.run_id, "procedure_update", status="completed",
                payload={"verified_tools": done_tools if 'done_tools' in locals() else [], "procedural_memory": procedure_result},
            )
        similar=self.store.similar_experiences(signature,limit=20)
        lesson_keys=[]
        lesson_data=contrastive_lesson(exp,similar)
        if lesson_data:
            lesson=Lesson(created_at=datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S"),status="active",uses=0,**lesson_data)
            self.store.upsert_lesson(lesson)
            lesson_keys.append(lesson.key)
        # Verified successful trajectories are useful as compact heuristics, but only when multi-step.
        if trajectory:
            for item in trajectory:
                reflection = item.get("reflection") if isinstance(item, dict) else None
                if not isinstance(reflection, dict):
                    continue
                summary_text = sanitize(reflection.get("rationale_summary") or "", 360)
                next_objective = sanitize(reflection.get("next_objective") or "", 220)
                if not summary_text and not next_objective:
                    continue
                reflection_status = str(reflection.get("goal_status") or "progressing")
                failure_hint = bool(reflection.get("failure_class")) or bool(reflection.get("should_replan")) or reflection_status in {"blocked", "ambiguous"}
                # Reflection lessons are failure-driven memory. A model's narrative can be
                # wrong, but the runtime's verified step outcome is authoritative. Only a
                # genuinely failed step may create this lesson class.
                step_ok = bool(item.get("ok", True))
                if step_ok:
                    continue
                if not failure_hint and not reflection_status in {"blocked", "ambiguous"}:
                    continue
                rkey = "reflection:" + hashlib.sha256((signature + "|" + summary_text + "|" + next_objective).encode()).hexdigest()[:16]
                rlesson = Lesson(key=rkey, task_signature=signature, kind="reflection",
                    lesson=sanitize((summary_text + (" Next: " + next_objective if next_objective else "")).strip(), 520),
                    when_to_apply=(signature,), avoid=(), evidence_run_ids=(state.run_id,), confidence=0.50,
                    status="active", uses=0, created_at=datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S"))
                self.store.upsert_lesson(rlesson); lesson_keys.append(rkey)
        if state.status=="completed" and len([s for s in steps if s["status"]=="done"])>=2:
            success_key="success:"+hashlib.sha256((signature+"|"+"|".join(s["tool"] for s in steps)).encode()).hexdigest()[:16]
            success_lesson=Lesson(key=success_key,task_signature=signature,kind="success-heuristic",
                lesson=sanitize("Verified workflow preference: "+" → ".join(s["tool"] for s in steps if s["status"]=="done")),
                when_to_apply=(signature,),avoid=(),evidence_run_ids=(state.run_id,),confidence=0.55,
                status="active",uses=0,created_at=datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S"))
            self.store.upsert_lesson(success_lesson); lesson_keys.append(success_key)
        self.store.record_learning_stage(
            state.run_id, "lesson_update", status="completed",
            payload={"lesson_count": len(lesson_keys), "lesson_keys": lesson_keys[:12]},
        )
        if inserted and lesson_keys:
            self.store.record_event("runtime", "lesson_created", "trajectory evidence produced a reusable lesson", {"run_id":state.run_id,"lesson_keys":lesson_keys})
        # Failure/recovery learning is separate from prose lessons. It persists a causal diagnosis
        # and bounded recovery candidates; it never executes a real-world side effect.
        try:
            diagnosis = self.failure_recovery.diagnose(exp, similar=similar)
            if diagnosis is None:
                recovery_payload = {"applicable": False, "reason": "no-failure"}
            else:
                recovery = self.failure_recovery.choose_recovery(diagnosis)
                recovery_payload = self.failure_recovery.learn(
                    diagnosis, recovery,
                    recovery_verified=bool(state.status == "completed" and verified_rate >= 0.80 and recovery.selected_action_signature),
                )
                recovery_payload["applicable"] = True
            self.store.record_learning_stage(state.run_id, "failure_recovery_learning", status="completed", payload=recovery_payload)
        except Exception as exc:
            self.store.record_learning_stage(state.run_id, "failure_recovery_learning", status="failed", error=sanitize(f"{type(exc).__name__}: {exc}", 500))
        # Second independent success is the cold-start point for a skill candidate.
        successes=[x for x in similar if x.status=="completed" and x.verified_rate>=0.80]
        candidate=None
        if len(successes)>=2:
            source=successes[0]
            workflow=source.steps
            skill_workflow=[]
            for idx, s in enumerate(workflow):
                if s.get("status") != "done":
                    continue
                deps = list(s.get("depends_on", ()))
                # Real-user/model trajectories may omit explicit dependencies even when
                # the second step consumes the first step's output. Preserve the causal
                # chain rather than teaching an order-free skill that can lose dataflow.
                if not deps and skill_workflow:
                    prev = workflow[idx - 1].get("step") if idx > 0 else None
                    if prev:
                        deps = [prev]
                    else:
                        deps = [f"s{len(skill_workflow)}"]
                skill_workflow.append({"tool":s["tool"],"depends_on":deps,"capability":s.get("capability",s["tool"]),"args_policy":"derive-from-live-goal"})
            if len(skill_workflow)>=2:
                key=_skill_key(signature)
                candidate=self.bank.upsert(
                    key=key,name=f"Evolving workflow: {sanitize(source.goal,80)}",
                    triggers=_triggers(sanitize(source.goal,120)),contraindications=("outside learned task family",),
                    preconditions=(),workflow=tuple(skill_workflow),termination="verified outputs or explicit failure",
                    outputs=("verified_output",),evidence=[{"kind":"trajectory","run_id":x.run_id,"goal":x.goal,"task_signature":x.task_signature,"verified":x.verified_rate>=0.80,"reward":x.reward} for x in successes[:6]],
                    confidence=min(0.9,0.50+0.10*len(successes)),source="self-improvement",source_run_id=source.run_id,status="candidate")
                self.store.record_event(candidate.key,"candidate_created","repeated verified experience produced a candidate",{"signature":signature,"source_runs":[x.run_id for x in successes[:6]]})
                if registry:
                    try:
                        evaluator=ReplayEvaluator(registry,self.store,memory)
                        evaluator.evaluate(candidate,successes[:6])
                        decision=self.evolve_candidate(candidate.key,memory=memory)
                        result_payload = {"experience":exp.to_dict(),"inserted":inserted,"replay_indexed":replay_indexed,"transition_model_updates":model_updates,
                                "value_learning":value_learning.to_dict(),
                                "replay_learning":replay_learning.to_dict(),
                                "self_model_learning":self_model_learning,
                                "language_pattern_learning":language_pattern_learning,
                                "prediction_error_learning":prediction_error_learning.to_dict(),
                                "lessons":lesson_keys,
                                "candidate":candidate.__dict__|{"utility":candidate.utility},"evolution":decision.to_dict()}
                    except Exception as exc:
                        self.store.record_event(candidate.key,"evaluation_error",sanitize(str(exc)),{})
        self.store.record_learning_stage(
            state.run_id, "skill_update", status="completed",
            payload={"candidate_created": bool(candidate), "candidate_key": candidate.key if candidate else ""},
        )
        if "result_payload" not in locals():
            result_payload = {"experience":exp.to_dict(),"inserted":inserted,"replay_indexed":replay_indexed,"transition_model_updates":model_updates,
                    "value_learning":value_learning.to_dict(),
                    "replay_learning":replay_learning.to_dict(),
                    "self_model_learning":self_model_learning,
                    "language_pattern_learning":language_pattern_learning,
                    "prediction_error_learning":prediction_error_learning.to_dict(),
                    "lessons":lesson_keys,
                    "candidate":candidate.__dict__|{"utility":candidate.utility} if candidate else None}
        self.store.complete_learning_cycle(state.run_id, status="completed")
        result_payload["learning_cycle"] = self._cycle_result(
            state.run_id, status="completed", duplicate=False, transitions=len(transitions)
        ).to_dict()
        return result_payload

    def learning_cycle(self, run_id: str) -> dict | None:
        """Return the durable learning-cycle ledger for one real execution."""
        return self.store.learning_cycle(str(run_id))

    def guidance(self, goal: str, *, limit: int=6):
        signature=task_signature(goal)
        tokens=set(signature.split())
        lessons=self.store.search_lessons(signature,tokens,limit=limit)
        if lessons:
            self.store.touch_lessons([x.key for x in lessons])
        return [
            {"kind":l.kind,"lesson":l.lesson,"when_to_apply":list(l.when_to_apply),"avoid":list(l.avoid),"confidence":l.confidence,"evidence_run_ids":list(l.evidence_run_ids[:4])}
            for l in lessons
        ]

    def self_model_snapshot(self, *, limit: int = 200) -> dict:
        return self.self_model.snapshot(limit=limit)

    def self_model_assessment(self, *, tool: str, capability: str = "", context_signature: str = "") -> dict:
        return self.self_model.assess(tool=tool, capability=capability, context_signature=context_signature).to_dict()

    def language_pattern_snapshot(self, *, limit: int = 100) -> dict:
        return self.language_pattern_cache.snapshot(limit=limit)

    def language_pattern_lookup(self, text: str, language: str = "") -> dict | None:
        key = self.language_pattern_cache.pattern_key(text, language)
        return self.store.language_pattern_lookup(key)

    def evolve_candidate(self, key: str, *, memory, registry=None) -> EvolutionDecision:
        registry=registry or {}
        current=self.bank.get(key)
        candidate_signature=""
        for evidence in current.evidence:
            if isinstance(evidence, dict) and evidence.get("task_signature"):
                candidate_signature=str(evidence["task_signature"])
                break
        candidate_signature = candidate_signature or task_signature(" ".join(current.triggers)) or task_signature(current.name)
        experiences=self.store.similar_experiences(candidate_signature,limit=20)
        evals=self.store.evaluations(key)
        gates=promotion_gate(current,experiences,evals)
        if gates["promotable"] and self.bank.trust(key) in {"local","trusted"}:
            before=current.status
            self.bank.set_status(key,"approved")
            self.bank.set_status(key,"active")
            self.store.record_event(key,"promote","promotion gates passed",gates)
            return EvolutionDecision(key,"promote","promotion gates passed",gates,before,self.bank.get(key).status)
        reason=gates["reason"]
        self.store.record_event(key,"observe",reason,gates)
        return EvolutionDecision(key,"observe",reason,gates,current.status,current.status)

    def evaluate_candidate(self,key: str,*,registry=None,memory=None,limit:int=20):
        registry=registry or {}
        skill=self.bank.get(key)
        candidate_signature=""
        for evidence in skill.evidence:
            if isinstance(evidence, dict) and evidence.get("task_signature"):
                candidate_signature=str(evidence["task_signature"])
                break
        candidate_signature = candidate_signature or task_signature(" ".join(skill.triggers)) or task_signature(skill.name)
        experiences=self.store.similar_experiences(candidate_signature,limit=limit)
        runtime_memory = memory if hasattr(memory, "tool_reliability_posterior") else None
        evaluator=ReplayEvaluator(registry,self.store,runtime_memory)
        results=evaluator.evaluate(skill,experiences)
        return {"candidate":skill.__dict__|{"utility":skill.utility},"evaluations":[x.to_dict() for x in results],"gate":promotion_gate(skill,experiences,results)}

    def status(self) -> dict:
        out=self.store.stats()
        out["replay"]=self.replay.stats()
        out["transition_model"]=self.transition_model.stats()
        out["value_model"]=self.value_model.stats()
        out["prediction_error"]=self.prediction_error_model.stats()
        out["self_model"]=self.self_model.store.self_model_stats()
        out["language_patterns"]=self.language_pattern_cache.stats()
        out["skills"]={"candidate":len(self.bank.list("candidate")),"approved":len(self.bank.list("approved")),"active":len(self.bank.list("active"))}
        return out

    def replay_sample(self, batch_size: int = 8, *, seed: int | None = None) -> list[dict]:
        """Return prioritized transition evidence for a later learner; never executes it."""
        return [item.to_dict() for item in self.replay.sample(batch_size, seed=seed)]

    def rollback(self, key: str) -> dict:
        current=self.bank.get(key)
        if current.status == "active":
            self.bank.set_status(key,"candidate")
            self.store.record_event(key,"rollback","active candidate rolled back to candidate without deleting evidence",{})
        return {"key":key,"status":self.bank.get(key).status,"trust":self.bank.trust(key),"action":"rollback"}
