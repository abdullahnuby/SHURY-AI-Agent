import re

CALC_KW = ("احسب", "حساب", "احسبلي", "احسبها", "calc", "calculate")
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

def _normalize_numbering(text: str) -> str:
    table = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
    return str(text or '').translate(table).replace('٪', '%')


def _natural_arithmetic(text: str) -> str | None:
    n = _normalize_numbering(text)
    number = r"-?\d+(?:\.\d+)?%?"
    # Compound multiply-then-percentage must be recognized before the generic
    # "base + percentage" suffix, otherwise only the final numeric operand is captured.
    m = re.search(
        r"(?P<a>-?\d+(?:\.\d+)?)\s+(?:في|ضرب|×|times|multiplied by)\s+"
        r"(?P<b>-?\d+(?:\.\d+)?)\s+(?:و\s*|ثم\s+|and\s+|then\s+)?"
        r"(?:زود|زودي|زودت|أضف|اضف|زائد|plus)\s+(?P<p>\d+(?:\.\d+)?)%",
        n, re.I,
    )
    if m:
        p = float(m.group('p')) / 100.0
        return f"({m.group('a')}*{m.group('b')})*(1+{p})"
    # Percent after an already parsed arithmetic base is an uplift/reduction of that result.
    if re.search(r"(?:زود|زودي|زودت|أضف|اضف|زائد|plus)\s+" + number + r"\s*$", n, re.I):
        m = re.search(
            r"(?P<base>[-+*/()\d. ]+)\s+(?:زود|زودي|زودت|أضف|اضف|زائد|plus)\s+"
            r"(?P<p>\d+(?:\.\d+)?)%?\s*$", n, re.I
        )
        if m and any(c.isdigit() for c in m.group('base')):
            p = float(m.group('p')) / 100.0
            return f"({m.group('base').strip()})*(1+{p})"
    m = re.search(r"(?P<a>-?\d+(?:\.\d+)?)\s+(?:في|ضرب|×|times|multiplied by)\s+(?P<b>-?\d+(?:\.\d+)?)", n, re.I)
    if m: return f"{m.group('a')}*{m.group('b')}"
    m = re.search(r"(?P<a>-?\d+(?:\.\d+)?)\s+(?:على|قسمة|÷|divided by)\s+(?P<b>-?\d+(?:\.\d+)?)", n, re.I)
    if m: return f"{m.group('a')}/{m.group('b')}"
    m = re.search(r"(?P<a>-?\d+(?:\.\d+)?)\s+(?:زائد|و|plus|add)\s+(?P<b>-?\d+(?:\.\d+)?)%?", n, re.I)
    if m: return f"{m.group('a')}+{m.group('b')}"
    m = re.search(r"(?P<a>-?\d+(?:\.\d+)?)\s+(?:ناقص|طرح|minus|subtract)\s+(?P<b>-?\d+(?:\.\d+)?)", n, re.I)
    if m: return f"{m.group('a')}-{m.group('b')}"
    return None


def extract_calculation_expression(goal: str) -> str | None:
    text = _normalize_numbering(str(goal or '').strip())
    natural = _natural_arithmetic(text)
    if natural:
        return natural
    for pattern, builder in _NATURAL_CALC_PATTERNS:
        m = pattern.search(text)
        if m:
            return builder(m)
    m = re.search(r"(?:^|\b)(?:calculate|calc|احسب)\s+(.+)$", text, re.I | re.S)
    if m:
        tail = re.split(r"\s+(?:and|then|و|ثم)\s+(?=(?:save|store|احفظ|سجل)\b)", m.group(1), maxsplit=1, flags=re.I)[0]
        candidate = re.sub(r"\s+(?:please|pls|لو\s+سمحت|من\s+فضلك)$", "", tail.strip(), flags=re.I).strip(" .!?؟")
        candidate = candidate.replace('×', '*').replace('÷', '/').replace('٪', '%')
        # A percentage operand in a simple +/- expression is a percentage of the base,
        # not a decimal fraction concatenated to it (100 + 14% => 114).
        m_pct = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([+\-])\s*(\d+(?:\.\d+)?)%", candidate)
        if m_pct:
            sign = '+' if m_pct.group(2) == '+' else '-'
            factor = 1 + float(m_pct.group(3)) / 100.0 if sign == '+' else 1 - float(m_pct.group(3)) / 100.0
            return f"{m_pct.group(1)}*{factor}"
        if re.fullmatch(r"[\d\s.\+\-*/%^()]+", candidate) and any(ch.isdigit() for ch in candidate):
            return candidate
    m = EXPR_RE.search(text)
    if m:
        candidate = m.group(0).strip()
        depth = 0
        for ch in candidate:
            if ch == '(': depth += 1
            elif ch == ')': depth -= 1
            if depth < 0: break
        if depth == 0 and any(symbol in candidate for symbol in '+-*/%^'):
            return candidate
    return None


def has(goal: str, kws) -> bool:
    g = goal.lower()
    return any(k in g for k in kws)


def other_intent(goal: str) -> bool:
    return (has(goal, SAVE_KW + SEARCH_KW + LIST_KW + HISTORY_KW + TIME_KW)
            or bool(REMEMBER_RE.search(goal)) or bool(RECALL_RE.search(goal)))
