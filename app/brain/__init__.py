"""Brain public API with lazy exports to keep canonical learning imports acyclic.

The brain model types are foundational and are imported by the learning layer.  The
kernel itself imports the learning layer, so eager ``from .kernel`` here creates a
package-initialisation cycle.  Keep the public surface stable while loading the heavy
orchestration objects only when requested.
"""

_MODEL_EXPORTS = {
    'Belief', 'Capability', 'CanonicalState', 'ActionSpec', 'Transition',
    'CognitiveState', 'Decision', 'Evidence', 'GoalSpec', 'Hypothesis',
    'PlannedAction', 'SemanticFrame',
}

__all__ = [
    'BrainResult', 'CognitiveKernel', 'BrainStateStore', *_MODEL_EXPORTS,
]


def __getattr__(name):
    if name in {'BrainResult', 'CognitiveKernel'}:
        from .kernel import BrainResult, CognitiveKernel
        return {'BrainResult': BrainResult, 'CognitiveKernel': CognitiveKernel}[name]
    if name == 'BrainStateStore':
        from .store import BrainStateStore
        return BrainStateStore
    if name in _MODEL_EXPORTS:
        from . import models
        return getattr(models, name)
    raise AttributeError(name)
