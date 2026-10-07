from __future__ import annotations

"""Governed company-level self-improvement.

Layer 5 already learns candidate Skills and can evaluate/rollback them. This module adds the
organizational control plane: no Company-visible change is applied from learning evidence alone.
Changes become durable proposals, require regression evidence and an independent security review,
and only then may the CEO approve activation/deprecation. Organizational topology changes are
staged as proposals and are never mutated automatically.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from pathlib import Path

from app.learning.manager import SelfImprovementManager
from app.learning.promotion import promotion_gate
from app.learning.store import LearningStore
from app.skills.registry import SkillBank

from .company import DEFAULT_COMPANY
from .company_memory import CompanyMemory
from .governance import CompanyGovernance


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _fingerprint(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class OrganizationChangeProposal:
    proposal_id: str
    company_id: str
    change_kind: str
    target_key: str
    payload: dict[str, Any]
    evidence: tuple[dict[str, Any], ...]
    regression: dict[str, Any]
    security_review: dict[str, Any]
    executive_approval: dict[str, Any]
    status: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"] = [dict(x) for x in self.evidence]
        return data


class CompanySelfImprovementError(ValueError):
    pass


class CompanySelfImprovementManager:
    """Company governance over the existing Layer-5 learning lifecycle."""

    def __init__(self, *, company=DEFAULT_COMPANY, learning_store: LearningStore | None = None,
                 skill_bank: SkillBank | None = None, learning_manager: SelfImprovementManager | None = None,
                 company_id: str = "shury-company"):
        self.company = company
        self.learning = learning_store or LearningStore()
        self.skills = skill_bank or SkillBank()
        self.learning_manager = learning_manager or SelfImprovementManager(store=self.learning, bank_path=self.skills.path)
        self.company_id = company_id
        self.governance = CompanyGovernance(company)

    @staticmethod
    def _proposal(row: dict) -> OrganizationChangeProposal:
        return OrganizationChangeProposal(
            proposal_id=row["proposal_id"], company_id=row["company_id"], change_kind=row["change_kind"],
            target_key=row["target_key"], payload=dict(row.get("payload") or {}),
            evidence=tuple(row.get("evidence") or ()), regression=dict(row.get("regression") or {}),
            security_review=dict(row.get("security_review") or {}),
            executive_approval=dict(row.get("executive_approval") or {}), status=row["status"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def get(self, proposal_id: str) -> OrganizationChangeProposal | None:
        row = self.learning.get_company_change_proposal(proposal_id)
        return self._proposal(row) if row else None

    def list(self, *, status: str | None = None, limit: int = 100) -> tuple[OrganizationChangeProposal, ...]:
        return tuple(self._proposal(row) for row in self.learning.list_company_change_proposals(self.company_id, limit=limit, status=status))

    def _new_id(self, kind: str, target_key: str, payload: dict[str, Any]) -> str:
        seed = f"{self.company_id}:{kind}:{target_key}:{_fingerprint(payload)}"
        return "chg:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]

    def _validate_producer(self, producer: str) -> str:
        producer = str(producer or '').strip()
        if not producer:
            raise PermissionError("producer role is required")
        try:
            role = self.company.role(producer)
        except KeyError as exc:
            raise PermissionError(f"unknown producer role: {producer}") from exc
        if role.agent_class == "reviewer":
            raise PermissionError("reviewer cannot be the change producer")
        return producer

    def _record_rejection(self, proposal: OrganizationChangeProposal, *, action: str, actor: str, reason: str) -> None:
        self.learning.record_event(
            proposal.proposal_id, action, reason,
            {"proposal_id": proposal.proposal_id, "actor": actor, "producer": proposal.payload.get("producer", ""), "reason": reason},
        )

    def propose_skill_acquisition(self, *, key: str, name: str, producer: str, triggers=(), workflow=(),
                                  source: str = "self-improvement", source_run_id: str | None = None,
                                  evidence: list[dict[str, Any]] | None = None, verification=(), outputs=(),
                                  confidence: float = 0.5) -> OrganizationChangeProposal:
        producer = self._validate_producer(producer)
        if any(x.key == key for x in self.skills.list()):
            raise CompanySelfImprovementError(f"skill already exists: {key}")
        spec = {
            "key": str(key), "name": str(name), "triggers": list(triggers), "workflow": list(workflow),
            "source": str(source), "source_run_id": source_run_id, "verification": list(verification),
            "outputs": list(outputs), "confidence": max(0.0, min(1.0, float(confidence))),
        }
        candidate = self.skills.upsert(**spec, status="candidate")
        # A proposal can never self-assign trust. Acquisition always enters quarantine.
        self.skills.set_trust(candidate.key, "quarantined")
        payload = {"skill": candidate.__dict__, "producer": producer}
        row = self.learning.create_company_change_proposal(
            proposal_id=self._new_id("skill_acquisition", candidate.key, payload), company_id=self.company_id,
            change_kind="skill_acquisition", target_key=candidate.key, payload=payload,
            evidence=list(evidence or []), regression={"status": "not_run"},
        )
        return self._proposal(row)

    def propose_skill_promotion(self, key: str, *, producer: str) -> OrganizationChangeProposal:
        producer = self._validate_producer(producer)
        skill = self.skills.get(key)
        if skill.status not in {"candidate", "approved"}:
            raise CompanySelfImprovementError(f"skill is not a promotion candidate: {key}:{skill.status}")
        evidence = [dict(x) for x in skill.evidence]
        from app.runtime.registry import load_tools
        eval_result = self.learning_manager.evaluate_candidate(key, registry=load_tools(), memory=self.learning, limit=20)
        regression = {
            "status": "not_run",
            "promotion_gate": dict(eval_result.get("gate") or {}),
            "evaluations": list(eval_result.get("evaluations") or []),
        }
        row = self.learning.create_company_change_proposal(
            proposal_id=self._new_id("skill_promotion", key, regression), company_id=self.company_id,
            change_kind="skill_promotion", target_key=key,
            payload={"before_status": skill.status, "before_version": skill.version, "producer": producer},
            evidence=evidence, regression=regression,
        )
        return self._proposal(row)

    def propose_skill_deprecation(self, key: str, *, producer: str) -> OrganizationChangeProposal:
        producer = self._validate_producer(producer)
        skill = self.skills.get(key)
        if skill.status != "active":
            raise CompanySelfImprovementError(f"skill is not active: {key}:{skill.status}")
        recommendation = self.skills.adaptive_evidence(key)
        row = self.learning.create_company_change_proposal(
            proposal_id=self._new_id("skill_deprecation", key, recommendation), company_id=self.company_id,
            change_kind="skill_deprecation", target_key=key,
            payload={"before_status": skill.status, "before_version": skill.version, "producer": producer},
            evidence=list(skill.evidence), regression={"status": "not_run", "lifecycle": recommendation},
        )
        return self._proposal(row)

    def propose_organization_change(self, *, change_kind: str, target_key: str, payload: dict[str, Any],
                                    evidence: list[dict[str, Any]], producer: str) -> OrganizationChangeProposal:
        producer = self._validate_producer(producer)
        if change_kind not in {"role_change", "department_change", "capability_change"}:
            raise CompanySelfImprovementError("unsupported organization change kind")
        if not evidence:
            raise CompanySelfImprovementError("organization changes require evidence")
        row = self.learning.create_company_change_proposal(
            proposal_id=self._new_id(change_kind, target_key, payload), company_id=self.company_id,
            change_kind=change_kind, target_key=target_key, payload={**dict(payload), "producer": producer}, evidence=list(evidence),
            regression={"status": "not_run"},
        )
        return self._proposal(row)

    def _skill_snapshot(self, key: str) -> dict[str, Any]:
        skill = self.skills.get(key)
        return {"status": skill.status, "trust": self.skills.trust(key), "success_count": skill.success_count, "failure_count": skill.failure_count, "version": skill.version}

    @staticmethod
    def _rate(snapshot: dict[str, Any]) -> float:
        total = int(snapshot.get("success_count", 0)) + int(snapshot.get("failure_count", 0))
        return float(snapshot.get("success_count", 0)) / max(1, total)

    @staticmethod
    def _verification_signatures(cases: tuple | list) -> tuple[str, ...]:
        signatures: list[str] = []
        for case in cases or ():
            if not isinstance(case, dict):
                continue
            raw = json.dumps(case, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
            signatures.append(hashlib.sha256(raw).hexdigest())
        return tuple(dict.fromkeys(signatures))

    def _skill_capabilities(self, key: str) -> tuple[str, ...]:
        skill = self.skills.get(key)
        capabilities = []
        for step in skill.workflow:
            if isinstance(step, dict):
                capability = str(step.get("capability") or "").strip()
                if capability:
                    capabilities.append(capability)
        return tuple(dict.fromkeys(capabilities))

    def _capability_reliability(self, capabilities: tuple[str, ...]) -> dict[str, Any]:
        wanted = {str(x).strip() for x in capabilities if str(x).strip()}
        rows = self.learning.company_delegation_evidence(limit=5000)
        rows = [row for row in rows if row.get("capability") in wanted] if wanted else []
        attempts = sum(int(row.get("attempts") or 0) for row in rows)
        successes = sum(int(row.get("verified_successes") or 0) for row in rows)
        failures = sum(int(row.get("verified_failures") or 0) for row in rows)
        return {
            "capabilities": sorted(wanted), "attempts": attempts, "verified_successes": successes,
            "verified_failures": failures, "verified_success_rate": successes / max(1, attempts),
        }

    def _organization_reliability(self) -> dict[str, Any]:
        rows = self.learning.company_delegation_evidence(limit=5000)
        attempts = sum(int(row.get("attempts") or 0) for row in rows)
        successes = sum(int(row.get("verified_successes") or 0) for row in rows)
        failures = sum(int(row.get("verified_failures") or 0) for row in rows)
        specialists = sorted({str(row.get("specialist") or "") for row in rows if str(row.get("specialist") or "")})
        return {
            "attempts": attempts, "verified_successes": successes, "verified_failures": failures,
            "verified_success_rate": successes / max(1, attempts), "specialist_count": len(specialists),
        }

    def _monitor_outcomes(self, proposal_id: str) -> list[dict[str, Any]]:
        return [
            event for event in self.learning.recent_evolution_events(limit=1000, candidate_key=proposal_id)
            if event.get("action") == "company_post_change_outcome"
        ]

    def record_post_change_outcome(self, proposal_id: str, *, capability: str, department: str, specialist: str,
                                   tool: str, success: bool, verified: bool, run_id: str, task_signature: str,
                                   duration: float = 0.0, failure_class: str = "",
                                   evidence: tuple[str, ...] | list[str] = ()) -> dict[str, Any]:
        """Record one verified post-change runtime outcome in canonical company evidence paths."""
        proposal = self.get(proposal_id)
        if proposal is None:
            raise KeyError(proposal_id)
        if proposal.status != "monitoring":
            raise PermissionError("post-change outcome requires monitoring state")
        if not str(run_id or "").strip() or not str(task_signature or "").strip():
            raise PermissionError("run_id and task_signature are required")
        try:
            role = self.company.role(str(specialist))
        except KeyError as exc:
            raise PermissionError("specialist is not in the Company registry") from exc
        if role.agent_class == "reviewer" or role.department != str(department):
            raise PermissionError("post-change outcome specialist/department assignment is invalid")
        from app.runtime.registry import load_tools
        registry_tool = load_tools().get(str(tool))
        if registry_tool is None:
            raise PermissionError("post-change outcome tool is not registered")
        declared_capability = str(getattr(registry_tool, "capability", "") or "").strip()
        if declared_capability and declared_capability != str(capability):
            raise PermissionError("post-change outcome capability does not match the registered tool")
        verification_signatures = set(proposal.regression.get("change_specific", {}).get("verification_signatures") or ())
        raw_signature = str(task_signature).strip()
        unseen = raw_signature not in verification_signatures
        if not unseen:
            raise PermissionError("post-change outcome is part of the verification set, not an unseen-task outcome")
        evidence_list = [str(x) for x in evidence if str(x).strip()]
        if bool(verified) and not evidence_list:
            raise PermissionError("verified post-change outcomes require evidence references")
        reliability = self.learning.record_company_delegation_outcome(
            capability=str(capability), department=str(department), specialist=str(specialist),
            skill_key=proposal.target_key, tool=str(tool), verified=bool(success),
            duration=float(duration or 0.0), run_id=str(run_id), failure_class=str(failure_class or ""),
        )
        memory_id = None
        if bool(verified):
            memory_id = CompanyMemory(company_id=self.company_id).remember_outcome(
                run_id=str(run_id), status="success" if bool(success) else "failure",
                summary={"proposal_id": proposal_id, "change_kind": proposal.change_kind,
                         "target_key": proposal.target_key, "capability": str(capability),
                         "department": str(department), "specialist": str(specialist), "tool": str(tool),
                         "task_signature": raw_signature, "unseen": True, "failure_class": str(failure_class or ""),
                         "evidence": evidence_list},
                verified=True, confidence=1.0,
            )
        payload = {
            "proposal_id": proposal_id, "change_kind": proposal.change_kind, "target_key": proposal.target_key,
            "capability": str(capability), "department": str(department), "specialist": str(specialist),
            "tool": str(tool), "success": bool(success), "verified": bool(verified), "run_id": str(run_id),
            "task_signature": raw_signature, "unseen": True, "duration": float(duration or 0.0),
            "failure_class": str(failure_class or ""), "evidence": evidence_list,
            "reliability": reliability, "company_memory_id": memory_id,
        }
        self.learning.record_event(proposal_id, "company_post_change_outcome", "verified post-change outcome recorded", payload)
        return payload

    def _open_monitor_rollback_proposal(self, proposal: OrganizationChangeProposal, verdict: dict[str, Any]) -> str | None:
        if proposal.change_kind not in {"skill_acquisition", "skill_promotion"} or not proposal.target_key:
            return None
        for row in self.learning.list_company_change_proposals(self.company_id, limit=1000):
            payload = row.get("payload") or {}
            if row.get("change_kind") == "skill_rollback" and payload.get("source_proposal_id") == proposal.proposal_id and row.get("status") not in {"rejected", "applied"}:
                return str(row.get("proposal_id"))
        producer = str(proposal.payload.get("producer") or "").strip()
        if not producer:
            # A rollback proposal without an accountable producer cannot pass the C15 governance contract.
            return None
        rollback_payload = {
            "producer": producer, "source_proposal_id": proposal.proposal_id,
            "reason": "C16 monitoring detected a post-change regression or failed generalization gate",
            "monitoring": verdict,
        }
        rollback_id = self._new_id("skill_rollback", proposal.target_key, rollback_payload)
        row = self.learning.create_company_change_proposal(
            proposal_id=rollback_id, company_id=self.company_id, change_kind="skill_rollback",
            target_key=proposal.target_key, payload=rollback_payload, evidence=[
                {"kind": "c16-monitoring", "source_proposal_id": proposal.proposal_id, "verified": True}
            ], regression={"status": "passed", "auto_opened": True, "source_proposal_id": proposal.proposal_id},
        )
        self.learning.record_event(
            rollback_id, "company_rollback_proposal_opened", "C16 monitoring opened a governed rollback proposal",
            {"source_proposal_id": proposal.proposal_id, "target_key": proposal.target_key, "monitoring": verdict},
        )
        return str(row["proposal_id"])

    def _isolated_company_eval(self, *, skill_key: str | None = None, activate: bool = False) -> dict[str, Any]:
        from app.evaluation.company import CompanyEvaluationSuite
        import os, shutil, tempfile
        with tempfile.TemporaryDirectory(prefix="shury-company-regression-") as td:
            root = Path(td)
            isolated_skills = root / "skills.db"
            shutil.copy2(self.skills.path, isolated_skills)
            if skill_key and activate:
                bank = SkillBank(isolated_skills, bootstrap=False)
                bank.set_trust(skill_key, "local")
                bank.set_status(skill_key, "active")
            old_skills = os.environ.get("AGENT_SKILLS_DB")
            old_learning = os.environ.get("AGENT_LEARNING_DB")
            os.environ["AGENT_SKILLS_DB"] = str(isolated_skills)
            os.environ["AGENT_LEARNING_DB"] = str(root / "learning.db")
            try:
                return CompanyEvaluationSuite().evaluate().to_dict()
            finally:
                if old_skills is None: os.environ.pop("AGENT_SKILLS_DB", None)
                else: os.environ["AGENT_SKILLS_DB"] = old_skills
                if old_learning is None: os.environ.pop("AGENT_LEARNING_DB", None)
                else: os.environ["AGENT_LEARNING_DB"] = old_learning

    def _run_skill_verification_cases(self, skill_key: str) -> dict[str, Any]:
        from app.runtime.registry import load_tools
        skill = self.skills.get(skill_key)
        cases = [c for c in skill.verification if isinstance(c, dict) and (c.get("tool") or c.get("workflow"))]
        if not cases:
            return {"passed": False, "case_count": 0, "passed_count": 0, "cases": [], "error": "no executable verification cases"}
        tools = load_tools()
        results = []
        for index, case in enumerate(cases, 1):
            workflow = case.get("workflow") or ((case,) if case.get("tool") else ())
            if not workflow:
                results.append({"case": index, "passed": False, "error": "empty verification case"})
                continue
            previous = {}
            case_ok = True
            errors = []
            for step in workflow:
                if not isinstance(step, dict):
                    case_ok = False; errors.append("invalid verification step"); continue
                tool_name = str(step.get("tool") or "")
                tool = tools.get(tool_name)
                if tool is None:
                    case_ok = False; errors.append(f"unknown tool: {tool_name}"); continue
                args = dict(step.get("args") or {})
                for key, value in list(args.items()):
                    if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
                        args[key] = previous.get(value[2:-2])
                result = tool.run(**args)
                previous[str(step.get("id") or tool_name)] = result.data
                if not result.ok:
                    case_ok = False; errors.append(result.error or "tool failed")
                expected = step.get("expect", case.get("expect"))
                if expected is not None and result.data != expected:
                    case_ok = False; errors.append("verification expectation mismatch")
            results.append({"case": index, "passed": case_ok, "errors": errors})
        return {"passed": all(x["passed"] for x in results), "case_count": len(results), "passed_count": sum(1 for x in results if x["passed"]), "cases": results}

    def run_regression_gate(self, proposal_id: str) -> dict[str, Any]:
        proposal = self.get(proposal_id)
        if proposal is None:
            raise KeyError(proposal_id)
        from app.evaluation.company import company_release_gate
        from app.evaluation.self_improvement_benchmark import run_self_improvement_benchmark
        company_before = self._isolated_company_eval()
        company_after = company_before
        change_specific = {"passed": True}
        if proposal.change_kind == "skill_acquisition":
            change_specific = self._run_skill_verification_cases(proposal.target_key)
            change_specific["verification_signatures"] = list(self._verification_signatures(self.skills.get(proposal.target_key).verification))
            company_after = self._isolated_company_eval(skill_key=proposal.target_key, activate=True) if change_specific.get("passed") else {"case_count": 0, "pass_count": 0, "pass_rate": 0.0}
            change_specific["company_before_pass_rate"] = company_before.get("pass_rate", 0.0)
            change_specific["company_after_pass_rate"] = company_after.get("pass_rate", 0.0)
            change_specific["company_non_regression"] = company_after.get("pass_count", 0) >= company_before.get("pass_count", 0)
        elif proposal.change_kind in {"skill_promotion", "skill_deprecation"}:
            change_specific["verification_signatures"] = list(self._verification_signatures(self.skills.get(proposal.target_key).verification))
            company_after = self._isolated_company_eval(skill_key=proposal.target_key, activate=(proposal.change_kind == "skill_promotion"))
        company_gate = company_release_gate(company_after)
        self_improvement_report = run_self_improvement_benchmark()
        skill_gate = dict(proposal.regression.get("promotion_gate") or {})
        required_skill_ok = bool(change_specific.get("passed", True))
        if proposal.change_kind == "skill_promotion":
            required_skill_ok = required_skill_ok and bool(skill_gate.get("promotable"))
        elif proposal.change_kind == "skill_deprecation":
            lifecycle = dict(proposal.regression.get("lifecycle") or {})
            required_skill_ok = required_skill_ok and lifecycle.get("recommendation") == "demote"
        regression = {
            "status": "passed" if company_gate.get("release_allowed") and self_improvement_report.get("green") and required_skill_ok and change_specific.get("company_non_regression", True) else "failed",
            "company_gate": company_gate, "company_evaluation_before": company_before, "company_evaluation_after": company_after,
            "self_improvement_benchmark": self_improvement_report, "change_specific": change_specific,
            "checked_at": _now(),
        }
        status = "evaluated" if regression["status"] == "passed" else "blocked"
        row = self.learning.update_company_change_proposal(proposal_id, status=status, regression=regression)
        return row["regression"] if row else regression

    def security_review(self, proposal_id: str, *, reviewer: str, approved: bool, reason: str = "") -> OrganizationChangeProposal:
        proposal = self.get(proposal_id)
        if proposal is None:
            raise KeyError(proposal_id)
        try:
            role = self.company.role(reviewer)
        except KeyError as exc:
            self._record_rejection(proposal, action="company_change_review_rejected", actor=reviewer, reason="unknown reviewer role")
            raise PermissionError("unknown reviewer role") from exc
        if role.agent_class != "reviewer":
            self._record_rejection(proposal, action="company_change_review_rejected", actor=reviewer, reason="reviewer must be reviewer-class")
            raise PermissionError("company change reviewer must be reviewer-class")
        producer = str(proposal.payload.get("producer") or "")
        if reviewer == producer:
            self._record_rejection(proposal, action="company_change_review_rejected", actor=reviewer, reason="producer cannot review")
            raise PermissionError("producer cannot review organizational change")
        if not str(reason or "").strip():
            self._record_rejection(proposal, action="company_change_review_rejected", actor=reviewer, reason="review reason is required")
            raise PermissionError("security review reason is required")
        review = {"reviewer": reviewer, "approved": bool(approved), "reason": str(reason), "reviewed_at": _now()}
        status = "reviewed" if approved else "rejected"
        row = self.learning.update_company_change_proposal(proposal_id, status=status, security_review=review)
        return self._proposal(row)  # type: ignore[arg-type]

    def grant_skill_trust(self, proposal_id: str, *, reviewer: str, trust_level: str, reason: str) -> OrganizationChangeProposal:
        proposal = self.get(proposal_id)
        if proposal is None:
            raise KeyError(proposal_id)
        if proposal.change_kind != "skill_acquisition":
            raise PermissionError("trust grant applies only to skill acquisition")
        if trust_level not in {"local", "trusted"}:
            raise PermissionError("trust grant must be local or trusted")
        if not str(reason or "").strip():
            raise PermissionError("trust grant reason is required")
        try:
            role = self.company.role(reviewer)
        except KeyError as exc:
            raise PermissionError("unknown reviewer role") from exc
        if role.agent_class != "reviewer":
            raise PermissionError("trust grant requires reviewer-class actor")
        if reviewer == proposal.payload.get("producer"):
            self._record_rejection(proposal, action="company_skill_trust_rejected", actor=reviewer, reason="producer cannot grant trust")
            raise PermissionError("producer cannot grant trust")
        self.skills.set_trust(proposal.target_key, trust_level)
        self.learning.record_event(proposal.proposal_id, "company_skill_trust_granted", "independent reviewer granted Skill trust", {"reviewer": reviewer, "trust_level": trust_level, "reason": reason, "producer": proposal.payload.get("producer")})
        return proposal

    def approve(self, proposal_id: str, *, approver: str = "executive:chief-executive") -> OrganizationChangeProposal:
        proposal = self.get(proposal_id)
        if proposal is None:
            raise KeyError(proposal_id)
        if approver != self.company.ceo.key:
            self._record_rejection(proposal, action="company_change_approval_rejected", actor=approver, reason="only Company CEO may approve")
            raise PermissionError("only the Company CEO may approve organization changes")
        if approver == proposal.payload.get("producer"):
            self._record_rejection(proposal, action="company_change_approval_rejected", actor=approver, reason="producer cannot approve")
            raise PermissionError("producer cannot approve organizational change")
        if proposal.regression.get("status") != "passed":
            self._record_rejection(proposal, action="company_change_approval_rejected", actor=approver, reason="regression gate is not passing")
            raise PermissionError("organization change requires a passing regression gate")
        if proposal.security_review.get("approved") is not True:
            self._record_rejection(proposal, action="company_change_approval_rejected", actor=approver, reason="independent security review is required")
            raise PermissionError("independent security review is required")
        fingerprint = _fingerprint({"proposal_id": proposal.proposal_id, "kind": proposal.change_kind, "target": proposal.target_key, "payload": proposal.payload})
        approval = {"approver": approver, "approved": True, "approved_at": _now(), "fingerprint": fingerprint}
        row = self.learning.update_company_change_proposal(proposal_id, status="approved", executive_approval=approval)
        return self._proposal(row)  # type: ignore[arg-type]

    def apply(self, proposal_id: str) -> OrganizationChangeProposal:
        proposal = self.get(proposal_id)
        if proposal is None:
            raise KeyError(proposal_id)
        if proposal.status != "approved":
            raise PermissionError("proposal is not approved")
        expected = str(proposal.executive_approval.get("fingerprint") or "")
        actual = _fingerprint({"proposal_id": proposal.proposal_id, "kind": proposal.change_kind, "target": proposal.target_key, "payload": proposal.payload})
        if not expected or expected != actual:
            self._record_rejection(proposal, action="company_change_apply_rejected", actor="runtime", reason="approved payload fingerprint mismatch")
            raise PermissionError("approved proposal payload fingerprint mismatch")
        if proposal.change_kind == "skill_acquisition":
            events = self.learning.recent_evolution_events(limit=200, candidate_key=proposal.proposal_id)
            trusted = any(e.get("action") == "company_skill_trust_granted" and e.get("payload", {}).get("trust_level") in {"local", "trusted"} for e in events)
            if not trusted:
                raise PermissionError("acquired skill was not trusted through independent governance")
        elif proposal.change_kind not in {"skill_promotion", "skill_deprecation"}:
            if proposal.change_kind in {"role_change", "department_change", "capability_change"}:
                raise PermissionError("organization topology changes are staged proposals; apply through the catalog change process")
            raise PermissionError(f"unsupported organization change kind: {proposal.change_kind}")
        # Capture the baseline before the governed mutation. The baseline must represent
        # the exact pre-apply state so monitoring can detect regressions caused by the change.
        baseline = {
            "company_evaluation": self._isolated_company_eval(),
            "skill": self._skill_snapshot(proposal.target_key),
            "capability_reliability": self._capability_reliability(self._skill_capabilities(proposal.target_key)),
            "organization_reliability": self._organization_reliability(),
            "verification_signatures": list(proposal.regression.get("change_specific", {}).get("verification_signatures") or self._verification_signatures(self.skills.get(proposal.target_key).verification)),
        }
        if proposal.change_kind == "skill_acquisition":
            self.skills.set_status(proposal.target_key, "approved")
            self.skills.set_status(proposal.target_key, "active")
        elif proposal.change_kind == "skill_promotion":
            self.skills.set_status(proposal.target_key, "approved")
            self.skills.set_status(proposal.target_key, "active")
        elif proposal.change_kind == "skill_deprecation":
            self.skills.set_status(proposal.target_key, "deprecated")
        regression = dict(proposal.regression)
        regression["baseline_at_apply"] = baseline
        regression["monitoring_started_at"] = _now()
        self.learning.record_event(proposal.proposal_id, "company_change_applied", "governed organizational change applied", {"kind": proposal.change_kind, "target": proposal.target_key})
        row = self.learning.update_company_change_proposal(proposal_id, status="monitoring", regression=regression)
        return self._proposal(row)  # type: ignore[arg-type]

    def monitor_change(self, proposal_id: str) -> dict[str, Any]:
        proposal = self.get(proposal_id)
        if proposal is None:
            raise KeyError(proposal_id)
        if proposal.status != "monitoring":
            raise PermissionError("proposal is not in monitoring state")
        baseline = dict(proposal.regression.get("baseline_at_apply") or {})
        if not baseline:
            raise PermissionError("monitoring baseline is missing")
        after_company = self._isolated_company_eval()
        after_skill = self._skill_snapshot(proposal.target_key)
        after_capability = self._capability_reliability(tuple((baseline.get("capability_reliability") or {}).get("capabilities") or self._skill_capabilities(proposal.target_key)))
        after_organization = self._organization_reliability()
        before_company = baseline.get("company_evaluation") or {}
        before_skill = baseline.get("skill") or {}
        before_capability = baseline.get("capability_reliability") or {}
        before_organization = baseline.get("organization_reliability") or {}
        outcomes = self._monitor_outcomes(proposal_id)
        unseen = [dict(event.get("payload") or {}) for event in outcomes if bool((event.get("payload") or {}).get("unseen"))]
        unseen_verified = [x for x in unseen if bool(x.get("verified"))]
        unseen_successes = sum(1 for x in unseen_verified if bool(x.get("success")))
        unseen_attempts = len(unseen_verified)
        unseen_rate = unseen_successes / max(1, unseen_attempts)
        baseline_cap_attempts = int(before_capability.get("attempts") or 0)
        baseline_cap_rate = float(before_capability.get("verified_success_rate") or 0.0)
        generalization_improved = bool(unseen_attempts) and (
            unseen_rate > baseline_cap_rate if baseline_cap_attempts > 0 else unseen_successes > 0
        )
        skill_before_rate = self._rate(before_skill)
        skill_after_rate = self._rate(after_skill)
        single_change_non_regression = skill_after_rate >= skill_before_rate
        company_non_regression = int(after_company.get("pass_count", 0)) >= int(before_company.get("pass_count", 0))
        organization_non_regression = float(after_organization.get("verified_success_rate", 0.0)) >= float(before_organization.get("verified_success_rate", 0.0))
        governance_limits = {
            "company_release": after_company.get("pass_rate", 0.0) >= 1.0 and int(after_company.get("safety_violations", 0)) == 0,
            "company_non_regression": company_non_regression,
            "organization_non_regression": organization_non_regression,
            "single_change_non_regression": single_change_non_regression,
        }
        keep = bool(generalization_improved and all(governance_limits.values()))
        verdict: dict[str, Any] = {
            "status": "keep" if keep else "recommend_rollback", "proposal_id": proposal_id,
            "generalization": {
                "unseen_attempts": unseen_attempts, "unseen_verified_successes": unseen_successes,
                "unseen_success_rate": unseen_rate, "baseline_capability": before_capability,
                "improved": generalization_improved,
            },
            "company": {"before": before_company, "after": after_company, "non_regression": company_non_regression},
            "single_change": {"before": before_skill, "after": after_skill, "before_rate": skill_before_rate, "after_rate": skill_after_rate, "non_regression": single_change_non_regression},
            "organization": {"before": before_organization, "after": after_organization, "non_regression": organization_non_regression},
            "governance_limits": governance_limits, "checked_at": _now(),
        }
        rollback_proposal_id = None
        if not keep:
            rollback_proposal_id = self._open_monitor_rollback_proposal(proposal, verdict)
        verdict["rollback_proposal_id"] = rollback_proposal_id
        regression = dict(proposal.regression)
        regression["monitoring"] = verdict
        self.learning.update_company_change_proposal(proposal_id, status="monitoring", regression=regression)
        self.learning.record_event(proposal_id, "company_change_monitoring_completed", "C16 controlled post-change monitoring completed", verdict)
        return verdict

    def rollback_skill(self, key: str, *, actor: str, reason: str) -> dict[str, Any]:
        if actor != self.company.ceo.key and actor != "security:reviewer":
            raise PermissionError("only Company CEO or security reviewer may rollback a Skill")
        if not str(reason or "").strip():
            raise PermissionError("rollback reason is required")
        current = self.skills.get(key)
        before = self._skill_snapshot(key)
        if current.status != "active":
            raise PermissionError("only active Skills may be rolled back")
        self.skills.set_status(key, "candidate")
        after = self._skill_snapshot(key)
        proposal_id = self._new_id("skill_rollback", key, {"actor": actor, "reason": reason, "before": before})
        row = self.learning.create_company_change_proposal(proposal_id=proposal_id, company_id=self.company_id, change_kind="skill_rollback", target_key=key, payload={"actor": actor, "reason": reason, "before": before, "after": after, "producer": ""}, evidence=[], regression={"status": "passed"})
        self.learning.update_company_change_proposal(proposal_id, status="applied", executive_approval={"approver": actor, "approved": True, "approved_at": _now()})
        self.learning.record_event(proposal_id, "company_skill_rollback", "governed Skill rollback applied", {"change_kind": "skill_rollback", "before": before, "after": after, "actor": actor, "reason": reason})
        return {"proposal_id": proposal_id, "key": key, "before": before, "after": after, "status": "applied", "reason": reason}

    def reject(self, proposal_id: str, *, reason: str) -> OrganizationChangeProposal:
        if not str(reason or "").strip():
            raise ValueError("rejection reason is required")
        row = self.learning.update_company_change_proposal(proposal_id, status="rejected", security_review={"approved": False, "reason": str(reason), "reviewed_at": _now()})
        return self._proposal(row)  # type: ignore[arg-type]

    def snapshot(self) -> dict[str, Any]:
        proposals = self.list(limit=50)
        return {
            "company_id": self.company_id,
            "active_proposals": sum(1 for p in proposals if p.status in {"proposed", "evaluated", "reviewed", "approved"}),
            "proposal_count": len(proposals),
            "proposals": [p.to_dict() for p in proposals],
            "policy": {
                "learning_is_advisory": True,
                "regression_required": True,
                "independent_security_review_required": True,
                "ceo_approval_required": True,
                "topology_changes_staged": True,
                "rollback_supported_for_skills": True,
            },
        }
