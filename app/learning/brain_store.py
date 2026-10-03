from __future__ import annotations

"""Compatibility facade for SHURY's single canonical learning store.

Historically this module owned ``brain.db`` and a parallel capability schema. That is
no longer allowed in production. Capability priors, procedures and execution evidence
now share ``LearningStore``. The facade remains only so old imports/CLI commands keep
working while callers migrate to ``LearningStore`` directly.
"""

import json
import os
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .store import LearningStore, DEFAULT_PATH as LEARNING_DB, _connect

DEFAULT_PATH = LEARNING_DB
LEGACY_BRAIN_PATH = Path(__file__).resolve().parents[1] / "data" / "brain.db"

TOKEN_RE = re.compile(r"[\w\u0600-\u06ff]+", re.UNICODE)
STOP = {
    "the","a","an","to","for","of","and","or","is","my","me","what","how","should","i","you",
    "in","on","this","that","do","can","please","could","find","show","tell","about","use","using",
    "من","في","على","إلى","عن","ما","هو","ايه","كيف","لي","أنا","انا","ممكن","اعمل","نفذ","ثم","و",
}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _tokens(text: str) -> list[str]:
    out = []
    for token in TOKEN_RE.findall(str(text or "").casefold()):
        if token in STOP or len(token) < 2:
            continue
        if token not in out:
            out.append(token)
    return out


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class BrainKnowledgeStore:
    """Legacy facade backed by the canonical ``LearningStore`` database.

    ``path`` is retained as a test-isolation/compatibility argument, but it is a
    LearningStore path now, not a parallel brain schema. Production defaults to
    ``AGENT_LEARNING_DB`` or the canonical ``learning.db``.
    """

    def __init__(self, path: str | Path | None = None):
        canonical_path = Path(path or os.environ.get("AGENT_LEARNING_DB") or LEARNING_DB)
        self.store = LearningStore(canonical_path)
        self.path = canonical_path
        self._cap_cache: list[dict[str, Any]] | None = None
        self._proc_cache: list[dict[str, Any]] | None = None
        self._migrate_legacy_capability_priors()

    @staticmethod
    def compatible_seed_record(record: dict[str, Any], registry: dict[str, Any]) -> tuple[bool, str]:
        required = list(record.get("required_tools") or record.get("tool_order") or [])
        if not required:
            return False, "missing-tool-order"
        if any(name not in registry for name in required):
            return False, "tool-not-installed"
        cap = str(record.get("capability") or "").casefold().strip()
        tools = [registry[name] for name in required]
        if len(required) == 1:
            tool_cap = str(getattr(tools[0], "capability", "") or required[0]).casefold().strip()
            if cap and cap not in {tool_cap, str(required[0]).casefold().strip()}:
                return False, "capability-tool-mismatch"
        return True, "compatible"

    def ingest_records(self, records: Iterable[dict[str, Any]], *, source: str,
                       registry: dict[str, Any] | None = None) -> dict[str, Any]:
        registry = registry or {}
        cap_groups: dict[tuple[str, str], dict[str, Any]] = {}
        seen = accepted = rejected = 0
        reject_reasons = Counter()
        for record in records:
            if not isinstance(record, dict):
                continue
            seen += 1
            if registry:
                ok, reason = self.compatible_seed_record(record, registry)
                if not ok:
                    rejected += 1
                    reject_reasons[reason] += 1
                    continue
            domain = str(record.get("domain") or "general").strip() or "general"
            capability = str(record.get("capability") or "").strip()
            if not capability:
                rejected += 1
                reject_reasons["missing-capability"] += 1
                continue
            shape = str(record.get("interaction_shape") or "single_turn").strip() or "single_turn"
            goal = str(record.get("goal") or record.get("text") or "").strip()
            tools = tuple(str(x).strip() for x in (record.get("tool_order") or record.get("required_tools") or []) if str(x).strip())
            if not goal or not tools:
                rejected += 1
                reject_reasons["missing-goal-or-tools"] += 1
                continue
            key = (domain, capability)
            group = cap_groups.setdefault(key, {
                "domain": domain, "capability": capability, "examples": 0,
                "phrases": Counter(), "tokens": Counter(), "required_tools": Counter(),
                "interaction_shapes": Counter(), "failure_modes": Counter(), "success_invariants": Counter(),
            })
            group["examples"] += 1
            group["phrases"][goal] += 1
            group["tokens"].update(_tokens(goal))
            group["required_tools"].update(tools)
            group["interaction_shapes"][shape] += 1
            group["failure_modes"].update(str(x) for x in (record.get("failure_modes") or []) if str(x).strip())
            group["success_invariants"].update(str(x) for x in (record.get("success_invariants") or []) if str(x).strip())
            accepted += 1

        conn = _connect(self.store.path)
        try:
            with conn:
                for (domain, capability), group in cap_groups.items():
                    key = f"cap:{domain}:{capability}"
                    existing = conn.execute(
                        "SELECT examples,phrases,tokens,required_tools,interaction_shapes,failure_modes,success_invariants FROM capability_priors WHERE key=?",
                        (key,),
                    ).fetchone()
                    old = {}
                    if existing:
                        old = {
                            "examples": int(existing[0] or 0),
                            "phrases": json.loads(existing[1] or "[]"),
                            "tokens": json.loads(existing[2] or "[]"),
                            "required_tools": json.loads(existing[3] or "[]"),
                            "interaction_shapes": json.loads(existing[4] or "[]"),
                            "failure_modes": json.loads(existing[5] or "[]"),
                            "success_invariants": json.loads(existing[6] or "[]"),
                        }
                    examples = old.get("examples", 0) + group["examples"]

                    def merged(counter, previous, limit=64):
                        ordered = [str(x) for x in previous]
                        ordered.extend(str(x) for x, _ in counter.most_common(limit))
                        return list(dict.fromkeys(x for x in ordered if x))[:limit]

                    confidence = min(0.82, 0.35 + 0.012 * (examples ** 0.5))
                    row = (
                        key, domain, capability, examples,
                        _json(merged(group["phrases"], old.get("phrases", []), 24)),
                        _json(merged(group["tokens"], old.get("tokens", []), 48)),
                        _json(merged(group["required_tools"], old.get("required_tools", []), 24)),
                        _json(merged(group["interaction_shapes"], old.get("interaction_shapes", []), 8)),
                        _json(merged(group["failure_modes"], old.get("failure_modes", []), 16)),
                        _json(merged(group["success_invariants"], old.get("success_invariants", []), 16)),
                        confidence, source, _now(),
                    )
                    conn.execute(
                        "INSERT INTO capability_priors(key,domain,capability,examples,phrases,tokens,required_tools,interaction_shapes,failure_modes,success_invariants,confidence,source,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(key) DO UPDATE SET examples=excluded.examples,phrases=excluded.phrases,tokens=excluded.tokens,required_tools=excluded.required_tools,interaction_shapes=excluded.interaction_shapes,failure_modes=excluded.failure_modes,success_invariants=excluded.success_invariants,confidence=excluded.confidence,source=excluded.source,updated_at=excluded.updated_at",
                        row,
                    )
                conn.execute(
                    "INSERT INTO capability_meta(key,value) VALUES('last_source',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (source,),
                )
                conn.execute(
                    "INSERT INTO capability_meta(key,value) VALUES('last_ingest',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (_now(),),
                )
        finally:
            conn.close()
        self._cap_cache = None
        return {
            "source": source, "seen": seen, "accepted": accepted, "rejected": rejected,
            "reject_reasons": dict(reject_reasons), "capability_priors": len(cap_groups),
            "procedure_priors": self.store.procedural_memory_stats().get("memories", 0),
        }

    def _load_caps(self) -> list[dict[str, Any]]:
        if self._cap_cache is not None:
            return self._cap_cache
        conn = _connect(self.store.path)
        try:
            rows = conn.execute(
                "SELECT key,domain,capability,examples,phrases,tokens,required_tools,interaction_shapes,failure_modes,success_invariants,confidence,source FROM capability_priors"
            ).fetchall()
        finally:
            conn.close()
        self._cap_cache = [
            {
                "key": r[0], "domain": r[1], "capability": r[2], "examples": int(r[3]),
                "phrases": json.loads(r[4] or "[]"), "tokens": json.loads(r[5] or "[]"),
                "required_tools": json.loads(r[6] or "[]"), "interaction_shapes": json.loads(r[7] or "[]"),
                "failure_modes": json.loads(r[8] or "[]"), "success_invariants": json.loads(r[9] or "[]"),
                "confidence": float(r[10]), "source": r[11],
            }
            for r in rows
        ]
        return self._cap_cache

    def _migrate_legacy_capability_priors(self) -> None:
        """One-time import from the pre-unification brain.db without creating a new schema."""
        legacy = Path(os.environ.get("AGENT_LEGACY_BRAIN_DB") or LEGACY_BRAIN_PATH)
        if legacy.resolve() == self.path.resolve() or not legacy.exists():
            return
        conn = None
        try:
            conn = sqlite3.connect(legacy, timeout=5)
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='capability_priors'"
            ).fetchone()
            if not exists:
                return
            rows = conn.execute(
                "SELECT key,domain,capability,examples,phrases,tokens,required_tools,interaction_shapes,failure_modes,success_invariants,confidence,source,updated_at FROM capability_priors"
            ).fetchall()
        except sqlite3.Error:
            return
        finally:
            if conn is not None:
                conn.close()
        target = _connect(self.store.path)
        try:
            with target:
                marker = target.execute(
                    "SELECT value FROM capability_meta WHERE key='legacy_brain_migration_v1'"
                ).fetchone()
                if marker:
                    return
                for row in rows:
                    target.execute(
                        "INSERT INTO capability_priors(key,domain,capability,examples,phrases,tokens,required_tools,interaction_shapes,failure_modes,success_invariants,confidence,source,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(key) DO NOTHING",
                        row,
                    )
                target.execute(
                    "INSERT INTO capability_meta(key,value) VALUES('legacy_brain_migration_v1',?)",
                    (_now(),),
                )
        finally:
            target.close()

    @staticmethod
    def _score_text(query: str, candidate: dict[str, Any]) -> float:
        q = set(_tokens(query))
        if not q:
            return 0.0
        tokens = set(candidate.get("tokens") or [])
        phrases = candidate.get("phrases") or []
        phrase_tokens = set(_tokens(" ".join(phrases[:12])))
        overlap = len(q & tokens) / max(1, len(q))
        phrase_overlap = len(q & phrase_tokens) / max(1, len(q))
        cap_tokens = set(_tokens(candidate.get("capability", "").replace("_", " ")))
        cap_overlap = len(q & cap_tokens) / max(1, len(q))
        return 0.58 * overlap + 0.27 * phrase_overlap + 0.15 * cap_overlap

    def match_capabilities(self, query: str, *, registry: dict[str, Any] | None = None, limit: int = 6) -> list[dict[str, Any]]:
        registry = registry or {}
        results = []
        for item in self._load_caps():
            available_tools = [x for x in item["required_tools"] if x in registry] if registry else item["required_tools"]
            availability = len(available_tools) / max(1, len(item["required_tools"]))
            lexical = self._score_text(query, item)
            score = 0.78 * lexical + 0.22 * availability
            if score < 0.18:
                continue
            results.append({**item, "score": round(score, 4), "available_tools": available_tools})
        results.sort(key=lambda x: (-x["score"], -x["examples"], x["capability"]))
        return results[:max(1, int(limit))]

    def match_procedures(self, query: str, *, registry: dict[str, Any] | None = None, capability: str | None = None,
                         limit: int = 6, min_steps: int = 2) -> list[dict[str, Any]]:
        registry = registry or {}
        from .procedures import task_family_signature
        family = task_family_signature(query)
        results = []
        for item in self.store.procedural_memories(limit=500):
            workflow = [x.get("tool") if isinstance(x, dict) else str(x) for x in item.get("workflow", [])]
            workflow = [str(x) for x in workflow if x]
            if len(workflow) < min_steps or (registry and any(x not in registry for x in workflow)):
                continue
            family_match = 1.0 if item.get("task_family_signature") == family else 0.0
            cap_match = 0.0
            if capability:
                cap_match = 1.0 if str(capability).casefold().strip() == str(item.get("capability") or "").casefold().strip() else 0.0
            lexical = self._score_text(query, {**item, "phrases": item.get("trigger_conditions", [])})
            score = 0.68 * family_match + 0.18 * cap_match + 0.09 * lexical + 0.05 * min(1.0, float(item.get("successes", 0)) / 10.0)
            if score < 0.12:
                continue
            results.append({**item, "score": round(score, 4), "capability_affinity": cap_match, "tool_overlap": lexical})
        results.sort(key=lambda x: (-x["score"], -int(x.get("successes", 0)), x["key"]))
        return results[:max(1, int(limit))]

    def stats(self) -> dict[str, Any]:
        conn = _connect(self.store.path)
        try:
            caps = int(conn.execute("SELECT COUNT(*) FROM capability_priors").fetchone()[0])
            examples = int(conn.execute("SELECT COALESCE(SUM(examples),0) FROM capability_priors").fetchone()[0])
            last_source = conn.execute("SELECT value FROM capability_meta WHERE key='last_source'").fetchone()
            last_ingest = conn.execute("SELECT value FROM capability_meta WHERE key='last_ingest'").fetchone()
        finally:
            conn.close()
        proc_stats = self.store.procedural_memory_stats()
        return {
            "path": str(self.path), "canonical_learning_store": True,
            "capability_priors": caps, "procedure_priors": proc_stats["memories"],
            "indexed_examples": examples,
            "last_source": last_source[0] if last_source else None,
            "last_ingest": last_ingest[0] if last_ingest else None,
        }


__all__ = ["BrainKnowledgeStore", "DEFAULT_PATH", "LEGACY_BRAIN_PATH"]
