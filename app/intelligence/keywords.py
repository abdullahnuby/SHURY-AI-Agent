import re

CALC_KW = ("احسب", "حساب", "calc")
SAVE_KW = ("سجل", "احفظ", "فكرني", "note", "save")
TIME_KW = ("الساعة كام", "الوقت", "التاريخ", "time")
LIST_KW = ("اعرض", "ملاحظاتي", "الملاحظات", "list")
SEARCH_KW = ("دور على", "ابحث عن", "search")
HISTORY_KW = ("اخر الاهداف", "آخر الأهداف", "آخر الاهداف", "اخر الأهداف", "history", "السجل")
PIPE_KW = ("النتيجة", "النتيجه", "نتيجتها", "الناتج")

# Fact assignment supports both explicit key/value syntax and common natural-language
# forms such as "save my name as Abdullah", "save me name Abdullah", and "my name is Abdullah".
REMEMBER_RE = re.compile(
    r"(?:افتكر|تذكر أن|remember(?: that)?)\s+(.+?)\s*[:=]\s*(.+)",
    re.I | re.S,
)
NAME_FACT_RE = re.compile(
    r"(?:"
    r"(?:save|store|remember)(?:\s+that)?\s+(?:me\s+)?(?:my\s+)?name\s*(?:as|is)?:?\s*(?P<saved>.+)"
    r"|(?:my\s+name|اسمي)\s*(?:is|هو|=|:)\s*(?P<stated>.+)"
    r"|(?:احفظ|سجل|افتكر|ثبت)\s+(?:اسمي|اسم\s*؟?ك|الاسم)\s*(?:هو|=|:)\s*(?P<arabic>.+)"
    r")$",
    re.I | re.S,
)
RECALL_RE = re.compile(
    r"(?:"
    r"(?:فاكر\s+(?:ايه|إيه)\s+عن|what do you remember about|recall)\s+(?P<key>.+)"
    r"|(?:what(?:'s| is)\s+my\s+(?P<mykey>[a-zA-Z][\w -]{0,48}))\s*[?؟]?$"
    r"|(?:do\s+you\s+remember\s+my\s+(?P<rememberkey>[a-zA-Z][\w -]{0,48}))\s*[?؟]?$"
    r"|(?:what(?:'s| is)\s+my\s+name|do\s+you\s+remember\s+my\s+name|remember\s+my\s+name|who\s+am\s+i)\s*[?؟]?$"
    r"|(?:ما\s+(?:هو\s+)?اسمي|ايه\s+اسمي|إيه\s+اسمي|فاكر\s+اسمي)\s*[?؟]?$"
    r")",
    re.I | re.S,
)

NUM = r"[\d\s\.\+\-\*/\(\)%\^]"
EXPR_RE = re.compile(r"(?<![A-Za-z0-9_])(?:\-?\d(?:[\d\s\.]*\d)?(?:\s*[+\-*/%^]\s*\-?\d(?:[\d\s\.]*\d)?|\s*[()]*)+)(?![A-Za-z0-9_])")

_NATURAL_CALC_PATTERNS = (
    (re.compile(r"\bwhat\s+is\s+(-?\d+(?:\.\d+)?)\s+times\s+(-?\d+(?:\.\d+)?)\b", re.I), lambda m: f"{m.group(1)}*{m.group(2)}"),
    (re.compile(r"\b(?:multiply)\s+(-?\d+(?:\.\d+)?)\s+by\s+(-?\d+(?:\.\d+)?)\b", re.I), lambda m: f"{m.group(1)}*{m.group(2)}"),
    (re.compile(r"\b(?:divide)\s+(-?\d+(?:\.\d+)?)\s+by\s+(-?\d+(?:\.\d+)?)\b", re.I), lambda m: f"{m.group(1)}/{m.group(2)}"),
    (re.compile(r"\b(?:subtract)\s+(-?\d+(?:\.\d+)?)\s+from\s+(-?\d+(?:\.\d+)?)\b", re.I), lambda m: f"{m.group(2)}-{m.group(1)}"),
    (re.compile(r"\b(?:add)\s+(-?\d+(?:\.\d+)?)\s+and\s+(-?\d+(?:\.\d+)?)\b", re.I), lambda m: f"{m.group(1)}+{m.group(2)}"),
    (re.compile(r"(?:اضرب|ضرب)\s+(-?\d+(?:\.\d+)?)\s+(?:في|و)\s+(-?\d+(?:\.\d+)?)", re.I), lambda m: f"{m.group(1)}*{m.group(2)}"),
    (re.compile(r"(?:اقسم|قسمة)\s+(-?\d+(?:\.\d+)?)\s+(?:على|و)\s+(-?\d+(?:\.\d+)?)", re.I), lambda m: f"{m.group(1)}/{m.group(2)}"),
    (re.compile(r"(?:اطرح|طرح)\s+(-?\d+(?:\.\d+)?)\s+(?:من)\s+(-?\d+(?:\.\d+)?)", re.I), lambda m: f"{m.group(2)}-{m.group(1)}"),
    (re.compile(r"(?:اجمع|جمع)\s+(-?\d+(?:\.\d+)?)\s+(?:و)\s+(-?\d+(?:\.\d+)?)", re.I), lambda m: f"{m.group(1)}+{m.group(2)}"),
)

def extract_calculation_expression(goal: str) -> str | None:
    text = str(goal or "").strip()
    for pattern, builder in _NATURAL_CALC_PATTERNS:
        m = pattern.search(text)
        if m:
            return builder(m)
    # Explicit calculation commands: isolate the arithmetic tail before a chained action.
    m = re.search(r"(?:^|\b)(?:calculate|calc|احسب)\s+(.+)$", text, re.I | re.S)
    if m:
        tail = re.split(r"\s+(?:and|then|و|ثم)\s+(?=(?:save|store|احفظ|سجل)\b)", m.group(1), maxsplit=1, flags=re.I)[0]
        # Strip trailing politeness markers without weakening the arithmetic grammar.
        candidate = re.sub(r"\s+(?:please|pls|لو\s+سمحت|من\s+فضلك)$", "", tail.strip(), flags=re.I).strip(" .!?؟")
        if re.fullmatch(r"[\d\s\.\+\-*/%^()]+", candidate) and any(ch.isdigit() for ch in candidate):
            return candidate
    m = EXPR_RE.search(text)
    if m:
        candidate = m.group(0).strip()
        # Verify parenthesis balance before exposing the candidate to ast.parse.
        depth = 0
        for ch in candidate:
            if ch == "(": depth += 1
            elif ch == ")": depth -= 1
            if depth < 0: break
        if depth == 0 and any(op in candidate for op in "+-*/%^"):
            return candidate
    return None


def has(goal: str, kws) -> bool:
    g = goal.lower()
    return any(k in g for k in kws)


def other_intent(goal: str) -> bool:
    return (has(goal, SAVE_KW + SEARCH_KW + LIST_KW + HISTORY_KW + TIME_KW)
            or bool(REMEMBER_RE.search(goal)) or bool(RECALL_RE.search(goal)))
