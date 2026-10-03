"""Deterministic repository inspection and build/test management.

Commands are selected from detected project manifests and executed without a shell.
This keeps the agent useful for development while preventing arbitrary command strings
from being interpreted as trusted code.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from app.runtime.security import safe_workspace_path

IGNORED = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "dist", "build", "target"}


def _run(argv: list[str], cwd: Path, timeout: float = 90.0) -> dict:
    started = time.monotonic()
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, shell=False)
        return {"command": argv, "returncode": proc.returncode, "ok": proc.returncode == 0,
                "stdout": proc.stdout[-20_000:], "stderr": proc.stderr[-20_000:],
                "duration_ms": round((time.monotonic() - started) * 1000.0, 3)}
    except subprocess.TimeoutExpired as exc:
        return {"command": argv, "returncode": None, "ok": False, "stdout": (exc.stdout or "")[-20_000:],
                "stderr": (exc.stderr or "")[-20_000:], "timeout": True,
                "duration_ms": round((time.monotonic() - started) * 1000.0, 3)}


def _resolve_project_path(path: str | Path) -> Path:
    return safe_workspace_path(path)

def inspect_project(path: str | Path) -> dict:
    root = _resolve_project_path(path)
    if not root.is_dir():
        raise FileNotFoundError(str(root))
    files = {p.name.lower(): p for p in root.iterdir() if p.is_file()}
    dirs = {p.name.lower() for p in root.iterdir() if p.is_dir()}
    stack: list[str] = []
    commands: list[dict] = []
    metadata: dict = {}
    if "pyproject.toml" in files or "requirements.txt" in files or "setup.py" in files:
        stack.append("python")
        commands.extend([{"name": "compile", "argv": ["python", "-m", "compileall", "-q", "."]},
                         {"name": "pytest", "argv": ["python", "-m", "pytest", "-q"]}])
        if "pyproject.toml" in files:
            metadata["pyproject"] = files["pyproject.toml"].read_text(encoding="utf-8", errors="replace")[:30_000]
    package = None
    if "package.json" in files:
        stack.append("node")
        package = json.loads(files["package.json"].read_text(encoding="utf-8", errors="replace"))
        scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
        for key in ("lint", "test", "build", "typecheck"):
            if key in scripts:
                commands.append({"name": f"npm:{key}", "argv": ["npm", "run", key]})
        metadata["package_scripts"] = sorted(scripts)
    if "cargo.toml" in files or "cargo.lock" in files:
        stack.append("rust")
        commands += [{"name": "cargo:test", "argv": ["cargo", "test"]}, {"name": "cargo:build", "argv": ["cargo", "build"]}]
    if "go.mod" in files:
        stack.append("go")
        commands += [{"name": "go:test", "argv": ["go", "test", "./..."]}, {"name": "go:build", "argv": ["go", "build", "./..."]}]
    if "pom.xml" in files:
        stack.append("java-maven")
        commands += [{"name": "maven:test", "argv": ["mvn", "test"]}, {"name": "maven:package", "argv": ["mvn", "package", "-DskipTests"]}]
    if "build.gradle" in files or "build.gradle.kts" in files:
        stack.append("java-gradle")
        commands += [{"name": "gradle:test", "argv": ["gradle", "test"]}, {"name": "gradle:build", "argv": ["gradle", "build"]}]
    if ".github" in dirs:
        metadata["ci_present"] = True
    metadata["git_present"] = (root / ".git").exists()
    metadata["files"] = sorted(p.name for p in root.iterdir() if p.is_file())
    return {"path": str(root), "stack": stack or ["unknown"], "commands": commands,
            "metadata": metadata, "policy": "manifest-detected commands only; no shell evaluation"}


def git_status(path: str | Path) -> dict:
    root = safe_workspace_path(path)
    if not (root / ".git").exists():
        return {"path": str(root), "git": False}
    branch = _run(["git", "branch", "--show-current"], root, 10)
    status = _run(["git", "status", "--short", "--branch"], root, 10)
    recent = _run(["git", "log", "-5", "--oneline", "--decorate"], root, 10)
    return {"path": str(root), "git": True, "branch": branch.get("stdout", "").strip(),
            "status": status.get("stdout", "").strip(), "recent_commits": recent.get("stdout", "").splitlines()}


def check_project(path: str | Path, checks=("git-diff-check", "compile"), timeout: float = 90.0) -> dict:
    info = inspect_project(path)
    root = _resolve_project_path(path)
    results = []
    for check in checks:
        if check == "git-diff-check":
            if not (root / ".git").exists():
                continue
            results.append(_run(["git", "diff", "--check"], root, timeout))
            continue
        match = next((c for c in info["commands"] if c["name"] == check or c["name"].endswith(f":{check}")), None)
        if match is None:
            continue
        results.append(_run(match["argv"], root, timeout))
    return {"path": str(root), "stack": info["stack"], "checks": results,
            "passed": sum(1 for r in results if r["ok"]), "total": len(results),
            "all_passed": bool(results) and all(r["ok"] for r in results),
            "reason": "no applicable checks detected" if not results else None}
