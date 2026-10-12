"""Per-execution memory authority, owner, session, and run context."""
from __future__ import annotations
from contextvars import ContextVar
from typing import Any

_CURRENT_MEMORY: ContextVar[Any | None] = ContextVar("shury_memory_authority", default=None)
_CURRENT_OWNER: ContextVar[str | None] = ContextVar("shury_memory_owner", default=None)
_CURRENT_SESSION: ContextVar[str | None] = ContextVar("shury_memory_session", default=None)
_CURRENT_RUN: ContextVar[str | None] = ContextVar("shury_memory_run", default=None)

def current_memory() -> Any | None:
    return _CURRENT_MEMORY.get()

def push_memory(memory: Any):
    return _CURRENT_MEMORY.set(memory)

def pop_memory(token) -> None:
    _CURRENT_MEMORY.reset(token)

def current_memory_owner() -> str | None:
    return _CURRENT_OWNER.get()

def current_memory_session() -> str | None:
    return _CURRENT_SESSION.get()

def current_memory_run() -> str | None:
    return _CURRENT_RUN.get()

def push_memory_context(owner_id: str | None = None, session_id: str | None = None, run_id: str | None = None):
    return (_CURRENT_OWNER.set(str(owner_id) if owner_id else None),
            _CURRENT_SESSION.set(str(session_id) if session_id else None),
            _CURRENT_RUN.set(str(run_id) if run_id else None))

def pop_memory_context(tokens) -> None:
    owner_token, session_token, run_token = tokens
    _CURRENT_RUN.reset(run_token)
    _CURRENT_SESSION.reset(session_token)
    _CURRENT_OWNER.reset(owner_token)
