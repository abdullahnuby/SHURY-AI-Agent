"""Deterministic evidence-backed question answering.

This is a runtime capability, not a language model.  It answers from local RAG first,
then uses bounded web retrieval when local evidence is absent or when the question is
freshness-sensitive.  The final text is extractive and citation-bearing.
"""
from __future__ import annotations

from collections import Counter
import re
from typing import Any

from app.runtime.registry import tool
from app.intelligence.understanding import normalize
from app.intelligence.answer_policy import classify_question, is_generic_question
from app.knowledge.rag import RAGEngine
from app.knowledge.web_research import WebResearchEngine


def _question(goal: str) -> str:
    quoted = re.findall(r'["\']([^"\']+)["\']', goal)
    if quoted:
        return quoted[-1].strip()
    for marker in (
        "answer question ", "answer this question ", "question:", "سؤال معرفي:", "جاوب على:",
        "أجب عن:", "اشرح لي:",
    ):
        pos = goal.casefold().find(marker.casefold())
        if pos >= 0:
            return goal[pos + len(marker):].strip(" :،,؟?") or goal.strip()
    return goal.strip()


def _question_tokens(text: str) -> set[str]:
    return set(re.findall(r"[\w\u0600-\u06ff]+", normalize(text), flags=re.UNICODE))


def _split_sentences(text: str) -> list[str]:
    text = str(text or "").replace("\r", "\n")
    raw = re.split(r"(?<=[.!؟])\s+|\n+", text)
    return [s.strip(" \t-•") for s in raw if len(s.strip(" \t-•")) >= 25]


def _extractive_from_web(query: str, sources: list[dict], limit: int = 5) -> tuple[str, list[dict]]:
    q = _question_tokens(query)
    candidates: list[tuple[float, int, str, dict]] = []
    for source_idx, source in enumerate(sources):
        text = str(source.get("text") or "")
        title = str(source.get("title") or "")
        base = float(source.get("score", 0.0) or 0.0)
        title_tokens = _question_tokens(title)
        for sentence_idx, sentence in enumerate(_split_sentences(text)):
            st = _question_tokens(sentence)
            overlap = len(q & st) / max(1, len(q))
            title_overlap = len(q & title_tokens) / max(1, len(q))
            if overlap <= 0:
                continue
            score = 0.68 * overlap + 0.17 * title_overlap + 0.15 * base
            candidates.append((score, source_idx, sentence_idx, sentence, source))
    candidates.sort(key=lambda x: (-x[0], x[1], x[2]))
    selected: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for score, _source_idx, _sentence_idx, sentence, source in candidates:
        key = normalize(sentence)
        if key in seen:
            continue
        seen.add(key)
        selected.append((sentence, source))
        if len(selected) >= max(1, limit):
            break
    if not selected:
        return "", []

    evidence: list[dict] = []
    parts: list[str] = []
    seen_source: set[str] = set()
    for idx, (sentence, source) in enumerate(selected, 1):
        marker = f"[W{idx}]"
        parts.append(f"{sentence} {marker}")
        source_key = str(source.get("url") or source.get("title") or idx)
        if source_key not in seen_source:
            seen_source.add(source_key)
            evidence.append({
                "citation": marker,
                "title": source.get("title", ""),
                "url": source.get("url", ""),
                "score": round(float(source.get("score", 0.0) or 0.0), 6),
            })
    return "\n".join(parts), evidence


def _empty_answer(query: str, arabic: bool) -> dict[str, Any]:
    if arabic:
        message = "مش عندي دليل كفاية للإجابة على السؤال ده، ومش هخمن."
    else:
        message = "I don't have enough evidence to answer that safely, so I won't guess."
    return {"query": query, "status": "abstained", "route": "none", "answer": message,
            "grounded": False, "evidence": [], "reason": "no_grounded_evidence"}


def answer_question(query: str, *, rag: Any | None = None, web: Any | None = None) -> dict[str, Any]:
    q = str(query or "").strip()
    if not q:
        return _empty_answer(q, arabic=False)
    arabic = bool(re.search(r"[\u0600-\u06ff]", q))
    decision = classify_question(q)
    rag_engine = rag or RAGEngine()
    web_engine = web or WebResearchEngine()

    # Local evidence is the cheapest and most stable source.  Freshness-sensitive
    # questions still go to web after a local check because stale indexed material must
    # not be silently presented as current.
    try:
        local = rag_engine.query(q, top_k=6, max_hops=3)
    except Exception as exc:
        local = {"grounded": False, "answer": "", "evidence": [], "reason": f"rag_error:{exc}"}

    if local.get("grounded") and not decision.requires_fresh_data:
        return {
            "query": q, "status": "answered", "route": "rag", "answer": str(local.get("answer") or "").strip(),
            "grounded": True, "evidence": list(local.get("evidence") or []),
            "confidence": float((local.get("evidence_gate") or {}).get("score", 0.0) or 0.0),
            "reason": "local_rag_grounded", "trace": local.get("trace", []),
        }

    # Web is the fallback for open-world questions and the preferred source for current
    # facts.  Research itself indexes the fetched pages; a second RAG query then gets us
    # the same evidence gate and extractive citation machinery used locally.
    try:
        web_result = web_engine.research(q, limit=5, index=True)
    except Exception as exc:
        web_result = {"sources": [], "count": 0, "error": str(exc)}

    try:
        grounded_after_web = rag_engine.query(q, top_k=6, max_hops=2)
    except Exception:
        grounded_after_web = {"grounded": False, "answer": "", "evidence": []}

    if grounded_after_web.get("grounded") and grounded_after_web.get("answer"):
        return {
            "query": q, "status": "answered", "route": "web+ragra", "answer": str(grounded_after_web["answer"]).strip(),
            "grounded": True, "evidence": list(grounded_after_web.get("evidence") or []),
            "confidence": float((grounded_after_web.get("evidence_gate") or {}).get("score", 0.0) or 0.0),
            "reason": "web_retrieval_then_rag_grounding", "sources_found": int(web_result.get("count", 0) or 0),
        }

    answer, evidence = _extractive_from_web(q, list(web_result.get("sources") or []))
    if answer:
        return {
            "query": q, "status": "answered", "route": "web_extractive", "answer": answer,
            "grounded": True, "evidence": evidence,
            "confidence": round(max((float(x.get("score", 0.0) or 0.0) for x in evidence), default=0.0), 6),
            "reason": "web_extract", "sources_found": int(web_result.get("count", 0) or 0),
        }

    return _empty_answer(q, arabic)


@tool(
    "إجابة أسئلة المعرفة بشكل حتمي: RAG محلي أولًا ثم بحث ويب bounded عند الحاجة، مع evidence gate وcitations؛ بلا مولد نصوص؛ الإجابات extractive ومربوطة بالأدلة",
    {"query": "السؤال"},
    name="answer_question",
    triggers=("answer question", "answer this question", "knowledge question", "سؤال معرفي", "جاوب على", "أجب عن", "اشرح لي"),
    match=lambda g: is_generic_question(g) or any(x in g.casefold() for x in (
        "answer question", "answer this question", "knowledge question", "سؤال معرفي", "جاوب على", "أجب عن", "اشرح لي",
    )),
    build_args=lambda g: {"query": _question(g)},
    capability="question_answering",
    produces=("answer_grounded",),
    cost=4.0,
    duration=3.0,
    parallel_safe=False,
    idempotent=True,
    verification_level="strong",
    intent_priority=9,
)
def answer_question_tool(query: str):
    return answer_question(query)
