from __future__ import annotations

import re
from dataclasses import dataclass

from app.brain.models import SemanticFrame


ARABIC_WORDS = re.compile(r'[\u0600-\u06ff]')


def detect_language(text: str) -> str:
    ar = len(ARABIC_WORDS.findall(text))
    en = len(re.findall(r'[A-Za-z]', text))
    if ar and en:
        return 'mixed'
    if ar:
        return 'ar'
    if en:
        return 'en'
    return 'other'


def _norm(text: str) -> str:
    return re.sub(r'\s+', ' ', str(text or '').strip()).casefold()


def _clean(value: str) -> str:
    return re.sub(r'\s+', ' ', str(value or '').strip(' \t\r\n.,،:;؛?!؟')).strip()


def perceive(text: str, *, last_goal: str = '', recent_topics: tuple[str, ...] = ()) -> SemanticFrame:
    original = str(text or '').strip()
    n = _norm(original)
    lang = detect_language(original)
    concepts: set[str] = set()
    entities: list[tuple[str, str]] = []
    slots: dict[str, str] = {}
    conditions: list[str] = []
    temporal: list[str] = []
    uncertainty: list[str] = []
    operation = ''
    object_text = ''
    question_type = ''

    is_greeting = bool(re.search(r'^(?:hi|hello|hey|مرحبا|اهلا|أهلا|ازيك|إزيك|عامل ايه|ايه الأخبار|إيه الأخبار)\b', n))
    is_question = bool(re.search(r'[?؟]$', original)) or bool(re.match(r'^(?:what|who|when|where|why|how|is|are|can|do|does|ايه|إيه|ما|ماذا|مين|من|متى|اين|فين|ليه|لماذا|ازاي|إزاي|هل)\b', n))

    if is_greeting:
        speech_act = 'greeting'
    elif is_question:
        speech_act = 'question'
    elif re.search(r'^(?:save|store|remember|calculate|compute|find|search|research|learn|study|teach|run|build|inspect|احفظ|افتكر|تذكر|احسب|دور|ابحث|بحث|تعلم|تعلّم|ادرس|علمني|علّمني|شغل|نفذ|افحص|حلل|اكتب|اعمل)\b', n):
        speech_act = 'instruction'
    else:
        speech_act = 'statement'

    if re.search(r'(?:who am i|what(?:\'s| is) my name|do you remember my name|who is me|انا مين|أنا مين|مين انا|مين أنا|من انا|من أنا|ما(?: هو)? اسمي|ما(?: هو)? إسمي|إيه(?: هو)? اسمي|ايه(?: هو)? اسمي|إيه اسمي|ايه اسمي|فاكر اسمي|فاكر اسمي ايه|إيه اسمي)', n):
        concepts.add('person_identity'); operation = 'query_identity'; question_type = 'identity'
        slots['key'] = 'name'; slots['predicate'] = 'name'
    elif re.search(r'(?:what(?:\'s| is) my (?:city|origin|language)|where am i from|where do i come from|what is my origin|ما(?: هو| هي)? (?:مدينتي|أصلي|اصلي|لغتي)|فين انا من|أنا من فين|انا من فين)', n):
        concepts.add('memory'); operation = 'query_memory'; question_type = 'memory_fact'
        if re.search(r'origin|come from|am i from|أصلي|اصلي|من فين', n, re.I):
            slots['key'] = 'origin'
        elif re.search(r'language|لغتي', n, re.I):
            slots['key'] = 'language'
        else:
            slots['key'] = 'city'
    elif re.search(r'(?:what can you do|what are your capabilities|what capabilities do you have|what can you help with|ماذا تستطيع|ما الذي تستطيع|إنت بتعمل إيه|انت بتعمل ايه|بتعرف تعمل ايه|بتعرف تعمل ايه معايا|إيه اللي بتعرف تعمله)', n):
        concepts.add('capability'); operation = 'query_capabilities'; question_type = 'capabilities'
    elif re.search(r'(?:what(?:\'s| is) the time|what time is it|متى الوقت|الساعة كام|الساعه كام|الوقت كام|ممكن تقولي الساعة)', n):
        concepts.add('time'); operation = 'query_time'; question_type = 'time'
    elif re.search(r'(?:calculate|compute|احسب|حساب)', n) and re.search(r'\d+(?:\s*[+\-*/%^x×÷]\s*\d+)+', n) and re.search(r'(?:save|remember|store|احفظ|افتكر|سجل).*(?:result|الناتج|النتيجة)', n):
        concepts.update({'calculation', 'memory'}); operation = 'compound_calculate_remember'
        expr = re.search(r'\d+(?:\s*[+\-*/%^x×÷]\s*\d+)+', n)
        if expr:
            slots['expression'] = expr.group(0).replace('×','*').replace('÷','/')
        mkey = re.search(r'(?:as|named|under(?: the)? name|باسم|تحت اسم)\s+([A-Za-z0-9_\-]+)', original, re.I)
        if mkey:
            slots['result_key'] = mkey.group(1).strip()
    elif re.search(r'(?:calculate|compute|احسب|حساب)', n) and re.search(r'\d+(?:\s*[+\-*/%^x×÷]\s*\d+)+', n):
        concepts.add('calculation'); operation = 'calculate'
        expr = re.search(r'\d+(?:\s*[+\-*/%^x×÷]\s*\d+)+', n)
        if expr:
            slots['expression'] = expr.group(0).replace('×','*').replace('÷','/')
        mkey = re.search(r'(?:as|named|under(?: the)? name|باسم|تحت اسم)\s+([A-Za-z0-9_\-]+)', original, re.I)
        if mkey:
            slots['result_key'] = mkey.group(1).strip()
        else:
            mkey = re.search(r'(?:باسم|تحت اسم)\s+([\u0600-\u06ffA-Za-z0-9_\-]+)', original, re.I)
            if mkey:
                slots['result_key'] = mkey.group(1).strip()
    elif re.search(r'(?:what do you remember|what do you know about me|ماذا تعرف عني|ماذا تتذكر عني|ذاكرتي|ملفي في الذاكرة)', n):
        concepts.add('memory'); operation = 'query_memory'; question_type = 'memory_profile'
    elif re.search(r'(?:remember|save|store|my name is|remember that|افتكر|تذكر|احفظ|اسمي هو|اسمي=|اسمي:)', n):
        concepts.add('memory'); operation = 'remember'
        m = re.search(r'(?:my name is|اسمي\s*(?:هو|=|:)?|أنا اسمي|انا اسمي)\s+(.+)$', original, re.I)
        if m:
            slots['predicate'] = 'name'; slots['value'] = _clean(m.group(1))
        else:
            m = re.search(r'(?:remember(?: that)?|افتكر|تذكر(?: أن)?|احفظ)\s+([^:=：]+?)\s*[:=：]\s*(.+)$', original, re.I | re.S)
            if m:
                slots['predicate'] = _clean(m.group(1)).casefold(); slots['value'] = _clean(m.group(2))
            else:
                uncertainty.append('remember_request_missing_key_or_value')
    elif re.search(r'(?:when is|what(?:\'s| is)|متى|ما هو|ما|ايه|إيه|فين|أين)\s+(.+?)[?؟]?$', original, re.I):
        concepts.add('knowledge'); operation = 'query_knowledge'; question_type = 'open'
        m = re.search(r'^(?:when is|what(?:\'s| is)|متى|ما(?: هو)?|ايه|إيه|فين|أين)\s+(.+?)[?؟]?$', original, re.I)
        object_text = _clean(m.group(1) if m else original)
        slots['query'] = object_text
    elif re.search(r'(?:learn\s+from\s+(?:the\s+)?(?:web|internet)|learn\s+online|study\s+online|teach\s+(?:yourself|me)\s+from\s+(?:the\s+)?(?:web|internet)|تعلم\s+من\s+(?:الانترنت|الإنترنت|الويب)|تعلّم\s+من\s+(?:الانترنت|الإنترنت|الويب)|ابحث\s+وتعلم|تعلم\s+من\s+البحث)', n):
        concepts.update({'research', 'learning', 'internet'}); operation = 'research'
        markers = ('learn from the web ', 'learn from web ', 'learn from the internet ', 'learn from internet ', 'learn online ', 'study online ', 'teach yourself from the web ', 'teach yourself from web ', 'teach yourself from the internet ', 'teach yourself from internet ', 'teach me from the web ', 'teach me from internet ', 'تعلم من الانترنت ', 'تعلم من الإنترنت ', 'تعلم من الويب ', 'تعلّم من الانترنت ', 'تعلّم من الإنترنت ', 'تعلّم من الويب ', 'ابحث وتعلم ', 'تعلم من البحث ')
        query = original
        for marker in markers:
            pos = n.find(marker.casefold())
            if pos >= 0:
                query = _clean(original[pos + len(marker):])
                break
        slots['query'] = query or original
    elif re.search(r'(?:learn|study|teach|تعلم|تعلّم|ادرس|علمني|علّمني)', n):
        concepts.add('learning'); operation = 'learning_intent'
        subject = re.sub(r'^(?:learn|study|teach(?: me| yourself)?|تعلم|تعلّم|ادرس|علمني|علّمني)\s*', '', original, flags=re.I).strip(' :,-')
        if subject:
            slots['learning_topic'] = subject
        else:
            uncertainty.append('learning_topic_required')
    elif re.search(r'(?:search|research|browse|ابحث|دور|اعرف من الانترنت|ابحث على الإنترنت|أحدث الأبحاث)', n):
        concepts.add('research'); operation = 'research'; slots['query'] = original
    elif re.search(r'(?:discover|find|suggest|match|identify|recommend).*(?:skill|skills)|(?:اكتشف|دور على|اقترح|رشح|هات).*(?:مهارة|مهارات)|(?:المهارات المناسبة|مهارات مناسبة)', n):
        concepts.add('skill'); operation = 'skill_query'; question_type = 'skill_selection'
        m = re.search(r'(?:for|for the|لـ|للمهمة|للمهمه|بخصوص)\s+(.+?)[?؟]?$', original, re.I)
        if m:
            slots['query'] = _clean(m.group(1))
        else:
            m = re.search(r'(?:المناسبة|مناسبة|للمهمة دي|للمهمه دي)\s*(?:لـ|ل|في|for)?\s*(.+)?$', original, re.I)
            if m and m.group(1):
                slots['query'] = _clean(m.group(1))
    elif re.search(r'(?:skill|skills|مهارة|مهارات)', n):
        concepts.add('skill'); operation = 'skill_query'; question_type = 'skill'
    elif re.search(r'(?:project|repository|repo|مشروع|الريبو|المستودع)', n):
        concepts.add('project'); operation = 'project_task'; object_text = original

    if not operation:
        if speech_act == 'question':
            question_type = 'unknown'
            uncertainty.append('question_operation_unknown')
        elif speech_act == 'instruction':
            operation = 'unknown_task'
            uncertainty.append('capability_not_identified')
        else:
            operation = 'statement'

    for marker in ('if', 'unless', 'otherwise', 'until', 'لو', 'إذا', 'إلا إذا', 'غير كده', 'لحد ما'):
        if re.search(rf'\b{re.escape(marker)}\b', n, re.I):
            conditions.append(marker)

    for marker in ('today', 'tomorrow', 'yesterday', 'last', 'previous', 'اليوم', 'بكرة', 'غدا', 'امبارح', 'السابق', 'الأخير'):
        if marker in n:
            temporal.append(marker)

    # Typed references. 'it' in 'what time is it' is expletive, not unresolved.
    if re.search(r'\b(?:it)\b', n) and operation != 'query_time':
        slots['reference'] = 'it'
        if 'it' not in recent_topics and not last_goal:
            uncertainty.append('anaphoric_reference_unresolved')

    if re.search(r'\b(?:this task|this|that task)\b|\b(?:ذلك الطلب|المهمة دي|ده|دي)\b', n):
        if last_goal:
            slots['reference_target'] = last_goal
            if slots.get('query') in {'دي', 'ده', 'this', 'this task', 'that', 'ذلك'} or not slots.get('query'):
                slots['query'] = last_goal
        else:
            uncertainty.append('anaphoric_reference_unresolved')

    if operation == 'query_knowledge' and not slots.get('query'):
        slots['query'] = object_text or original

    return SemanticFrame(
        text=original,
        language=lang,
        speech_act=speech_act,
        concepts=tuple(sorted(concepts)),
        entities=tuple(entities),
        requested_operation=operation,
        object_text=object_text,
        slots=tuple(sorted(slots.items())),
        question_type=question_type,
        temporal=tuple(temporal),
        conditions=tuple(conditions),
        uncertainty=tuple(sorted(set(uncertainty))),
    )
