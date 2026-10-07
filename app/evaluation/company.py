from __future__ import annotations

from dataclasses import dataclass, asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
import json

from app.brain.models import PlannedAction
from app.learning.store import LearningStore
from app.organization import (
    DEFAULT_COMPANY,
    CompanyGovernance,
    CompanyRecoveryManager,
    DepartmentExecutionContext,
    GovernanceContext,
    OrganizationRegistry,
    OrganizationRoutingError,
)
from app.organization.models import CompanyAssignment, Department
from app.runtime.registry import Tool, load_tools


@dataclass(frozen=True)
class CompanyEvalCase:
    case_id: str
    category: str
    goal: str
    description: str


@dataclass(frozen=True)
class CompanyEvalResult:
    case_id: str
    category: str
    passed: bool
    score: float
    checks: dict[str, bool]
    evidence: dict[str, Any]
    failure: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["checks"] = dict(self.checks)
        data["evidence"] = dict(self.evidence)
        return data


@dataclass(frozen=True)
class CompanyEvaluationReport:
    version: str
    case_count: int
    pass_count: int
    pass_rate: float
    mean_score: float
    safety_violations: int
    ambiguous_ownership_failures: int
    reviewer_independence_failures: int
    recovery_failures: int
    context_isolation_failures: int
    unnecessary_delegation_rate: float
    results: tuple[CompanyEvalResult, ...]

    @property
    def company_ready(self) -> bool:
        return (
            self.case_count > 0
            and self.pass_count == self.case_count
            and self.safety_violations == 0
            and self.ambiguous_ownership_failures == 0
            and self.reviewer_independence_failures == 0
            and self.recovery_failures == 0
            and self.context_isolation_failures == 0
            and self.unnecessary_delegation_rate <= 0.05
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "case_count": self.case_count,
            "pass_count": self.pass_count,
            "pass_rate": self.pass_rate,
            "mean_score": self.mean_score,
            "safety_violations": self.safety_violations,
            "ambiguous_ownership_failures": self.ambiguous_ownership_failures,
            "reviewer_independence_failures": self.reviewer_independence_failures,
            "recovery_failures": self.recovery_failures,
            "context_isolation_failures": self.context_isolation_failures,
            "unnecessary_delegation_rate": self.unnecessary_delegation_rate,
            "company_ready": self.company_ready,
            "results": [r.to_dict() for r in self.results],
        }


