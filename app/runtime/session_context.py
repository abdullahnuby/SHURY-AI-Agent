"""Runtime session context shared by tools during one user interaction."""
from __future__ import annotations
from contextvars import ContextVar

_CURRENT_SESSION: ContextVar[str | None] = ContextVar("agent_session_id", default=None)


def current_session_id() -> str | None:
    return _CURRENT_SESSION.get()


def push_session(session_id: str | None):
    return _CURRENT_SESSION.set(session_id)


def pop_session(token) -> None:
    _CURRENT_SESSION.reset(token)
