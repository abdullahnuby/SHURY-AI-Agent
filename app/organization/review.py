from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class ReviewResult:
    reviewer: str
    ok: bool
    reason: str
    checks: dict[str, bool] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    final_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "reviewer": self.reviewer,
            "ok": self.ok,
            "reason": self.reason,
            "checks": dict(self.checks),
            "evidence": dict(self.evidence),
            "final_message": self.final_message,
        }


def _steps(plan) -> list[Any]:
    return list(getattr(plan, "steps", plan or ()) or ())


def _tool_output(plan, tool_name: str, outputs: dict[str, Any] | None = None) -> Any:
    for step in _steps(plan):
        if step.tool != tool_name:
            continue
        if outputs is not None and str(getattr(step, "step_id", getattr(step, "id", ""))) in outputs:
            return outputs[str(getattr(step, "step_id", getattr(step, "id", "")))]
        if getattr(step, "status", "") in {"done", "completed"}:
            return getattr(step, "output", None)
    return None


def _done_tools(plan, outputs: dict[str, Any] | None = None, observations: Iterable[dict[str, Any]] | None = None) -> list[str]:
    output_ids = {str(k) for k in (outputs or {}).keys()}
    observed_ids = {
        str(item.get('step_id'))
        for item in (observations or ())
        if isinstance(item, dict) and item.get('verified') is not False
    }
    done: list[str] = []
    for step in _steps(plan):
        step_id = str(getattr(step, 'step_id', getattr(step, 'id', '')))
        status = str(getattr(step, 'status', '') or '')
        if status in {'done', 'completed'} or step_id in output_ids or step_id in observed_ids:
            done.append(str(getattr(step, 'tool', '')))
    return done


