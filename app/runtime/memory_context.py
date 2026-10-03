"""Per-execution memory authority context for Brain-invoked tools."""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_CURRENT_MEMORY: ContextVar[Any | None] = ContextVar("shury_memory_authority", default=None)


def current_memory() -> Any | None:
    return _CURRENT_MEMORY.get()


def push_memory(memory: Any):
    return _CURRENT_MEMORY.set(memory)


def pop_memory(token) -> None:
    _CURRENT_MEMORY.reset(token)