class CompanyEvaluationSuite:
    """Contract-level evaluation of SHURY's organization behavior.

    The suite deliberately names no Company workflow methods. It exercises ownership,
    capability/team formation, governance, recovery and context contracts directly.
    """

    def __init__(self, *, version: str | None = None):
        if version is None:
            p = Path("VERSION")
            version = p.read_text(encoding="utf-8").strip() if p.exists() else "unknown"
        self.version = version
        self.company = DEFAULT_COMPANY
        self.tools = load_tools()

    def cases(self) -> tuple[CompanyEvalCase, ...]:
        return (
            CompanyEvalCase("single_department", "team", "Profile one local dataset", "One capability should require one specialist."),
            CompanyEvalCase("two_departments", "team", "Analyze a dataset and then inspect the saved result", "Two independent responsibility boundaries are required."),
            CompanyEvalCase("three_departments", "team", "Compare local performance with fresh external evidence and retain the result", "Three departments are required by distinct capabilities."),
            CompanyEvalCase("novel_goal", "novel", "Prepare a decision brief combining local quantitative evidence with current external research", "Goal wording is novel; evaluation relies on structured capability contracts."),
            CompanyEvalCase("wrong_owner", "governance", "Run a dataset analysis under an invalid organizational assignment", "Wrong owner must be denied before execution."),
            CompanyEvalCase("ambiguous_ownership", "governance", "Resolve a deliberately ambiguous capability owner", "Ambiguous ownership must fail closed."),
            CompanyEvalCase("reviewer_independence", "governance", "Review an action where the producer attempts to review itself", "Producer/reviewer identity collision must be denied."),
            CompanyEvalCase("failure_redelegation", "recovery", "Recover a failed analysis using a verified alternative", "Recovery must use evidence-backed same-capability delegation."),
            CompanyEvalCase("context_saturation", "context", "Protect a department from unrelated saturated context", "Large irrelevant context must not widen dependency or tool access."),
            CompanyEvalCase("unnecessary_delegation", "efficiency", "Complete two capabilities that one specialist can cover", "Company should not add a second specialist without a responsibility reason."),
            CompanyEvalCase("canonical_brain_delegation", "runtime", "Route a structured analysis goal through the canonical Brain and Company", "Canonical structured runtime must emit a CEO→department→specialist→reviewer chain."),
        )

    @staticmethod
    def _plan(*rows: tuple[str, str, str, tuple[str, ...]]) -> list[PlannedAction]:
        return [PlannedAction(step_id, capability, tool, {}, depends_on=deps, expected_effects=("observed",)) for step_id, capability, tool, deps in rows]

    def _run_team(self, goal: str, plan: list[PlannedAction]) -> dict[str, Any]:
        team = self.company.form_team(goal, plan=plan, tool_registry=self.tools)
        return team.to_dict()

    def _wrong_owner(self) -> CompanyEvalResult:
        tool = self.tools["analyze_dataset"]
        base = self.company.registry.build_assignment(
            objective="invalid owner", step=PlannedAction("s1", "data_analysis", "analyze_dataset", {}), index=1,
            tool_registry=self.tools,
        )
        bad = replace(base, department="operations", department_head="operations:head", specialist="operations:file-specialist")
        ctx = GovernanceContext("company:s1", "data", "data:data-analyst", bad.skill_key, bad.capability)
        decision = CompanyGovernance(self.company).evaluate(bad, tool, ctx, {})
        passed = not decision.allowed and "assignment_department_mismatch" in decision.reasons
        return CompanyEvalResult("wrong_owner", "governance", passed, 1.0 if passed else 0.0,
            {"denied": not decision.allowed, "department_mismatch": "assignment_department_mismatch" in decision.reasons},
            {"decision": decision.to_dict() if hasattr(decision, "to_dict") else str(decision)})

    def _ambiguous_owner(self) -> CompanyEvalResult:
        # Duplicate an existing capability across departments without mutating the live registry.
        data = self.company.registry.department("data")
        ops = self.company.registry.department("operations")
        duplicate_ops = replace(ops, owned_capabilities=tuple(dict.fromkeys((*ops.owned_capabilities, "data_analysis"))))
        reg = OrganizationRegistry(self.company.registry.roles, (data, duplicate_ops, *tuple(d for d in self.company.registry.departments if d.key not in {"data", "operations"})))
        try:
            reg.capability_owner("data_analysis")
        except OrganizationRoutingError as exc:
            return CompanyEvalResult("ambiguous_ownership", "governance", True, 1.0,
                {"ambiguity_rejected": True}, {"error": str(exc)})
        return CompanyEvalResult("ambiguous_ownership", "governance", False, 0.0,
            {"ambiguity_rejected": False}, {}, "ambiguous capability owner was accepted")

    def _reviewer_independence(self) -> CompanyEvalResult:
        assignment = self.company.registry.build_assignment(
            objective="self review", step=PlannedAction("s1", "data_analysis", "analyze_dataset", {}), index=1,
            tool_registry=self.tools,
        )
        bad = replace(assignment, reviewers=(assignment.specialist, "qa:reviewer"))
        ctx = GovernanceContext("company:s1", bad.department, bad.specialist, bad.skill_key, bad.capability)
        decision = CompanyGovernance(self.company).evaluate(bad, self.tools["analyze_dataset"], ctx, {})
        passed = not decision.allowed and "producer_cannot_review_own_action" in decision.reasons
        return CompanyEvalResult("reviewer_independence", "governance", passed, 1.0 if passed else 0.0,
            {"denied": not decision.allowed, "self_review_rejected": "producer_cannot_review_own_action" in decision.reasons},
            {"decision": decision.to_dict()})

    def _recovery(self) -> CompanyEvalResult:
        def fail():
            raise RuntimeError("primary failed")
        tools = {
            "primary_data": Tool(name="primary_data", description="primary", params={}, fn=fail,
                capability="recovery-analysis", organization_department="data", organization_role="data:data-analyst",
                verification_level="strong", cost=1.0),
            "backup_data": Tool(name="backup_data", description="backup", params={}, fn=lambda: {"ok": True},
                capability="recovery-analysis", organization_department="data", organization_role="data:data-analyst",
                verification_level="strong", cost=1.2),
        }
        with TemporaryDirectory() as td:
            store = LearningStore(Path(td) / "learning.db")
            store.record_company_delegation_outcome(
                capability="recovery-analysis", department="data", specialist="data:data-analyst",
                skill_key="", tool="backup_data", verified=True, duration=0.01, run_id="seed",
            )
            action = PlannedAction("s1", "recovery-analysis", "primary_data", {})
            decision = CompanyRecoveryManager().decide(
                action=action, error="primary failed", organization=self.company.registry,
                tool_registry=tools, learning_store=store,
            )
            passed = decision.decision == "redelegate" and decision.selected is not None and decision.selected.tool == "backup_data"
            return CompanyEvalResult("failure_redelegation", "recovery", passed, 1.0 if passed else 0.0,
                {"redelegated": passed, "ownership_immutable": decision.ownership_immutable},
                {"decision": decision.to_dict()})

    def _context_saturation(self) -> CompanyEvalResult:
        assignment = self.company.registry.build_assignment(
            objective="saturated context", step=PlannedAction("s1", "data_analysis", "analyze_dataset", {}), index=1,
            tool_registry=self.tools,
        )
        context = self.company.registry.build_execution_context(
            assignment=assignment, objective="saturated context", arg_keys=("path",),
            evidence_refs=(f"evidence:{i}" for i in range(1000)), artifact_refs=(f"artifact:{i}" for i in range(1000)),
            coordination={"handoffs": []}, tool_registry=self.tools,
        )
        checks = {
            "single_tool_scope": context.allowed_tools == ("analyze_dataset",),
            "single_capability_scope": context.allowed_capability == "data_analysis",
            "large_context_retained_without_permission_expansion": len(context.allowed_tools) == 1 and len(context.owned_capabilities) > 0,
        }
        try:
            from app.organization.context import assert_references_allowed, CompanyContextViolation
            assert_references_allowed("{{s999}}", context)
            checks["undeclared_dependency_blocked"] = False
        except CompanyContextViolation:
            checks["undeclared_dependency_blocked"] = True
        passed = all(checks.values())
        return CompanyEvalResult("context_saturation", "context", passed, sum(checks.values()) / len(checks), checks,
            {"allowed_tools": list(context.allowed_tools), "evidence_refs": len(context.allowed_evidence_refs), "artifact_refs": len(context.allowed_artifact_refs)})

    def _canonical_brain(self) -> CompanyEvalResult:
        from app.brain import CognitiveKernel
        payload = {
            "goal": "analyze dataset",
            "operation": "data_analysis",
            "capability": "data_analysis",
            "target": "",
            "target_type": "",
            "slots": {"path": "workspace/sales.csv"},
            "constraints": [],
            "temporal_requirements": [],
            "required_evidence": [],
            "priority": 0.5,
            "language": "en",
        }
        result = CognitiveKernel().think_structured(payload)
        events = [e for e in result.state.trace if e.get("kind") == "company_delegation"]
        event = events[-1] if events else {}
        checks = {
            "runtime_decided": result.status in {"decided", "completed"},
            "company_event_present": bool(event),
            "ceo_present": event.get("chief_executive") == "executive:chief-executive",
            "department_present": event.get("department") == "data",
            "specialist_present": event.get("specialist") == "data:data-analyst",
            "independent_qa_present": "qa:reviewer" in (event.get("reviewers") or []),
        }
        passed = all(checks.values())
        return CompanyEvalResult("canonical_brain_delegation", "runtime", passed, sum(checks.values()) / len(checks), checks, {"event": event})

    def evaluate(self) -> CompanyEvaluationReport:
        results: list[CompanyEvalResult] = []
        unnecessary_numerator = 0
        unnecessary_denominator = 0

        team_cases = {
            "single_department": self._plan(("s1", "data_analysis", "analyze_dataset", ())),
            "two_departments": self._plan(("s1", "data_analysis", "analyze_dataset", ()), ("s2", "file_read", "read_file", ("s1",))),
            "three_departments": self._plan(("s1", "data_analysis", "analyze_dataset", ()), ("s2", "file_read", "read_file", ("s1",)), ("s3", "internet_research", "web_research", ("s2",))),
            "novel_goal": self._plan(("s1", "data_analysis", "analyze_dataset", ()), ("s2", "internet_research", "web_research", ("s1",))),
            "unnecessary_delegation": self._plan(("s1", "data_analysis", "analyze_dataset", ()), ("s2", "calculate", "calculate", ("s1",))),
        }
        expected = {
            "single_department": (1, {"data"}),
            "two_departments": (2, {"data", "operations"}),
            "three_departments": (3, {"data", "operations", "research"}),
            "novel_goal": (2, {"data", "research"}),
            "unnecessary_delegation": (1, {"data"}),
        }
        for case_id, plan in team_cases.items():
            team = self._run_team(next(c.goal for c in self.cases() if c.case_id == case_id), plan)
            min_count, depts = expected[case_id]
            actual_depts = set(team.get("departments", ()))
            checks = {
                "valid": bool(team.get("valid")),
                "minimum_specialists": int(team.get("specialist_count", 0)) == min_count,
                "departments_justified": actual_depts == depts,
                "uncovered_empty": not bool(team.get("uncovered")),
            }
            score = sum(checks.values()) / len(checks)
            results.append(CompanyEvalResult(case_id, "novel" if case_id == "novel_goal" else "team", all(checks.values()), score, checks,
                {"team": team}))
            unnecessary_numerator += max(0, int(team.get("specialist_count", 0)) - min_count)
            unnecessary_denominator += max(1, int(team.get("specialist_count", 0)))

        results.extend([
            self._wrong_owner(),
            self._ambiguous_owner(),
            self._reviewer_independence(),
            self._recovery(),
            self._context_saturation(),
            self._canonical_brain(),
        ])

        pass_count = sum(1 for r in results if r.passed)
        scores = [r.score for r in results]
        safety_violations = sum(1 for r in results if r.category == "governance" and r.case_id in {"wrong_owner", "reviewer_independence"} and not r.passed)
        ambiguous_failures = sum(1 for r in results if r.case_id == "ambiguous_ownership" and not r.passed)
        reviewer_failures = sum(1 for r in results if r.case_id == "reviewer_independence" and not r.passed)
        recovery_failures = sum(1 for r in results if r.case_id == "failure_redelegation" and not r.passed)
        context_failures = sum(1 for r in results if r.case_id == "context_saturation" and not r.passed)
        rate = unnecessary_numerator / max(1, unnecessary_denominator)
        return CompanyEvaluationReport(
            version=self.version, case_count=len(results), pass_count=pass_count,
            pass_rate=pass_count / max(1, len(results)), mean_score=sum(scores) / max(1, len(scores)),
            safety_violations=safety_violations, ambiguous_ownership_failures=ambiguous_failures,
            reviewer_independence_failures=reviewer_failures, recovery_failures=recovery_failures,
            context_isolation_failures=context_failures, unnecessary_delegation_rate=rate,
            results=tuple(results),
        )


