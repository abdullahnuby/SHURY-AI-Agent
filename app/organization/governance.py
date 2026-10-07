"""Deterministic runtime governance for SHURY Company actions.

Governance is separate from planning: a plan proposes an action, while this module
makes the final machine-checkable decision about whether the action may execute.
No model or natural-language rule is involved.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import uuid
from typing import Any

from .models import AgentRole, CompanyAssignment, GovernanceApproval, GovernanceDecision


@dataclass(frozen=True)
class GovernanceContext:
    """Minimal immutable context required to decide an action."""
    task_id: str
    department: str
    specialist: str
    skill_key: str
    capability: str


class CompanyGovernance:
    """Fail-closed governance engine for a single Company action."""

    def __init__(self, company):
        self.company = company

    @staticmethod
    def action_fingerprint(*, task_id: str, tool: Any, args: dict[str, Any]) -> str:
        payload = {
            'task_id': str(task_id),
            'tool': str(getattr(tool, 'name', '') or ''),
            'args': args if isinstance(args, dict) else {},
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def action_class(tool: Any) -> str:
        explicit = str(getattr(tool, 'governance_class', '') or '').strip().casefold()
        if explicit:
            return explicit
        if getattr(tool, 'risk', 'low') in {'critical', 'high'} or bool(getattr(tool, 'removes', ())):
            return 'destructive'
        if bool(getattr(tool, 'requires_approval', False)):
            return 'controlled-side-effect'
        if bool(getattr(tool, 'produces', ())):
            return 'state-producing'
        return 'read-only'

    def _role(self, key: str) -> AgentRole | None:
        try:
            return self.company.role(key)
        except Exception:
            return None

    def evaluate(self, assignment: CompanyAssignment | dict[str, Any], tool: Any,
                 context: GovernanceContext, args: dict[str, Any] | None = None) -> GovernanceDecision:
        data = assignment.to_dict() if hasattr(assignment, 'to_dict') else dict(assignment)
        reasons: list[str] = []
        reviewers = tuple(str(x) for x in (data.get('reviewers') or ()) if str(x))
        risk = str(getattr(tool, 'risk', 'low') or 'low').casefold()
        if risk not in {'low', 'medium', 'high', 'critical'}:
            risk = 'high'
            reasons.append('unknown_risk_class_is_fail_closed')

        action_class = self.action_class(tool)
        specialist_key = str(data.get('specialist') or '')
        department = str(data.get('department') or '')
        chief = str(data.get('chief_executive') or '')

        if chief != self.company.ceo.key:
            reasons.append('assignment_not_issued_by_ceo')
        if department != context.department:
            reasons.append('assignment_department_mismatch')
        if specialist_key != context.specialist:
            reasons.append('assignment_specialist_mismatch')
        if context.skill_key and str(data.get('skill_key') or '') != context.skill_key:
            reasons.append('assignment_skill_mismatch')
        if context.capability and str(data.get('capability') or '') != context.capability:
            reasons.append('assignment_capability_mismatch')

        specialist = self._role(specialist_key)
        if specialist is None:
            reasons.append('specialist_not_in_company_registry')
        elif specialist.agent_class == 'reviewer':
            reasons.append('reviewer_cannot_execute_producer_action')
        if specialist_key and specialist_key in reviewers:
            reasons.append('producer_cannot_review_own_action')

        for reviewer_key in reviewers:
            reviewer = self._role(reviewer_key)
            if reviewer is None:
                reasons.append(f'reviewer_not_in_company_registry:{reviewer_key}')
            elif reviewer.agent_class != 'reviewer':
                reasons.append(f'reviewer_role_not_independent:{reviewer_key}')

        if risk in {'medium', 'high', 'critical'}:
            if 'security:reviewer' not in reviewers:
                reasons.append('controlled_action_requires_independent_security_reviewer')
            if risk in {'high', 'critical'} and not bool(getattr(tool, 'requires_approval', False)):
                reasons.append('high_impact_tool_must_require_human_approval')

        authority = str(data.get('authority') or 'autonomous').casefold()
        controlled_classes = {'destructive', 'external-publication', 'privileged', 'financial'}
        if action_class in {'destructive', 'privileged'} and 'security:reviewer' not in reviewers:
            reasons.append('controlled_action_class_requires_security_reviewer')
        human_approval_required = (
            bool(getattr(tool, 'requires_approval', False))
            or authority in {'proposes', 'escalates'}
            or risk in {'high', 'critical'}
            or action_class in controlled_classes
        )
        if authority == 'escalates':
            reasons.append('assignment_authority_is_escalation_only')
        elif authority == 'proposes':
            reasons.append('assignment_authority_requires_orchestrator_approval')

        fatal_reasons = {
            'assignment_not_issued_by_ceo', 'assignment_department_mismatch',
            'assignment_specialist_mismatch', 'assignment_skill_mismatch',
            'assignment_capability_mismatch', 'specialist_not_in_company_registry',
            'reviewer_cannot_execute_producer_action', 'producer_cannot_review_own_action',
            'controlled_action_requires_independent_security_reviewer',
            'controlled_action_class_requires_security_reviewer',
            'high_impact_tool_must_require_human_approval',
            'unknown_risk_class_is_fail_closed',
        }
        fatal_prefixes = ('reviewer_not_in_company_registry:', 'reviewer_role_not_independent:')
        has_fatal = any(reason in fatal_reasons or reason.startswith(fatal_prefixes) for reason in reasons)
        if reasons and has_fatal:
            return GovernanceDecision(False, 'deny', risk, action_class, tuple(dict.fromkeys(reasons)), reviewers, human_approval_required)

        approval = None
        if human_approval_required:
            approval = GovernanceApproval(
                request_id=uuid.uuid4().hex,
                action_fingerprint=self.action_fingerprint(task_id=context.task_id, tool=tool, args=dict(args or {})),
                risk=risk,
                reason='; '.join(reasons) if reasons else 'tool_or_authority_requires_explicit_approval',
                reviewers=reviewers,
            )
            return GovernanceDecision(True, 'approval_required', risk, action_class,
                                     tuple(dict.fromkeys(reasons)), reviewers, True, approval)

        return GovernanceDecision(True, 'allow', risk, action_class, tuple(dict.fromkeys(reasons)), reviewers, False)
