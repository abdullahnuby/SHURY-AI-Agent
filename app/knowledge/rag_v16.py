"""V16 adaptive retrieval portfolio for the Personal Agent.

Deterministic adaptive retrieval control with Arabic semantic embeddings:
- query-complexity-aware routing instead of one fixed retriever
- multiple complementary lexical/structural retrieval strategies
- greedy evidence set coverage in addition to MMR
- adaptive escalation only when evidence remains insufficient
- local strategy experience with recency-weighted UCB
- Arabic-Retrieval-v1.0 semantic scoring through the base RAG engine
- hop-aware traces and marginal-gain accounting
- safe abstention remains the final state when evidence is inadequate

No generative model is used. Network retrieval remains a separate bounded tool, while local semantic retrieval uses Arabic-Retrieval-v1.0.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from app.knowledge.rag import RAGEngine, RetrievalResult, _tokens, _char_ngrams, _cosine
from app.intelligence.understanding import normalize


@dataclass(frozen=True)
class QueryProfile:
    normalized: str
    token_count: int
    subqueries: int
    phrase_like: bool
    structured: bool
    comparative: bool
    temporal: bool
    complexity: float
    context_key: str


@dataclass(frozen=True)
class StrategyDecision:
    strategy: str
    score: float
    mean_reward: float
    observations: int
    source: str


STRATEGIES = ("focused", "broad", "decomposed", "neighbor", "fusion")
_SCHEMA_EXT = {".csv", ".json", ".sqlite", ".sqlite3", ".db"}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _ctx_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class AdaptiveRAGEngine:
    """Adaptive strategy portfolio over an existing :class:`RAGEngine` corpus."""

    def __init__(self, db_path=None):
        self.base = RAGEngine(db_path) if db_path is not None else RAGEngine()
        self._ensure_schema()

    @property
    def db_path(self):
        return self.base.db_path

    def _connect(self):
        return self.base._connect()

    def _ensure_schema(self):
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS retrieval_observations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        context_key TEXT NOT NULL,
                        strategy TEXT NOT NULL,
                        reward REAL NOT NULL,
                        grounded INTEGER NOT NULL,
                        hops INTEGER NOT NULL,
                        metadata TEXT NOT NULL DEFAULT '{}',
                        ts TEXT NOT NULL
                    )"""
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_retrieval_obs_ctx ON retrieval_observations(context_key, strategy, id)")
        finally:
            conn.close()

    def index(self, path):
        return self.base.index(path)

    def index_memory(self, memory_db_path=None):
        return self.base.index_memory(memory_db_path)

    def stats(self):
        base = self.base.stats()
        conn = self._connect()
        try:
            obs = conn.execute("SELECT COUNT(*) FROM retrieval_observations").fetchone()[0]
        finally:
            conn.close()
        base["adaptive_observations"] = obs
        return base

    def _corpus_hint(self) -> dict:
        conn = self._connect()
        try:
            total = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            structured = conn.execute("SELECT COUNT(*) FROM sources WHERE lower(kind)='table'").fetchone()[0]
            distinct_sources = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            return {"chunks": total, "structured_sources": structured, "sources": distinct_sources}
        finally:
            conn.close()

    def profile(self, query: str) -> QueryProfile:
        n = normalize(query)
        toks = _tokens(n)
        sub = self.base.decompose_query(n)
        phrase_like = ('"' in query or "'" in query or len(toks) <= 4)
        structured = bool(re.search(r"\b(?:id|ids|column|columns|row|rows|csv|json|sqlite|table|schema|sum|total|average|count)\b", n)) or any(
            k in n for k in ("عمود", "أعمدة", "صف", "صفوف", "جدول", "مجموع", "متوسط", "عدد", "معرف", "اعمدة")
        )
        comparative = any(k in n for k in ("compare", "versus", "difference", "between", "مقارنة", "مقابل", "الفرق", "بين"))
        temporal = any(k in n for k in ("before", "after", "latest", "recent", "trend", "over time", "قبل", "بعد", "احدث", "أحدث", "اخير", "آخر", "اتجاه", "زمني"))
        length_factor = min(1.0, len(toks) / 14.0)
        sub_factor = min(1.0, max(0, len(sub) - 1) / 3.0)
        flags = sum((phrase_like, structured, comparative, temporal)) / 4.0
        complexity = min(1.0, 0.20 + 0.30 * length_factor + 0.25 * sub_factor + 0.25 * flags)
        bucket = "complex" if complexity >= 0.66 else "medium" if complexity >= 0.42 else "simple"
        context = f"{bucket}|sub={len(sub)}|structured={int(structured)}|comparative={int(comparative)}|temporal={int(temporal)}"
        return QueryProfile(n, len(toks), len(sub), phrase_like, structured, comparative, temporal, round(complexity, 6), _ctx_hash(context))

    def _history(self, context_key: str, strategy: str) -> tuple[float, int]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT reward,ts FROM retrieval_observations WHERE context_key=? AND strategy=? ORDER BY id DESC LIMIT 100",
                (context_key, strategy),
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            return 0.5, 0
        now = time.time()
        weighted_sum = 0.0
        weights = 0.0
        for reward, ts in rows:
            try:
                age_days = max(0.0, (now - time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%S"))) / 86400.0)
            except Exception:
                age_days = 3650.0
            w = 0.5 ** (age_days / 30.0)
            weighted_sum += float(reward) * w
            weights += w
        mean = weighted_sum / max(weights, 1e-12)
        return round(mean, 6), len(rows)

    def _decisions(self, profile: QueryProfile, tried: Iterable[str]) -> list[StrategyDecision]:
        tried_set = set(tried)
        corpus = self._corpus_hint()
        total_obs = 0
        stats = {}
        for strategy in STRATEGIES:
            mean, n = self._history(profile.context_key, strategy)
            stats[strategy] = (mean, n)
            total_obs += n
        out = []
        for strategy in STRATEGIES:
            if strategy in tried_set:
                continue
            mean, n = stats[strategy]
            prior = 0.50
            exploration = 0.85 * math.sqrt(math.log1p(total_obs + len(STRATEGIES)) / (n + 1))
            prior_fit = {
                "focused": 0.22 if profile.phrase_like else 0.05,
                "broad": 0.18 if profile.complexity < 0.55 else 0.08,
                "decomposed": 0.24 if profile.subqueries > 1 or profile.complexity > 0.60 else 0.08,
                "neighbor": 0.16 if profile.complexity > 0.50 else 0.05,
                "fusion": 0.12 if profile.complexity > 0.70 else 0.04,
            }[strategy]
            corpus_fit = 0.03 if (strategy in {"decomposed", "neighbor"} and corpus["chunks"] >= 20) else 0.0
            if strategy == "focused" and profile.structured and corpus["structured_sources"]:
                prior_fit += 0.10
            score = 0.55 * mean + 0.45 * prior + prior_fit + corpus_fit + exploration
            source = "history+current-fit" if n else "current-fit+prior"
            out.append(StrategyDecision(strategy, round(score, 6), mean, n, source))
        out.sort(key=lambda d: (-d.score, d.strategy))
        return out

    @staticmethod
    def _dedupe(results: list[RetrievalResult]) -> list[RetrievalResult]:
        best = {}
        for r in results:
            prev = best.get(r.chunk_id)
            if prev is None or r.score > prev.score:
                best[r.chunk_id] = r
        return sorted(best.values(), key=lambda x: (-x.score, x.chunk_id))

    def _focused(self, query: str, top_k: int) -> list[RetrievalResult]:
        base = self.base.retrieve(query, top_k=max(top_k * 4, 12), candidate_k=60)
        qn = normalize(query)
        qt = set(_tokens(query))
        scored = []
        for r in base:
            title_tokens = set(_tokens(r.title))
            text_norm = normalize(r.text)
            overlap = len(qt & set(_tokens(r.text))) / max(1, len(qt))
            phrase = 1.0 if qn in text_norm else 0.0
            heading = len(qt & title_tokens) / max(1, len(qt))
            schema = 0.08 if any(x in text_norm for x in ("columns:", "schema", "table:", "csv columns")) else 0.0
            score = 0.55 * r.score + 0.22 * overlap + 0.15 * phrase + 0.08 * heading + schema
            scored.append((score, r))
        scored.sort(key=lambda x: (-x[0], x[1].chunk_id))
        return [r for _, r in scored[:top_k]]

    def _broad(self, query: str, top_k: int) -> list[RetrievalResult]:
        # Larger candidate pool + lower lexical commitment improves recall for unusual wording.
        results = self.base.retrieve(query, top_k=max(top_k * 5, 20), candidate_k=80)
        return results[:top_k]

    def _decomposed(self, query: str, top_k: int) -> list[RetrievalResult]:
        pieces = self.base.decompose_query(query)
        all_r = []
        for hop, piece in enumerate(pieces):
            all_r.extend(self.base.retrieve(piece, top_k=max(6, top_k * 2), hop=hop, candidate_k=60))
        if len(pieces) > 1 and len(all_r) < top_k * 2:
            expanded = self.base._expand_from_results(query, all_r[:10])
            all_r.extend(self.base.retrieve(expanded, top_k=max(6, top_k * 2), hop=len(pieces), candidate_k=60))
        all_r = self._dedupe(all_r)
        return self._set_cover(query, pieces, all_r, top_k)

    def _neighbor(self, query: str, top_k: int) -> list[RetrievalResult]:
        seeds = self.base.retrieve(query, top_k=max(4, top_k), candidate_k=50)
        if not seeds:
            return []
        conn = self._connect()
        try:
            out = list(seeds)
            seen = {r.chunk_id for r in out}
            for seed in seeds[: min(4, len(seeds))]:
                rows = conn.execute(
                    "SELECT c.id,c.ordinal,c.title,c.text,c.token_count,c.access_count,c.last_accessed,s.path,s.kind "
                    "FROM chunks c JOIN sources s ON s.id=c.source_id "
                    "WHERE c.source_id=(SELECT source_id FROM chunks WHERE id=?) AND c.ordinal BETWEEN ? AND ? "
                    "ORDER BY c.ordinal",
                    (seed.chunk_id, max(0, seed.ordinal - 1), seed.ordinal + 1),
                ).fetchall()
                for row in rows:
                    cid = row[0]
                    if cid in seen:
                        continue
                    text = row[3]
                    terms = set(_tokens(text))
                    qterms = set(_tokens(query))
                    overlap = len(terms & qterms) / max(1, len(qterms))
                    score = 0.34 * seed.score + 0.66 * overlap
                    out.append(RetrievalResult(query, cid, row[7], row[8], row[2], text, round(score, 6), None, None, round(score, 6), seed.hop + 1))
                    seen.add(cid)
        finally:
            conn.close()
        return self._set_cover(query, [query], out, top_k)

    def _fusion(self, query: str, top_k: int) -> list[RetrievalResult]:
        groups = [self._focused(query, top_k * 2), self._broad(query, top_k * 2)]
        if len(self.base.decompose_query(query)) > 1:
            groups.append(self._decomposed(query, top_k * 2))
        by = {}
        ranks = [
            {r.chunk_id: i + 1 for i, r in enumerate(group)}
            for group in groups
        ]
        obj = {}
        for group in groups:
            obj.update({r.chunk_id: r for r in group})
        for cid in obj:
            s = 0.0
            for rankmap in ranks:
                if cid in rankmap:
                    s += 1.0 / (60 + rankmap[cid])
            r = obj[cid]
            obj[cid] = RetrievalResult(r.query, r.chunk_id, r.source, r.title, r.text, round(s, 6), r.rank_bm25, r.rank_char, round(s, 6), r.hop)
        fused = sorted(obj.values(), key=lambda r: (-r.score, r.chunk_id))
        return self._set_cover(query, self.base.decompose_query(query), fused, top_k)

    def _set_cover(self, query: str, subqueries: list[str], candidates: list[RetrievalResult], top_k: int) -> list[RetrievalResult]:
        """Greedy maximum-coverage selection with source diversity.

        The objective combines uncovered query tokens, uncovered subquery tokens and source diversity.
        This complements MMR by explicitly rewarding coverage of distinct evidence-seeking intents.
        """
        target = set()
        for part in subqueries or [query]:
            target.update(_tokens(part))
        covered = set()
        seen_sources = set()
        selected = []
        remaining = list(candidates)
        while remaining and len(selected) < top_k:
            best_idx = -1
            best_gain = -1.0
            for i, r in enumerate(remaining):
                toks = set(_tokens(r.text + " " + r.title))
                new_tokens = len((toks & target) - covered) / max(1, len(target))
                source_gain = 0.10 if r.source not in seen_sources else 0.0
                support_gain = 0.20 * min(1.0, r.score)
                gain = 0.62 * new_tokens + source_gain + support_gain
                key = (gain, r.score, -r.chunk_id)
                if best_idx < 0 or key > (best_gain, remaining[best_idx].score, -remaining[best_idx].chunk_id):
                    best_idx, best_gain = i, gain
            chosen = remaining.pop(best_idx)
            selected.append(chosen)
            covered.update(set(_tokens(chosen.text + " " + chosen.title)) & target)
            seen_sources.add(chosen.source)
        return selected

    def _strategy(self, strategy: str, query: str, top_k: int) -> list[RetrievalResult]:
        return {
            "focused": self._focused,
            "broad": self._broad,
            "decomposed": self._decomposed,
            "neighbor": self._neighbor,
            "fusion": self._fusion,
        }[strategy](query, top_k)

    def _evidence(self, query: str, results: list[RetrievalResult], profile: QueryProfile) -> dict:
        gate = self.base._coverage(query, results)
        subs = self.base.decompose_query(query)
        sub_scores = []
        for sq in subs:
            st = set(_tokens(sq))
            covered = set()
            for r in results:
                covered |= st & set(_tokens(r.text + " " + r.title))
            sub_scores.append(len(covered) / max(1, len(st)))
        gate["subquery_coverage"] = round(sum(sub_scores) / max(1, len(sub_scores)), 6)
        gate["uncertainty"] = round(1.0 - gate["score"], 6)
        gate["complexity"] = profile.complexity
        gate["sufficient"] = bool(results) and gate["score"] >= (0.70 if profile.complexity >= 0.66 else 0.58) and gate["subquery_coverage"] >= (0.60 if profile.subqueries > 1 else 0.45)
        return gate

    @staticmethod
    def _reward(evidence: dict, selected: list[RetrievalResult], baseline: float = 0.0) -> float:
        gain = max(0.0, evidence["score"] - baseline)
        precision = sum(1 for r in selected if r.score >= 0.18) / max(1, len(selected))
        diversity = min(1.0, len({r.source for r in selected}) / 3.0)
        return round(min(1.0, 0.45 * evidence["score"] + 0.25 * gain + 0.20 * precision + 0.10 * diversity), 6)

    def _record(self, profile: QueryProfile, strategy: str, reward: float, evidence: dict, hops: int):
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO retrieval_observations(context_key,strategy,reward,grounded,hops,metadata,ts) VALUES(?,?,?,?,?,?,?)",
                    (profile.context_key, strategy, reward, int(bool(evidence.get("sufficient"))), int(hops),
                     json.dumps({k: evidence.get(k) for k in ("score", "subquery_coverage", "uncertainty", "source_diversity")}, ensure_ascii=False), _now()),
                )
        finally:
            conn.close()

    def query(self, query: str, top_k: int = 6, max_strategies: int = 3) -> dict:
        profile = self.profile(query)
        attempted = []
        all_results: list[RetrievalResult] = []
        trace = []
        previous_evidence = 0.0
        final_gate = self._evidence(query, [], profile)

        for _ in range(max(1, min(4, max_strategies))):
            decisions = self._decisions(profile, attempted)
            if not decisions:
                break
            decision = decisions[0]
            started = time.monotonic()
            current = self._strategy(decision.strategy, query, top_k)
            latency_ms = round((time.monotonic() - started) * 1000.0, 3)
            all_results = self._dedupe(all_results + current)
            all_results = self._set_cover(query, profile and self.base.decompose_query(query), all_results, max(top_k * 2, top_k))
            gate = self._evidence(query, all_results, profile)
            marginal = max(0.0, gate["score"] - previous_evidence)
            reward = self._reward(gate, current, previous_evidence)
            trace.append({
                "strategy": decision.strategy,
                "selection_score": decision.score,
                "policy_source": decision.source,
                "historical_mean": decision.mean_reward,
                "historical_observations": decision.observations,
                "marginal_gain": round(marginal, 6),
                "retrieved": len(current),
                "aggregate": len(all_results),
                "evidence": gate,
                "latency_ms": latency_ms,
            })
            self._record(profile, decision.strategy, reward, gate, len(attempted) + 1)
            attempted.append(decision.strategy)
            final_gate = gate
            previous_evidence = gate["score"]
            # Evidence-aware stopping: don't retrieve again when uncertainty has fallen enough.
            if gate["sufficient"]:
                break
            # Avoid spending a full portfolio budget when the last strategy adds essentially nothing.
            if len(attempted) >= 2 and marginal < 0.02:
                break

        final_results = all_results[:top_k]
        if not final_gate["sufficient"] or not final_results:
            answer = "لا توجد أدلة كافية من المصادر المفهرسة للإجابة بأمان."
            grounded = False
            evidence = []
            reason = "adaptive_evidence_gate_failed"
        else:
            answer, evidence = self.base._extractive_answer(query, final_results)
            grounded = bool(answer)
            reason = "adaptive_grounded_extract" if grounded else "no_extractable_support"
            if not grounded:
                answer = "لا توجد جمل قابلة للاستخراج تدعم السؤال في الأدلة المسترجعة."
                evidence = []
        return {
            "query": query,
            "answer": answer,
            "grounded": grounded,
            "abstained": not grounded,
            "reason": reason,
            "profile": profile.__dict__,
            "strategies": attempted,
            "strategy_portfolio": [
                {"strategy": s.strategy, "score": s.score, "mean_reward": s.mean_reward, "observations": s.observations, "source": s.source}
                for s in self._decisions(profile, [])
            ],
            "evidence_gate": final_gate,
            "trace": trace,
            "evidence": evidence,
            "retrieval": [r.__dict__ for r in final_results],
            "policy": "complexity-aware adaptive portfolio + recency-weighted UCB + evidence-aware stopping",
            "model_free": True,
        }


def adaptive_rag_query(query: str, top_k: int = 6, db_path=None) -> dict:
    return AdaptiveRAGEngine(db_path=db_path).query(query, top_k=top_k)
