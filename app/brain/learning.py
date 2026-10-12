"""Deprecated compatibility import for the canonical SHURY learning store.

There is intentionally no Brain-owned learning database. ``BrainExperienceStore`` is a
compatibility alias for :class:`app.learning.store.LearningStore`, which owns the single
learning schema, experience history, replay index, transition model evidence, value model,
and prediction-error records.
"""
from app.learning.store import LearningStore

BrainExperienceStore = LearningStore

__all__ = ["BrainExperienceStore", "LearningStore"]
