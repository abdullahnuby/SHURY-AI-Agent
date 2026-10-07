from __future__ import annotations

import json
import re
import sys
import subprocess
import time
from pathlib import Path

from app.runtime.registry import tool
from app.runtime.security import safe_project_path, safe_workspace_path, workspace_root
from app.integrations.devops import inspect_project, git_status


def _resolve_root(path: str) -> Path:
    return safe_project_path(path or ".")


def _run(argv: list[str], cwd: Path, timeout: float = 120.0) -> dict:
    started = time.monotonic()
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, shell=False)
        return {
            "command": argv,
            "returncode": proc.returncode,
            "ok": proc.returncode == 0,
            "stdout": proc.stdout[-20_000:],
            "stderr": proc.stderr[-20_000:],
            "duration_ms": round((time.monotonic() - started) * 1000.0, 3),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": argv,
            "returncode": None,
            "ok": False,
            "stdout": str(exc.stdout or "")[-20_000:],
            "stderr": str(exc.stderr or "")[-20_000:],
            "timeout": True,
            "duration_ms": round((time.monotonic() - started) * 1000.0, 3),
        }


def _commands(info: dict) -> list[tuple[str, list[str]]]:
    commands: list[tuple[str, list[str]]] = []
    for item in info.get("commands", []):
        name = str(item.get("name") or "")
        argv = [str(x) for x in item.get("argv", [])]
        if not argv:
            continue
        # Audit observes only commands already produced by the trusted project inspector.
        # The inspector itself constructs argv from known manifests; this filter merely keeps
        # the audit focused on validation/build operations and never accepts free-form shell.
        lname = name.casefold()
        if (lname in {"pytest", "compile"}
                or lname.endswith(":test")
                or lname.endswith(":build")
                or lname in {"maven:package", "cargo:build", "go:build", "gradle:build"}):
            commands.append((name, argv))
    return commands


@tool(
    "يشغل فحوصات المشروع المناسبة ويعيد evidence حتى عند وجود failures؛ الهدف تشخيص المشروع وليس إخفاء الفشل",
    {"path": "str"},
    name="audit_project_tests",
    triggers=("audit project tests", "run project tests for audit", "حلل اختبارات المشروع", "شغل اختبارات المشروع"),
    match=lambda g: bool(re.search(r"(?:project.*tests|tests.*project|اختبارات.*المشروع|الاختبارات.*المشروع)", g, re.I)),
    build_args=lambda g: {"path": "."},
    capability="project_test_audit",
    produces=("project_tests_observed",),
    requires_approval=True,
    risk="medium",
    cost=4.0,
    duration=20.0,
    parallel_safe=False,
    idempotent=True,
    verification_level="strong",
    intent_priority=10,
    pipe_source=True,
)
def audit_project_tests(path: str):
    root = _resolve_root(path)
    info = inspect_project(root)
    results = [_run(argv, root, 120.0) for _name, argv in _commands(info)]
    return {
        "path": str(root),
        "commands": [r["command"] for r in results],
        "results": results,
        "attempted": len(results),
        "passed": sum(1 for r in results if r.get("ok")),
        "failed": sum(1 for r in results if not r.get("ok")),
        "all_passed": bool(results) and all(r.get("ok") for r in results),
        "policy": "manifest-detected safe test/build commands only; shell=False",
    }


def _parse_test_audit(value: object) -> dict:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        # Brain placeholder substitution serializes Python dicts with repr().
        import ast
        try:
            parsed = ast.literal_eval(text)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}


def _dependencies(root: Path) -> list[str]:
    requirements = root / "requirements.txt"
    if requirements.is_file():
        lines = []
        for raw in requirements.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                lines.append(line)
        return lines[:40]
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8", errors="replace")
        deps = re.findall(r"['\"]([A-Za-z0-9_.-]+(?:[><=!~]=?.*)?)['\"]", text)
        return deps[:40]
    return []


def _failure_records(audit: dict) -> list[dict]:
    failures: list[dict] = []
    for result in audit.get("results", []) or []:
        if result.get("ok"):
            continue
        combined = ((result.get("stdout") or "") + "\n" + (result.get("stderr") or "")).strip()
        failed_tests = re.findall(r"FAILED\s+([^\s]+)", combined)
        files = re.findall(r"(?:^|[\s(])((?:app|tests)/[^\s:)]+\.(?:py|ts|tsx|js|jsx))", combined)
        signature = ""
        for line in reversed(combined.splitlines()):
            stripped = line.strip()
            if stripped.startswith("E ") or "Error" in stripped or "AssertionError" in stripped or "FAILED" in stripped:
                signature = stripped[:500]
                break
        failures.append({
            "command": result.get("command"),
            "returncode": result.get("returncode"),
            "timeout": bool(result.get("timeout")),
            "tests": failed_tests[:10],
            "files": list(dict.fromkeys(files))[:10],
            "evidence": signature or combined[-800:],
        })
    return failures


def _top_problems(failures: list[dict]) -> list[dict]:
    problems = []
    for idx, item in enumerate(failures[:3], 1):
        location = ", ".join(item.get("files") or item.get("tests") or ["command-level failure"])
        reason = item.get("evidence") or "validation command failed"
        problems.append({"priority": idx, "location": location, "reason": reason, "evidence": item})
    return problems


