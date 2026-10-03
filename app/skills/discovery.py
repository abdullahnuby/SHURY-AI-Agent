"""Remote Agent Skill discovery, acquisition, auditing, and refresh.

V21 turns open-world research into a real skill supply chain:
  discover -> inspect metadata -> materialize bounded package -> validate -> quarantine
  -> benchmark/observe -> explicit activation -> refresh with upstream provenance.

Remote content is never executed during acquisition.  Only the existing governed
SkillBank controls activation and runtime reuse.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib
import json
import re
import shutil
import time
from urllib.parse import quote

from app.integrations.network import NetworkGateway
from app.skills.standard import validate_skill_package, load_skill
from app.skills.governance import assess_skill
from app.skills.research import import_package

DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "data" / "external_skills"
DEFAULT_MANIFEST = DEFAULT_ROOT / "registry.json"

CURATED_REPOSITORIES = (
    "vercel-labs/agent-skills",
    "langchain-ai/langchain-skills",
    "NVIDIA/skills",
    "elastic/agent-skills",
    "VectorSpaceLab/AREX-Skill",
)

SKILL_FILE_NAMES = {"SKILL.md", "SKILL.MD"}
MAX_PACKAGE_FILES = 120
MAX_PACKAGE_BYTES = 4_000_000
MAX_SINGLE_FILE_BYTES = 600_000


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _safe_name(value: str, fallback: str = "skill") -> str:
    raw = re.sub(r"[^a-z0-9._-]+", "-", str(value).casefold()).strip(".-_")
    return raw[:90] or fallback


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _skill_key(repo: str, skill_path: str) -> str:
    return "remote:" + _sha(f"{repo}:{skill_path}")[:20]


def _skill_root_from_path(skill_path: str) -> str:
    value = skill_path.replace("\\", "/").strip("/")
    if value.lower().endswith("/skill.md"):
        return value[: -len("/SKILL.md")].strip("/") or "."
    return value.rsplit("/", 1)[0] if "/" in value else "."


@dataclass(frozen=True)
class DiscoveredSkill:
    repository: str
    branch: str
    skill_path: str
    url: str
    name: str
    description: str
    source_kind: str = "github-skill"


class SkillDiscovery:
    def __init__(self, gateway: NetworkGateway | None = None, root=DEFAULT_ROOT, manifest=DEFAULT_MANIFEST):
        self.gateway = gateway or NetworkGateway()
        self.root = Path(root)
        self.manifest = Path(manifest)
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest.parent.mkdir(parents=True, exist_ok=True)

    def _load_manifest(self) -> dict:
        if not self.manifest.exists():
            return {"version": 1, "skills": {}}
        try:
            return json.loads(self.manifest.read_text(encoding="utf-8"))
        except Exception:
            return {"version": 1, "skills": {}}

    def _save_manifest(self, data: dict):
        tmp = self.manifest.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.manifest)

    @staticmethod
    def _matches(path: str) -> bool:
        return Path(path).name in SKILL_FILE_NAMES

    def scan_repository(self, repo: str, *, max_skills: int = 80) -> list[DiscoveredSkill]:
        meta = self.gateway.github_repo(repo)
        branch = meta.get("default_branch") or "HEAD"
        tree = self.gateway.github_tree_recursive(repo, branch, limit=5000)
        out: list[DiscoveredSkill] = []
        for item in tree:
            path = str(item.get("path") or "")
            if not self._matches(path):
                continue
            if "/node_modules/" in f"/{path}" or "/.git/" in f"/{path}":
                continue
            try:
                file = self.gateway.github_file(repo, path, branch)
                text = file["text"]
            except Exception:
                text = ""
            name = _safe_name(Path(path).parent.name, fallback="remote-skill")
            description = ""
            if text:
                try:
                    info = validate_skill_package_from_text(name, text)
                    name = info.get("name") or name
                    description = info.get("description") or ""
                except Exception:
                    description = ""
            out.append(DiscoveredSkill(repository=repo, branch=branch, skill_path=path,
                                       url=f"https://github.com/{repo}/blob/{quote(branch, safe='')}/{quote(path, safe='/')}",
                                       name=name, description=description))
            if len(out) >= max_skills:
                break
        return out

    def discover(self, query: str, *, repositories: tuple[str, ...] = CURATED_REPOSITORIES,
                 repo_limit: int = 8, max_skills: int = 40) -> dict:
        q = str(query or "").strip()
        repos: list[dict] = []
        seen = set()
        search_terms = [
            f"{q} agent skills" if q else "agent skills",
            f"{q} SKILL.md" if q else "SKILL.md agent skills",
        ]
        for term in search_terms:
            try:
                rows = self.gateway.github_search_repositories(term, limit=repo_limit)
            except Exception:
                rows = []
            for row in rows:
                repo = row.get("full_name")
                if repo and repo not in seen:
                    repos.append(row); seen.add(repo)
        for repo in repositories:
            if repo not in seen:
                repos.append({"full_name": repo, "description": "curated Agent Skills source", "html_url": f"https://github.com/{repo}"})
                seen.add(repo)
        skills: list[dict] = []
        for row in repos[:max(1, repo_limit + len(repositories))]:
            repo = row.get("full_name")
            if not repo:
                continue
            try:
                found = self.scan_repository(repo, max_skills=max_skills - len(skills))
            except Exception as exc:
                found = []
                row = dict(row); row["error"] = str(exc)
            for item in found:
                skills.append(asdict(item))
                if len(skills) >= max_skills:
                    break
            if len(skills) >= max_skills:
                break
        return {"query": q, "repositories_considered": repos[:len(seen)],
                "skills": skills, "count": len(skills),
                "policy": "GitHub discovery is read-only; skills remain external until bounded materialization + audit"}

    def _write_file(self, base: Path, rel: str, text: str, total_state: list[int]):
        if len(text.encode("utf-8", errors="replace")) > MAX_SINGLE_FILE_BYTES:
            raise ValueError(f"file exceeds per-file limit: {rel}")
        raw_size = len(text.encode("utf-8", errors="replace"))
        total_state[0] += raw_size
        total_state[1] += 1
        if total_state[0] > MAX_PACKAGE_BYTES:
            raise ValueError("skill package exceeds total byte limit")
        if total_state[1] > MAX_PACKAGE_FILES:
            raise ValueError("skill package exceeds total file limit")
        dest = base / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")

    def materialize(self, repo: str, skill_path: str, *, branch: str | None = None) -> dict:
        meta = self.gateway.github_repo(repo)
        branch = branch or meta.get("default_branch") or "HEAD"
        root_rel = _skill_root_from_path(skill_path)
        prefix = "" if root_rel == "." else root_rel.rstrip("/") + "/"
        tree = self.gateway.github_tree_recursive(repo, branch, limit=5000)
        all_paths = [str(x.get("path")) for x in tree if x.get("path")]
        if root_rel == ".":
            candidates = [p for p in all_paths if p == skill_path or
                          p == "workflow.json" or p.startswith("references/") or
                          p.startswith("scripts/") or p.startswith("assets/")]
        else:
            candidates = [p for p in all_paths if p.startswith(prefix)]
        skill_md = skill_path.replace("\\", "/").strip("/")
        if skill_md not in candidates:
            # The recursive tree may be unavailable for very large repos; still require exact SKILL.md.
            candidates = [skill_md]
        key = _skill_key(repo, skill_md)
        try:
            commits = self.gateway._github_json(
                f"https://api.github.com/repos/{repo}/commits?sha={quote(branch, safe='')}&per_page=1")
            source_revision = (commits[0].get("sha") if isinstance(commits, list) and commits else None)
        except Exception:
            source_revision = None
        target = self.root / _safe_name(repo.replace("/", "--")) / _safe_name(Path(skill_md).parent.name or "root")
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
        totals = [0, 0]
        files = []
        for rel in candidates:
            if not rel:
                continue
            lower = rel.casefold()
            # Keep package resources bounded and skip repository-wide noise.
            if any(part in {".git", "node_modules", "__pycache__", ".venv"} for part in Path(rel).parts):
                continue
            if rel != skill_md and not lower.endswith((".md", ".json", ".py", ".sh", ".txt", ".yaml", ".yml", ".toml")):
                continue
            try:
                item = self.gateway.github_file(repo, rel, branch)
                text = item["text"]
            except Exception:
                continue
            local_rel = rel[len(prefix):] if prefix else rel
            if local_rel == "":
                local_rel = Path(rel).name
            self._write_file(target, local_rel, text, totals)
            files.append(local_rel)
        validation = validate_skill_package(target)
        admission = assess_skill(validation, source="github")
        manifest = self._load_manifest()
        family = Path(skill_md).parent.name if Path(skill_md).parent.name else "root"
        area = Path(skill_md).parts[0] if Path(skill_md).parts else "root"
        entry = {
            "key": key, "repository": repo, "branch": branch, "skill_path": skill_md,
            "area": area, "family": family,
            "source_revision": source_revision, "local_path": str(target), "files": files, "validation": validation,
            "admission": asdict(admission), "sha256": validation.get("sha256"),
            "updated_at": _now(), "status": "quarantined" if admission.allowed else "blocked",
        }
        manifest.setdefault("skills", {})[key] = entry
        self._save_manifest(manifest)
        return entry

    def install(self, repo: str, skill_path: str, *, branch: str | None = None, bank_path=None) -> dict:
        materialized = self.materialize(repo, skill_path, branch=branch)
        if not materialized.get("validation", {}).get("valid"):
            return {"installed": False, "reason": "validation_failed", **materialized}
        imported = import_package(materialized["local_path"], source="github", bank_path=bank_path, skill_key=materialized["key"])
        from app.skills.registry import SkillBank
        manifest = self._load_manifest()
        if materialized.get("key") in manifest.get("skills", {}):
            entry = manifest["skills"][materialized["key"]]
            entry["bank_key"] = imported.get("skill", {}).get("key", materialized["key"])
            entry["bank_path"] = str(Path(bank_path).expanduser().resolve()) if bank_path else str(SkillBank().path)
            entry["updated_at"] = _now()
            manifest["skills"][materialized["key"]] = entry
            self._save_manifest(manifest)
        return {"installed": bool(imported.get("imported")), "materialized": materialized, "imported": imported,
                "policy": "remote skill is quarantined/requires approval; no executable activation occurs during discovery"}

    def refresh(self, key: str) -> dict:
        manifest = self._load_manifest()
        entry = manifest.get("skills", {}).get(key)
        if not entry:
            raise KeyError(key)
        refreshed = self.materialize(entry["repository"], entry["skill_path"], branch=entry.get("branch"))
        changed = refreshed.get("sha256") != entry.get("sha256")
        bank_key = entry.get("bank_key", key)
        if changed:
            # A changed upstream artifact is a new artifact. Never preserve trusted/approved
            # activation across a content hash change. Re-audit and re-approve explicitly.
            from app.skills.registry import SkillBank
            try:
                bank = SkillBank(entry.get("bank_path")) if entry.get("bank_path") else SkillBank()
                if bank.get(bank_key):
                    bank.set_trust(bank_key, "quarantined")
                    bank.set_status(bank_key, "candidate")
            except KeyError:
                pass
            manifest = self._load_manifest()
            if key in manifest.get("skills", {}):
                updated = manifest["skills"][key]
                updated["bank_key"] = bank_key
                updated["status"] = "quarantined" if refreshed.get("admission", {}).get("allowed") else "blocked"
                manifest["skills"][key] = updated
                self._save_manifest(manifest)
        return {"key": key, "bank_key": bank_key, "changed": bool(changed), "previous_sha256": entry.get("sha256"),
                "current_sha256": refreshed.get("sha256"), "entry": refreshed,
                "reapproval_required": bool(changed)}

    def list_installed(self) -> list[dict]:
        return list(self._load_manifest().get("skills", {}).values())

    def route(self, query: str = "", *, limit: int = 20) -> dict:
        """Progressive-disclosure router: request -> area -> family -> skill root."""
        q = str(query or "").casefold().strip()
        tokens = {x for x in re.findall(r"[a-z0-9_]+", q) if len(x) > 2}
        rows = []
        for item in self.list_installed():
            text = " ".join([str(item.get("name", "")), str(item.get("description", "")),
                               str(item.get("area", "")), str(item.get("family", "")), str(item.get("skill_path", ""))]).casefold()
            overlap = len(tokens & set(re.findall(r"[a-z0-9_]+", text)))
            rows.append((overlap, item))
        rows.sort(key=lambda x: (-x[0], x[1].get("area", ""), x[1].get("family", ""), x[1].get("skill_path", "")))
        selected = [x for score, x in rows[:max(1, limit)] if score > 0 or not tokens]
        areas = {}
        for item in selected:
            areas.setdefault(item.get("area", "root"), {}).setdefault(item.get("family", "root"), []).append(item.get("key"))
        return {"query": query, "routes": areas, "candidates": selected,
                "policy": "progressive disclosure: route metadata first, package contents only after selection"}

    def approve_and_trust(self, key: str, *, bank_path=None) -> dict:
        from app.skills.registry import SkillBank
        manifest = self._load_manifest()
        entry = manifest.get("skills", {}).get(key)
        effective_bank_path = bank_path or (entry.get("bank_path") if entry else None)
        bank = SkillBank(effective_bank_path) if effective_bank_path else SkillBank()
        if not entry:
            raise KeyError(key)
        validation = entry.get("validation", {})
        if not validation.get("valid"):
            raise ValueError("cannot trust an invalid skill package")
        findings = validation.get("security_findings", [])
        if any(f.get("severity") == "critical" for f in findings):
            raise PermissionError("critical security finding blocks trust promotion")
        bank_key = entry.get("bank_key", key)
        if bank_key not in {s.key for s in bank.list()}:
            # Recovery for manifests created by pre-V21 key mapping: locate the package by
            # its provenance path/hash before failing closed.
            candidates = []
            for skill in bank.list():
                for ev in skill.evidence:
                    if isinstance(ev, dict) and (ev.get("sha256") == validation.get("sha256") or ev.get("path") == entry.get("local_path")):
                        candidates.append(skill.key)
            if len(candidates) == 1:
                bank_key = candidates[0]
            else:
                raise KeyError(f"skill not present in SkillBank: {bank_key}")
        bank.set_trust(bank_key, "trusted")
        bank.set_status(bank_key, "approved")
        # Keep manifest identity stable while recording the actual SkillBank identity.
        manifest = self._load_manifest()
        if key in manifest.get("skills", {}):
            manifest["skills"][key]["bank_key"] = bank_key
            manifest["skills"][key]["status"] = "approved"
            self._save_manifest(manifest)
        return {"key": key, "bank_key": bank_key, "trust": bank.trust(bank_key), "status": bank.get(bank_key).status,
                "verified": True, "policy": "human-reviewed trust promotion; activation remains explicit"}


def validate_skill_package_from_text(name: str, text: str) -> dict:
    """Minimal metadata extraction used before a package is materialized."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {"name": name, "description": ""}
    end = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
    if end is None:
        return {"name": name, "description": ""}
    meta = {}
    for raw in lines[1:end]:
        line = raw.strip()
        if ":" not in line or raw.startswith(" "):
            continue
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip().strip('"\'')
    return {"name": meta.get("name", name), "description": meta.get("description", "")}


def discovery_snapshot(root=DEFAULT_ROOT) -> dict:
    p = Path(root) / "registry.json"
    if not p.exists():
        return {"installed": 0, "path": str(p)}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        skills = data.get("skills", {})
        states = {}
        for v in skills.values():
            state = v.get("status", "unknown")
            states[state] = states.get(state, 0) + 1
        return {"installed": len(skills), "states": states, "path": str(p)}
    except Exception:
        return {"installed": 0, "path": str(p), "corrupt": True}
