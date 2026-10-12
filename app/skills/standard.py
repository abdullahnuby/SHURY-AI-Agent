"""Open Agent Skills package reader/validator with progressive disclosure.

Implements the stable parts of the Agent Skills directory format without third-party
YAML dependencies. External packages are data until explicitly imported and approved.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json
import re

NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
MAX_SKILL_MD = 600_000
MAX_INSTRUCTION_LINES = 500
DANGEROUS = [
    ("shell-execution", re.compile(r"\b(?:subprocess|os\.system|shell\s*=\s*true|eval\s*\(|exec\s*\()", re.I), "high"),
    ("destructive-command", re.compile(r"\b(?:rm\s+-rf|del\s+/|format\s+disk|shutdown|reboot)\b", re.I), "critical"),
    ("credential-access", re.compile(r"\b(?:aws_secret|api[_-]?key|password|private[_-]?key|token)\b", re.I), "high"),
    ("remote-fetch", re.compile(r"\b(?:curl|wget|Invoke-WebRequest|requests\.(?:get|post))\b", re.I), "medium"),
]

@dataclass(frozen=True)
class SkillPackage:
    root: str
    name: str
    description: str
    license: str | None
    compatibility: str | None
    metadata: dict[str, str]
    allowed_tools: tuple[str, ...]
    body: str
    references: tuple[str, ...]
    scripts: tuple[str, ...]
    assets: tuple[str, ...]
    workflow: dict | None
    sha256: str

    @property
    def instruction_lines(self) -> int:
        return len(self.body.splitlines())


def _scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _frontmatter(text: str) -> tuple[dict, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md must start with YAML frontmatter")
    end = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
    if end is None:
        raise ValueError("missing YAML frontmatter terminator")
    meta: dict = {}
    nested = None
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()
        if indent and nested:
            if ":" not in line:
                raise ValueError(f"invalid nested frontmatter: {raw}")
            k, v = line.split(":", 1)
            meta[nested][k.strip()] = _scalar(v)
            continue
        if ":" not in line:
            raise ValueError(f"invalid frontmatter line: {raw}")
        k, v = line.split(":", 1)
        k = k.strip(); v = v.strip()
        if not v:
            meta[k] = {}
            nested = k
        else:
            meta[k] = _scalar(v)
            nested = None
    return meta, "\n".join(lines[end + 1:])


def _list_files(root: Path, folder: str) -> tuple[str, ...]:
    p = root / folder
    if not p.is_dir():
        return ()
    out = []
    for item in p.rglob("*"):
        if item.is_file():
            out.append(item.relative_to(root).as_posix())
    return tuple(sorted(out))


def _sha256(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def validate_skill_package(path: str | Path) -> dict:
    root = Path(path).expanduser().resolve()
    skill_md = root / "SKILL.md"
    errors: list[str] = []
    warnings: list[str] = []
    if not root.is_dir():
        return {"valid": False, "errors": [f"not a directory: {root}"], "warnings": []}
    if not skill_md.is_file():
        return {"valid": False, "errors": ["missing SKILL.md"], "warnings": []}
    if skill_md.stat().st_size > MAX_SKILL_MD:
        errors.append(f"SKILL.md exceeds {MAX_SKILL_MD} bytes")
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    try:
        fm, body = _frontmatter(text)
    except Exception as exc:
        return {"valid": False, "errors": [str(exc)], "warnings": []}
    name = str(fm.get("name", ""))
    desc = str(fm.get("description", ""))
    if not NAME_RE.fullmatch(name):
        errors.append("name must be lowercase alphanumeric/hyphen, 1-64 chars, no consecutive hyphens")
    if name != root.name:
        errors.append("name must match parent directory name")
    if not (1 <= len(desc) <= 1024):
        errors.append("description must be 1-1024 characters")
    compat = fm.get("compatibility")
    if compat is not None and not (1 <= len(str(compat)) <= 500):
        errors.append("compatibility must be 1-500 characters")
    md_lines = body.splitlines()
    if len(md_lines) > MAX_INSTRUCTION_LINES:
        warnings.append(f"instruction body is {len(md_lines)} lines; progressive disclosure recommends <= {MAX_INSTRUCTION_LINES}")
    metadata = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
    allowed = tuple(x for x in re.split(r"\s+", str(fm.get("allowed-tools", "")).strip()) if x)
    workflow_path = root / "workflow.json"
    workflow = None
    if workflow_path.exists():
        try:
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            if not isinstance(workflow, dict):
                errors.append("workflow.json must contain an object")
        except Exception as exc:
            errors.append(f"workflow.json invalid: {exc}")
    findings = []
    for label, rx, severity in DANGEROUS:
        if rx.search(text):
            findings.append({"finding": label, "severity": severity, "file": "SKILL.md"})
    for rel in _list_files(root, "scripts"):
        p = root / rel
        try:
            content = p.read_text(encoding="utf-8", errors="replace")[:250_000]
        except Exception:
            content = ""
        for label, rx, severity in DANGEROUS:
            if rx.search(content):
                findings.append({"finding": label, "severity": severity, "file": rel})
    for f in findings:
        if f["severity"] in {"critical", "high"}:
            warnings.append(f"{f['severity']} risk: {f['finding']} in {f['file']}")
    if (root / "scripts").is_dir() and not allowed:
        warnings.append("scripts/ present without allowed-tools declaration")
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "name": name,
        "description": desc,
        "license": fm.get("license"),
        "compatibility": compat,
        "metadata": metadata,
        "allowed_tools": list(allowed),
        "instruction_lines": len(md_lines),
        "references": list(_list_files(root, "references")),
        "scripts": list(_list_files(root, "scripts")),
        "assets": list(_list_files(root, "assets")),
        "workflow_present": workflow is not None,
        "security_findings": findings,
        "sha256": _sha256(text),
    }


def load_skill(path: str | Path, *, level: str = "metadata") -> SkillPackage:
    root = Path(path).expanduser().resolve()
    skill_md = root / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    fm, body = _frontmatter(text)
    name = str(fm.get("name", root.name))
    description = str(fm.get("description", ""))
    license_value = fm.get("license")
    compatibility = fm.get("compatibility")
    metadata = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
    allowed = tuple(x for x in re.split(r"\s+", str(fm.get("allowed-tools", "")).strip()) if x)
    body_loaded = body if level in {"full", "resources"} else ""
    workflow = None
    if level == "resources" and (root / "workflow.json").exists():
        workflow = json.loads((root / "workflow.json").read_text(encoding="utf-8"))
    return SkillPackage(str(root), name, description, license_value, compatibility,
                        {str(k): str(v) for k, v in metadata.items()}, allowed,
                        body_loaded, _list_files(root, "references"), _list_files(root, "scripts"),
                        _list_files(root, "assets"), workflow, _sha256(text))
