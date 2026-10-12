from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.knowledge.seed_policy import CLASSIFICATION, validate_seed_payload

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "seed" / "agent_scenarios_100k.db"

_WORD_RE = re.compile(r"[\w']+", re.UNICODE)

_QUERY_ALIASES = {
    "skill": {"skills", "skill_selection", "skill_management"},
    "skills": {"skills", "skill_selection", "skill_management"},
    "dataset": {"data", "data_analysis"},
    "outlier": {"data", "outliers", "data_analysis"},
    "anomaly": {"data", "diagnose", "data_analysis"},
    "research": {"research", "web_research", "science", "research_ops"},
    "paper": {"science", "arxiv"},
    "rag": {"knowledge", "rag_reasoning", "agentic_rag"},
    "evidence": {"knowledge", "research_ops", "rag_reasoning"},
    "memory": {"memory", "recall_fact", "remember_fact"},
    "file": {"workspace", "documents"},
    "workspace": {"workspace", "documents"},
    "project": {"development", "project_management"},
    "code": {"development", "github"},
    "tests": {"development", "quality_assurance"},
    "github": {"github", "skills"},
    "repo": {"github", "development"},
    "simulate": {"world", "world_simulation"},
    "world": {"world"},
    "state": {"world", "observability"},
    "security": {"security", "quality_assurance"},
    "safe": {"security", "quality_assurance"},
}
_DOMAIN_HINTS = {
    "حلل": {"data"},
    "تحليل": {"data"},
    "بيانات": {"data"},
    "داتا": {"data"},
    "اكتشف": {"data", "knowledge", "research"},
    "قيم": {"data", "quality_assurance"},
    "انحراف": {"data"},
    "outlier": {"data"},
    "outliers": {"data"},
    "anomaly": {"data"},
    "anomalies": {"data"},
    "dataset": {"data"},
    "data": {"data", "data_acquisition"},
    "research": {"research", "web_research", "science", "research_ops"},
    "paper": {"science"},
    "papers": {"science"},
    "memory": {"memory"},
    "skill": {"skills"},
    "skills": {"skills"},
    "github": {"github"},
    "repo": {"github", "development"},
    "project": {"development", "project_management"},
    "workspace": {"workspace", "documents"},
    "file": {"workspace", "documents"},
    "world": {"world"},
    "simulate": {"world"},
    "security": {"security"},
}

_INTENT_RULES = (
    (re.compile(r"\b(?:weather|forecast|temperature|climate|today|current|now)\b|(?:الطقس|الجو|درجه|درجة|الحرارة|اليوم|حاليا|حاليًا)"),
     {"web_research"}, {"web_research", "web_research"}),
    (re.compile(r"\b(?:latest|recent|research|search|look up|find online|internet|web)\b|(?:احدث|أحدث|ابحث|بحث|الانترنت|الويب|على الانترنت)"),
     {"web_research", "research_ops"}, {"research"}),
    (re.compile(r"\b(?:paper|papers|arxiv|academic|scientific)\b|(?:ورقة|اوراق|أوراق|علمي|علمية|ابحاث|أبحاث)"),
     {"science"}, {"research"}),
    (re.compile(r"\b(?:rag|retrieval|evidence|citation|citations)\b|(?:استرجاع|دليل|أدلة|مصادر)"),
     {"knowledge"}, {"rag_reasoning", "agentic_rag"}),
    (re.compile(r"\b(?:memory|remember|forget|recall)\b|(?:ذاكرة|تذكر|افتكر|انسى|استرجع)"),
     {"memory"}, {"remember_fact", "recall_fact"}),
    (re.compile(r"\b(?:skill|skills|use a skill|install a skill)\b|(?:مهارة|مهارات|استخدم مهارة|ثبت مهارة)"),
     {"skills"}, {"skill_selection", "skill_management"}),
    (re.compile(r"\b(?:github|repository|repo|pull request|commit)\b|(?:جيت هب|مستودع|ريبو|كوميت)"),
     {"github"}, {"github"}),
    (re.compile(r"\b(?:dataset|data|outlier|outliers|anomaly|anomalies|average|mean|correlation|trend|drift|analyze)\b|(?:dataset|بيانات|داتا|انحراف|شذوذ|متوسط|ارتباط|اتجاه|حلل|تحليل|اكتشف)"),
     {"data"}, {"analyze", "outliers", "diagnose", "profile", "average", "correlation", "trend", "drift"}),
    (re.compile(r"\b(?:test|tests|build|compile|bug|debug|fix the project|codebase)\b|(?:اختبار|اختبارات|ابني|بناء|ترجمة|خطأ|اصلح|أصلح|كود)"),
     {"development", "quality_assurance"}, {"check", "compile", "git", "inspect"}),
    (re.compile(r"\b(?:file|folder|directory|workspace|write|read)\b|(?:ملف|مجلد|مسار|ورك سبيس|اكتب|اقرأ)"),
     {"workspace", "documents"}, {"read", "write", "list", "search"}),
)

