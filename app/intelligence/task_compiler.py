"""Deterministic semantic-to-task compiler.

This is a deterministic compilation layer. It compiles the typed semantic parse into
an intermediate task representation and a conservative planner-facing canonical form.
The existing planner remains the authority for executable planning.
"""
from __future__ import annotations

import re
from typing import Any

from app.intelligence.understanding import normalize

from app.domain.goal import parse_goal
from app.domain.task_ir import TaskCondition, TaskIR, TaskNode
from app.intelligence.semantic.models import SemanticParse
from app.planning.capabilities import INTENT_TO_CAPABILITY


_INTENT_GOAL = {
    "time": "what time is it",
    "development_validation": "check project",
    "development_inspection": "inspect project",
    "development_git": "git status",
    "skill_discovery": "discover skills",
    "skill_selection": "match skills",
    "skill_inventory": "installed skills",
    "skill_routing": "route skills",
    "list_skills": "list skills",
    "skill_inventory": "installed skills",
    "github_discovery": "find github repositories",
    "github_learning": "analyze this github repository",
    "scientific_research": "find recent academic papers",
    "web_research": "search online",
    "open_world_learning": "research and learn",
    "workspace_reasoning": "analyze workspace",
    "data_analysis": "analyze data",
    "agentic_rag": "agentic retrieval",
    "rag_reasoning": "retrieve evidence from the knowledge base",
    "memory_search": "search my memory",
    "memory_profile": "what do you remember about me",
    "memory_stats": "memory stats",
    "history": "history",
    "list_notes": "list notes",
    "calculate": "calculate",
    "save_note": "save note",
    "remember_fact": "remember",
    "recall_fact": "recall",
    "remember_result": "save the result as",
    "remember_last_result": "save the previous result as",
    "knowledge_query": "answer question",
}


def _query_from_slots(parse: SemanticParse) -> str:
    for key in ("research:query", "skill:query", "query"):
        value = parse.slots.get(key)
        if value:
            # Slot extraction is deliberately broad; normalize connector residue so
            # splitting a compound request does not send a query ending in "and"/"ثم"
            # to a downstream research or skill service.
            cleaned = re.sub(r"(?:\s+(?:and|or|then|ثم|و)\s*)+$", "", str(value).strip(), flags=re.I)
            if cleaned:
                return cleaned
    return ""


_SURFACE_INTENTS = (
    ("development_inspection", ("inspect the project", "inspect project", "inspect the repo", "inspect repository", "analyze the project", "حلل المشروع", "افحص المشروع", "حلل الريبو", "افحص الريبو")),
    ("development_validation", ("verify the repo", "verify repository", "verify the build", "passes its checks", "pass its checks", "run the tests", "the tests", "tests", "test project", "check the project", "build the project", "اختبر المشروع", "شغل الاختبارات", "افحص build", "تحقق من المشروع")),
    ("list_notes", ("list my notes", "show my notes", "display my notes", "اعرض الملاحظات", "اعرض ملاحظاتي")),
    ("save_note", ("save a note", "save note", "note this", "سجل عندي", "سجل لي", "سجل اجتماع", "احفظ ملاحظة")),
    ("list_skills", ("list skills", "show skills", "show my skills", "my skills", "list my skills", "الـskills", "الskills", "عرض المهارات", "اعرض المهارات", "قائمة المهارات", "مهاراتي")),
    ("skill_inventory", ("installed skills", "show installed skills", "remote skills", "skills inventory", "show the installed skills", "عرض المهارات المثبتة", "المهارات المثبتة", "المهارات الخارجية", "جرد المهارات")),
    ("skill_discovery", ("discover skills", "find skills", "find a skill", "search skills", "اكتشف المهارات", "اكتشف مهارات", "ابحث عن مهارات", "دور على skills")),
    ("skill_selection", ("match skills", "choose the right skill", "find the right skill", "skill for", "ما المهارة المناسبة", "مهارة مناسبة")),
    ("data_analysis", ("profile the dataset", "profile the data", "analyze the dataset", "analyze anomalies", "find anomalies", "find outliers", "حلل البيانات", "القيم الشاذة", "تحليل البيانات")),
    ("scientific_research", ("latest papers", "recent academic papers", "newest papers", "scientific papers", "أحدث الأبحاث", "الأوراق العلمية")),
    ("web_research", ("search the internet", "search online", "search the web", "ابحث على الانترنت", "ابحث على الإنترنت", "ابحث على الويب")),
    ("development_git", ("git status", "repository status", "check its state", "check repository state", "check repo state", "حالة git", "حالة المستودع")),
    ("github_discovery", ("find github repos", "search github repositories", "ابحث عن مشاريع github", "دور على مشاريع github")),
    ("github_learning", ("analyze github repo", "inspect github", "حلل مستودع github", "تعلم من github")),
    ("rag_reasoning", ("retrieve evidence from the knowledge base", "search the knowledge base", "retrieve evidence", "استرجع الأدلة", "ابحث في المعرفة")),
    ("recall_fact", ("what do you remember about", "recall", "فاكر ايه عن", "ماذا تتذكر عن", "ما اسم", "ايه اسمي", "ما اسمي")),
    ("calculate", ("calculate ", "calc ", "احسب ", "اضرب ", "اقسم ", "اطرح ", "اجمع ")),
)


