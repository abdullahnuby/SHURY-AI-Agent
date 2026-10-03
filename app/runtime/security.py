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
    candidate = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"path escapes workspace: {path}")
    return candidate


def safe_workspace_paths(paths: list[str | Path] | tuple[str | Path, ...]) -> list[Path]:
    return [safe_workspace_path(path) for path in paths]


__all__ = ["workspace_root", "safe_workspace_path", "safe_workspace_paths"]
