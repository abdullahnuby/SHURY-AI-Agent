from __future__ import annotations
from datetime import datetime, timedelta, time as dt_time
import re
from .models import TemporalExpression
from app.core.time import DEFAULT_TIMEZONE, attach_timezone, get_timezone, now_in_timezone

TZ = DEFAULT_TIMEZONE
_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
    "الاثنين": 0, "الاتنين": 0, "الثلاثاء": 1, "الأربعاء": 2, "الاربعاء": 2,
    "الخميس": 3, "الجمعة": 4, "السبت": 5, "الأحد": 6, "الاحد": 6,
}


def _week_bounds(d):
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


def _add(out, text, kind, start, end, granularity, confidence):
    out.append(TemporalExpression(text, kind, start.isoformat() if hasattr(start, "isoformat") else str(start),
                                  end.isoformat() if hasattr(end, "isoformat") else str(end), granularity, TZ, confidence))


def extract_temporal(text: str, now: datetime | None = None) -> list[TemporalExpression]:
    now = now or now_in_timezone(TZ)
    now = attach_timezone(now, TZ)
    d = now.date()
    out: list[TemporalExpression] = []

    rel = [
        (r"\btoday\b|\bاليوم\b", 0, 0, "date", "day", 0.97),
        (r"\btomorrow\b|\bغدا\b|\bغدًا\b|\bبكره\b|\bبكرة\b", 1, 1, "date", "day", 0.97),
        (r"\byesterday\b|\bامبارح\b|\bأمس\b", -1, -1, "date", "day", 0.97),
        (r"\bthis week\b|\bهذا الأسبوع\b|\bالاسبوع ده\b|\bالأسبوع ده\b", 0, 0, "range", "week", 0.96),
        (r"\bnext week\b|\bالأسبوع القادم\b|\bالأسبوع الجاي\b|\bالاسبوع الجاي\b", 7, 13, "range", "week", 0.96),
        (r"\blast week\b|\bالأسبوع الماضي\b|\bالأسبوع اللي فات\b", -7, -1, "range", "week", 0.96),
    ]
    for pattern, ds, de, kind, gran, conf in rel:
        m = re.search(pattern, text, re.I)
        if not m:
            continue
        if kind == "range" and ds == 0:
            start, end = _week_bounds(d)
        elif kind == "range":
            start, end = _week_bounds(d + timedelta(days=ds))
        else:
            start, end = d + timedelta(days=ds), d + timedelta(days=de)
        _add(out, m.group(0), kind, start, end, gran, conf)

    # Relative durations: in two days / after 3 hours / بعد يومين.
    units = {
        "day": 1, "days": 1, "يوم": 1, "يومين": 2,
        "week": 7, "weeks": 7, "أسبوع": 7, "اسبوع": 7, "أسبوعين": 14, "اسبوعين": 14,
        "hour": 0, "hours": 0, "ساعة": 0, "ساعات": 0,
    }
    for m in re.finditer(r"(?:in|after|بعد|خلال)\s+(\d+)\s+(day|days|week|weeks|hour|hours|يوم|يومين|أسبوع|اسبوع|أسبوعين|اسبوعين|ساعة|ساعات)\b", text, re.I):
        count = int(m.group(1)); unit = m.group(2).casefold()
        if unit not in units: continue
        if "hour" in unit or unit in {"ساعة", "ساعات"}:
            point = now + timedelta(hours=count)
            _add(out, m.group(0), "relative_datetime", point, point, "hour", 0.93)
        else:
            days = count * units[unit]
            point = d + timedelta(days=days)
            _add(out, m.group(0), "date", point, point, "day", 0.93)

    # Weekday grounding: next Monday / الاثنين القادم, with no guessing about locale.
    for name, idx in _WEEKDAYS.items():
        pattern = r"\b(?:next\s+|this\s+|القادم\s+|الجاي\s+|هذا\s+)?" + re.escape(name) + r"\b"
        m = re.search(pattern, text, re.I)
        if not m: continue
        delta = (idx - d.weekday()) % 7
        if delta == 0 and re.search(r"(?:next|القادم|الجاي)", m.group(0), re.I):
            delta = 7
        point = d + timedelta(days=delta)
        _add(out, m.group(0), "date", point, point, "day", 0.90)

    for m in re.finditer(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", text):
        try: explicit = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=get_timezone(TZ)).date()
        except ValueError: continue
        _add(out, m.group(0), "date", explicit, explicit, "day", 0.99)
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b", text):
        try: explicit = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)), tzinfo=get_timezone(TZ)).date()
        except ValueError: continue
        _add(out, m.group(0), "date", explicit, explicit, "day", 0.98)

    # Clock time, including "at 10", "at 10:30", and Arabic الساعة ١٠ when digits normalized upstream.
    for m in re.finditer(r"(?:\bat\s+|\bالساعة\s+|\bالساعه\s+)(\d{1,2})(?::(\d{2}))?\s*(am|pm|ص|م)?\b", text, re.I):
        hour = int(m.group(1)); minute = int(m.group(2) or 0); mer = (m.group(3) or "").casefold()
        if hour > 23 or minute > 59: continue
        if mer in {"pm", "م"} and hour < 12: hour += 12
        if mer in {"am", "ص"} and hour == 12: hour = 0
        value = dt_time(hour, minute).isoformat(timespec="seconds")
        _add(out, m.group(0), "time", value, value, "minute", 0.95)
    # Colon time without a preposition, e.g. 18:30.
    for m in re.finditer(r"\b(\d{1,2}):(\d{2})\s*(am|pm|ص|م)?\b", text, re.I):
        hour = int(m.group(1)); minute=int(m.group(2)); mer=(m.group(3) or "").casefold()
        if hour > 23 or minute > 59: continue
        if mer in {"pm","م"} and hour < 12: hour += 12
        if mer in {"am","ص"} and hour == 12: hour = 0
        value = dt_time(hour, minute).isoformat(timespec="seconds")
        _add(out, m.group(0), "time", value, value, "minute", 0.93)

    # Deduplicate grounded expressions by semantic interval, not surface text.
    # "at 10:30" and "10:30" denote the same time.
    uniq = {}
    for item in out:
        key = (item.kind, item.start, item.end)
        if key not in uniq or item.confidence > uniq[key].confidence:
            uniq[key] = item
    return list(uniq.values())[:16]
