from __future__ import annotations
import re
from app.intelligence.understanding import normalize
from app.intelligence.keywords import extract_calculation_expression


def extract_slots(text: str) -> dict[str, str]:
    n = normalize(text)
    question = re.sub(r"[?؟!.,]+$", "", n).strip()
    slots: dict[str, str] = {}
    patterns = [
        (r"^(?:no\b|actually\b|i\s+meant|i\s+mean(?!t)|that\s+isn't\s+right|not\s+that)\s*(?:[:,;-]?\s*)?(?:i\s+mean|i\s+meant)?\s*(.+)$", "correction:value"),
        (r"^(?:لا\b|بل\b|قصدي\b|اقصد\b|أقصد\b)\s*(?:[:,;-]?\s*)?(.+)$", "correction:value"),
        (r"(?:my\s+name\s+is|my\s+name\s+as|save\s+my\s+name(?:\s+as)?|store\s+my\s+name(?:\s+as)?|اسمي(?:\s+هو)?|احفظ\s+اسمي(?:\s+هو)?)\s*[:=]?\s*([^,.!?؟\n]+)", "fact:name"),
        (r"(?:my\s+city\s+is|store\s+my\s+city(?:\s+as)?|save\s+my\s+city(?:\s+as)?|i\s+live\s+in|i\s+am\s+living\s+in|مدينتي(?:\s+هي)?|احفظ\s+مدينتي(?:\s+باسم)?|انا\s+ساكن\s+في|انا\s+عايش\s+في|انا\s+اعيش\s+في|انا\s+اسكن\s+في|ساكن\s+في|عايش\s+في|اعيش\s+في|اسكن\s+في)\s*[:=]?\s*(?:مدينة\s+)?([^,.!?؟\n]+)", "fact:city"),
        (r"(?:my\s+language\s+is|my\s+preferred\s+language\s+is|لغتي(?:\s+هي)?)\s*[:=]?\s*([^,.!?؟\n]+)", "fact:language"),
        (r"(?:my\s+job\s+is|my\s+work\s+is|my\s+profession\s+is|i\s+work\s+as|i\s+am\s+a(?:\s+\w+)?\s+\w|وظيفتي\s+هي|وظيفتي|مهنتي\s+هي|مهنتي|شغلتي|شغلي|انا\s+شغال|انا\s+بشتغل|بشتغل|انا\s+اعمل\s+ك|اعمل\s+ك)\s*[:=]?\s*([^,.!?؟\n]+)", "fact:job"),
        # Generic explicit memory assignment. Specific patterns above still win because
        # they preserve canonical aliases such as name/city/origin.
        (r"(?:save|store|remember|احفظ|سجل|افتكر|تذكر(?:\s+ان)?)\s+(?:this|that)\s+(?:information|fact|detail|المعلومة|المعلومة\s+دي|المعلومة\s+ده)\s*[:：=]\s*([^:：=,.!?؟\n]+)\s*[:：=]\s*([^,.!?؟\n]+)", "fact:generic"),
        (r"(?:save|store|remember|احفظ|سجل|افتكر|تذكر(?:\s+ان)?)(?!\s+(?:this|that)\s+(?:information|fact|detail)\b)\s+([^:：=]+)\s*[:：=]\s*([^,.!?؟\n]+)", "fact:generic"),
        (r"(?:احفظ|سجل)\s+ان\s+(اسم\s+المشروع)\s+([^,.!?؟\n]+)", "fact:generic"),
        (r"(?:i\s*(?:[\'’]?m|am)\s+(?:originally\s+)?from|i\s+come\s+from|i\s+originally\s+from|i\s+was\s+born\s+in|انا\s+من|أنا\s+من|انا\s+اصلي\s+من|أنا\s+أصلي\s+من|انا\s+اتولدت\s+في|أنا\s+اتولدت\s+في)\s*[:=]?\s*([^,.!?؟\n]+)", "fact:origin"),
        (r"انا\s+(?:سني|عمري)\s+(\d{1,3})\s*(?:سنه|سنين|عام|اعوام)?", "fact:age"),
        (r"(?:i\s+prefer|i\s+like|i\s+usually\s+use|انا\s+بفضل|انا\s+افضل|انا\s+احب|انا\s+عادة\s+بستخدم)\s+(.+)", "preference:general"),
        (r"(?:i\s+prefer\s+(?:the\s+)?)?(dark|light)\s+mode", "preference:theme"),
        (r"(?:انا\s+بفضل\s+)?الوضع\s+(الداكن|الفاتح)", "preference:theme"),
        (r"(?:save|store|remember)\s+(?:the\s+)?(?:result|output|previous\s+result|last\s+result)\s+as\s+([A-Za-z_][\w-]*)", "result:key"),
        (r"(?:احفظ|سجل|افتكر)\s+(?:النتيجة|الناتج)\s+(?:السابقة|السابق|اللي فات)?\s*(?:باسم|تحت اسم)\s+([\w-]+)", "result:key"),
        (r"(?:what(?:'s|\s+is)\s+my\s+(?:preferred|favorite)\s+theme|what\s+theme\s+do\s+i\s+prefer|ما(?: هو)?\s+(?:الثيم|الوضع)\s+(?:المفضل|المفضلة)|ما\s+(?:الثيم|الوضع)\s+اللي\s+بفضله)\s*[?؟]?$", "recall:key"),
        (r"(?:what(?:'s|\s+is)\s+my|do\s+you\s+remember\s+my)\s+([A-Za-z][A-Za-z0-9 _-]{0,48}?)[?؟]?$", "recall:key"),
        (r"(?:calculate|احسب|calc)\s+(.+?)(?:\s+(?:and|then|و|ثم)\s+(?:save|store|احفظ|سجل).*)?$", "operation:expression"),
        (r"(?:search(?:\s+the)?\s+(?:internet|web)|ابحث\s+(?:على|في)\s+(?:الانترنت|الإنترنت|الويب)|دور\s+على)\s+(.+)", "research:query"),
    ]
    forget_match = re.match(r"^\s*(?:forget|delete|erase|remove|انس|انسى|امسح|احذف)\s+(?!everything\b)(?:my\s+|this\s+|that\s+)?(.+?)\s*[?؟!]?$", n, re.I)
    if forget_match:
        candidate = forget_match.group(1).strip()
        if candidate and candidate.casefold() not in {"everything about me", "everything", "all my memory", "كل ذاكرتي", "كل حاجة عني"}:
            slots["forget:key"] = candidate

    expression = extract_calculation_expression(n)
    if expression:
        slots["operation:expression"] = expression
    for pattern, key in patterns:
        m = re.search(pattern, n, re.I | re.S)
        if not m:
            continue
        if key == "fact:generic" and len(m.groups()) > 1:
            fact_key = (m.group(1) or "").strip(" .!?؟:：=")
            fact_value = (m.group(2) or "").strip(" .!?؟")
            if fact_key and fact_value:
                slots[f"fact:{fact_key}"] = fact_value
            continue
        value = next((g for g in m.groups() if g), "").strip(" .!?؟")
        if value:
            # The dedicated arithmetic extractor is the canonical producer for
            # operation:expression. Generic slot regexes may capture trailing
            # politeness or mixed-language text, but must never overwrite a
            # validated expression.
            if key == "operation:expression" and slots.get(key):
                continue
            slots[key] = value
    if re.fullmatch(r"(?:what(?:'s|\s+is)\s+my\s+(?:preferred|favorite)\s+theme|what\s+theme\s+do\s+i\s+prefer)", n, re.I):
        slots["recall:key"] = "theme"
    elif re.fullmatch(r"(?:ما(?:\s+هو)?\s+(?:الثيم|الوضع)\s+(?:المفضل|المفضلة)|ما\s+(?:الثيم|الوضع)\s+اللي\s+بفضله)", n, re.I):
        slots["recall:key"] = "theme"
    if re.fullmatch(r"(?:ma(?:\s+is|\s+am)|what(?:\s+is|\'s)?|tell\s+me|say)\s+(?:my\s+)?name(?:\s+again)?", question, re.I) or re.fullmatch(r"(?:ما(?:\s+هو|\s+هي)?\s+(?:اسمي|إسمي)|ايه(?:\s+هو|\s+هي)?\s+(?:اسمي|إسمي)|(?:فاكر|تفتكر)\s+(?:انا\s+)?(?:اسمي|إسمي)(?:\s+(?:ايه|إيه))?|(?:قولي|قولّي|قوليلي|قولى)\s+(?:انا\s+)?(?:اسمي|إسمي)(?:\s+(?:تاني|ثاني))?|اسم\s+مين\s+المسجل\s+عندك)", question, re.I):
        slots["recall:key"] = "name"
    elif re.fullmatch(r"(?:what(?:\s+is|\'s)?\s+my\s+city|where\s+is\s+my\s+city|what\s+city\s+(?:am\s+i\s+in|do\s+i\s+live\s+in)|ما(?:\s+هو|\s+هي)?\s+مدينتي|ايه(?:\s+هو|\s+هي)?\s+مدينتي|(?:اين|فين)\s+(?:هي\s+)?مدينتي)", question, re.I):
        slots["recall:key"] = "city"
    elif re.fullmatch(r"(?:ما(?:\s+هي|\s+هو)?\s+لغتي(?:\s+المفضلة)?|ايه(?:\s+هي|\s+هو)?\s+لغتي(?:\s+المفضلة)?|لغتي\s+المفضلة)", question, re.I):
        slots["recall:key"] = "preference" if re.search(r"المفضلة", question) else "language"
    elif re.fullmatch(r"(?:where\s+am\s+i\s+from|where\s+do\s+i\s+come\s+from|what\s+is\s+my\s+origin|من\s+انا|انا\s+من\s+فين|انا\s+منين(?:\s+يا\s+شوري)?|انا\s+اصلي\s+منين|(?:فاكر|تفتكر)\s+(?:انا\s+)?(?:منين|من\s+فين))", question, re.I):
        slots["recall:key"] = "origin"
    if not slots.get("recall:key"):
        if re.search(r"(?:اين\s+(?:اعيش|اسكن)|فين\s+(?:ساكن|عايش)|(?:اعيش|اسكن)\s+فين|where\s+do\s+i\s+live|where\s+am\s+i\s+living)", n, re.I):
            slots["recall:key"] = "city"
        elif re.search(r"(?:انا\s+)?بشتغل\s+ايه|وظيفتي\s+ايه|شغلتي\s+ايه|مهنتي\s+ايه|ما\s+مهنتي|ما\s+وظيفتي|what\s+is\s+my\s+job|what\s+is\s+my\s+profession|what\s+do\s+i\s+do|do\s+you\s+remember\s+my\s+job", n, re.I):
            slots["recall:key"] = "job"
    if slots.get("recall:key"):
        for key in tuple(slots):
            if key.startswith("fact:"):
                slots.pop(key, None)
    return slots
