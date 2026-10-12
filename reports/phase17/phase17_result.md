# PHASE 17 — SECOND 1000-DIALOGUE ROUND

## Status
BLOCKED_BY_ENVIRONMENT

## Scope
Generated a new unseen 1,000-dialogue Round 2 corpus, validated reproducibility and exact non-overlap with Round 1, and attempted the complete real-agent execution.

## Round 2 generation
- Seed: `20261017`
- Generator: `phase17-dialogue-generator.v1`
- Sessions: `1000`
- Minimum turns/session: `3`
- Unique session IDs: `1000`
- Unique session seeds: `1000`
- Unique transcripts: `767`
- Exact transcript overlap with Round 1: `0`
- Session-ID overlap with Round 1: `0`
- Byte-identical regeneration: `PASS`
- Round 2 JSONL SHA-256: `2705ebd9f7372cb3c618130c123d1ce11eaaa142ee2f6009e44436fe8abdc000`

## New variation coverage
- New wording: `1000/1000`
- New topic variants: `415/1000`
- New reference variants: `415/1000`
- Correction sessions: `167/1000`
- Typo sessions: `117/1000`
- Noise sessions: `313/1000`
- Topic-switch sessions: `248/1000`

## Round 1 vs Round 2
| Metric | Round 1 | Round 2 |
|---|---:|---:|
| Sessions | 1000 | 1000 |
| Unique transcripts | 624 | 767 |
| Language: English | 221 | 201 |
| Language: Arabic | 193 | 185 |
| Language: Mixed | 229 | 268 |
| Arabic → English | 183 | 167 |
| English → Arabic | 174 | 179 |

Unique transcript diversity increased by **22.92%**.

There is no exact transcript overlap and no conversation-ID overlap.

## Complete-agent execution
The actual canonical real-runtime runner was invoked for all 1,000 Round-2 sessions.

Result:
- requested sessions: `1000`
- executed sessions: `0`
- model: `omarelshehy/Arabic-Retrieval-v1.0`
- status: `BLOCKED_BY_ENVIRONMENT`
- error: `sentence_transformers` is not installed and the required model cannot load
- exit code: `2`

No offline/fallback model was substituted and no simulated execution was counted.

## Runtime comparison
A valid Round-1 vs Round-2 runtime improvement/regression comparison is **not available**, because the required real model could not execute Round 2 (and Phase 12 established the same hard production preflight requirement for real runs).

## Changes
- Added `app/evaluation/round2_dialogue_generator.py`
- Added `scripts/generate_round2.py`
- Added `scripts/compare_rounds.py`
- Added `tests/test_phase17_round2_generator.py`
- Added Round-2 corpus, manifest, comparison, and execution evidence under `benchmarks/dialogues/round2`, `benchmarks/round2_runtime`, and `reports/phase17`

No production agent/runtime code was modified.

## Gate
`BLOCKED_BY_ENVIRONMENT`

Phase 17 is not closed because the complete real-agent Round-2 run could not execute.
