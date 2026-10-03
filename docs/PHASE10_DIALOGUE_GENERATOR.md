# SHURY Phase 10 — Reproducible Dialogue Generator

## Purpose

Phase 10 introduces a deterministic, pure dialogue generator for stateful conversational-agent validation. The generator composes reusable scenario templates instead of manually enumerating 1,000 conversations.

## Composition dimensions

- intent and conversation-class templates
- memory, task, research, analysis, reference, clarification, tool, bilingual, and topic-switch scenarios
- English, Arabic, mixed, Arabic→English, and English→Arabic language modes
- neutral Arabic, Egyptian Arabic, and MSA variants
- generic typo transformations (deletion/swap)
- generic noise/politeness/punctuation transformations
- correction scenarios
- topic-switch insertion
- reference/deictic variation

## Reproducibility

Each session receives a deterministic derived seed from `sha256(root_seed:index)` and a stable conversation identifier containing the transcript digest. Generation uses no runtime state and no model.

## Artifact

The Phase 10 acceptance corpus is:

`benchmarks/dialogues/dialogues_phase10_seed_20261002.jsonl`

with manifest:

`benchmarks/dialogues/dialogues_phase10_manifest.json`

Each session contains:

- `conversation_id`
- root `seed` and `session_seed`
- multi-turn `turns`
- per-turn language/dialect/noise/typo metadata
- structured expectations for class, intent, slots, entities, references, memory action, tool, and clarification
- `expected_final_state`
- independent-session metadata

## Acceptance

The committed corpus contains 1,000 independent sessions and 3,216 turns, with a minimum of three turns per session. A fresh regeneration with the same seed is byte-for-byte identical to the committed JSONL artifact.
