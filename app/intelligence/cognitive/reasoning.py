from __future__ import annotations

from app.intelligence.cognitive.models import CognitiveBrief, CognitiveReflection, Hypothesis
from app.intelligence.cognitive.reflection import sanitize
from app.intelligence.cognitive.hypothesis import heuristic_hypotheses


class CognitiveReasoner:
    """Deterministic cognitive summary adapter.

    Language understanding is handled by Arabic-Retrieval-v1.0 in Layer 2. This class only
    derives concise structured summaries from already parsed/runtime-grounded data.
    """

    def analyze(self, goal: str, context: dict) -> CognitiveBrief:
        semantic = context.get("semantic") or {}
        intents = context.get("intents") or []
        ambiguous = bool(context.get("ambiguous"))
        top = intents[0] if intents else {}
        strategy = "clarify" if ambiguous else "execute" if context.get("deterministic_candidate", {}).get("steps") else "inspect"
        hyps = heuristic_hypotheses(goal, intents, context.get("deterministic_candidate", {}).get("steps", []))
        confidence = float(getattr(top, "confidence", 0.0) or (top.get("confidence", 0.0) if isinstance(top, dict) else 0.0) or 0.0)
        return CognitiveBrief(
            goal=goal[:1000],
            task_type=str((top.get("capability") if isinstance(top, dict) else getattr(top, "capability", "")) or "general"),
            success_criteria=[], constraints=[], ambiguities=context.get("ambiguities", []),
            assumptions=[], subgoals=[], information_gaps=context.get("information_gaps", []),
            hypotheses=[Hypothesis(str(x.get("statement", ""))[:500], [str(e) for e in x.get("evidence_needed", [])][:6], float(x.get("confidence", 0.0))) for x in hyps if isinstance(x, dict)],
            strategy=strategy, risk="low", confidence=confidence,
            needs_clarification=ambiguous, clarification_question=str(context.get("clarification_question") or ""),
            first_action_hint=str((context.get("deterministic_candidate", {}).get("steps") or [{}])[0].get("tool", "")) if context.get("deterministic_candidate", {}).get("steps") else "",
            baseline_plan=context.get("deterministic_candidate", {}).get("steps", [])[:16],
            mode="deterministic",
        )

    def validate_final(self, brief: CognitiveBrief, answer: str, trajectory: list[dict]) -> dict:
        ok = bool(str(answer or "").strip())
        return {"goal_status": "achieved" if ok else "ambiguous", "answer_supported": ok,
                "missing_information": [] if ok else ["answer"], "user_question": "",
                "rationale_summary": "deterministic runtime verification", "confidence": 1.0 if ok else 0.0}

    def reflect(self, brief: CognitiveBrief, step: dict, observation: dict, trajectory: list[dict]) -> CognitiveReflection:
        ok = bool(observation.get("ok"))
        return CognitiveReflection(
            progress=1.0 if ok else 0.0, goal_status="achieved" if ok else "blocked",
            new_facts=[], changed_assumptions=[], information_gaps=[],
            failure_class="" if ok else "execution_failure", should_replan=not ok,
            next_objective="retry_or_replan" if not ok else "",
            rationale_summary="deterministic observation verification", confidence=1.0 if ok else 0.0,
        )
