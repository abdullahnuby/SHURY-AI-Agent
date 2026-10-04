from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Literal

DecisionKind = Literal['respond', 'execute', 'retrieve', 'research', 'clarify', 'refuse']


def _canonicalize(value: Any) -> Any:
    """Normalize state/action values for deterministic semantic identity."""
    if isinstance(value, dict):
        return {str(k): _canonicalize(value[k]) for k in sorted(value, key=lambda x: str(x))}
    if isinstance(value, (set, frozenset)):
        normalized = [_canonicalize(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, default=str))
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, float):
        rounded = round(value, 8)
        return int(rounded) if rounded.is_integer() else rounded
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)


def _fingerprint(payload: Any) -> str:
    normalized = _canonicalize(payload)
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Belief:
    subject: str
    predicate: str
    value: Any
    confidence: float = 1.0
    source: str = 'user'
    provenance: str = ''
    created_at: str = ''
    updated_at: str = ''
    revision: int = 1
    status: str = 'active'
    supersedes: str = ''

    def key(self) -> str:
        return f'{self.subject}:{self.predicate}'

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d['confidence'] = round(max(0.0, min(1.0, float(self.confidence))), 3)
        return d


@dataclass(frozen=True)
class Evidence:
    kind: str
    content: str
    source: str
    confidence: float = 1.0
    reference: str = ''
    provenance: str = ''

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d['confidence'] = round(max(0.0, min(1.0, float(self.confidence))), 3)
        return d


@dataclass(frozen=True)
class SemanticFrame:
    text: str
    language: str
    speech_act: str
    concepts: tuple[str, ...] = ()
    entities: tuple[tuple[str, str], ...] = ()
    requested_operation: str = ''
    object_text: str = ''
    slots: tuple[tuple[str, str], ...] = ()
    question_type: str = ''
    temporal: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()
    uncertainty: tuple[str, ...] = ()
    memory_need: str = 'none'
    memory_types: tuple[str, ...] = ()
    memory_reason: str = ''

    def slot(self, name: str) -> str:
        for k, v in self.slots:
            if k == name:
                return v
        return ''

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GoalSpec:
    name: str
    objective: str
    desired_state: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    success_conditions: tuple[str, ...] = ()
    query: str = ''
    required_evidence: tuple[str, ...] = ()
    required_capability: str = ''
    priority: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Hypothesis:
    statement: str
    confidence: float
    evidence_needed: tuple[str, ...] = ()
    status: str = 'open'

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d['confidence'] = round(max(0.0, min(1.0, float(self.confidence))), 3)
        return d


@dataclass(frozen=True)
class Capability:
    name: str
    tool: str
    description: str
    preconditions: tuple[str, ...] = ()
    effects: tuple[str, ...] = ()
    cost: float = 1.0
    risk: str = 'low'
    verification: str = 'standard'
    reversible: bool = True

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d['cost'] = round(float(self.cost), 4)
        return d


@dataclass(frozen=True)
class CanonicalState:
    """Stable, text-independent representation of decision-relevant world state."""
    facts: tuple[tuple[str, Any], ...] = ()
    variables: tuple[tuple[str, Any], ...] = ()
    entities: tuple[tuple[str, Any], ...] = ()
    relations: tuple[tuple[str, Any], ...] = ()
    capabilities: tuple[str, ...] = ()
    resources: tuple[tuple[str, float], ...] = ()
    active_goals: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    pending_actions: tuple[str, ...] = ()
    completed_actions: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    environment_conditions: tuple[tuple[str, Any], ...] = ()
    temporal_context: tuple[str, ...] = ()
    uncertainty: tuple[str, ...] = ()
    observations: tuple[dict[str, Any], ...] = ()
    historical_state: tuple[dict[str, Any], ...] = ()
    learned_features: tuple[tuple[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            'facts': dict(self.facts),
            'variables': dict(self.variables),
            'entities': dict(self.entities),
            'relations': dict(self.relations),
            'capabilities': sorted(self.capabilities),
            'resources': dict(self.resources),
            'active_goals': sorted(self.active_goals),
            'constraints': sorted(self.constraints),
            'pending_actions': list(self.pending_actions),
            'completed_actions': sorted(self.completed_actions),
            'failures': sorted(self.failures),
            'environment_conditions': dict(self.environment_conditions),
            'temporal_context': sorted(self.temporal_context),
            'uncertainty': sorted(self.uncertainty),
            'observations': list(self.observations),
            'historical_state': list(self.historical_state),
            'learned_features': dict(self.learned_features),
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.to_dict())


@dataclass(frozen=True)
class ActionSpec:
    """Structured transition operator used by the cognitive planner."""
    action_id: str
    capability: str
    tool: str
    parameters: tuple[tuple[str, Any], ...] = ()
    preconditions: tuple[str, ...] = ()
    expected_effects: tuple[str, ...] = ()
    risk: str = 'low'
    cost: float = 0.0
    reversible: bool = True
    execution_time: float | None = None
    historical_success: int = 0
    historical_failure: int = 0
    expected_reward: float | None = None
    uncertainty: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            'action_id': self.action_id,
            'capability': self.capability,
            'tool': self.tool,
            'parameters': dict(self.parameters),
            'preconditions': list(self.preconditions),
            'expected_effects': list(self.expected_effects),
            'risk': self.risk,
            'cost': round(float(self.cost), 8),
            'reversible': self.reversible,
            'execution_time': self.execution_time,
            'historical_success': int(self.historical_success),
            'historical_failure': int(self.historical_failure),
            'expected_reward': self.expected_reward,
            'uncertainty': round(max(0.0, min(1.0, float(self.uncertainty))), 8),
        }

    def signature(self) -> str:
        return _fingerprint({
            'capability': self.capability,
            'tool': self.tool,
            'parameters': dict(self.parameters),
            'preconditions': sorted(self.preconditions),
            'expected_effects': sorted(self.expected_effects),
            'risk': self.risk,
            'reversible': self.reversible,
        })

    @classmethod
    def from_candidate(cls, candidate: 'CandidateAction', *, action_id: str = '', parameters: dict[str, Any] | None = None) -> 'ActionSpec':
        return cls(
            action_id=action_id or candidate.tool,
            capability=candidate.capability,
            tool=candidate.tool,
            parameters=tuple(sorted((parameters or {}).items(), key=lambda item: item[0])),
            preconditions=tuple(sorted(candidate.preconditions)),
            expected_effects=tuple(sorted(candidate.effects)),
            risk=candidate.risk,
            cost=float(candidate.cost),
            reversible=bool(candidate.reversible),
            uncertainty=1.0,
        )


