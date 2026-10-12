# Personal Agent V22.4.1 Architecture

V22.4.1 keeps the deterministic governed runtime and adds Layer 1 — Cognitive Core.

## Cognitive flow

`Input → Semantic Frame → Baseline Candidate → Deterministic Plan → Observation → Reflection → Next Decision`

### Cognitive Core responsibilities

- Understand the desired outcome and success criteria.
- Identify ambiguity, assumptions, constraints, and information gaps.
- Form a small set of explicit hypotheses rather than blindly committing to one interpretation.
- Critique the deterministic planner's candidate plan.
- Reflect after observations and signal progress, blockage, changed assumptions, or replanning.
- Produce structured decision summaries without storing private chain-of-thought.

### Authority boundary

The semantic/cognitive layer is advisory. It cannot:
- bypass tool validation;
- change policy or approval requirements;
- activate untrusted Skills;
- mutate WorldState directly;
- assert a side effect occurred without runtime verification.

The execution authority remains in `app/runtime/`.

## Layered package map

## Package boundaries

| Package | Responsibility |
| --- | --- |
| `app/domain/` | Domain data and state: goals, plans, operators, world/state, sessions. |
| `app/runtime/` | Agent orchestration, tool registry, execution policy, verification, certificates. |
| `app/planning/` | Planning algorithms, hierarchical/search planning, scheduling, adaptation, repair. |
| `app/knowledge/` | Memory, RAG, research memory, open-world research, web research, data analysis, statistics. |
| `app/intelligence/` | Natural-language understanding and evaluation helpers. |
| `app/observability/` | Runtime analytics and operational telemetry. |
| `app/skills/` | Skill discovery, standards, governance, evaluation, compilation, evolution, registry. |
| `app/integrations/` | External-system adapters: network, workspace, project/development operations. |
| `app/services/` | Stable capability-oriented service facades used by the CLI and tools. |
| `app/tools/` | Thin executable tool adapters grouped by responsibility. |
| `app/evaluation/` | Benchmarks and historical release validation. |
| `app/interfaces/` | CLI and other user-facing interfaces. |

## Dependency direction

- Domain modules should not depend on CLI code.
- Tools depend on runtime contracts and call domain/knowledge/services; they should remain thin.
- Services compose capabilities; they should not become a second orchestration runtime.
- Integrations own external I/O.
- Evaluation code is not a production dependency of the runtime.
- `app/main.py` is an entrypoint only.

## Public integration point

External callers should prefer `app.api` for stable imports instead of reaching into implementation packages.

## Historical material

Version-specific architecture notes, research notes, changelogs, and verification reports live in `docs/history/` and are not part of the production runtime.


## Layer 2 — Semantic Understanding

Layer 2 sits between raw user input and cognitive/planning components. It produces a typed, inspectable semantic contract; it does not execute tools or grant permissions.

```text
User message
  ↓
Semantic normalization
  ├─ language / speech act / actionability
  ├─ intent candidates + domain
  ├─ entities + slots
  ├─ references / coreference
  ├─ temporal expressions
  ├─ constraints
  ├─ fresh-data requirement
  └─ ambiguity / clarification signals
  ↓
Cognitive Core / Planner
  ↓
Governed Runtime
```

The parser is deterministic-first. A model-backed semantic interpreter is invoked only for novel, low-confidence, or unresolved-reference cases. Model output is schema-constrained and safety-merged: it cannot invent entities, executable intent names, or arbitrary reference targets.

Semantic modules live under `app/intelligence/semantic/`; executable tools remain under `app/tools/`; policy and side effects remain owned by `app/runtime/`.


## Layer 5 — Self-Improvement

Layer 5 closes an evidence-driven learning loop without giving learning components execution authority:

`Run → Experience → Diagnosis → Contrastive/Advisory Lesson → Candidate Skill → Counterfactual Replay → Promotion Gate → Active Skill → Monitoring/Rollback`

The runtime records only bounded, sanitized experience. Failure lessons require failed-step evidence. Repeated verified workflows can form candidates, but activation requires repeated verified success, independent/contextual evidence, positive replay benefit, and zero regressions. Candidate workflow dependencies are preserved and triggers are generalized from task-family signatures rather than one-off argument values.

Learned guidance is passed to the agent as untrusted context. Replay is side-effect free. Skill trust is an independent gate, and active skills can be rolled back while preserving evidence.


## Layer 6 — Evaluation Lab

The evaluation layer is a separate measurement system over the agent runtime. It captures trajectories, deterministic outcome/tool/verification/efficiency/world/safety scores, workspace frame-condition changes, repeated-trial consistency, horizon survival, failure patterns, and regression deltas against pinned baselines. It does not grant the evaluator execution authority and it never lets an optional semantic judge override deterministic safety gates.

The intended release path is:

`scenario pack → isolated environment → agent run → trajectory capture → deterministic scoring → repeated trials → failure attribution → baseline comparison → release gate`.
