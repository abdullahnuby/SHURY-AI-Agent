"""Deterministic user-facing response composition for SHURY runtime results."""
from __future__ import annotations

from typing import Any


def _lang(semantic: Any) -> str:
    value = str(getattr(semantic, "language", "en") or "en").casefold()
    return "ar" if value.startswith("ar") else "en"


def _intent(semantic: Any) -> str:
    top = getattr(semantic, "top_intent", None)
    return str(getattr(top, "name", "") or "")


def _effective_intent(semantic: Any, plan: Any) -> str:
    # Once execution is verified, the executed tool is stronger evidence for response
    # composition than a low-confidence surface classifier. This prevents a fuzzy
    # semantic top-intent such as "development" from turning a successful memory recall
    # into a raw tool dump.
    tool_map = {
        "get_time": "time",
        "calculator": "calculate",
        "remember_fact": "remember_fact",
        "recall_fact": "recall_fact",
        "remember_result": "remember_result",
        "remember_last_result": "remember_last_result",
        "save_note": "save_note",
        "list_notes": "list_notes",
        "list_skills": "list_skills",
        "installed_remote_skills": "skill_inventory",
        "answer_question": "knowledge_query",
    }
    steps = _done_steps(plan)
    if steps:
        tool = str(getattr(steps[-1], "tool", "") or "")
        if tool in tool_map:
            return tool_map[tool]
    return _intent(semantic)


def _done_steps(plan: Any) -> list[Any]:
    return [s for s in getattr(plan, "steps", []) or [] if getattr(s, "status", "") in {"done", "completed"}]


def _last_output(plan: Any) -> Any:
    steps = _done_steps(plan)
    if not steps:
        return None
    return getattr(steps[-1], "output", None)


def _stringify(value: Any, limit: int = 1400) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, (int, float, bool)):
        text = str(value)
    elif isinstance(value, dict):
        # Prefer obvious human-readable fields returned by the tools.
        for key in ("message", "answer", "summary", "result", "output", "value"):
            if value.get(key) not in (None, ""):
                return _stringify(value[key], limit)
        text = ", ".join(f"{k}: {v}" for k, v in value.items())
    elif isinstance(value, (list, tuple)):
        text = "\n".join(_stringify(x, 400) for x in value if x not in (None, ""))
    else:
        text = str(value)
    return text[:limit].rstrip()


def _memory_save_response(goal: str, semantic: Any, plan: Any, arabic: bool) -> str:
    steps = _done_steps(plan)
    step = steps[-1] if steps else None
    args = getattr(step, "args", {}) or {}
    key = str(args.get("key") or "").strip()
    value = str(args.get("value") or "").strip()
    entity_type = "person" if key == "name" else "location" if key in {"origin", "city"} else ""
    entity_value = next((str(getattr(entity, "text", "") or "").strip()
                         for entity in getattr(semantic, "entities", []) or []
                         if getattr(entity, "type", "") == entity_type), "") if entity_type else ""
    value = entity_value or value
    if arabic:
        if key and value and getattr(step, "tool", "") == "remember_fact":
            if key == "name":
                return f"تشرفت يا {value}."
            if key in {"origin", "city"}:
                return f"تمام، هفتكر إنك من {value}."
            return f"تم حفظ {key} = {value}."
        return "تم حفظ المعلومة."
    if key and value and getattr(step, "tool", "") == "remember_fact":
        if key == "name":
            return f"Nice to meet you, {value}."
        if key in {"origin", "city"}:
            return f"Got it. I'll remember you're from {value}."
        return f"Saved {key} = {value}."
    return "Saved."


def _memory_recall_response(plan: Any, arabic: bool) -> str:
    value = _last_output(plan)
    if value in (None, ""):
        return "مش لاقي معلومة محفوظة بالمفتاح ده." if arabic else "I couldn't find a stored value for that key."
    # `recall_fact` and `remember_*` commonly return a scalar/dict. The semantic key is
    # intentionally taken from the original plan args, not inferred from arbitrary text.
    key = ""
    for step in reversed(getattr(plan, "steps", []) or []):
        if getattr(step, "tool", "") == "recall_fact":
            key = str((getattr(step, "args", {}) or {}).get("key") or "").strip()
            break
    if arabic:
        if key == "name":
            return f"أيوه، فاكر إن اسمك {_stringify(value)}."
        return f"أفتكر إن {key} = {_stringify(value)}" if key else f"أفتكر إن القيمة = {_stringify(value)}"
    if key == "name":
        return f"Yes, I remember your name is {_stringify(value)}."
    return f"I remember that {key} = {_stringify(value)}" if key else f"I remember the value as {_stringify(value)}"


