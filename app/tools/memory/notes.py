import re
from app.runtime.registry import tool
from app.knowledge.memory import get_memory
from app.intelligence.keywords import SAVE_KW, LIST_KW, SEARCH_KW, HISTORY_KW, NAME_FACT_RE, has


def _note_args(goal: str) -> dict:
    text = re.sub(r"^.*?(سجل لي|سجل عندي|سجل|احفظ|فكرني|save|note)\s*", "", goal.strip(), flags=re.I | re.S).strip()
    return {"text": text}


def _query_args(goal: str) -> dict:
    return {"query": re.sub(r"^.*?(دور على|ابحث عن|search)\s*", "", goal.strip(), flags=re.I | re.S).strip()}


def _note_match(goal: str) -> bool:
    # Name/fact assignment is a memory operation, not a free-form note.
    if NAME_FACT_RE.search(goal) or has(goal, SEARCH_KW + LIST_KW):
        return False
    return has(goal, SAVE_KW)


@tool(description="يحفظ ملاحظة", params={"text": "نص الملاحظة"}, stage=1, requires_approval=True,
      retries=1, match=_note_match, build_args=_note_args, pipe_param="text",
      capability="save_note", produces=("note_saved",), cost=2.0, risk="medium", idempotent=False, parallel_safe=False, verification_level="strong")
def save_note(text: str):
    if not text.strip():
        raise ValueError("الملاحظة فاضية")
    return f"تم الحفظ (إجمالي الملاحظات: {get_memory().add_note(text.strip())})"


def _list_notes_match(goal: str) -> bool:
    g = goal.casefold().strip()
    return bool(re.search(
        r"(?:show|list|display)\s+(?:my\s+)?notes\b|"
        r"(?:اعرض|اعرض لي|اعرضلي|هات)\s+(?:كل\s+)?(?:الملاحظات|ملاحظاتي)",
        g, re.I,
    ))


@tool(description="يعرض كل الملاحظات", stage=0,
      match=_list_notes_match,
      capability="list_notes", produces=("notes_list_available",), cost=1.0, risk="low", parallel_safe=True)
def list_notes():
    return get_memory().list_notes()


def _search_notes_match(goal: str) -> bool:
    g = goal.casefold().strip()
    return bool(re.search(r"(?:^|\s)(?:search|ابحث عن|دور على)(?:$|\s)|(?:search|find|look)\s+(?:my\s+)?notes\b|(?:ابحث|دور)\s+(?:في\s+)?الملاحظات", g, flags=re.I)) and not any(
        x in g for x in (
            "memory", "my memory", "knowledge", "web", "internet", "online", "latest", "newest",
            "arxiv", "github", "skill", "skills", "file", "files", "project", "dataset",
            "على الانترنت", "على الإنترنت", "على الويب", "أحدث"
        )
    )


@tool(description="يدور في الملاحظات", params={"query": "كلمة البحث"}, stage=0,
      triggers=(), match=_search_notes_match,
      build_args=_query_args, capability="search_notes", produces=("notes_search_completed",),
      cost=1.2, risk="low", parallel_safe=True)

def search_notes(query: str):
    if not query:
        raise ValueError("كلمة البحث فاضية")
    return get_memory().search_notes(query)
