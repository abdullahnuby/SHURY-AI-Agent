from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from app.brain.models import PlannedAction
from .capability_planning import CapabilityCandidate, CapabilityRequirement, ExecutiveCapabilitySynthesizer


@dataclass(frozen=True)
class DelegationEvidence:
    capability: str
    department: str
    specialist: str
    skill_key: str
    tool: str
    attempts: int
    verified_successes: int
    verified_failures: int
    verified_success_rate: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecoveryCandidate:
    tool: str
    capability: str
    department: str
    specialist: str
    skill_key: str
    score: float
    verified_successes: int
    attempts: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DelegationRecoveryDecision:
    step_id: str
    failed_tool: str
    failure_class: str
    decision: str  # redelegate | retry | escalate
    selected: RecoveryCandidate | None = None
    candidates: tuple[RecoveryCandidate, ...] = ()
    confidence: float = 0.0
    reason: str = ''
    ownership_immutable: bool = True

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data['selected'] = self.selected.to_dict() if self.selected else None
        data['candidates'] = [x.to_dict() for x in self.candidates]
        return data


class CompanyRecoveryManager:
    """Evidence-bounded delegation recovery.

    The manager never mutates OrganizationCatalog ownership. It may select another already
    qualified candidate for the same capability when durable verified execution evidence exists;
    otherwise it escalates. Governance, authorization, and undeclared-dependency failures never
    trigger delegation changes.
    """

    _GOVERNANCE_FAILURES = {'authorization', 'policy', 'approval', 'context', 'dependency'}

    @staticmethod
    def classify_failure(error: str, *, verification_failed: bool = False) -> str:
        if verification_failed:
            return 'verification'
        text = str(error or '').casefold()
        checks = (
            ('authorization', ('تفويض', 'authorization', 'مالك الخطوة', 'mandate')),
            ('policy', ('policy', 'السياسة', 'runtime policy', 'blocked by')),
            ('approval', ('موافقة', 'approval', 'تم رفض العملية')),
            ('context', ('context', 'السياق', 'خارج نطاق', 'undeclared dependency')),
            ('dependency', ('depends on', 'تعتمد على', 'نتيجة لم تتوفر')),
        )
        for kind, terms in checks:
            if any(term in text for term in terms):
                return kind
        return 'execution'

    def _evidence_rows(self, learning_store: Any, capability: str) -> dict[tuple[str, str], DelegationEvidence]:
        if learning_store is None or not hasattr(learning_store, 'company_delegation_evidence'):
            return {}
        rows = {}
        try:
            for row in learning_store.company_delegation_evidence(capability=capability, limit=100):
                item = DelegationEvidence(
                    capability=str(row.get('capability') or capability),
                    department=str(row.get('department') or ''),
                    specialist=str(row.get('specialist') or ''),
                    skill_key=str(row.get('skill_key') or ''),
                    tool=str(row.get('tool') or ''),
                    attempts=int(row.get('attempts') or 0),
                    verified_successes=int(row.get('verified_successes') or 0),
                    verified_failures=int(row.get('verified_failures') or 0),
                    verified_success_rate=float(row.get('verified_success_rate') or 0.0),
                )
                rows[(item.specialist, item.tool)] = item
        except Exception:
            return {}
        return rows

    def decide(
        self,
        *,
        action: PlannedAction,
        error: str,
        organization: Any,
        tool_registry: dict[str, Any],
        learning_store: Any = None,
        verification_failed: bool = False,
    ) -> DelegationRecoveryDecision:
        failure_class = self.classify_failure(error, verification_failed=verification_failed)
        if failure_class in self._GOVERNANCE_FAILURES:
            return DelegationRecoveryDecision(
                step_id=action.step_id, failed_tool=action.tool, failure_class=failure_class,
                decision='escalate', confidence=1.0,
                reason='governance or context failure; delegation ownership must not be changed automatically',
            )

        capability = str(action.capability or '').strip()
        if not capability:
            return DelegationRecoveryDecision(
                step_id=action.step_id, failed_tool=action.tool, failure_class=failure_class,
                decision='escalate', reason='failed action has no structured capability for safe re-delegation',
            )

        requirement = CapabilityRequirement(
            key=action.step_id, objective=str(getattr(action, 'objective', '') or capability), capability=capability,
            source='recovery', depends_on=tuple(action.depends_on or ()),
            expected_effects=tuple(action.expected_effects or ()), arguments=dict(action.args or {}),
            preferred_tool='', confidence=1.0,
        )
        synthesizer = ExecutiveCapabilitySynthesizer()
        try:
            raw_candidates = synthesizer.candidates_for(requirement, registry=tool_registry, organization=organization)
        except Exception:
            raw_candidates = ()
        evidence = self._evidence_rows(learning_store, capability)
        scored: list[RecoveryCandidate] = []
        for candidate in raw_candidates:
            if candidate.tool == action.tool:
                continue
            tool = tool_registry.get(candidate.tool)
            if tool is None:
                continue
            args = dict(action.args or {})
            try:
                if tool.validate_args(args):
                    continue
            except Exception:
                continue
            item = evidence.get((candidate.specialist, candidate.tool))
            if not item or item.verified_successes <= 0:
                # No verified organizational success = no automatic redelegation.
                continue
            empirical = item.verified_successes / max(1, item.attempts)
            evidence_bonus = min(0.45, 0.15 * min(item.verified_successes, 3))
            score = float(candidate.fit) + evidence_bonus + 0.30 * empirical - 0.03 * max(0.0, candidate.cost)
            reason = (
                'same capability, independently qualified ownership, compatible arguments, and verified organizational success history'
            )
            scored.append(RecoveryCandidate(
                tool=candidate.tool, capability=candidate.capability, department=candidate.department,
                specialist=candidate.specialist, skill_key=candidate.skill_key, score=score,
                verified_successes=item.verified_successes, attempts=item.attempts, reason=reason,
            ))
        # C18: capacity-aware secondary ordering among already-qualified recovery candidates.
        try:
            from .routing import AdaptiveDelegationController
            controller = AdaptiveDelegationController(organization, learning_store)
            route_rank = {
                item.candidate.tool: item.routing_score
                for item in controller.rank([
                    CapabilityCandidate(
                        requirement_key=action.step_id, tool=item.tool, skill_key=item.skill_key,
                        capability=item.capability, department=item.department, specialist=item.specialist,
                        fit=0.0, cost=0.0, risk='low', verification_level='standard', reason='',
                    ) for item in scored
                ])
            }
        except Exception:
            route_rank = {}
        scored.sort(key=lambda x: (-x.score, -route_rank.get(x.tool, 0.0), -x.verified_successes, x.attempts, x.tool))
        if not scored:
            return DelegationRecoveryDecision(
                step_id=action.step_id, failed_tool=action.tool, failure_class=failure_class,
                decision='escalate', reason='no alternative qualified specialist has verified success evidence for the same capability',
            )
        selected = scored[0]
        confidence = max(0.0, min(1.0, 0.55 + 0.10 * min(selected.verified_successes, 3) + 0.25 * (selected.verified_successes / max(1, selected.attempts))))
        return DelegationRecoveryDecision(
            step_id=action.step_id, failed_tool=action.tool, failure_class=failure_class,
            decision='redelegate', selected=selected, candidates=tuple(scored[:5]), confidence=confidence,
            reason='re-delegation selected from verified same-capability organizational evidence',
        )

    @staticmethod
    def redelegate_action(action: PlannedAction, decision: DelegationRecoveryDecision, tool_registry: dict[str, Any]) -> PlannedAction | None:
        if decision.decision != 'redelegate' or decision.selected is None:
            return None
        candidate = decision.selected
        tool = tool_registry.get(candidate.tool)
        if tool is None:
            return None
        args = dict(action.args or {})
        if tool.validate_args(args):
            return None
        return PlannedAction(
            action.step_id, action.capability, candidate.tool, args,
            depends_on=tuple(action.depends_on or ()),
            skill_key=candidate.skill_key or action.skill_key,
            expected_effects=tuple(action.expected_effects or ()), rationale=(
                f'company-redelegated from {action.tool} after verified failure; {decision.reason}'
            ),
        )
