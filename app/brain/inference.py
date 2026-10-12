from __future__ import annotations

import re
from typing import Any, Iterable

from app.brain.models import Belief, Evidence, Hypothesis


def _tokenize(text: str) -> set[str]:
    return {x for x in re.findall(r'[A-Za-z0-9_\u0600-\u06ff]+', str(text or '').casefold()) if len(x) > 1}



CONCEPT_QUERY_ALIASES = {
    'meeting': ('meeting', 'appointment', 'اجتماع', 'الاجتماع', 'موعد', 'الموعد'),
    'person_identity': ('name', 'الاسم', 'اسمي'),
    'time': ('time', 'وقت', 'ساعة', 'الساعة'),
}

def query_aliases(query: str) -> list[str]:
    text = str(query or '').casefold().strip()
    aliases = [text]
    for concept, values in CONCEPT_QUERY_ALIASES.items():
        if any(v.casefold() in text for v in values):
            aliases.extend(values)
    return list(dict.fromkeys(aliases))

def belief_to_evidence(row: dict[str, Any]) -> Evidence:
    value = row.get('value')
    content = f"{row.get('predicate', '')} = {value}"
    return Evidence(
        kind='belief', content=content, source=str(row.get('source') or 'brain'),
        confidence=float(row.get('confidence', 1.0) or 1.0),
        reference=f"{row.get('subject')}:{row.get('predicate')}:r{row.get('revision', 1)}",
        provenance=str(row.get('provenance') or ''),
    )


def rank_beliefs(rows: Iterable[dict[str, Any]], query: str, *, limit: int = 8) -> list[Evidence]:
    aliases = query_aliases(query)
    q = set().union(*(_tokenize(x) for x in aliases)) if aliases else _tokenize(query)
    ranked: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        hay = f"{row.get('subject','')} {row.get('predicate','')} {row.get('value','')}"
        overlap = len(q & _tokenize(hay))
        score = overlap * 2.0 + float(row.get('confidence', 1.0) or 1.0)
        if overlap or not q:
            ranked.append((score, row))
    ranked.sort(key=lambda x: (-x[0], -float(x[1].get('confidence', 1.0) or 1.0), str(x[1].get('updated_at',''))))
    return [belief_to_evidence(row) for _, row in ranked[:limit]]


def infer(state: Any) -> list[Hypothesis]:
    frame = state.semantic
    beliefs = state.beliefs
    op = frame.requested_operation if frame else ''
    hypotheses: list[Hypothesis] = []
    if op == 'query_identity':
        value = next((b.value for b in beliefs if b.predicate == 'name' and b.status == 'active'), None)
        if value:
            hypotheses.append(Hypothesis('هوية المستخدم مدعومة ببلاغ/حقيقة محفوظة.', 0.99, ('user.name',), 'supported'))
        else:
            hypotheses.append(Hypothesis('لا توجد حقيقة اسم موثوقة في الحالة الحالية.', 0.86, ('user.name',), 'unsupported'))
    elif op == 'query_memory':
        hypotheses.append(Hypothesis('يمكن الإجابة من beliefs المستمرة بعد ترتيبها حسب الصلة والمصدر.', 0.93, ('memory-retrieval',), 'supported' if beliefs else 'open'))
    elif op == 'query_knowledge' or op == 'research':
        hypotheses.append(Hypothesis('السؤال الخارجي يحتاج evidence موثق قبل تقديم جواب.', 0.95, ('external-evidence',), 'open'))
    elif op == 'calculate':
        hypotheses.append(Hypothesis('التعبير يمكن تقييمه بشكل حتمي ثم تسجيل النتيجة كملاحظة.', 0.99, ('calculation-result',), 'supported'))
    elif op == 'query_time':
        hypotheses.append(Hypothesis('الوقت الحالي ملاحظة قابلة للقياس مباشرة من النظام.', 0.99, ('clock-observation',), 'supported'))
    elif op == 'remember':
        hypotheses.append(Hypothesis('المعلومة يمكن تحويلها إلى belief durable إذا كان المفتاح والقيمة واضحين.', 0.98, ('belief-write',), 'supported' if frame.slot('predicate') and frame.slot('value') else 'blocked'))
    elif op == 'query_capabilities':
        hypotheses.append(Hypothesis('الإجابة يمكن توليدها من capability registry الحالي.', 0.96, ('capability-registry',), 'supported'))
    else:
        hypotheses.append(Hypothesis('لم يتم التعرف على عملية معرفية حاسمة؛ يجب اكتشاف capability أو طلب توضيح.', 0.45, ('capability-discovery',), 'open'))
    return hypotheses


def contradiction_pairs(beliefs: list[Belief]) -> list[tuple[Belief, Belief]]:
    by_key: dict[str, list[Belief]] = {}
    for belief in beliefs:
        if belief.status != 'active':
            continue
        by_key.setdefault(belief.key(), []).append(belief)
    pairs: list[tuple[Belief, Belief]] = []
    for values in by_key.values():
        for i, left in enumerate(values):
            for right in values[i+1:]:
                if left.value != right.value:
                    pairs.append((left, right))
    return pairs