@dataclass(frozen=True)
class Transition:
    """A single state/action boundary; prediction and actual outcome are distinct evidence."""
    state_before: str
    action: ActionSpec
    predicted_state: str | None = None
    state_after: str | None = None
    outcome: Any = None
    reward: float | None = None
    prediction_error: float | None = None
    verified: bool = False
    timestamp: str = ''
    metadata: tuple[tuple[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            'state_before': self.state_before,
            'action': self.action.to_dict(),
            'predicted_state': self.predicted_state,
            'state_after': self.state_after,
            'outcome': _canonicalize(self.outcome),
            'reward': self.reward,
            'prediction_error': self.prediction_error,
            'verified': self.verified,
            'timestamp': self.timestamp,
            'metadata': dict(self.metadata),
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.to_dict())

    @classmethod
    def from_states(cls, before: CanonicalState, action: ActionSpec, after: CanonicalState | None = None, *,
                    predicted: CanonicalState | None = None, outcome: Any = None, reward: float | None = None,
                    prediction_error: float | None = None, verified: bool = False, metadata: dict[str, Any] | None = None) -> 'Transition':
        return cls(
            state_before=before.fingerprint(),
            action=action,
            predicted_state=predicted.fingerprint() if predicted else None,
            state_after=after.fingerprint() if after else None,
            outcome=outcome,
            reward=reward,
            prediction_error=prediction_error,
            verified=verified,
            timestamp=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            metadata=tuple(sorted((metadata or {}).items(), key=lambda item: item[0])),
        )


@dataclass(frozen=True)
class CandidateAction:
    capability: str
    tool: str
    score: float
    reason: str
    requires_input: tuple[str, ...] = ()
    reversible: bool = True
    preconditions: tuple[str, ...] = ()
    effects: tuple[str, ...] = ()
    risk: str = 'low'
    cost: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d['score'] = round(float(self.score), 4)
        d['requires_input'] = list(self.requires_input)
        return d


@dataclass(frozen=True)
class PlannedAction:
    step_id: str
    capability: str
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    expected_effects: tuple[str, ...] = ()
    rationale: str = ''
    skill_key: str = ''
    # Phase-8 metadata. These fields describe why a safe information action was selected;
    # they never grant execution authority.
    exploration_mode: str = ''
    information_gain: float = 0.0
    exploration_reason: str = ''

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Decision:
    kind: DecisionKind
    confidence: float
    rationale: str
    answer_source: str = ''
    capability: str = ''
    tool: str = ''
    query: str = ''
    missing_information: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    candidates: tuple[CandidateAction, ...] = ()
    plan: tuple[PlannedAction, ...] = ()
    conclusion: str = ''

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d['confidence'] = round(max(0.0, min(1.0, float(self.confidence))), 3)
        d['missing_information'] = list(self.missing_information)
        d['evidence'] = [x.to_dict() for x in self.evidence]
        d['candidates'] = [x.to_dict() for x in self.candidates]
        d['plan'] = [x.to_dict() for x in self.plan]
        return d


@dataclass
class CognitiveState:
    user_text: str
    session_id: str | None = None
    semantic: SemanticFrame | None = None
    goal: GoalSpec | None = None
    beliefs: list[Belief] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    capabilities: list[Capability] = field(default_factory=list)
    candidates: list[CandidateAction] = field(default_factory=list)
    selected_skill: Any = None
    selected_skills: list[Any] = field(default_factory=list)
    plan: list[PlannedAction] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    world_facts: dict[str, Any] = field(default_factory=dict)
    trace: list[dict[str, Any]] = field(default_factory=list)
    decision: Decision | None = None
    revision: int = 0
    self_model: dict[str, Any] = field(default_factory=dict)
    action_specs: list[ActionSpec] = field(default_factory=list)

    def to_canonical_state(self) -> CanonicalState:
        goal = self.goal
        world = getattr(self, 'world', None)
        if world is not None:
            world_facts = dict(world.facts)
            variables = dict(world.variables)
            entities = dict(world.entities)
            relations = dict(world.relations)
            capabilities = tuple(sorted(world.capabilities))
            resources = dict(world.resources)
            environment_conditions = dict(getattr(world, 'environment_conditions', {}))
            temporal_context = tuple(getattr(world, 'temporal_context', ()))
            historical_state = tuple(getattr(world, 'history', ())[-20:])
            learned_features = dict(getattr(world, 'learned_features', {}))
            uncertainty = tuple(sorted(set(self.uncertainties) | set(getattr(world, 'uncertainties', ()))))
        else:
            world_facts = dict(self.world_facts)
            variables, entities, relations = {}, {}, {}
            capabilities, resources = tuple(), {}
            environment_conditions, temporal_context = {}, tuple()
            historical_state, learned_features = tuple(), {}
            uncertainty = tuple(sorted(set(self.uncertainties)))
        completed = tuple(sorted(str(item.get('step_id')) for item in self.observations if item.get('ok') and item.get('step_id')))
        failures = tuple(sorted(f"{item.get('tool', '')}:{item.get('error', '')}" for item in self.observations if item.get('ok') is False))
        pending = tuple(str(step.step_id) for step in self.plan if step.step_id not in completed)
        return CanonicalState(
            facts=tuple(sorted(world_facts.items(), key=lambda item: item[0])),
            variables=tuple(sorted(variables.items(), key=lambda item: item[0])),
            entities=tuple(sorted(entities.items(), key=lambda item: item[0])),
            relations=tuple(sorted(relations.items(), key=lambda item: item[0])),
            capabilities=capabilities,
            resources=tuple(sorted(((key, float(value)) for key, value in resources.items()), key=lambda item: item[0])),
            active_goals=(goal.objective,) if goal else tuple(),
            constraints=tuple(sorted(goal.constraints if goal else tuple())),
            pending_actions=pending, completed_actions=completed, failures=failures,
            environment_conditions=tuple(sorted(environment_conditions.items(), key=lambda item: item[0])),
            temporal_context=tuple(sorted(temporal_context)), uncertainty=uncertainty,
            observations=tuple(self.observations[-20:]), historical_state=historical_state,
            learned_features=tuple(sorted(learned_features.items(), key=lambda item: item[0])),
        )

    @property
    def memories(self) -> list[Evidence]:
        # Compatibility alias during V22 → V23 migration. The cognitive model owns
        # evidence; callers that still expect `memories` receive the same evidence list.
        out: list[Evidence] = []
        for item in self.evidence:
            # Canonical durable-memory evidence is exposed through the compatibility
            # memory view as `kind=memory`; the cognitive evidence list may retain the
            # lower-level `belief` representation for inference/diagnostics.
            if item.kind in {'legacy_memory', 'belief'} and item.source == 'canonical_memory':
                out.append(Evidence('memory', item.content, item.source, item.confidence, item.reference, item.provenance))
            elif item.kind == 'legacy_memory':
                out.append(Evidence('memory', item.content, item.source, item.confidence, item.reference, item.provenance))
            else:
                out.append(item)
        return out

    def event(self, kind: str, **data: Any) -> None:
        self.trace.append({'kind': kind, **data})

    def to_dict(self) -> dict[str, Any]:
        return {
            'user_text': self.user_text,
            'session_id': self.session_id,
            'semantic': self.semantic.to_dict() if self.semantic else None,
            'goal': self.goal.to_dict() if self.goal else None,
            'beliefs': [x.to_dict() for x in self.beliefs],
            'evidence': [x.to_dict() for x in self.evidence],
            'hypotheses': [x.to_dict() for x in self.hypotheses],
            'capabilities': [x.to_dict() for x in self.capabilities],
            'candidates': [x.to_dict() for x in self.candidates],
            'action_specs': [x.to_dict() for x in self.action_specs],
            'plan': [x.to_dict() for x in self.plan],
            'uncertainties': list(self.uncertainties),
            'observations': list(self.observations),
            'world_facts': dict(self.world_facts),
            'trace': list(self.trace),
            'decision': self.decision.to_dict() if self.decision else None,
            'revision': self.revision,
            'self_model': dict(self.self_model),
        }
