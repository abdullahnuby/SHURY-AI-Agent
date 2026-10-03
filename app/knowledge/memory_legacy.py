"""Compatibility facade for the pre-canonical memory import path.

Phase 1 removes the second memory authority: all legacy imports resolve to
``app.knowledge.memory.Memory``, which is the single canonical authority.
"""

from app.knowledge.memory import Memory as MemoryAuthority
from app.knowledge.memory import configure, get_memory

Memory = MemoryAuthority

__all__ = ["Memory", "MemoryAuthority", "configure", "get_memory"]