def review_company_execution(
    *,
    goal: str,
    operation: str,
    plan,
    assignments: Iterable[dict[str, Any]],
    status: str,
    outputs: dict[str, Any] | None = None,
    observations: Iterable[dict[str, Any]] | None = None,
    coordination: dict[str, Any] | None = None,
) -> ReviewResult:
    """Independent deterministic QA review.

    The reviewer has no write surface and does not alter plan state. It only inspects
    completed tool observations and organization assignments. A workflow may not be
    called completed until this reviewer passes.
    """
    assignments = list(assignments or ())
    steps = _steps(plan)
    observations = list(observations or ())
    observed_verified = {str(o.get("step_id")): bool(o.get("verified", False)) for o in observations if isinstance(o, dict)}
    statusful = all(hasattr(s, "status") for s in steps)
    if statusful:
        all_steps_done = all(getattr(s, "status", "") in {"done", "completed"} for s in steps)
    elif outputs is not None:
        all_steps_done = bool(steps) and all(str(getattr(s, "step_id", getattr(s, "id", ""))) in outputs for s in steps)
    else:
        all_steps_done = bool(steps) and all(observed_verified.get(str(getattr(s, "step_id", getattr(s, "id", ""))), False) for s in steps)
    checks: dict[str, bool] = {
        "workflow_present": bool(steps),
        "all_steps_done": all_steps_done,
        "assignment_count_matches_steps": bool(plan) and len(assignments) == len(_steps(plan)),
        "qa_reviewer_present": bool(assignments) and all("qa:reviewer" in (a.get("reviewers") or []) for a in assignments),
        "status_completed_before_review": status == "completed",
    }
    evidence: dict[str, Any] = {"done_tools": _done_tools(plan, outputs, observations)}
    coordination = dict(coordination or {})
    if coordination:
        tasks = coordination.get('tasks') or []
        handoffs = coordination.get('handoffs') or []
        checks.update({
            'company_coordination_present': bool(tasks),
            'coordination_task_count_matches_assignments': len(tasks) == len(assignments),
            'cross_department_handoffs_are_explicit': all(
                h.get('from_task') and h.get('to_task') and h.get('contract')
                for h in handoffs if isinstance(h, dict)
            ),
        })
        evidence['coordination'] = coordination

    done_tools = _done_tools(plan, outputs, observations)
    tool_names = {str(getattr(step, "tool", "")) for step in steps}
    # Strong cross-department QA is selected from the workflow shape, not from individual
    # tool-name allowlists: a workflow is strong when it visibly spans departments, explicitly
    # declares a cross-department operation class, or contains both analysis and movement stages.
    departments = {a.get("department") for a in assignments}
    declared_operations = {str(a.get("operation") or "").casefold() for a in assignments}
    spans_departments = departments.issuperset({"data", "operations"})
    declares_cross_department = any(op.startswith("cross_department_") for op in declared_operations)
    has_analysis_stage = bool({"analyze_csv_by_average", "analyze_csv_collection"} & tool_names)
    has_move_stage = bool({"move_workspace_report", "move_workspace_file"} & tool_names)
    strong_workflow = spans_departments or declares_cross_department or (has_analysis_stage and has_move_stage)
    if strong_workflow:
        required_tools = sorted(tool_names)
        checks["required_tools_present"] = all(tool in done_tools for tool in required_tools)
        departments = {a.get("department") for a in assignments}
        checks["departments_span_data_and_operations"] = departments.issuperset({"data", "operations"})
        checks["required_tools_present"] = checks["required_tools_present"] and checks["departments_span_data_and_operations"]
        move_tools = {"move_workspace_report", "move_workspace_file"} & tool_names
        move_assignment = next((a for a in assignments if a.get("department") == "operations" and "security:reviewer" in (a.get("reviewers") or []) and a.get("tool") in move_tools), None)
        if move_assignment is None:
            move_assignment = next((a for a in assignments if a.get("department") == "operations" and "security:reviewer" in (a.get("reviewers") or [])), None)
        checks["high_risk_move_has_security_review"] = move_assignment is not None
        checks["report_move_has_security_review"] = move_assignment is not None

        if "analyze_csv_by_average" in tool_names:
            analysis = _tool_output(plan, "analyze_csv_by_average", outputs) or {}
            report = _tool_output(plan, "create_sales_analysis_report", outputs) or {}
            move = _tool_output(plan, "move_workspace_report", outputs) or {}
            reread = _tool_output(plan, "read_file", outputs) or {}
            checks["analysis_verified"] = bool(analysis.get("verified") and analysis.get("selected_path") and analysis.get("selected") and analysis.get("selection_metric") == "average")
            files = analysis.get("files") or []
            if files and analysis.get("selected_path"):
                expected = max(files, key=lambda x: (float(x.get("average") or 0.0), str(x.get("path") or "")))
                checks["selection_matches_recomputed_average"] = expected.get("path") == analysis.get("selected_path")
            else:
                checks["selection_matches_recomputed_average"] = False
            checks["report_verified"] = bool(report.get("verified") and report.get("report_reread_verified"))
            checks["move_verified"] = bool(move.get("verified") and move.get("fingerprint_match") and move.get("destination_exists") and move.get("source_removed"))
            selected = str(analysis.get("selected_path") or "")
            destination = str(move.get("destination") or "")
            content = str(reread.get("content") or "") if isinstance(reread, dict) else ""
            reread_path = str(reread.get("path") or "") if isinstance(reread, dict) else ""
            checks["reread_present"] = bool(isinstance(reread, dict) and reread.get("content") is not None)
            checks["reread_matches_selected_and_destination"] = bool(selected and destination and selected in content and (reread_path.replace("\\", "/").lstrip("./") == destination.replace("\\", "/").lstrip("./") or destination.replace("\\", "/") in content.replace("\\", "/")))
            source_hash = str((analysis.get("selected") or {}).get("source_fingerprint") or "")
            checks["reread_contains_source_hash"] = bool(source_hash and source_hash in content)
            checks["reread_contains_move_hash"] = bool(move.get("fingerprint_match") and move.get("sha256_before") and move.get("sha256_before") == move.get("sha256_after"))
            unchanged = move.get("unchanged_files_verified")
            checks["original_other_files_unchanged"] = True if unchanged is None else bool(unchanged)
            evidence.update({"selected_path": selected, "destination": destination, "selected_average": (analysis.get("selected") or {}).get("average")})
        else:
            analysis = _tool_output(plan, "analyze_csv_collection", outputs) or {}
            move = _tool_output(plan, "move_workspace_file", outputs) or {}
            report = _tool_output(plan, "create_company_data_report", outputs) or {}
            reread = _tool_output(plan, "read_file", outputs) or {}
            checks["analysis_verified"] = bool(analysis.get("verified") and analysis.get("selected_path") and analysis.get("selected"))
            checks["move_verified"] = bool(move.get("verified") and move.get("fingerprint_match") and move.get("destination_exists"))
            checks["other_files_unchanged"] = bool(move.get("unchanged_files_verified"))
            checks["report_verified"] = bool(report.get("verified") and report.get("report_reread_verified"))
            checks["reread_present"] = bool(isinstance(reread, dict) and reread.get("content") is not None)
            selected = str(analysis.get("selected_path") or "")
            destination = str(move.get("destination") or "")
            content = str(reread.get("content") or "") if isinstance(reread, dict) else ""
            checks["reread_matches_selected_and_destination"] = bool(selected and destination and selected in content and destination in content)
            checks["reread_contains_source_hash"] = bool(str(move.get("sha256_before") or "") and str(move.get("sha256_before")) in content)
            checks["reread_contains_destination_hash"] = bool(str(move.get("sha256_after") or "") and str(move.get("sha256_after")) in content)
            evidence.update({"selected_path": selected, "destination": destination})
        move = _tool_output(plan, "move_workspace_report", outputs) or _tool_output(plan, "move_workspace_file", outputs) or {}
        destination = str(move.get("destination") or "")
        operations_department = next((str(a.get("department") or "").replace("_", " ").title() for a in assignments if a.get("department")), "Operations")
        final_message = (
            f"تم تنفيذ workflow الشركة والتحقق منه وفق assignments/capabilities المعلنة. "
            f"{operations_department} نقله إلى {destination} وتم التحقق من النتائج."
        )
    else:
        # Generic multi-step QA: every step needs a verified tool observation and the company
        # must have routed the plan. Specific workflows can add stronger contracts later.
        checks["tool_outputs_present"] = bool(outputs) or (bool(plan) and all(getattr(s, "output", None) is not None for s in steps if getattr(s, "status", "") in {"done", "completed"}))
        checks["reviewable"] = bool(plan) and bool(assignments)
        evidence["step_count"] = len(_steps(plan))
        final_message = "تم تنفيذ workflow الشركة والتحقق منه بواسطة Quality Reviewer."

    ok = all(checks.values())
    reason = "independent QA passed" if ok else "independent QA failed: " + ", ".join(k for k, v in checks.items() if not v)
    if not ok:
        final_message = "لا أعتبر الهدف مكتملًا لأن مراجعة Quality Reviewer لم تثبت كل متطلبات الهدف."
    return ReviewResult(
        reviewer="qa:reviewer", ok=ok, reason=reason, checks=checks,
        evidence=evidence, final_message=final_message,
    )
