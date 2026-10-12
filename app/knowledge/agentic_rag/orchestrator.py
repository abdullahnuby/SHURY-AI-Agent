from __future__ import annotations
import re
import time
from collections import Counter, defaultdict
from app.knowledge.rag_v16 import AdaptiveRAGEngine
from app.knowledge.web_research import WebResearchEngine
from app.knowledge.agentic_rag.models import AgenticRAGResult, Claim, EvidenceItem
from app.knowledge.agentic_rag.router import build_plan
from app.knowledge.agentic_rag.evidence import make_evidence, extract_claims_from_evidence, detect_conflicts, claim_support_score
from app.knowledge.seed_scenarios import SeedScenarioStore
from app.knowledge.seed_policy import CLASSIFICATION, is_explicit_seed_query

def _token_terms(text: str) -> list[str]:
    return re.findall(r"[\w\u0600-\u06ff]+", text.casefold(), flags=re.UNICODE)


class AgenticRAGEngine:
    """Adaptive retrieve→inspect→evaluate→refine→verify→synthesize loop.

    The engine performs multi-round retrieval, source scoring, per-subquestion coverage,
    conservative conflict detection and citation-grounded extractive synthesis. Semantic
    retrieval is provided by Arabic-Retrieval-v1.0 through the local RAG index.
    """

    def __init__(self, rag: AdaptiveRAGEngine | None = None, web: WebResearchEngine | None = None,
                 max_seconds: float = 180.0):
        self.rag = rag or AdaptiveRAGEngine()
        self.web = web or WebResearchEngine()
        self.max_seconds = max(5.0, float(max_seconds))
        self.seed = SeedScenarioStore()

    def _local(self, query: str, top_k: int) -> list[dict]:
        out = self.rag.query(query, top_k=top_k, max_strategies=3)
        rows = []
        for i, r in enumerate(out.get("evidence", []) or [], 1):
            rows.append(make_evidence("local", r.get("title", ""), r.get("source", ""),
                                      r.get("text", ""), query, rank=i,
                                      metadata={"chunk_id": r.get("chunk_id"), "score": r.get("score", 0)},
                                      indexed=True, freshness_value=None, diversity=0.55))
        rows.extend(self._seed_summary(query))
        rows.extend(self._seed_local(query, max(1, top_k // 2)))
        return rows

    def _seed_summary(self, query: str) -> list[dict]:
        q = str(query or "").casefold()
        if not is_explicit_seed_query(query) or not any(term in q for term in ("pattern", "patterns", "composition", "coverage", "distribution", "statistics", "how many", "كم", "أنماط", "توزيع", "إحصائ")):
            return []
        stats = self.seed.stats()
        if not stats.get("available"):
            return []
        top_domains = sorted((stats.get("domains") or {}).items(), key=lambda x: (-x[1], x[0]))[:8]
        top_domains_text = ", ".join(f"{name}={count}" for name, count in top_domains)
        text = (
            f"Synthetic seed catalog summary (non-authoritative prior, not execution evidence): "
            f"count={stats.get('count', 0)}; domains={len(stats.get('domains') or {})}; "
            f"languages={stats.get('languages', {})}; top_domains={top_domains_text}. "
            "Use this only to describe the synthetic seed catalog itself."
        )
        return [make_evidence("synthetic_seed", "seed://catalog-summary", "seed://catalog-summary", text, query, rank=0,
                               metadata={"synthetic": True, "non_authoritative": True, "catalog_summary": True}, indexed=True, diversity=0.85)]

    def _seed_local(self, query: str, top_k: int) -> list[dict]:
        q = str(query or "").casefold()
        # Synthetic seed is non-authoritative and is exposed only for explicit
        # scenario/example/library queries; it must never masquerade as factual evidence.
        if not any(term in q for term in ("seed", "scenario", "scenarios", "example", "examples", "البذرة", "سيناريو", "سيناريوهات", "أمثلة")):
            return []
        rows = []
        for i, item in enumerate(self.seed.search(query, limit=top_k), 1):
            text = (f"Synthetic seed scenario. Goal: {item.goal}. "
                    f"Domain: {item.domain}. Capability: {item.capability}. "
                    f"Task signature: {item.task_signature}. "
                    f"Required tools: {', '.join(item.required_tools)}. "
                    f"Success invariants: {', '.join(item.success_invariants)}.")
            rows.append(make_evidence("synthetic_seed", item.anchor_id, f"seed://{item.id}", text, query, rank=i,
                                      metadata={"seed_id": item.id, "synthetic": True, "non_authoritative": True, "domain": item.domain, "capability": item.capability, **CLASSIFICATION.to_dict()},
                                      indexed=True, freshness_value=None, diversity=0.5))
        return rows

    def _web(self, query: str, limit: int) -> list[dict]:
        try:
            out = self.web.research(query, limit=min(8, max(1, limit)), index=True)
        except Exception:
            return []
        rows = []
        for i, r in enumerate(out.get("sources", []) or [], 1):
            if not r.get("text"):
                continue
            rows.append(make_evidence("web", r.get("title", ""), r.get("url", ""), r.get("text", ""), query,
                                      rank=i, metadata={"snippet": r.get("snippet", ""), "score": r.get("score", 0),
                                                        "source_quality": r.get("source_quality", 0)},
                                      indexed=bool(r.get("indexed")), content_hash=r.get("sha256", ""),
                                      diversity=0.7 / max(1, i), freshness_value=r.get("published")))
        return rows

    def _dedupe(self, rows: list[dict]) -> list[dict]:
        best = {}
        source_domains = set()
        for r in rows:
            key = (r.get("url") or r.get("title"), r.get("content_hash") or r.get("text", "")[:160])
            source_domains.add(r.get("url", ""))
            if key not in best or self._score(r) > self._score(best[key]):
                best[key] = r
        domain_count = max(1, len(source_domains))
        out = []
        for idx, r in enumerate(best.values(), 1):
            rr = dict(r)
            rr["evidence_id"] = f"E{idx:03d}"
            rr["diversity"] = min(1.0, 0.35 + 0.65 / domain_count if domain_count else 0.35)
            rr["quality"] = self._score(rr)
            out.append(rr)
        out.sort(key=lambda x: (-x["quality"], x["source_kind"], x["url"], x["title"]))
        return out

    @staticmethod
    def _score(r: dict) -> float:
        return round(0.50 * float(r.get("relevance", 0)) + 0.22 * float(r.get("authority", 0)) +
                     0.16 * float(r.get("freshness", 0)) + 0.12 * float(r.get("diversity", 0)), 6)

    def _coverage(self, sub, evidence: list[dict]) -> dict:
        q = set(_token_terms(sub.question))
        if not q:
            return {"score": 0.0, "supported_items": 0, "best_quality": 0.0}
        covered = 0.0
        best = 0.0
        source_kinds = set()
        for r in evidence:
            overlap = len(q & set(_token_terms(r["title"] + " " + r["text"]))) / max(1, len(q))
            if overlap > 0:
                covered = max(covered, overlap)
                best = max(best, self._score(r))
                source_kinds.add(r["source_kind"])
        source_bonus = min(0.18, 0.09 * len(source_kinds))
        return {"score": round(min(1.0, 0.67 * covered + 0.23 * best + source_bonus), 6),
                "supported_items": len(source_kinds), "best_quality": round(best, 6)}

    def _refine(self, sub, evidence: list[dict], round_no: int) -> str:
        # Lightweight logical refinement: retain the user's intent, add discriminative
        # evidence terms, remove terms already saturated, and vary the query per round.
        qterms = set(_token_terms(sub.question))
        freq = Counter()
        for r in evidence[:8]:
            for term in _token_terms(r["title"] + " " + r["text"]):
                if len(term) >= 4 and term not in qterms:
                    freq[term] += 1
        extras = [t for t, _ in freq.most_common(8)]
        if round_no == 2 and extras:
            return f"{sub.question} {' '.join(extras[:4])}".strip()
        if round_no >= 3 and extras:
            return f"{sub.question} {' '.join(extras[4:8])}".strip()
        return sub.question

    def _extractive_synthesize(self, query: str, evidence: list[dict], conflicts: list[dict]) -> tuple[list[dict], str]:
        candidates = extract_claims_from_evidence(query, evidence, limit=8)
        claims = []
        parts = []
        conflict_ids = {x["a"] for x in conflicts} | {x["b"] for x in conflicts}
        for idx, c in enumerate(candidates, 1):
            eid = c["support_ids"][0]
            status = "conflicting" if eid in conflict_ids else "supported"
            claims.append({"text": c["text"], "support_ids": [eid], "verification": status, "confidence": c["score"]})
            parts.append(f"{c['text']} [${eid}]".replace("$", ""))
        return claims, "\n".join(parts[:6])

    @staticmethod
    def _verify_claims(claims: list[dict], evidence: list[dict]) -> tuple[list[Claim], dict]:
        by_id = {r["evidence_id"]: r for r in evidence}
        verified = []
        dropped = 0
        support_values = []
        for idx, c in enumerate(claims, 1):
            text = str(c.get("text") or "").strip()
            ids = tuple(x for x in c.get("support_ids", []) if x in by_id)
            if not text or not ids:
                dropped += 1
                continue
            scores = [claim_support_score(text, by_id[eid]["text"]) for eid in ids]
            score = max(scores, default=0.0)
            if score < 0.42:
                dropped += 1
                continue
            verification = str(c.get("verification") or "supported")
            verified.append(Claim(f"C{idx:03d}", text, ids, tuple(c.get("conflict_ids", [])), verification, round(score, 6)))
            support_values.append(score)
        audit = {"claims_seen": len(claims), "claims_verified": len(verified), "claims_dropped": dropped,
                 "mean_support": round(sum(support_values) / max(1, len(support_values)), 6),
                 "all_citations_valid": all(all(eid in by_id for eid in c.support_ids) for c in verified)}
        return verified, audit

    @staticmethod
    def _is_seed_catalog_query(query: str) -> bool:
        q = str(query or "").casefold()
        has_seed = any(t in q for t in (
            "seed", "seeded", "seed catalog", "synthetic seed",
            "البذرة", "البيانات المزروعة", "سيناريوهات البداية",
        ))
        has_catalog_intent = any(t in q for t in (
            "pattern", "patterns", "distribution", "statistics", "how many", "how is it distributed",
            "أنماط", "توزيع", "إحصائ", "كام", "كم", "ما الذي يغطي", "ماذا يغطي",
        ))
        return has_seed and has_catalog_intent

    def _seed_catalog_result(self, query: str) -> dict | None:
        if not self._is_seed_catalog_query(query):
            return None
        stats = self.seed.stats()
        if not stats.get("available"):
            return None
        count = int(stats.get("count", 0))
        domain_count = len(stats.get("domains") or {})
        languages = stats.get("languages") or {}
        support = stats.get("support_level") or {}
        language_text = ", ".join(f"{k}={v}" for k, v in sorted(languages.items()))
        support_text = ", ".join(f"{k}={v}" for k, v in sorted(support.items()))
        summary = (
            f"The synthetic seed contains {count:,} scenarios across {domain_count} domains. "
            f"Language modes: {language_text}. Support levels: {support_text}. "
            "These are synthetic prior examples, not user memories, execution evidence, or authoritative facts."
        )
        if re.search(r"(?:أنماط|توزيع|إحصائ|كم|كام|ماذا يغطي|ما الذي يغطي)", query, re.I):
            summary = (
                f"البذرة تحتوي على {count:,} سيناريو اصطناعي موزعة على {domain_count} مجالًا. "
                f"أنماط اللغة: {language_text}. مستويات الدعم: {support_text}. "
                "هذه أمثلة اصطناعية تمهيدية وليست ذاكرة للمستخدم ولا دليل تنفيذ حقيقي."
            )
        plan = build_plan(query, None, max_rounds=1, max_evidence=1)
        evidence = [make_evidence(
            "synthetic_seed", "seed://catalog-summary", "seed://catalog-summary", summary, query, rank=0,
            metadata={"synthetic": True, "non_authoritative": True, "catalog_summary": True},
            indexed=True, diversity=0.85, freshness_value=None,
        )]
        evidence[0]["evidence_id"] = "E001"
        claim = Claim("C001", summary, ("E001",), (), "supported", 1.0)
        item = EvidenceItem(evidence[0]["evidence_id"], evidence[0]["source_kind"], evidence[0]["title"],
                            evidence[0]["url"], evidence[0]["text"], evidence[0]["query"], evidence[0]["rank"],
                            evidence[0]["relevance"], evidence[0]["authority"], evidence[0]["freshness"],
                            evidence[0]["diversity"], evidence[0]["indexed"], evidence[0]["content_hash"],
                            evidence[0]["metadata"])
        return AgenticRAGResult(
            query=query, outcome="answered", answer=f"{summary} [E001]", confidence=1.0, plan=plan,
            evidence=[item], claims=[claim],
            trace=[{"round": 1, "queries": [query], "retrieved": 1, "evidence_total": 1,
                    "coverage": {"q1": {"score": 1.0, "supported_items": 1, "best_quality": 0.42}},
                    "unresolved": []}],
            missing=[], conflicts=[],
            methods=["seed catalog statistics", "synthetic-prior isolation", "citation verification"],
            synthesis_mode="extractive", verification={"claims_seen": 1, "claims_verified": 1, "claims_dropped": 0,
                                             "mean_support": 1.0, "all_citations_valid": True},
            reason="seed_catalog_summary",
        ).to_dict()

    def query(self, query: str, semantic=None, max_rounds: int = 3, max_evidence: int = 24) -> dict:
        seed_catalog = self._seed_catalog_result(query)
        if seed_catalog is not None:
            return seed_catalog
        started = time.monotonic()
        plan = build_plan(query, semantic, max_rounds=max_rounds, max_evidence=max_evidence)
        evidence_rows: list[dict] = []
        trace = []
        missing = []
        for round_no in range(1, max_rounds + 1):
            if time.monotonic() - started > self.max_seconds:
                return AgenticRAGResult(query, "budget", "", 0.0, plan, trace=[{"round": round_no, "budget": "exceeded"}], reason="time_budget").to_dict()
            round_rows = []
            for sub in plan.subquestions:
                # Dependency-aware multi-hop: previous evidence primes the next query when required.
                dep_context = ""
                if sub.dependencies:
                    prior = evidence_rows[:6]
                    names = []
                    for r in prior:
                        title = str(r.get("title") or "")
                        if title:
                            names.append(title)
                    dep_context = " " + " ".join(names[:3]) if names else ""
                rq = self._refine(sub, evidence_rows, round_no) + dep_context

                # Corrective retrieval: start with the planned route, then escalate to the
                # complementary source class when coverage is weak. This implements CRAG-like
                # recovery without making web retrieval mandatory for every query.
                if sub.route in {"local", "hybrid"}:
                    round_rows.extend(self._local(rq, top_k=6))
                if sub.route in {"web", "hybrid"}:
                    round_rows.extend(self._web(rq, limit=5))

                current_local = self._coverage(sub, round_rows)
                if current_local["score"] < 0.58:
                    if sub.route == "local":
                        round_rows.extend(self._web(rq, limit=4))
                    elif sub.route == "web":
                        # A local corpus may contain private/project evidence absent from the web.
                        round_rows.extend(self._local(rq, top_k=5))
            all_rows = self._dedupe(evidence_rows + round_rows)
            evidence_rows = all_rows[:max_evidence]
            coverage = {s.id: self._coverage(s, evidence_rows) for s in plan.subquestions}
            unresolved = [s.id for s in plan.subquestions if coverage[s.id]["score"] < 0.58]
            trace.append({"round": round_no, "queries": [s.question for s in plan.subquestions],
                          "retrieved": len(round_rows), "evidence_total": len(evidence_rows),
                          "coverage": coverage, "unresolved": unresolved})
            if not unresolved:
                break
        if not evidence_rows:
            return AgenticRAGResult(query, "abstained", "لا توجد أدلة قابلة للاستخدام للإجابة بأمان.", 0.0,
                                    plan, trace=trace, missing=[s.question for s in plan.subquestions],
                                    methods=["adaptive routing", "bounded multi-round retrieval"], reason="no_evidence").to_dict()
        # Seed examples are an architectural prior only. They may be inspected for explicit
        # seed/benchmark queries, but must never become answer evidence for ordinary user questions.
        if not is_explicit_seed_query(query):
            evidence_rows = [r for r in evidence_rows if r.get("source_kind") != "synthetic_seed" and not bool((r.get("metadata") or {}).get("synthetic"))]
            evidence_rows = evidence_rows[:max_evidence]
        # Stable ids assigned during dedupe.
        conflicts = detect_conflicts([], evidence_rows)
        methods = ["query routing", "per-subquestion coverage", "iterative query refinement", "evidence ledger",
                   "semantic retrieval", "source quality", "conflict detection", "independent citation verification", "extractive synthesis"]
        raw_claims, summary = self._extractive_synthesize(query, evidence_rows, conflicts)
        verified_claims, verification = self._verify_claims(raw_claims, evidence_rows)
        if not verified_claims:
            return AgenticRAGResult(query, "abstained", "لا توجد أدلة كافية وموثقة للإجابة بأمان.", 0.0,
                                    plan, [EvidenceItem(r["evidence_id"], r["source_kind"], r["title"], r["url"], r["text"],
                                                        r["query"], r["rank"], r["relevance"], r["authority"], r["freshness"],
                                                        r["diversity"], r["indexed"], r["content_hash"], r["metadata"]) for r in evidence_rows],
                                    [], trace, [s.question for s in plan.subquestions], conflicts, methods, "extractive",
                                    verification, "verification_failed").to_dict()
        # Render from verified claims only. If a claim is conflicting, expose both evidence ids.
        answer_lines = []
        for c in verified_claims[:6]:
            cites = " ".join(f"[{eid}]" for eid in c.support_ids)
            answer_lines.append(f"{c.text} {cites}")
        confidence = min(1.0, sum(c.confidence for c in verified_claims) / max(1, len(verified_claims)))
        unresolved_ids = [s.id for s in plan.subquestions if trace and trace[-1]["coverage"].get(s.id, {}).get("score", 0.0) < 0.58]
        outcome = "answered" if not unresolved_ids else "partial"
        result_evidence = [EvidenceItem(r["evidence_id"], r["source_kind"], r["title"], r["url"], r["text"], r["query"],
                                         r["rank"], r["relevance"], r["authority"], r["freshness"], r["diversity"],
                                         r["indexed"], r["content_hash"], r["metadata"]) for r in evidence_rows]
        return AgenticRAGResult(query, outcome, "\n".join(answer_lines), round(confidence, 6), plan, result_evidence,
                                verified_claims, trace, [s.question for s in plan.subquestions if s.id in unresolved_ids],
                                conflicts, methods, "extractive", verification,
                                "evidence_sufficient" if outcome == "answered" else "partial_evidence").to_dict()
