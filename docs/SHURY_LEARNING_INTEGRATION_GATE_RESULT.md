# SHURY — Learning Integration Gate Result

## Purpose

This gate closes the architectural gap between the Phase-2..7 learning library and the actual SHURY decision/runtime entry points.

The target is the learning loop from the SHURY specification:

OBSERVE → STATE REPRESENTATION → EXPERIENCE → CANDIDATES → PREDICT → SIMULATE → EVALUATE → SELECT → EXECUTE → VERIFY → ACTUAL RESULT → REWARD → PREDICTION ERROR → STORE TRANSITION → UPDATE WORLD MODEL → UPDATE VALUE MODEL → REPLAY → continue.

The specification also requires a non-LLM cognitive engine, no duplicate learning/memory/planner authorities, and a strict runtime/policy/verification authority boundary.

## Findings Closed

### 1. `api.run_brain` now reaches the canonical learning stack

`CognitiveKernel` owns a single `SelfImprovementManager` instance and exposes that manager's canonical `LearningStore` as the Brain experience surface.

For every executed real action where state/action evidence is available, the kernel now captures:

- state before
- structured action
- pre-execution learned prediction
- state after
- observed outcome
- verification result
- duration

It then calls the same Layer-5 `observe_run()` lifecycle used by the runtime learning path.

This lifecycle performs reward annotation, prediction-error scoring against the pre-update prediction, persistent experience storage, replay indexing, transition-model update, and value update.

A real integration test executes the kernel twice and verifies that the second run produces a stored prediction-error observation.

### 2. Phase-7 model-based planning is no longer opt-in

The existing planners were extended rather than replaced.

`app/brain/planner.py` already contains the Brain-facing adapter to Phase-7 search. It is now treated as the default learned candidate whenever sufficient learned evidence exists.

`app/planning/planner.py` now does the same inside the existing `RulePlanner.plan()` facade.

The deterministic/portfolio planner remains the fallback when:

- no learned edge exists
- the model cannot produce a supported sequence
- the model-based result is invalid
- certification fails
- temporal validation fails

The learned planner never becomes execution authority; the normal validation/certificate/runtime/approval/verification controls remain authoritative.

### 3. Learning persistence is single-source

`app/brain/learning.py` no longer owns a second database implementation.

`BrainExperienceStore` is a compatibility alias for the canonical `app.learning.store.LearningStore`.

A compatibility `record()` adapter was added to `LearningStore` so existing Brain callers keep working without creating a parallel schema.

The canonical episode record now persists `operation` explicitly, so Brain and Layer-5 queries use the same task context.

### 4. Existing integration defects were corrected

A real failure was found in the Layer-5 bridge:

`SelfImprovementManager.observe_run()` called `_build_episode_transitions()` without the trajectory variable bound, causing `NameError` on the kernel learning path.

The method now accepts and consumes the kernel trajectory explicitly.

The store's recency/similarity sort was also corrected after the new `operation` column changed tuple positions.

### 5. Learned parameter reuse is guarded

Making model-based planning the default exposed an important generalization defect: an action learned under one goal could be reused with stale parameters under another goal when the world state alone was identical.

Phase-7 model-based action retrieval now checks deterministic tool argument builders when available. A learned binding must match the live goal's generated arguments exactly.

This prevents cases such as replaying a previously learned calculator expression for a new calculation request.

Actions without deterministic builders preserve their observed contract rather than fabricating a new parameter binding.

### 6. Kernel/API path is isolated from LLM integration

`app/brain` contains no direct LLM provider dependency.

`app.api` no longer eagerly imports the legacy LLM-backed `run_react` and `run_cognitive` implementations.

The semantic parser only imports its optional model parser at the point where a provider is actually requested.

This keeps importing and executing the `run_brain` surface independent from the legacy LLM runtime while preserving those legacy entry points for callers that explicitly use them.

## What remains intentionally NOT implemented here

Exploration / information gain is still the next learning phase.

The model-based planner still searches the learned action graph; it does not invent unknown actions or randomly execute dangerous actions.

Continual learning, procedural generalization, meta-strategy learning, deeper self-model integration, evaluation-lab integration, and model invalidation/recovery remain later architectural phases from the specification.

## Verification

Targeted integration + Phase-2..7 regression suite:

`114 passed`

Python compilation:

`python -m compileall -q app tests`

Full repository smoke run with fail-fast:

`240 passed` before stopping at an existing seed-database failure:

`sqlite3.OperationalError: no such table: scenarios`

That failure is in `tests/test_seed_scenarios.py` and concerns the repository seed database, not the learning integration gate.

## Architectural Result

The primary execution path is now materially different from the pre-gate architecture:

`api.run_brain`

→ `CognitiveKernel`

→ canonical state/action representation

→ existing Phase-7 learned planning candidate

→ governed execution

→ real observation + verification

→ canonical `SelfImprovementManager.observe_run()`

→ reward + prediction error

→ canonical `LearningStore`

→ replay + transition model + value model

→ updated evidence available to the next decision.

The system is still conservative by design: learning can recommend and update evidence, but it never acquires execution authority.