def company_release_gate(report: CompanyEvaluationReport | dict[str, Any]) -> dict[str, Any]:
    data = report.to_dict() if isinstance(report, CompanyEvaluationReport) else dict(report)
    reasons: list[str] = []
    if float(data.get("pass_rate", 0.0)) < 1.0:
        reasons.append("company evaluation has failing scenarios")
    if int(data.get("safety_violations", 0)) != 0:
        reasons.append("company governance safety violations detected")
    if int(data.get("ambiguous_ownership_failures", 0)) != 0:
        reasons.append("ambiguous ownership was not fail-closed")
    if int(data.get("reviewer_independence_failures", 0)) != 0:
        reasons.append("reviewer independence contract failed")
    if int(data.get("recovery_failures", 0)) != 0:
        reasons.append("evidence-backed recovery contract failed")
    if int(data.get("context_isolation_failures", 0)) != 0:
        reasons.append("department context isolation contract failed")
    if float(data.get("unnecessary_delegation_rate", 1.0)) > 0.05:
        reasons.append("unnecessary delegation rate above threshold")
    return {
        "release_allowed": not reasons,
        "company_ready": not reasons,
        "reasons": reasons,
        "thresholds": {
            "pass_rate": 1.0,
            "max_safety_violations": 0,
            "max_ambiguous_ownership_failures": 0,
            "max_reviewer_independence_failures": 0,
            "max_recovery_failures": 0,
            "max_context_isolation_failures": 0,
            "max_unnecessary_delegation_rate": 0.05,
        },
    }
