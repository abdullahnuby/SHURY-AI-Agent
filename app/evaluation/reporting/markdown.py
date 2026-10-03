from __future__ import annotations
from typing import Any


def render_report_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Agent Evaluation Report {report.get('run_id', '')}",
        "",
        f"**Version:** {report.get('version')}  ",
        f"**Pass rate:** {float(report.get('pass_rate', 0.0)):.1%}  ",
        f"**Mean score:** {float(report.get('mean_score', 0.0)):.3f}  ",
        f"**Safety violations:** {int(report.get('safety_violations', 0))}  ",
        f"**Reproducible:** {'yes' if report.get('reproducible') else 'no'}",
        "",
        "| Scenario | Pass | Score | Steps | Pass@N | All@N | Failures |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in report.get("scenario_results", []):
        failures = ", ".join(f"{k}:{v}" for k, v in row.get("failure_patterns", {}).items()) or "—"
        lines.append(
            f"| {row.get('scenario_id')} | {row.get('pass_rate', 0):.1%} | {row.get('mean_score', 0):.3f} | "
            f"{row.get('mean_steps', 0):.1f} | {row.get('pass_at_n', 0):.1%} | {row.get('all_n', 0):.1%} | {failures} |"
        )
    lines += ["", "## Failure patterns", ""]
    if report.get("failure_patterns"):
        for key, value in sorted(report["failure_patterns"].items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- **{key}:** {value}")
    else:
        lines.append("No failures recorded.")
    lines += ["", "## Release interpretation", "", "This report is evidence, not a single quality number. Use scenario-level deltas, safety gates, and repeated-trial consistency when deciding whether a change is safe to ship."]
    return "\n".join(lines) + "\n"