_CAPABILITY_PRIORITY = (
    "outliers", "diagnose", "average", "correlation", "trend", "drift", "profile", "analyze",
    "web_search", "research", "arxiv", "rag_reasoning", "agentic_rag",
    "recall_fact", "remember_fact", "skill_selection", "skill_management",
    "check", "compile", "git", "inspect", "read", "write", "list", "search",
)

_CAPABILITY_HINTS = {
    "حلل": {"analyze", "outliers", "diagnose", "profile", "average", "correlation", "trend", "drift"},
    "تحليل": {"analyze", "outliers", "diagnose", "profile", "average", "correlation", "trend", "drift"},
    "اكتشف": {"outliers", "diagnose"},
    "outlier": {"outliers"},
    "outliers": {"outliers"},
    "anomaly": {"diagnose", "outliers"},
    "anomalies": {"diagnose", "outliers"},
    "average": {"average"},
    "mean": {"average"},
    "correlation": {"correlation"},
    "trend": {"trend"},
    "drift": {"drift"},
    "profile": {"profile"},
    "research": {"research"},
    "paper": {"research"},
    "papers": {"research"},
}

_STOPWORDS = {
    "the", "a", "an", "to", "for", "of", "and", "or", "is", "my", "me", "what", "how", "should", "i", "you",
    "in", "on", "this", "that", "do", "can", "please", "could", "find", "show", "tell", "about", "use", "using",
    "عن", "في", "من", "ما", "هو", "ايه", "كيف", "لي", "أنا", "انا", "ممكن", "لو", "سمحت", "اعمل", "نفذ",
}


@dataclass(frozen=True)
class SeedScenario:
    id: str
    goal: str
    domain: str
    capability: str
    subtype: str
    difficulty: str
    language: str
    style: str
    task_signature: str
    interaction_shape: str
    required_tools: tuple[str, ...]
    forbidden_tools: tuple[str, ...]
    tool_order: tuple[str, ...]
    constraints: tuple[str, ...]
    failure_modes: tuple[str, ...]
    success_invariants: tuple[str, ...]
    support_level: str
    approval_required: bool
    anchor_id: str
    source: str = "synthetic_seed"
    payload: dict[str, Any] | None = None
    classification: dict[str, Any] | None = None


