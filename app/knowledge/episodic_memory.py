"""Deterministic episodic/experience-memory helpers for Phase 8.

Episodic memory is deliberately separate from factual memory.  These helpers
only normalize runtime evidence and rank stored episodes; they never promote
facts or change the Brain's planning authority.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.intelligence.understanding import normalize
from app.knowledge.memory_extraction import redact_secrets

_SECRET_KEYS = {
    "password", "passwd", "secret", "token", "access_token", "refresh_token",
    "api_key", "apikey", "authorization", "cookie", "session_cookie", "private_key",
}


def _sanitize(value: Any, *, max_text: int = 800, max_items: int = 64, depth: int = 3) -> Any:
    """Recursively redact secret-bearing values before episodic persistence."""
    if depth <= 0:
        return "<truncated>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        text = redact_secrets(value)
        return text[:max_text]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:max_items]:
            key_text = str(key)
            if key_text.strip().lower() in _SECRET_KEYS or any(part in key_text.lower() for part in ("password", "token", "secret", "api_key", "authorization", "private_key")):
                result[key_text] = "<redacted>"
            else:
                result[key_text] = _sanitize(item, max_text=max_text, max_items=max_items, depth=depth - 1)
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_sanitize(item, max_text=max_text, max_items=max_items, depth=depth - 1) for item in list(value)[:max_items]]
    return _sanitize(str(value), max_text=max_text, max_items=max_items, depth=depth - 1)


def sanitize_tool_events(events: Any) -> list[dict[str, Any]]:
    if events is None:
        return []
    raw = events if isinstance(events, (list, tuple)) else [events]
    out: list[dict[str, Any]] = []
    for event in raw[:64]:
        if isinstance(event, dict):
            item = _sanitize(event, max_text=1200)
        else:
            item = {"value": _sanitize(event, max_text=1200)}
        out.append(dict(item))
    return out



def sanitize_metadata(metadata: Any) -> dict[str, Any]:
    value = _sanitize(metadata or {}, max_text=800)
    return dict(value) if isinstance(value, dict) else {}

def sanitize_entities(entities: Any) -> list[dict[str, Any]]:
    if entities is None:
        return []
    raw = entities if isinstance(entities, (list, tuple)) else [entities]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entity in raw[:64]:
        if isinstance(entity, dict):
            item = _sanitize(entity, max_text=300)
            label = str(item.get("text") or item.get("name") or item.get("canonical") or "").strip()
            entity_type = str(item.get("type") or "entity").strip()
        elif isinstance(entity, (list, tuple)) and len(entity) >= 2:
            entity_type, label = str(entity[0]), str(entity[1])
            item = {"type": entity_type[:80], "text": redact_secrets(label)[:300]}
        else:
            label = str(entity).strip()
            entity_type = "entity"
            item = {"type": entity_type, "text": redact_secrets(label)[:300]}
        key = f"{normalize(label)}|{normalize(entity_type)}"
        if label and key not in seen:
            item.setdefault("type", entity_type)
            item.setdefault("text", redact_secrets(label)[:300])
            seen.add(key)
            out.append(item)
    return out


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w\u0600-\u06ff]+", normalize(str(text or "")), flags=re.UNICODE)


def _field_tokens(episode: dict[str, Any]) -> dict[str, set[str]]:
    tools = episode.get("tool_events") or []
    entities = episode.get("entities") or []
    tool_text = " ".join(
        str(item.get("tool") or "") + " " + str(item.get("capability") or "") + " " + str(item.get("error") or "")
        for item in tools if isinstance(item, dict)
    )
    entity_text = " ".join(
        str(item.get("text") or item.get("name") or item.get("canonical") or "")
        for item in entities if isinstance(item, dict)
    )
    return {
        "user": set(_tokens(episode.get("user_text", ""))),
        "assistant": set(_tokens(episode.get("assistant_text", ""))),
        "summary": set(_tokens(episode.get("summary", ""))),
        "outcome": set(_tokens(episode.get("outcome", ""))),
        "tools": set(_tokens(tool_text)),
        "entities": set(_tokens(entity_text)),
    }


def score_episode(query: str, episode: dict[str, Any], *, rank: int = 0) -> tuple[float, list[str]]:
    query_tokens = set(_tokens(query))
    reasons: list[str] = []
    if not query_tokens:
        return round(0.05 / (rank + 1), 6), ["recent"]
    fields = _field_tokens(episode)
    weights = {"user": 1.0, "summary": 1.25, "assistant": 0.55, "outcome": 0.45, "tools": 0.9, "entities": 1.0}
    weighted_overlap = 0.0
    total_weight = sum(weights.values())
    for field, tokens in fields.items():
        overlap = query_tokens & tokens
        if overlap:
            weighted_overlap += weights[field] * min(1.0, len(overlap) / max(1, len(query_tokens)))
            reasons.append(f"{field}-match")
    coverage = weighted_overlap / total_weight
    phrase = normalize(query).strip()
    combined = normalize(" ".join(str(episode.get(k) or "") for k in ("user_text", "assistant_text", "summary", "outcome")))
    phrase_bonus = 0.18 if phrase and phrase in combined else 0.0
    if phrase_bonus:
        reasons.append("phrase-match")
    recency = 0.04 / (rank + 1)
    if recency:
        reasons.append("recent")
    return round(min(1.0, coverage * 0.78 + phrase_bonus + recency), 6), reasons


def canonical_episode_payload(episode: dict[str, Any]) -> dict[str, Any]:
    """Return the stable public shape used by Phase-8 episodic APIs."""
    payload = {
        "episode_id": int(episode["id"]) if "id" in episode and str(episode["id"]).lstrip("-").isdigit() else episode.get("episode_id"),
        "owner_id": episode.get("owner_id"),
        "session_id": episode.get("session_id"),
        "run_id": episode.get("run_id"),
        "user_message": str(episode.get("user_text") or ""),
        "assistant_response": str(episode.get("assistant_text") or ""),
        "tool_events": sanitize_tool_events(episode.get("tool_events")),
        "outcome": episode.get("outcome"),
        "timestamp": episode.get("ts") or episode.get("timestamp"),
        "summary": episode.get("summary"),
        "entities": sanitize_entities(episode.get("entities")),
        "experience_kind": str(episode.get("experience_kind") or "interaction"),
        "metadata": dict(episode.get("metadata") or {}),
    }
    return payload