def _surface_intent(text: str) -> str:
    n = normalize(text).strip()
    # Explicit action verbs override noisy secondary tokens such as "time", "project",
    # or "skill". Longest phrase wins within the same intent family.
    matches: list[tuple[int, str]] = []
    for intent, phrases in _SURFACE_INTENTS:
        for phrase in phrases:
            phrase_n = normalize(phrase).strip()
            if phrase_n and phrase_n in n:
                matches.append((len(phrase_n), intent))
    if not matches:
        return ""
    return max(matches, key=lambda item: item[0])[1]


def _planner_goal_for(parse: SemanticParse, original: str | None = None, intent_override: str | None = None) -> str:
    intent = intent_override or (parse.top_intent.name if parse.top_intent else "")
    base = _INTENT_GOAL.get(intent, "")
    source = (original or parse.original).strip()

    if intent == "calculate":
        expr = parse.slots.get("operation:expression")
        return f"calculate {expr}" if expr else source
    if intent in {"remember_fact", "remember_result", "remember_last_result"}:
        return parse.canonical_goal or source
    if intent == "recall_fact":
        key = parse.slots.get("recall:key")
        return f"what is my {key}" if key else source
    if intent == "memory_search":
        query = parse.slots.get("memory:query") or parse.slots.get("query") or source
        return f"search memory {query}".strip()
    if intent in {"web_research", "scientific_research", "github_discovery", "github_learning", "skill_discovery", "skill_selection", "skill_routing"}:
        query = _query_from_slots(parse)
        return f"{base} {query}".strip() if query else source if base == "" else base
    if intent in {"development_validation", "development_inspection"}:
        path = next((e.text for e in parse.entities if e.type in {"file", "repository"}), "")
        return f"{base} {path}".strip() if path else base
    if intent in {"save_note", "list_notes", "list_skills", "skill_inventory", "recall_fact"}:
        return source
    if intent == "knowledge_query":
        return source
    if intent == "data_analysis":
        # Preserve the user's detailed analytical question and path.  Tool adapters
        # know how to extract those safely; collapsing it to "analyze data" loses intent.
        return source
    if base:
        return base
    return source


def _relation_for_text(text: str) -> str:
    if re.search(r"\b(?:otherwise|else|otherwise do|وإلا|غير كده|غير ذلك)\b", text, re.I):
        return "otherwise"
    if re.search(r"\b(?:if|when|unless|لو|إذا|اذا|إلا إذا)\b", text, re.I):
        return "if"
    if re.search(r"\b(?:then|after that|afterwards|thereafter|ثم|وبعدها|وبعدين)\b", text, re.I):
        return "then"
    return "and" if re.search(r"\b(?:and|و)\b", text, re.I) else "root"