def _calculate_response(plan: Any, arabic: bool) -> str:
    value = _last_output(plan)
    if arabic:
        return f"النتيجة = {_stringify(value)}"
    return f"The result is {_stringify(value)}."


def _memory_search_response(plan: Any, arabic: bool) -> str:
    value = _last_output(plan)
    if not isinstance(value, list) or not value:
        return "مش لاقي معلومة محفوظة مرتبطة بالسؤال ده." if arabic else "I couldn't find a stored memory related to that question."
    lines: list[str] = []
    for item in value[:5]:
        if isinstance(item, dict):
            text = item.get("value") or item.get("summary") or item.get("text") or item.get("message")
        else:
            text = item
        text = _stringify(text, 500)
        if text and text not in lines:
            lines.append(text)
    if not lines:
        return "مش لاقي معلومة محفوظة مرتبطة بالسؤال ده." if arabic else "I couldn't find a stored memory related to that question."
    if arabic:
        return "لقيت في الذاكرة:\n" + "\n".join(f"• {line}" for line in lines)
    return "I found this in memory:\n" + "\n".join(f"• {line}" for line in lines)


def _question_response(plan: Any, arabic: bool) -> str:
    value = _last_output(plan)
    if not isinstance(value, dict):
        text = _stringify(value)
        return text or ("مش عندي دليل كفاية للإجابة على السؤال ده، ومش هخمن." if arabic else "I don't have enough evidence to answer that safely, so I won't guess.")

    answer = _stringify(value.get("answer"))
    if not answer:
        return "مش عندي دليل كفاية للإجابة على السؤال ده، ومش هخمن." if arabic else "I don't have enough evidence to answer that safely, so I won't guess."

    evidence = value.get("evidence") or []
    # Keep the main answer readable while exposing source provenance when available.
    source_lines: list[str] = []
    seen: set[str] = set()
    for item in evidence[:4] if isinstance(evidence, list) else []:
        if not isinstance(item, dict):
            continue
        title = _stringify(item.get("title"), 180)
        url = _stringify(item.get("url"), 320)
        label = title or url
        if label and label not in seen:
            seen.add(label)
            source_lines.append(f"• {label}" + (f" — {url}" if title and url and url != title else ""))
    if source_lines:
        if arabic:
            return f"{answer}\n\nالمصادر:\n" + "\n".join(source_lines)
        return f"{answer}\n\nSources:\n" + "\n".join(source_lines)
    return answer


def _time_response(plan: Any, arabic: bool) -> str:
    value = _stringify(_last_output(plan))
    if arabic:
        return f"الوقت الحالي هو {value}."
    return f"The current time is {value}."


def _generic_completed_response(plan: Any, arabic: bool) -> str:
    value = _last_output(plan)
    text = _stringify(value)
    if len(_done_steps(plan)) > 1:
        if arabic:
            return f"تم تنفيذ المهمة بنجاح.\n{('\n'.join(_stringify(getattr(s, 'output', None), 500) for s in _done_steps(plan) if getattr(s, 'output', None) not in (None, ''))).strip()}".strip()
        return f"The task completed successfully.\n{text}" if text else "The task completed successfully."
    if text:
        return text
    return "تم تنفيذ المهمة بنجاح." if arabic else "The task completed successfully."


def compose_final_response(goal: str, semantic: Any, plan: Any, status: str, fallback: str | None = None) -> str:
    """Return a deterministic concise answer from verified execution output."""
    arabic = _lang(semantic) == "ar"
    intent = _effective_intent(semantic, plan)
    status = str(status or "")

    if status == "needs_user":
        return fallback or ("محتاج توضيح قبل التنفيذ." if arabic else "I need a clarification before I can execute that.")
    if status in {"failed", "blocked", "timeout"}:
        return fallback or ("التنفيذ توقف قبل الاكتمال." if arabic else "The task stopped before completion.")
    if status in {"cancelled", "max_steps"}:
        return fallback or ("أوقفت التنفيذ قبل الاكتمال." if arabic else "Execution stopped before completion.")
    if status != "completed":
        return fallback or ("المهمة ما زالت قيد المعالجة." if arabic else "The task is still processing.")

    if intent == "time":
        return _time_response(plan, arabic)
    if intent in {"calculate"}:
        return _calculate_response(plan, arabic)
    if intent in {"remember_fact", "save_note", "remember_result", "remember_last_result"}:
        return _memory_save_response(goal, semantic, plan, arabic)
    if intent == "recall_fact":
        return _memory_recall_response(plan, arabic)
    if intent == "memory_search":
        return _memory_search_response(plan, arabic)
    if intent == "knowledge_query":
        return _question_response(plan, arabic)

    return _generic_completed_response(plan, arabic)
