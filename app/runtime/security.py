"""Shared deterministic security boundaries for agent-controlled local resources."""
from __future__ import annotations

import os
from pathlib import Path


def workspace_root() -> Path:
    raw = os.getenv("AGENT_WORKSPACE")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path(__file__).resolve().parents[2] / "workspace").resolve()


def safe_workspace_path(path: str | Path) -> Path:
    """Resolve a user/tool path and reject anything outside AGENT_WORKSPACE."""
    root = workspace_root()
    raw = Path(str(path or ".")).expanduser()
    if not raw.is_absolute():
        # Accept user-facing paths such as ``workspace/file.csv`` without
        # interpreting them as ``<workspace>/workspace/file.csv``. The
        # normalized path still resolves strictly underneath AGENT_WORKSPACE.
        parts = raw.parts
        if parts and str(parts[0]).casefold() == "workspace":
            raw = Path(*parts[1:]) if len(parts) > 1 else Path(".")
        candidate = (root / raw).resolve()
    else:
        candidate = raw.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"path escapes workspace: {path}")
    return candidate


def project_root() -> Path:
    """Return the explicitly configured project root, or the current process directory.

    Project/development inspection is an explicitly approved agent capability.  It must not
    weaken the stricter workspace boundary used by ordinary file/memory tools.
    """
    raw = os.getenv("AGENT_PROJECT_ROOT")
    return Path(raw).expanduser().resolve() if raw else Path.cwd().resolve()


def safe_project_path(path: str | Path) -> Path:
    """Resolve project/development paths within the configured project or workspace roots."""
    project = project_root()
    workspace = workspace_root()
    raw = Path(str(path or ".")).expanduser()
    if not raw.is_absolute():
        parts = raw.parts
        if parts and str(parts[0]).casefold() == "workspace":
            raw = Path(*parts[1:]) if len(parts) > 1 else Path(".")
            candidate = (workspace / raw).resolve()
        else:
            candidate = (project / raw).resolve()
    else:
        candidate = raw.resolve()
    allowed = (project, workspace)
    if candidate != project and project not in candidate.parents and candidate != workspace and workspace not in candidate.parents:
        raise ValueError(f"path escapes project/workspace boundary: {path}")
    return candidate


def safe_workspace_paths(paths: list[str | Path] | tuple[str | Path, ...]) -> list[Path]:
    return [safe_workspace_path(path) for path in paths]


__all__ = ["workspace_root", "safe_workspace_path", "safe_project_path", "safe_workspace_paths", "project_root"]
