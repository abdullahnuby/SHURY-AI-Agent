from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Concept:
    name: str
    parents: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()


# This is a deliberately small ontology layer. It is not the intent list; it defines
# concepts the brain can reason about independent of any particular tool.
CONCEPTS: tuple[Concept, ...] = (
    Concept('person_identity', ('entity',), ('identity', 'name', 'هوية', 'اسم')),
    Concept('time', ('temporal',), ('time', 'وقت', 'ساعة')),
    Concept('memory', ('knowledge_source',), ('memory', 'ذاكرة')),
    Concept('knowledge', ('knowledge_source',), ('knowledge', 'معرفة')),
    Concept('calculation', ('operation',), ('calculate', 'حساب', 'حسبة')),
    Concept('project', ('artifact',), ('project', 'repository', 'repo', 'مشروع', 'ريبو')),
    Concept('research', ('information_gathering',), ('research', 'بحث', 'أبحاث')),
    Concept('skill', ('capability',), ('skill', 'skills', 'مهارة', 'مهارات')),
    Concept('meeting', ('event',), ('meeting', 'appointment', 'اجتماع', 'الاجتماع', 'موعد', 'الموعد')),
    Concept('location', ('entity',), ('location', 'place', 'مكان', 'فين', 'اين', 'أين')),
    Concept('preference', ('user_attribute',), ('preference', 'prefer', 'يفضل', 'مفضل')),
)


_ALIAS_TO_CONCEPT: dict[str, str] = {}
for concept in CONCEPTS:
    for alias in (concept.name, *concept.aliases):
        _ALIAS_TO_CONCEPT[alias.casefold()] = concept.name


def concept_for(value: str) -> str | None:
    text = str(value or '').casefold().strip()
    if not text:
        return None
    if text in _ALIAS_TO_CONCEPT:
        return _ALIAS_TO_CONCEPT[text]
    for alias, name in sorted(_ALIAS_TO_CONCEPT.items(), key=lambda x: -len(x[0])):
        if alias in text:
            return name
    return None


def semantic_concepts(semantic: Any) -> set[str]:
    values: set[str] = set()
    top = getattr(semantic, 'top_intent', None)
    if top:
        cap = str(getattr(top, 'capability', '') or '')
        intent = str(getattr(top, 'name', '') or '')
        for item in (cap, intent):
            c = concept_for(item.replace('_', ' '))
            if c:
                values.add(c)
    for entity in getattr(semantic, 'entities', ()) or ():
        c = concept_for(str(getattr(entity, 'type', '') or ''))
        if c:
            values.add(c)
    return values
