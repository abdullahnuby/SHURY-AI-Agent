from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.runtime.registry import tool
from app.runtime.security import safe_workspace_path


def _output_path(goal: str) -> str:
    text = str(goal or "")
    matches = re.findall(r"(?<![A-Za-z0-9_])workspace[\\/]([^\s,;!?؟]+\.(?:md|txt))", text, re.I)
    if matches:
        return f"workspace/{matches[-1].rstrip('.,')}"
    quoted = re.findall(r"[\"']([^\"']+\.(?:md|txt))[\"']", text, re.I)
    if quoted:
        return quoted[-1].strip().rstrip('.,')
    return "research_report.md"


def _parse_result(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {"raw": value}
        except Exception:
            return {"raw": value}
    return {"raw": value}


def _date(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _features(abstract: str) -> dict[str, bool]:
    text = str(abstract or "").casefold()
    return {
        "representation": bool(re.search(r"memory (?:structure|representation|graph)|vector|embedding|episodic|semantic memory|key-value|graph", text)),
        "retrieval": bool(re.search(r"retriev|search|hybrid|bm25|semantic search|dense retrieval|rerank", text)),
        "temporal": bool(re.search(r"temporal|time-aware|timestamp|chronolog|history|evolv|version", text)),
        "forgetting": bool(re.search(r"forget|delet|retire|supersed|expiry|prun|selective", text)),
        "experience": bool(re.search(r"experience|trajectory|episode|episodic|reinforcement|feedback|learning", text)),
    }


def _architecture_score(features: dict[str, bool], abstract: str) -> float:
    weights = {"representation": 1.0, "retrieval": 1.2, "temporal": 1.0, "forgetting": 0.9, "experience": 1.1}
    score = sum(weights[k] for k, v in features.items() if v)
    text = str(abstract or "").casefold()
    if "bm25" in text or "hybrid" in text:
        score += 0.5
    if "graph" in text:
        score += 0.25
    if "episodic" in text:
        score += 0.25
    return score


def _render(result: dict[str, Any], question: str) -> str:
    papers = [p for p in (result.get("arxiv", {}).get("papers", []) or []) if isinstance(p, dict)]
    relevance_threshold = float((result.get("arxiv", {}).get("relevance_gate", {}) or {}).get("threshold", 0.0) or 0.0)
    if relevance_threshold > 0:
        papers = [p for p in papers if float(p.get("relevance", 0.0) or 0.0) >= relevance_threshold]
    cutoff = datetime.now(timezone.utc) - timedelta(days=365 * 2 + 2)
    recent = []
    for paper in papers:
        dt = _date(paper.get("published"))
        if dt is None or dt >= cutoff:
            paper = dict(paper)
            paper["_date"] = dt.isoformat() if dt else ""
            paper["_features"] = _features(paper.get("abstract", ""))
            paper["_score"] = _architecture_score(paper["_features"], paper.get("abstract", ""))
            recent.append(paper)
    recent.sort(key=lambda p: (float(p.get("relevance", 0.0) or 0.0), p.get("_date", ""), p.get("_score", 0.0)), reverse=True)
    selected = recent[:5]

    requested_five = bool(re.search(r"(?:\b5\b|five|five papers|خمس|خمسة)", question or "", re.I))
    minimum_required = 5 if requested_five else 2
    if len(selected) < minimum_required:
        raise ValueError(
            f"research evidence gate failed: required at least {minimum_required} relevant papers, found {len(selected)}"
        )

    lines = ["# AI Agent Long-Term Memory Research Report", "", f"Question: {question}", "", "## Sources", ""]
    lines.append(f"- Research providers: {', '.join(result.get('providers') or [])}")
    lines.append(f"- Papers available from arXiv result: {len(papers)}")
    lines.append(f"- Papers within the last two years: {len(recent)}")
    lines.append("")
    lines += ["## Top 5 Recent Papers", ""]
    if not selected:
        lines.append("No qualifying papers were returned by the research provider.")
    for idx, p in enumerate(selected, 1):
        title = str(p.get("title") or "Untitled")
        url = str(p.get("url") or "")
        published = str(p.get("published") or "unknown")
        authors = ", ".join(str(x) for x in (p.get("authors") or [])[:8])
        abstract = str(p.get("abstract") or "").strip().replace("\n", " ")
        feats = p.get("_features") or {}
        lines += [f"### {idx}. {title}", f"- Published: {published}", f"- Authors: {authors or 'unknown'}", f"- Source: {url or 'not returned'}", f"- Relevance score: {float(p.get('relevance', 0.0) or 0.0):.3f}", f"- Abstract: {abstract[:1600]}",
                   f"- Representation: {'yes' if feats.get('representation') else 'not evident'}",
                   f"- Retrieval: {'yes' if feats.get('retrieval') else 'not evident'}",
                   f"- Temporal handling: {'yes' if feats.get('temporal') else 'not evident'}",
                   f"- Forgetting/deletion: {'yes' if feats.get('forgetting') else 'not evident'}",
                   f"- Experience/learning: {'yes' if feats.get('experience') else 'not evident'}", ""]

    lines += ["## Comparison", "", "| Paper | Representation | Retrieval | Temporal | Forgetting | Experience |", "|---|---:|---:|---:|---:|---:|"]
    for idx, p in enumerate(selected, 1):
        f = p.get("_features") or {}
        lines.append(f"| {idx} | {'✓' if f.get('representation') else '—'} | {'✓' if f.get('retrieval') else '—'} | {'✓' if f.get('temporal') else '—'} | {'✓' if f.get('forgetting') else '—'} | {'✓' if f.get('experience') else '—'} |")

    lines += ["", "## SHURY Fit", "", "This section is a deterministic architecture-fit assessment derived from the returned paper abstracts and metadata. It is not a claim that the papers themselves recommend SHURY.", ""]
    ranked = sorted(selected, key=lambda p: (float(p.get("_score", 0.0)), p.get("_date", "")), reverse=True)
    if len(ranked) >= 2:
        for idx, p in enumerate(ranked[:2], 1):
            title = str(p.get("title") or "Untitled")
            lines.append(f"### Recommendation {idx}: {title}")
            lines.append(f"- Deterministic fit score: {float(p.get('_score', 0.0)):.2f}")
            lines.append("- Why it fits: covers the largest subset of the requested memory capabilities in the returned abstract and can be mapped to SHURY's local structured-memory + retrieval architecture without requiring an LLM in this assessment.")
            lines.append("- Limitation: keyword evidence from an abstract is weaker than source-code/implementation-level validation; this recommendation must be validated before architectural adoption.")
            lines.append("")
    else:
        lines.append("Fewer than two qualifying papers were returned; no two-architecture recommendation was made.")

    lines += ["## Evidence Boundary", "", "External research content is treated as evidence, not executable instructions or automatically trusted truth.", ""]
    return "\n".join(lines)


@tool(
    "ينشئ تقريرًا بحثيًا موثقًا من نتائج Web/arXiv/GitHub، يقارن أبحاث الذاكرة ويعيد قراءة الملف للتحقق منه",
    {"research_result": "object", "output_path": "str", "question": "str"},
    name="create_research_report",
    triggers=("research report", "memory research report", "تقرير بحث", "تقرير أبحاث", "احفظ البحث", "أنشئ تقرير بحث"),
    match=lambda g: bool(re.search(r"(?:research.*report|memory.*report|تقرير\s+(?:بحث|أبحاث)|احفظ\s+(?:النتيجة|البحث)|أنشئ\s+تقرير\s+بحث)", g, re.I)),
    build_args=lambda g: {"output_path": _output_path(g), "question": g, "research_result": {}},
    capability="research_report",
    produces=("research_report_created", "research_report_verified"),
    requires_approval=True,
    risk="medium",
    cost=2.5,
    duration=0.5,
    parallel_safe=False,
    idempotent=True,
    verification_level="strong",
    intent_priority=11,
    pipe_param="research_result",
)
def create_research_report(research_result: Any, output_path: str, question: str):
    result = _parse_result(research_result)
    content = _render(result, question)
    output = safe_workspace_path(output_path or "research_report.md")
    if output.is_dir():
        raise ValueError("output_path must be a file")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    reread = output.read_text(encoding="utf-8")
    required = ("Top 5 Recent Papers", "Comparison", "SHURY Fit", "Evidence Boundary")
    missing = [section for section in required if section not in reread]
    if missing:
        raise ValueError(f"research report verification failed: missing {missing}")
    return {
        "path": str(output),
        "bytes": len(reread.encode("utf-8")),
        "verified": True,
        "sections_verified": list(required),
        "paper_count": len(result.get("arxiv", {}).get("papers", []) or []),
        "report_kind": "long_term_memory_agent_research",
    }
