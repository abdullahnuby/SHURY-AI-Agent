from datetime import datetime, timedelta
from unittest.mock import patch

from zoneinfo import ZoneInfoNotFoundError

from app.core.time import get_timezone, now_in_timezone
from app.intelligence.semantic.temporal import extract_temporal


def test_cairo_fallback_works_without_iana_database():
    def missing_zone(_name):
        raise ZoneInfoNotFoundError("Africa/Cairo")

    with patch("app.core.time.ZoneInfo", side_effect=missing_zone):
        tz = get_timezone("Africa/Cairo")
        assert tz.key == "Africa/Cairo"
        assert datetime(2026, 9, 30, 12, tzinfo=tz).utcoffset() == timedelta(hours=3)
        assert datetime(2026, 1, 15, 12, tzinfo=tz).utcoffset() == timedelta(hours=2)


def test_temporal_parser_does_not_crash_without_tzdata():
    with patch("app.core.time.ZoneInfo", side_effect=ZoneInfoNotFoundError("Africa/Cairo")):
        parsed = extract_temporal("hello")
        assert parsed == []
        now = now_in_timezone("Africa/Cairo")
        assert now.tzinfo is not None


def test_temporal_relative_date_works_without_tzdata():
    with patch("app.core.time.ZoneInfo", side_effect=ZoneInfoNotFoundError("Africa/Cairo")):
        now = datetime(2026, 9, 30, 9, 0)
        parsed = extract_temporal("tomorrow", now=now)
        assert parsed[0].start == "2026-10-01"
        assert parsed[0].timezone == "Africa/Cairo"


def test_agent_hello_is_not_crashable_when_tzdata_is_missing():
    import app.core.time as time_module
    import app.runtime.agent as agent_module

    with patch.object(time_module, "ZoneInfo", side_effect=ZoneInfoNotFoundError("Africa/Cairo")):
        state = agent_module.run_agent("hello", session_id="tz-compat")
        assert state.status in {"completed", "needs_user", "failed"}


def test_greeting_does_not_require_a_plan():
    import app.runtime.agent as agent_module
    state = agent_module.run_agent("hello", session_id="greeting-test")
    assert state.status == "completed"
    assert "Hello" in state.final_message or "أهلًا" in state.final_message
