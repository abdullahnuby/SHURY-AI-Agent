"""Deterministic procedural SkillBank for the Personal Agent.

Skills are structured, versioned workflow contracts. They are never executable
by themselves; they can only expand into registered tools that still satisfy the
current planning/policy/verification contracts.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "skills.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'candidate',
    triggers TEXT NOT NULL DEFAULT '[]',
    contraindications TEXT NOT NULL DEFAULT '[]',
    preconditions TEXT NOT NULL DEFAULT '[]',
    workflow TEXT NOT NULL DEFAULT '[]',
    termination TEXT NOT NULL DEFAULT '',
    outputs TEXT NOT NULL DEFAULT '[]',
    evidence TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 0.5,
    trust_level TEXT NOT NULL DEFAULT 'local',
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'runtime',
    source_run_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    content_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skills_status ON skills(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_skills_source ON skills(source);
"""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _tokens(text: str) -> set[str]:
    n = re.sub(r"\s+", " ", str(text).casefold()).strip()
    return set(re.findall(r"[\w\u0600-\u06ff]+", n, flags=re.UNICODE))


@dataclass(frozen=True)
class SkillCandidate:
    key: str
    name: str
    version: int
    status: str
    triggers: tuple[str, ...]
    contraindications: tuple[str, ...]
    preconditions: tuple[str, ...]
    workflow: tuple[dict, ...]
    termination: str
    outputs: tuple[str, ...]
    evidence: tuple[dict, ...]
    confidence: float
    success_count: int
    failure_count: int
    source: str
    source_run_id: str | None
    updated_at: str

    @property
    def utility(self) -> float:
        total = self.success_count + self.failure_count
        if total <= 0:
            return self.confidence * 0.5
        empirical = self.success_count / total
        # Conservative shrinkage toward prior confidence.
        return 0.35 * self.confidence + 0.65 * empirical