class SeedScenarioStore:
    """Read-only corpus of synthetic seed scenarios.

    The corpus is deliberately separate from Memory/Learning stores. Synthetic scenarios
    are examples and prior patterns, never user facts, execution evidence, or promotion
    evidence. The store exposes search only; it has no mutation API.
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.environ.get("AGENT_SEED_DB") or DEFAULT_PATH)
        self._fts = False
        self._ensure_schema()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.execute("PRAGMA query_only=ON")
        return conn

    def _ensure_schema(self) -> None:
        if not self.path.exists():
            return
        conn = self._connect()
        try:
            row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='scenarios'").fetchone()
            self._fts = bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='scenarios_fts'").fetchone())
            if not row:
                return
        finally:
            conn.close()

    @property
    def available(self) -> bool:
        return self.path.exists()

    def stats(self) -> dict[str, Any]:
        if not self.available:
            return {"available": False, "count": 0}
        conn = self._connect()
        try:
            count = int(conn.execute("SELECT COUNT(*) FROM scenarios").fetchone()[0])
            domains = conn.execute("SELECT domain, COUNT(*) FROM scenarios GROUP BY domain ORDER BY COUNT(*) DESC, domain").fetchall()
            support = conn.execute("SELECT support_level, COUNT(*) FROM scenarios GROUP BY support_level ORDER BY support_level").fetchall()
            languages = conn.execute("SELECT language, COUNT(*) FROM scenarios GROUP BY language ORDER BY language").fetchall()
        finally:
            conn.close()
        return {
            "available": True,
            "count": count,
            "read_only": True,
            "classification": CLASSIFICATION.to_dict(),
            "domains": {k: int(v) for k, v in domains},
            "support_level": {k: int(v) for k, v in support},
            "languages": {k: int(v) for k, v in languages},
        }

    def _row_to_item(self, row) -> SeedScenario:
        # row: id, goal, domain, capability, subtype, difficulty, language, style,
        # task_signature, interaction_shape, required_tools, forbidden_tools, tool_order,
        # constraints, failure_modes, success_invariants, support_level, approval_required,
        # anchor_id, payload
        payload = json.loads(row[19] or "{}")
        return SeedScenario(
            id=row[0], goal=row[1], domain=row[2], capability=row[3], subtype=row[4],
            difficulty=row[5], language=row[6], style=row[7], task_signature=row[8],
            interaction_shape=row[9], required_tools=tuple(json.loads(row[10] or "[]")),
            forbidden_tools=tuple(json.loads(row[11] or "[]")), tool_order=tuple(json.loads(row[12] or "[]")),
            constraints=tuple(json.loads(row[13] or "[]")), failure_modes=tuple(json.loads(row[14] or "[]")),
            success_invariants=tuple(json.loads(row[15] or "[]")), support_level=row[16],
            approval_required=bool(row[17]), anchor_id=row[18], payload=payload,
        )

    def get(self, scenario_id: str) -> SeedScenario | None:
        if not self.available:
            return None
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT id,goal,domain,capability,subtype,difficulty,language,style,task_signature,interaction_shape,required_tools,forbidden_tools,tool_order,constraints,failure_modes,success_invariants,support_level,approval_required,anchor_id,payload FROM scenarios WHERE id=?",
                (scenario_id,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        item = self._row_to_item(row)
        ok, _ = validate_seed_payload(item.payload, source=item.source)
        return item if ok else None

    def search(self, query: str, *, limit: int = 6, support_level: str | None = None) -> list[SeedScenario]:
        if not self.available or not str(query or "").strip():
            return []
        text = str(query).casefold()
        raw_tokens = [x for x in _WORD_RE.findall(text) if len(x) >= 2 and x not in _STOPWORDS]
        alias_tokens: list[str] = []
        hinted_domains: set[str] = set()
        hinted_capabilities: set[str] = set()
        matched_rule = next(((domains, capabilities) for pattern, domains, capabilities in _INTENT_RULES if pattern.search(text)), None)
        if matched_rule:
            hinted_domains.update(matched_rule[0])
            hinted_capabilities.update(matched_rule[1])
        for token in raw_tokens:
            alias_tokens.extend(_QUERY_ALIASES.get(token, ()))
            hinted_domains.update(_DOMAIN_HINTS.get(token, ()))
            hinted_capabilities.update(_CAPABILITY_HINTS.get(token, ()))

        # A small amount of intent precedence makes seed retrieval action-first:
        # "research on agent memory" is a research task, while "remember my name" is a memory task.
        priority_caps = [cap for cap in _CAPABILITY_PRIORITY if cap in hinted_capabilities]
        if priority_caps:
            top_cap = priority_caps[0]
            hinted_capabilities = {top_cap}
            if top_cap in {"outliers", "diagnose", "average", "correlation", "trend", "drift", "profile", "analyze"}:
                hinted_domains = {"data"}
            elif top_cap in {"web_search", "research"}:
                hinted_domains = {"web_research", "research_ops"}
            elif top_cap in {"arxiv"}:
                hinted_domains = {"science"}
            elif top_cap in {"rag_reasoning", "agentic_rag"}:
                hinted_domains = {"knowledge"}
            elif top_cap in {"recall_fact", "remember_fact"}:
                hinted_domains = {"memory"}
            elif top_cap in {"skill_selection", "skill_management"}:
                hinted_domains = {"skills"}
            elif top_cap in {"check", "compile", "git", "inspect"}:
                hinted_domains = {"development", "quality_assurance"}
            elif top_cap in {"read", "write", "list", "search"}:
                hinted_domains = {"workspace", "documents"}

        lowered = text
        if re.search(r"\b(?:outlier|outliers)\b|(?:الشذوذ|القيم الشاذة|اكتشف الشذوذ)", lowered):
            hinted_capabilities = {"outliers"}; hinted_domains = {"data"}
        elif re.search(r"\b(?:anomaly|anomalies)\b|(?:شذوذ|انحراف|انحرافات)", lowered):
            hinted_capabilities = {"diagnose"}; hinted_domains = {"data"}
        elif re.search(r"\b(?:average|mean)\b|(?:متوسط|المتوسط)", lowered):
            hinted_capabilities = {"average"}; hinted_domains = {"data"}
        elif re.search(r"\b(?:correlation)\b|(?:ارتباط|علاقة بين)", lowered):
            hinted_capabilities = {"correlation"}; hinted_domains = {"data"}
        elif re.search(r"\b(?:trend|trends)\b|(?:اتجاه|اتجاهات)", lowered):
            hinted_capabilities = {"trend"}; hinted_domains = {"data"}
        elif re.search(r"\b(?:drift)\b|(?:انجراف)", lowered):
            hinted_capabilities = {"drift"}; hinted_domains = {"data"}
        elif re.search(r"\b(?:profile|profiling)\b|(?:بروفايل|وصف البيانات)", lowered):
            hinted_capabilities = {"profile"}; hinted_domains = {"data"}
        elif re.search(r"\b(?:research|researching|look up|find online)\b|(?:ابحث|بحث|أبحاث|ابحاث)", lowered):
            hinted_capabilities = {"web_search"}; hinted_domains = {"web_research", "research_ops"}
        elif re.search(r"\b(?:paper|papers|arxiv|academic|scientific)\b|(?:ورقة|أوراق|ابحاث علمية|أبحاث علمية)", lowered):
            hinted_capabilities = {"arxiv" if re.search(r"\barxiv\b", lowered) else "research"}; hinted_domains = {"science"}
        elif re.search(r"\b(?:remember|recall|forget|my name|my city)\b|(?:تذكر|افتكر|انسى|اسمي|مدينتي)", lowered):
            hinted_capabilities = {"recall_fact" if re.search(r"\b(?:recall|what is my|what's my|where am I|ما اسمي|ما مدينتي)\b", lowered) else "remember_fact"}; hinted_domains = {"memory"}
        elif re.search(r"\b(?:use a skill|which skill|match skill|skill)\b|(?:مهارة|مهارات|استخدم مهارة)", lowered):
            hinted_capabilities = {"skill_selection"}; hinted_domains = {"skills"}
        elif re.search(r"\b(?:tests?|build|compile|debug|fix)\b|(?:اختبار|اختبارات|اصلح|أصلح|ابني)", lowered):
            hinted_capabilities = {"check"}; hinted_domains = {"development", "quality_assurance"}
        elif re.search(r"\b(?:write|read|file|workspace)\b|(?:اكتب|اقرأ|ملف|ورك سبيس)", lowered):
            hinted_capabilities = {"write" if re.search(r"\bwrite\b|(?:اكتب)", lowered) else "read"}; hinted_domains = {"workspace", "documents"}
        search_tokens = list(dict.fromkeys(raw_tokens + alias_tokens))
        if not search_tokens:
            return []
        q = " ".join(search_tokens)[:500]
        limit_n = max(1, min(int(limit), 50))
        candidate_limit = max(80, min(limit_n * 20, 500))
        conn = self._connect()
        try:
            rows_by_id: dict[str, tuple] = {}

            def add_rows(items: list[tuple]) -> None:
                for row in items:
                    rows_by_id[row[0]] = row

            if self._fts:
                match = " OR ".join(x for x in q.split() if x)
                sql = (
                    "SELECT s.id,s.goal,s.domain,s.capability,s.subtype,s.difficulty,s.language,s.style,s.task_signature,s.interaction_shape,s.required_tools,s.forbidden_tools,s.tool_order,s.constraints,s.failure_modes,s.success_invariants,s.support_level,s.approval_required,s.anchor_id,s.payload "
                    "FROM scenarios_fts f JOIN scenarios s ON s.rowid=f.rowid WHERE scenarios_fts MATCH ?"
                )
                params: list[Any] = [match]
                if support_level:
                    sql += " AND s.support_level=?"
                    params.append(support_level)
                sql += " ORDER BY bm25(scenarios_fts), s.id LIMIT ?"
                params.append(candidate_limit)
                add_rows(conn.execute(sql, params).fetchall())

            # Guarantee domain/capability recall even when FTS ranks a broad alias too highly.
            if hinted_domains:
                placeholders = ",".join("?" for _ in hinted_domains)
                params = list(sorted(hinted_domains))
                sql = (
                    "SELECT id,goal,domain,capability,subtype,difficulty,language,style,task_signature,interaction_shape,required_tools,forbidden_tools,tool_order,constraints,failure_modes,success_invariants,support_level,approval_required,anchor_id,payload "
                    f"FROM scenarios WHERE domain IN ({placeholders})"
                )
                if support_level:
                    sql += " AND support_level=?"
                    params.append(support_level)
                sql += " ORDER BY id LIMIT ?"
                params.append(max(80, min(candidate_limit, 800)))
                add_rows(conn.execute(sql, params).fetchall())

            if hinted_capabilities:
                placeholders = ",".join("?" for _ in hinted_capabilities)
                params = list(sorted(hinted_capabilities))
                sql = (
                    "SELECT id,goal,domain,capability,subtype,difficulty,language,style,task_signature,interaction_shape,required_tools,forbidden_tools,tool_order,constraints,failure_modes,success_invariants,support_level,approval_required,anchor_id,payload "
                    f"FROM scenarios WHERE capability IN ({placeholders})"
                )
                if support_level:
                    sql += " AND support_level=?"
                    params.append(support_level)
                sql += " ORDER BY id LIMIT ?"
                params.append(max(80, min(candidate_limit, 800)))
                add_rows(conn.execute(sql, params).fetchall())

            rows = list(rows_by_id.values())
            if not rows:
                # Last-resort bounded lexical scan.
                params = []
                where = ""
                if support_level:
                    where = "WHERE support_level=?"
                    params.append(support_level)
                params.append(5000)
                rows = conn.execute(
                    "SELECT id,goal,domain,capability,subtype,difficulty,language,style,task_signature,interaction_shape,required_tools,forbidden_tools,tool_order,constraints,failure_modes,success_invariants,support_level,approval_required,anchor_id,payload "
                    f"FROM scenarios {where} ORDER BY id LIMIT ?",
                    params,
                ).fetchall()

            tokens = set(raw_tokens)
            alias_set = set(alias_tokens)
            ranked = []
            for row in rows:
                hay_tokens = set(_WORD_RE.findall((row[1] + " " + row[2] + " " + row[3] + " " + row[8]).casefold()))
                overlap = len(tokens & hay_tokens) / max(1, len(tokens))
                alias_hit = len(alias_set & hay_tokens) / max(1, len(alias_set)) if alias_set else 0.0
                domain = str(row[2]).casefold()
                capability = str(row[3]).casefold()
                domain_parts = set(domain.split("_"))
                capability_parts = set(capability.split("_"))
                domain_hint = 1.0 if domain in hinted_domains else 0.0
                cap_hint = 1.0 if capability in hinted_capabilities else 0.0
                raw_domain_hit = sum(1.0 for token in tokens if token == domain or token in domain_parts)
                raw_cap_hit = sum(1.0 for token in tokens if token == capability or token in capability_parts)
                # Strong semantic field boosts prevent broad aliases such as "data" from winning over the intended capability.
                score = (
                    0.9 * overlap
                    + 0.45 * alias_hit
                    + 4.0 * domain_hint
                    + 5.0 * cap_hint
                    + 1.25 * raw_domain_hit
                    + 1.75 * raw_cap_hit
                    + (0.35 if row[16] == "native" else 0.0)
                )
                ranked.append((score, row))
            ranked.sort(key=lambda x: (-x[0], x[1][0]))
            items = []
            for _, row in ranked[:limit_n]:
                item = self._row_to_item(row)
                ok, _ = validate_seed_payload(item.payload, source=item.source)
                if ok:
                    items.append(item)
            return items
        finally:
            conn.close()

    def context(self, goal: str, *, limit: int = 4) -> list[dict[str, Any]]:
        items = self.search(goal, limit=limit)
        return [
            {
                "seed_id": item.id,
                "goal": item.goal,
                "domain": item.domain,
                "capability": item.capability,
                "task_signature": item.task_signature,
                "interaction_shape": item.interaction_shape,
                "required_tools": list(item.required_tools),
                "tool_order": list(item.tool_order),
                "constraints": list(item.constraints),
                "failure_modes": list(item.failure_modes),
                "success_invariants": list(item.success_invariants),
                "support_level": item.support_level,
                "approval_required": item.approval_required,
                "provenance": item.source,
                "anchor_id": item.anchor_id,
                "classification": dict(item.classification or CLASSIFICATION.to_dict()),
                "authoritative": False,
                "not_user_memory": True,
                "not_execution_evidence": True,
                "not_promotion_evidence": True,
            }
            for item in items
        ]