def _output_path(goal: str) -> str:
    """Extract an explicitly requested workspace report path; otherwise use the default.

    This intentionally looks for an artifact path, not an arbitrary path, so a report file
    named in the goal can never become the inspected project root.
    """
    text = str(goal or "").strip()
    matches = re.findall(r'(?<![A-Za-z0-9_])workspace[\\/]([^\s,;!?؟]+\.(?:md|txt))', text, re.I)
    if matches:
        return f"workspace/{matches[-1].rstrip(".,")}"
    quoted = re.findall(r'["\']([^"\']+\.(?:md|txt))["\']', text, re.I)
    if quoted:
        return quoted[-1].strip().rstrip('.,')
    return "shury_project_audit.md"


@tool(
    "ينشئ تقرير تدقيق مشروع حقيقي من inspection وGit وtest evidence ويعيد قراءته ويتحقق من الأقسام",
    {"path": "str", "output_path": "str", "question": "str", "test_audit": "str"},
    name="create_project_audit_report",
    triggers=("project audit report", "audit report", "تقرير تدقيق المشروع", "تقرير فحص المشروع"),
    match=lambda g: bool(re.search(r"(?:project.*audit.*report|audit.*report|تقرير.*(?:تدقيق|فحص).*المشروع)", g, re.I)),
    build_args=lambda g: {"path": ".", "output_path": _output_path(g), "question": g, "test_audit": ""},
    capability="project_audit",
    produces=("project_audit_report_created",),
    requires_approval=True,
    risk="medium",
    cost=3.0,
    duration=0.5,
    parallel_safe=False,
    idempotent=True,
    verification_level="strong",
    intent_priority=11,
    pipe_param="test_audit",
)
def create_project_audit_report(path: str, output_path: str, question: str, test_audit: str):
    root = _resolve_root(path)
    inspection = inspect_project(root)
    git = git_status(root)
    audit = _parse_test_audit(test_audit)
    if not audit:
        # Safe fallback: report tool can still collect current test evidence itself.
        audit = audit_project_tests(str(root))
    failures = _failure_records(audit)
    top = _top_problems(failures)
    deps = _dependencies(root)
    py_version = sys.version.splitlines()[0]
    output = safe_workspace_path(output_path or "shury_project_audit.md")
    if output == root or output.is_dir():
        raise ValueError("report output must be a file inside the workspace")
    output.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# SHURY Project Audit Report", "",
        "## Project Stack", "",
        f"- Path: `{root}`", f"- Stack: {', '.join(inspection.get('stack') or ['unknown'])}", f"- Python: `{py_version}`", "",
        "## Dependencies", "",
    ]
    lines.extend(f"- `{dep}`" for dep in deps) if deps else lines.append("- No requirements.txt/pyproject dependency list found.")
    lines += ["", "## Git Status", "", f"- Git repository: `{bool(git.get('git'))}`", f"- Branch: `{git.get('branch') or 'n/a'}`", "", "```text", str(git.get('status') or '(clean or no status output)'), "```", "", "## Test Result", ""]
    lines += [f"- Commands attempted: {audit.get('attempted', 0)}", f"- Passed: {audit.get('passed', 0)}", f"- Failed: {audit.get('failed', 0)}", f"- All passed: `{bool(audit.get('all_passed'))}`", ""]
    for result in audit.get("results", []) or []:
        lines += [f"### Command: `{' '.join(result.get('command') or [])}`", "", f"- Return code: `{result.get('returncode')}`", f"- Status: `{result.get('ok')}`", "", "```text", (result.get('stderr') or result.get('stdout') or '')[-3000:], "```", ""]
    lines += ["## Failures", ""]
    if failures:
        for item in failures:
            lines += [f"- Command: `{item.get('command')}`", f"  - Files/tests: {', '.join(item.get('files') or item.get('tests') or ['command-level'])}", f"  - Evidence: {item.get('evidence')}"]
    else:
        lines.append("No failing validation command was observed.")
    lines += ["", "## Root Causes", ""]
    if top:
        for item in top:
            lines += [f"### Priority {item['priority']}", f"- Location: {item['location']}", f"- Observed cause: {item['reason']}", "- Root-cause confidence: evidence-derived from the failing command/trace; deeper causality requires targeted investigation.", ""]
    else:
        lines.append("No root-cause candidate was required because no validation command failed.")
    lines += ["## Priorities", ""]
    if top:
        for item in top:
            lines.append(f"{item['priority']}. Investigate `{item['location']}` using the recorded failure evidence before changing behavior.")
    else:
        lines.append("1. No blocking validation failure observed.")
    lines += ["", "## Recommendations", "", "- Preserve one canonical runtime and route project audit tasks through the governed project-audit Skill.", "- Treat test failures as observations to analyze, not as reasons to pretend the audit succeeded.", "- Keep generated audit artifacts in the workspace with reproducible evidence.", "", "## Verification", "", "The report was generated from live project inspection, live Git status, and live validation evidence. The output file is re-read before completion.", ""]
    content = "\n".join(lines)
    output.write_text(content, encoding="utf-8")
    reread = output.read_text(encoding="utf-8")
    required = ("## Project Stack", "## Dependencies", "## Git Status", "## Test Result", "## Failures", "## Root Causes", "## Priorities", "## Recommendations")
    verified = output.exists() and output.is_file() and all(section in reread for section in required)
    if not verified:
        raise RuntimeError("project audit report verification failed")
    try:
        output_label = str(output.relative_to(workspace_root()))
    except ValueError:
        output_label = str(output)
    return {
        "path": output_label,
        "verified": True,
        "stack": inspection.get("stack", []),
        "python": py_version,
        "dependency_count": len(deps),
        "test_summary": {"attempted": audit.get("attempted", 0), "passed": audit.get("passed", 0), "failed": audit.get("failed", 0), "all_passed": bool(audit.get("all_passed"))},
        "failures": failures,
        "top_problems": top,
    }
