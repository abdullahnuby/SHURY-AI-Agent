"""Goal model: clauses, ordering and explicit deterministic constraints."""
from dataclasses import dataclass, field
import re


@dataclass(frozen=True)
class GoalClause:
    text: str
    relation: str = "root"   # root | and | then | if
    index: int = 0


@dataclass
class GoalModel:
    original: str
    clauses: list[GoalClause] = field(default_factory=list)
    constraints: dict[str, object] = field(default_factory=dict)

    @property
    def compound(self) -> bool:
        return len(self.clauses) > 1


def _parse_constraints(text: str) -> dict[str, object]:
    c: dict[str, object] = {}
    # Time/cost budgets are optional and are only recognized when explicit.
    m = re.search(r"(?:خلال|في خلال|في غضون)\s+(\d+(?:\.\d+)?)\s*(?:ثانية|ثواني|دقيقة|دقائق|min|mins|sec|secs)", text, re.I)
    if m:
        value = float(m.group(1))
        unit = m.group(0).lower()
        c["max_duration"] = value * (60.0 if any(x in unit for x in ("دقيقة", "دقائق", "min")) else 1.0)
    m = re.search(r"(?:بميزانية|حد التكلفة|تكلفة أقصى|cost)\s*(?:=|:)?\s*(\d+(?:\.\d+)?)", text, re.I)
    if m:
        c["max_cost"] = float(m.group(1))
    m = re.search(r"(?:بحد أقصى|حد أقصى|max steps)\s*(\d+)\s*(?:خطوات|خطوة|steps)?", text, re.I)
    if m:
        c["max_steps"] = int(m.group(1))
    if re.search(r"(?:مع بعض|بالتوازي|معا|معًا|parallel|concurrently)", text, re.I):
        c["parallel"] = True
    return c


def parse_goal(text: str) -> GoalModel:
    original = text.strip()
    # Research questions often contain many conjunctions as part of the topic
    # ("RAG and algorithms and data analysis"), not separate executable steps.
    # Treat them as one research clause unless the user explicitly chains an action.
    low = original.casefold()
    research_markers = ("research", "newest research", "latest research", "web research", "rag", "retrieval", "knowledge base", "indexed documents",
                        "search the internet", "search online", "learn from the web", "learn from web", "learn from the internet", "learn online", "study online", "بحث على الانترنت", "بحث على الإنترنت",
                        "أحدث الأبحاث", "أحدث أبحاث", "تعلم من الانترنت", "تعلم من الإنترنت", "تعلم من الويب", "ابحث في أبحاث", "arxiv")
    chain_actions = ("save", "note", "download", "build", "test", "check", "inspect", "fetch",
                     "احفظ", "سجل", "نزّل", "نزل", "ابني", "اختبر", "افحص", "جلب", "هات")
    if any(m in low for m in research_markers) and not any(re.search(rf"\b{re.escape(a)}\b", low) for a in chain_actions):
        return GoalModel(original, [GoalClause(original, "root", 0)] if original else [], _parse_constraints(original))
    source = re.sub(
        r"\s+و(?=(?:احفظ|سجل|فكرني|اعرض|ابحث|دور|انس|انسى|امسح|افتكر|فاكر))",
        " ثم ",
        original,
        flags=re.I,
    )
    # Data-analysis requests commonly chain analysis with an explanation/finding
    # request. Those are one semantic task, not two executable clauses.
    low_source = source.casefold()
    analysis_context = any(x in low_source for x in (
        "analyze", "analysis", "dataset", "data", "outlier", "anomal", "correlation",
        "حلل", "تحليل", "البيانات", "ملف", "شذوذ", "القيم الشاذة", "ارتباط",
    ))
    explanatory_tail = any(x in low_source for x in (
        "explain", "describe", "interpret", "identify anomalies", "find anomalies", "find outliers", "explain anomalies",
        "اشرح", "فسر", "فسّر", "وضح", "وضّح", "اكتشف القيم الشاذة", "اكتشف الشذوذ",
    ))
    if analysis_context and explanatory_tail:
        matches = [m for m in re.finditer(r"\s+(وبعدها|ثم|وبعدين|و|and|then)\s+", source, flags=re.I)
                   if m.group(1).casefold() in {"ثم", "وبعدها", "وبعدين", "then"}]
    else:
        matches = list(re.finditer(r"\s+(وبعدها|ثم|وبعدين|و|and|then)\s+", source, flags=re.I))
    if not matches:
        clauses = [GoalClause(source.strip(), "root", 0)] if source.strip() else []
        return GoalModel(original, clauses, _parse_constraints(original))
    clauses = []
    start = 0
    for idx, m in enumerate(matches):
        part = source[start:m.start()].strip()
        if part:
            clauses.append(GoalClause(part, "root" if not clauses else m.group(1).lower(), len(clauses)))
        start = m.end()
    tail = source[start:].strip()
    if tail:
        relation = matches[-1].group(1).lower()
        if relation in ("و", "and"):
            relation = "and"
        elif relation in ("ثم", "then", "وبعدها", "وبعدين"):
            relation = "then"
        clauses.append(GoalClause(tail, relation if clauses else "root", len(clauses)))
    for i, c in enumerate(clauses):
        if i == 0:
            clauses[i] = GoalClause(c.text, "root", i)
    return GoalModel(original, clauses, _parse_constraints(original))
