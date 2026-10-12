# PHASE 10 RESULT — Reproducible Dialogue Generator

## Status

`PASS`

## Baseline gap

The repository's pre-existing stateful generator tests passed, but the Phase 10 acceptance artifact did not exist at the required scale. `benchmarks/dialogues/` contained only two example sessions, and the old generator was a compact fixed-template helper coupled to the stateful benchmark runner rather than a dedicated compositional corpus generator.

No source fixes were made until this baseline gap was recorded.

## Implemented

- Added `app/evaluation/dialogue_generator.py` as a pure deterministic dialogue generator.
- Added reusable scenario templates for memory, tasks, research, analysis, references, clarification, bilingual switching, topic switching, corrections, and tool tasks.
- Added deterministic language modes: English, Arabic, mixed, Arabic→English, English→Arabic.
- Added neutral Arabic, Egyptian Arabic, and MSA variants.
- Added generic typo transformations and noise/politeness/punctuation transformations.
- Added correction and topic-switch composition.
- Added per-turn structured expectations:
  - `expected_class`
  - `expected_intent`
  - `expected_slots`
  - `expected_entities`
  - `expected_reference`
  - `expected_memory_action`
  - `expected_tool`
  - `expected_clarification`
- Added `expected_final_state` and language metadata.
- Added deterministic session seeds derived from `sha256(root_seed:index)`.
- Added schema validation and JSONL/manifest output.
- Added `scripts/generate_dialogues.py` as the reproducible CLI entry point.

## Acceptance corpus

Path:

`benchmarks/dialogues/dialogues_phase10_seed_20261002.jsonl`

Seed:

`20261002`

Measured artifact:

- Sessions: `1000`
- Unique conversation IDs: `1000`
- Unique session seeds: `1000`
- Total turns: `3216`
- Minimum turns/session: `3`
- Maximum turns/session: `5`
- Unique transcripts: `624`
- Duplicate transcripts: `376` (allowed; session identities/state scopes are independent)

Category distribution:

- memory: 252
- task: 84
- reference: 83
- research: 83
- analysis: 83
- clarification: 83
- bilingual: 83
- topic_switch: 83
- correction: 83
- tool_task: 83

Language-mode distribution:

- English: 221
- Arabic: 193
- mixed: 229
- Arabic→English: 183
- English→Arabic: 174

Variation coverage:

- typo-bearing sessions: 113
- noise-bearing sessions: 327
- correction-bearing sessions: 167
- topic-switch sessions: 277

## Reproducibility

The committed JSONL was regenerated from the same seed and compared byte-for-byte.

SHA-256:

`91d6a04e2eba4e49a2ba1d04e451c1158fa1f15dad2a81792b12815b35a7f7b5`

The regenerated artifact produced the identical SHA-256.

## Tests

Phase 10 generator suite:

`6/6 PASS`

Pre-existing stateful-generator compatibility suite:

`2/2 PASS`

Python compile:

`PASS`

A related pre-existing Phase 9 bilingual suite reported seven passing tests before its process stopped responding; this was recorded as a process-level issue and was not used to claim Phase 10 success or failure.

## Independence invariant

Each generated session is marked `independent_session=true`, has a unique deterministic `session_seed`, and declares `state_scope=session-local`. The generator performs no runtime execution and creates no user memory.

## Scope compliance

- No generative LLM added.
- No model replacement or supplement added.
- No runtime or memory authority change.
- No sentence-specific benchmark patches.
- No test assertion weakened to obtain the gate.

## Gate 10

`PASS`