class SkillBank:
    def __init__(self, path=None):
        configured = path or __import__("os").environ.get("AGENT_SKILLS_DB") or DEFAULT_PATH
        self.path = Path(configured)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        try:
            with conn:
                conn.executescript(SCHEMA)
                cols = {r[1] for r in conn.execute("PRAGMA table_info(skills)").fetchall()}
                if "trust_level" not in cols:
                    conn.execute("ALTER TABLE skills ADD COLUMN trust_level TEXT NOT NULL DEFAULT 'local'")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_skills_trust ON skills(trust_level, updated_at)")
        finally:
            conn.close()

    def _connect(self):
        return sqlite3.connect(self.path)

    @staticmethod
    def _hash(payload: dict) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def upsert(self, *, key: str, name: str, triggers=(), contraindications=(), preconditions=(),
               workflow=(), termination="verified outputs produced or explicit failure",
               outputs=(), evidence=(), confidence=0.5, source="runtime", source_run_id=None,
               status="candidate") -> SkillCandidate:
        payload = {
            "key": key, "name": name, "triggers": list(triggers),
            "contraindications": list(contraindications), "preconditions": list(preconditions),
            "workflow": list(workflow), "termination": termination, "outputs": list(outputs),
            "evidence": list(evidence), "source": source,
        }
        chash = self._hash(payload)
        now = _now()
        existing = self._q("SELECT id,version,success_count,failure_count,status,trust_level FROM skills WHERE key=?", (key,))
        if existing:
            sid, version, success, failure, old_status, old_trust = existing[0]
            # Preserve approval/active lifecycle status across refreshed versions.
            final_status = old_status if old_status in {"approved", "active", "deprecated"} else status
            trust_level = old_trust if old_trust else ("local" if str(source) == "runtime" else "quarantined")
            version = int(version) + 1 if chash != self._q("SELECT content_hash FROM skills WHERE id=?", (sid,))[0][0] else int(version)
            self._q("UPDATE skills SET name=?,version=?,status=?,triggers=?,contraindications=?,preconditions=?,workflow=?,termination=?,outputs=?,evidence=?,confidence=?,source=?,source_run_id=?,updated_at=?,content_hash=?,trust_level=? WHERE id=?",
                    (name, version, final_status, json.dumps(list(triggers), ensure_ascii=False),
                     json.dumps(list(contraindications), ensure_ascii=False), json.dumps(list(preconditions), ensure_ascii=False),
                     json.dumps(list(workflow), ensure_ascii=False, default=str), termination,
                     json.dumps(list(outputs), ensure_ascii=False), json.dumps(list(evidence), ensure_ascii=False, default=str),
                     float(max(0.0, min(1.0, confidence))), source, source_run_id, now, chash, trust_level, sid))
        else:
            self._q("INSERT INTO skills(key,name,version,status,triggers,contraindications,preconditions,workflow,termination,outputs,evidence,confidence,success_count,failure_count,source,source_run_id,created_at,updated_at,content_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (key, name, 1, status, json.dumps(list(triggers), ensure_ascii=False),
                      json.dumps(list(contraindications), ensure_ascii=False), json.dumps(list(preconditions), ensure_ascii=False),
                      json.dumps(list(workflow), ensure_ascii=False, default=str), termination,
                      json.dumps(list(outputs), ensure_ascii=False), json.dumps(list(evidence), ensure_ascii=False, default=str),
                      float(max(0.0, min(1.0, confidence))), 0, 0, source, source_run_id, now, now, chash))
        return self.get(key)

    def _q(self, sql, params=()):
        conn = self._connect()
        try:
            with conn:
                return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def get(self, key: str) -> SkillCandidate:
        rows = self._q("SELECT key,name,version,status,triggers,contraindications,preconditions,workflow,termination,outputs,evidence,confidence,success_count,failure_count,source,source_run_id,updated_at FROM skills WHERE key=?", (key,))
        if not rows:
            raise KeyError(key)
        row = rows[0]
        return SkillCandidate(row[0], row[1], int(row[2]), row[3], tuple(json.loads(row[4])),
                              tuple(json.loads(row[5])), tuple(json.loads(row[6])), tuple(json.loads(row[7])),
                              row[8], tuple(json.loads(row[9])), tuple(json.loads(row[10])), float(row[11]),
                              int(row[12]), int(row[13]), row[14], row[15], row[16])

    def list(self, status: str | None = None) -> list[SkillCandidate]:
        # Fetch complete rows in one connection. Skill retrieval sits on the hot planning
        # path, so the previous N+1 ``SELECT key`` + ``get(key)`` pattern became visible
        # once structural skill matching was evaluated for every TaskIR request.
        sql = (
            "SELECT key,name,version,status,triggers,contraindications,preconditions,workflow,"
            "termination,outputs,evidence,confidence,success_count,failure_count,source,source_run_id,updated_at FROM skills"
        )
        params = ()
        if status:
            sql += " WHERE status=?"
            params = (status,)
        sql += " ORDER BY updated_at DESC, id DESC"
        rows = self._q(sql, params)
        return [SkillCandidate(
            row[0], row[1], int(row[2]), row[3], tuple(json.loads(row[4])),
            tuple(json.loads(row[5])), tuple(json.loads(row[6])), tuple(json.loads(row[7])),
            row[8], tuple(json.loads(row[9])), tuple(json.loads(row[10])), float(row[11]),
            int(row[12]), int(row[13]), row[14], row[15], row[16]
        ) for row in rows]

    def match(self, goal: str, limit: int = 5) -> list[SkillCandidate]:
        gt = _tokens(goal)
        scored = []
        for skill in self.list():
            if skill.status not in {"approved", "active"}:
                continue
            bad = set().union(*(_tokens(x) for x in skill.contraindications)) if skill.contraindications else set()
            if gt & bad:
                continue
            terms = set().union(*(_tokens(x) for x in skill.triggers)) if skill.triggers else set()
            overlap = len(gt & terms) / max(1, len(gt))
            exact = 1.0 if any(_tokens(x) and _tokens(x).issubset(gt) for x in skill.triggers) else 0.0
            differential = self.adaptive_evidence(skill.key)
            delta_bonus = max(-0.20, min(0.30, float(differential.get("mean_delta", 0.0))))
            trust_penalty = 0.10 if self.trust(skill.key) == "restricted" else 0.0
            # Stage 1 = recall. Stage 2 = compatibility with the requested workflow and
            # contraindications, inspired by current skill-routing work where top-K
            # correctness depends on the selected set, not isolated relevance.
            capability_tokens = _tokens(" ".join(skill.triggers + skill.outputs + skill.preconditions))
            compatibility = len(gt & capability_tokens) / max(1, len(gt))
            score = (0.44 * overlap + 0.14 * exact + 0.17 * skill.utility +
                     0.12 * compatibility + 0.15 * delta_bonus - trust_penalty)
            scored.append((score, overlap, compatibility, skill))
        scored.sort(key=lambda x: (-x[0], -x[1], -x[2], x[3].key))
        return [s[3] for s in scored[:limit]]


    def match_task_ir(self, task_ir, limit: int = 5) -> list[SkillCandidate]:
        """Match verified skills to a structured task, not just its wording.

        The primary signal is the ordered capability sequence stored in the learned
        workflow. Lexical overlap remains a secondary tie-breaker so an experience
        can generalize across paraphrases without allowing an unrelated skill to win.
        """
        nodes = list(getattr(task_ir, "nodes", []) or [])
        target_caps = [str(getattr(n, "capability", "") or getattr(n, "intent", "")) for n in nodes]
        target_caps = [x.casefold().strip() for x in target_caps if x.strip()]
        target_text = str(getattr(task_ir, "original", "") or getattr(task_ir, "objective", ""))
        target_tokens = _tokens(target_text)
        if not target_caps:
            return self.match(target_text, limit=limit)

        def sequence_score(skill: SkillCandidate) -> float:
            skill_caps = [str(item.get("capability", "") or "").casefold().strip()
                          for item in skill.workflow if isinstance(item, dict)]
            skill_caps = [x for x in skill_caps if x]
            if not skill_caps:
                return 0.0
            exact_pairs = sum(1 for a, b in zip(target_caps, skill_caps) if a == b)
            exact = exact_pairs / max(len(target_caps), len(skill_caps))
            # Ordered subsequence similarity tolerates a learned method that has an
            # extra verification step while still respecting procedure order.
            i = 0
            for cap in skill_caps:
                if i < len(target_caps) and cap == target_caps[i]:
                    i += 1
            subseq = i / max(1, len(target_caps))
            lexical = len(target_tokens & _tokens(" ".join(skill.triggers))) / max(1, len(target_tokens))
            return 0.60 * exact + 0.25 * subseq + 0.15 * lexical

        structural_candidates = []
        for skill in self.list():
            if skill.status not in {"approved", "active"}:
                continue
            bad = set().union(*(_tokens(x) for x in skill.contraindications)) if skill.contraindications else set()
            if target_tokens & bad:
                continue
            structural = sequence_score(skill)
            if structural < 0.35:
                continue
            structural_candidates.append((structural, skill))
        structural_candidates.sort(key=lambda x: (-x[0], x[1].key))

        # Evidence/lifecycle lookups are substantially more expensive than the pure
        # structural filter. Evaluate them only for the strongest few candidates.
        scored = []
        for structural, skill in structural_candidates[: max(limit * 2, 8)]:
            differential = self.adaptive_evidence(skill.key)
            delta_bonus = max(-0.15, min(0.25, float(differential.get("mean_delta", 0.0))))
            score = structural * 0.80 + 0.15 * skill.utility + 0.05 * delta_bonus
            scored.append((score, structural, skill))
        scored.sort(key=lambda x: (-x[0], -x[1], x[2].key))
        return [x[2] for x in scored[:limit]]

    def set_status(self, key: str, status: str):
        if status not in {"candidate", "approved", "active", "deprecated"}:
            raise ValueError("invalid skill status")
        rows = self._q("SELECT trust_level,status FROM skills WHERE key=?", (key,))
        if not rows:
            raise KeyError(key)
        trust, current_status = rows[0]
        if status == "approved" and trust not in {"trusted", "local"}:
            raise PermissionError("approval requires trusted or local skill provenance")
        if status == "active" and trust not in {"trusted", "local"}:
            raise PermissionError("skill trust level does not permit activation")
        if trust == "blocked" and status != "candidate":
            raise PermissionError("blocked skill cannot be promoted")
        self._q("UPDATE skills SET status=?,updated_at=? WHERE key=?", (status, _now(), key))

    def set_trust(self, key: str, trust_level: str):
        allowed = {"local", "quarantined", "restricted", "trusted", "blocked"}
        if trust_level not in allowed:
            raise ValueError("invalid trust level")
        rows = self._q("SELECT status FROM skills WHERE key=?", (key,))
        if not rows:
            raise KeyError(key)
        # Downgrading provenance must immediately remove runtime activation.
        status = rows[0][0]
        next_status = "candidate" if trust_level in {"quarantined", "restricted", "blocked"} and status in {"approved", "active"} else status
        self._q("UPDATE skills SET trust_level=?,status=?,updated_at=? WHERE key=?", (trust_level, next_status, _now(), key))

    def trust(self, key: str) -> str:
        rows = self._q("SELECT trust_level FROM skills WHERE key=?", (key,))
        if not rows:
            raise KeyError(key)
        return rows[0][0]

    def adaptive_evidence(self, key: str) -> dict:
        try:
            from app.skills.evaluation import summary, lifecycle_recommendation
            return lifecycle_recommendation(key, path=self.path)
        except Exception:
            return {"skill_key": key, "count": 0, "mean_delta": 0.0, "recommendation": "observe"}

    def apply_differential_lifecycle(self, key: str) -> dict:
        from app.skills.evaluation import lifecycle_recommendation
        recommendation = lifecycle_recommendation(key, path=self.path)
        current = self.get(key)
        action = "observe"
        if recommendation.get("recommendation") == "promote":
            trust = self.trust(key)
            if current.status == "candidate" and trust in {"local", "trusted"}:
                self.set_status(key, "active")
                action = "promote"
            elif trust in {"quarantined", "restricted"}:
                action = "approval-required"
        elif recommendation.get("recommendation") == "demote" and current.status == "active":
            self.set_status(key, "candidate")
            action = "demote"
        return {"key": key, "before": current.status, "after": self.get(key).status, "action": action,
                "trust": self.trust(key), "evidence": recommendation}

    def record_outcome(self, key: str, success: bool):
        current = self._q("SELECT success_count,failure_count,status FROM skills WHERE key=?", (key,))
        if not current:
            return
        ok_count, fail_count = int(current[0][0]), int(current[0][1])
        status = current[0][2]
        ok_count += 1 if success else 0
        fail_count += 0 if success else 1
        total = ok_count + fail_count
        next_status = status
        # Lifecycle policy: repeated independently-verified success can promote a
        # candidate automatically; repeated failure can demote an active skill.
        if ok_count >= 3 and fail_count == 0 and status == "candidate":
            next_status = "active"
        elif total >= 3 and fail_count / max(1, total) >= 0.40 and status == "active":
            next_status = "candidate"
        # Never auto-promote an external/quarantined/restricted skill. Evidence can improve
        # the candidate, but trust remains an independent gate.
        trust = self.trust(key)
        if next_status == "active" and trust not in {"local", "trusted"}:
            next_status = "candidate"
        self._q("UPDATE skills SET success_count=?, failure_count=?, status=?, updated_at=? WHERE key=?",
                 (ok_count, fail_count, next_status, _now(), key))

    def export_manifest(self) -> list[dict]:
        return [asdict(s) for s in self.list()]
