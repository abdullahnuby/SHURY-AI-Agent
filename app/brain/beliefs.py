from __future__ import annotations
from typing import Any

from app.brain.models import Fact, Evidence


def world_facts(world: Any) -> list[Fact]:
    facts: list[Fact] = []
    if world is None:
        return facts
    for key, value in (getattr(world, 'facts', {}) or {}).items():
        facts.append(Fact('world', str(key), value, 1.0, 'world'))
    for key, value in (getattr(world, 'variables', {}) or {}).items():
        facts.append(Fact('world', str(key), value, 1.0, 'world'))
    for cap in sorted(getattr(world, 'capabilities', set()) or set()):
        facts.append(Fact('agent', 'has_capability', cap, 1.0, 'world'))
    if getattr(world, 'last_goal', ''):
        facts.append(Fact('conversation', 'last_goal', world.last_goal, 1.0, 'world'))
    if getattr(world, 'last_outputs', None):
        facts.append(Fact('conversation', 'last_result', world.last_outputs.get('last_result'), 1.0, 'world'))
    return facts


def memory_to_evidence(payload: Any, *, source: str = 'memory') -> list[Evidence]:
    evidence: list[Evidence] = []
    if payload is None:
        return evidence
    items: list[Any]
    if isinstance(payload, dict):
        items = payload.get('items') or payload.get('hits') or payload.get('results') or []
        if not items and payload.get('value') is not None:
            items = [payload]
    elif isinstance(payload, list):
        items = payload
    else:
        items = [payload]
    for item in items[:12]:
        if isinstance(item, dict):
            content = item.get('value') or item.get('summary') or item.get('text') or item.get('message') or item.get('content')
            ref = str(item.get('id') or item.get('key') or '')
            confidence = float(item.get('confidence', 1.0) or 1.0)
            kind = str(item.get('kind') or 'memory')
        else:
            content, ref, confidence, kind = item, '', 1.0, 'memory'
        content = str(content or '').strip()
        if content:
            evidence.append(Evidence(kind, content, source, confidence, ref))
    return evidence