def _split_action_clause(text: str) -> list[tuple[str, str]]:
    """Split one legacy clause when it contains multiple distinct explicit actions.

    This is intentionally conservative: only clauses containing two or more distinct
    surface intents are split. Pure research phrases, free-form questions and single
    capability requests keep their original wording.
    """
    candidates: list[tuple[int, int, str]] = []
    for intent, phrases in _SURFACE_INTENTS:
        for phrase in phrases:
            if not phrase.strip():
                continue
            match = re.search(re.escape(phrase), text, re.I)
            if match:
                candidates.append((match.start(), match.end(), intent))
    # Keep the longest non-overlapping phrase at each region.
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    spans: list[tuple[int, int, str]] = []
    for start, end, intent in candidates:
        if any(start < e and end > s for s, e, _ in spans):
            continue
        spans.append((start, end, intent))
    spans.sort()
    if len({intent for _, _, intent in spans}) < 2:
        return [(text.strip(), "root")]

    parts: list[tuple[str, str]] = []
    for i, (start, _end, _intent) in enumerate(spans):
        seg_start = 0 if i == 0 else start
        seg_end = spans[i + 1][0] if i + 1 < len(spans) else len(text)
        segment = text[seg_start:seg_end].strip(" ,;:؛\t\n")
        # The connector can belong to the text immediately before the next action
        # span (e.g. "research X and retrieve evidence"). It is structural, not
        # part of the previous action's query.
        segment = re.sub(r"\s+(?:and|or|then|after that|afterwards|و|ثم|وبعدها|وبعدين)\s*$", "", segment, flags=re.I)
        if i > 0:
            segment = re.sub(r"^(?:and|then|after that|afterwards|و|ثم|وبعدها|وبعدين)\s+", "", segment, flags=re.I)
        if segment:
            connector = "root" if i == 0 else _relation_for_text(text[spans[i - 1][1]:start])
            if connector == "root":
                connector = "and"
            parts.append((segment, connector))
    return parts or [(text.strip(), "root")]


def _split_compound(text: str) -> list[tuple[str, str]]:
    """Split at meaningful action boundaries while preserving the *preceding* relation.

    The legacy goal parser stores separators on the clause to their left in some
    compound forms. For an agent task graph we need the relation that introduced each
    clause, because that relation determines dependency edges (especially ``then``).
    """
    normalized_text = re.sub(r"\s+(?:and\s+then|ثم\s+بعدها|و\s*بعدها)\s+", " then ", text, flags=re.I)
    model = parse_goal(normalized_text)
    raw = [(c.text.strip(), c.relation) for c in model.clauses if c.text.strip()]
    if not raw:
        return []
    refined: list[tuple[str, str]] = []
    for clause_text, clause_relation in raw:
        split_parts = _split_action_clause(clause_text)
        if len(split_parts) == 1:
            refined.append((clause_text, clause_relation))
            continue
        for idx, (part_text, relation) in enumerate(split_parts):
            refined.append((part_text, clause_relation if idx == 0 else relation))
    raw = refined
    if len(raw) == 1:
        return [(raw[0][0], "root")]

    def relation_between(segment: str) -> str:
        if re.search(r"\b(?:otherwise|else|وإلا|غير كده|غير ذلك)\b", segment, re.I):
            return "otherwise"
        if re.search(r"\b(?:if|when|unless|لو|إذا|اذا|إلا إذا)\b", segment, re.I):
            return "if"
        if re.search(r"\b(?:then|after that|afterwards|thereafter|ثم|وبعدها|وبعدين)\b", segment, re.I):
            return "then"
        return "and"

    clauses: list[tuple[str, str]] = [(raw[0][0], "root")]
    cursor = len(raw[0][0])
    for part, _legacy_relation in raw[1:]:
        pos = normalized_text.casefold().find(part.casefold(), cursor)
        if pos < 0:
            # Deterministic fallback when normalization/casing prevents a direct find.
            relation = _relation_for_text(part)
            if relation == "root":
                relation = "and"
        else:
            relation = relation_between(normalized_text[cursor:pos])
            cursor = pos + len(part)
        clauses.append((part, relation))

    # Collapse punctuation/ellipsis clauses that express one capability, e.g.
    # ``check the project build and tests``. Keep explicit ``then`` boundaries.
    merged: list[tuple[str, str, str]] = []
    for part, relation in clauses:
        surface = _surface_intent(part)
        if merged and relation == "and" and surface and merged[-1][2] == surface:
            previous, previous_relation, _ = merged[-1]
            merged[-1] = (f"{previous} and {part}", previous_relation, surface)
        else:
            merged.append((part, relation, surface))
    return [(part, relation) for part, relation, _surface in merged]


def _condition_from_text(text: str) -> TaskCondition | None:
    match = re.search(
        r"(?:if|when|لو|إذا|اذا)\s+(.+?)(?:,|\s+then\s+|\s+فـ|\s+ف)(.+)$",
        text.strip(), re.I | re.S,
    )
    if not match:
        return None
    expression = match.group(1).strip(" ,:؛")
    consequence = match.group(2).strip(" .!?؟")
    if not expression or not consequence:
        return None
    return TaskCondition("if", expression, consequence)


def compile_task_ir(parse: SemanticParse, world: Any = None) -> TaskIR:
    """Compile a semantic parse into a conservative, inspectable task graph."""
    original = parse.original.strip()
    parts = _split_compound(original)
    nodes: list[TaskNode] = []
    conditions: list[TaskCondition] = []
    unresolved = list(parse.required_information)
    all_planner_goals: list[str] = []

    for index, (part, relation) in enumerate(parts):
        # Import lazily to avoid an import cycle with the parser package.
        from app.intelligence.semantic.parser import semantic_understand

        subparse = parse if len(parts) == 1 and part == original else semantic_understand(part, mem=None, world=world)
        surface_intent = _surface_intent(part)
        intent = surface_intent or (subparse.top_intent.name if subparse.top_intent else "")
        objective = part if intent in {"web_research", "scientific_research", "github_discovery", "github_learning", "skill_discovery", "skill_selection"} else (subparse.canonical_goal or part)
        # Surface intent is a deterministic action override.  Use it consistently for
        # canonical planning too; storing the override while planning with a noisy top
        # intent was the cause of several previously observed regressions.
        planner_goal = _planner_goal_for(subparse, part, intent_override=intent)
        if surface_intent in {"list_skills", "skill_inventory", "list_notes", "save_note", "recall_fact"}:
            planner_goal = part
        node_id = f"t{index + 1}"
        depends = (f"t{index}",) if index > 0 and relation in {"then", "otherwise"} else ()
        if index > 0 and relation == "root":
            depends = (f"t{index}",)
        intent_capability = INTENT_TO_CAPABILITY.get(intent, "")
        if not intent_capability:
            intent_capability = next(
                (candidate.capability for candidate in subparse.intent_candidates if candidate.name == intent and candidate.capability),
                "",
            )
        node = TaskNode(
            id=node_id,
            objective=objective,
            planner_goal=planner_goal,
            kind="information" if subparse.actionability == "information" else "action",
            intent=intent,
            capability=intent_capability or subparse.domain,
            arguments=dict(subparse.slots),
            depends_on=depends,
            relation=relation or "root",
            success_conditions=(f"intent:{intent}",) if intent else (),
            confidence=float(subparse.confidence),
        )
        nodes.append(node)
        if planner_goal:
            all_planner_goals.append(planner_goal)
        unresolved.extend(subparse.required_information)
        condition = _condition_from_text(part)
        if condition is not None:
            conditions.append(condition)

    # Explicit conditional language can span clauses. Preserve it in the IR instead of
    # pretending the current planner already executes arbitrary branches.
    otherwise_match = re.search(r"(?:otherwise|else|وإلا|غير كده|غير ذلك)\s+(.+)$", original, re.I | re.S)
    if otherwise_match:
        conditions.append(TaskCondition("otherwise", "previous condition false", otherwise_match.group(1).strip()))

    # Remove duplicate unresolved requirements while preserving order.
    dedup_unresolved: list[str] = []
    for item in unresolved:
        if item and item not in dedup_unresolved:
            dedup_unresolved.append(item)

    confidence = min((node.confidence for node in nodes), default=float(parse.confidence))
    planner_goal = " then ".join(all_planner_goals) if all_planner_goals else original

    # Explicit result-save chains become typed dataflow.  The runtime reference is
    # intentionally NOT stored in TaskIR as ``$ref:t1`` because execution resolves
    # concrete step ids (``{{s1}}``) only after planning/renumbering.
    for index in range(1, len(nodes)):
        prev, current = nodes[index - 1], nodes[index]
        if current.intent in {"remember_result", "remember_last_result"}:
            nodes[index] = TaskNode(**{**current.__dict__, "depends_on": tuple(dict.fromkeys(current.depends_on + (prev.id,)))})

    return TaskIR(
        original=original,
        objective=parse.canonical_goal or (nodes[0].objective if nodes else original),
        nodes=nodes,
        conditions=conditions,
        constraints={c.key: c.value for c in parse.constraints},
        assumptions=[],
        unresolved=dedup_unresolved,
        planner_goal=planner_goal,
        confidence=max(0.0, min(1.0, confidence)),
    )
