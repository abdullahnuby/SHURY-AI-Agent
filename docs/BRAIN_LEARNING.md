# SHURY Brain Learning (No LLM)

SHURY now has a non-parametric Brain Knowledge layer. It learns reusable **capability priors**
and **procedural families** from structured examples. This is separate from user Memory and
separate from verified runtime Experience.

## Bootstrap the included seed corpus

```powershell
py -m app.interfaces.cli
/brain-bootstrap
/brain-stats
```

The bootstrap reads `data/seed/agent_scenarios_100k.db` but filters records whose declared
capability is incompatible with the installed tools. Synthetic examples are treated as prior
knowledge only; they do not increment Skill success counters and cannot auto-promote Skills.

## Add your own data

Preferred format is JSONL. One record should look like:

```json
{"goal":"inspect the project then run its checks","domain":"development","capability":"inspect_check","interaction_shape":"multi_step","required_tools":["inspect_project","check_project"],"tool_order":["inspect_project","check_project"],"constraints":["verify_before_completion"],"failure_modes":["wrong_root"],"success_invariants":["checks_match_project"]}
```

Then:

```powershell
/brain-ingest data/training/my_examples.jsonl
/brain-stats
```

Supported formats: `.jsonl`, `.ndjson`, `.json`, `.csv`, and `.jsonl.gz`.

## What SHURY learns

Examples improve:

1. Semantic routing as a weak prior when deterministic intent confidence is low.
2. Reusable multi-step procedures when the requested capability and learned workflow match.
3. Failure-mode and success-invariant metadata that can later be connected to verified runtime learning.

The runtime still verifies every actual tool call, checks preconditions, and keeps promotion
behind runtime evidence. Training data is not treated as proof that a procedure works.

## Inspect learned knowledge

```powershell
/brain-match review the project and run its validation checks
/brain-procedures inspect the project then run its checks
```

## The learning loop

```text
structured data
    ↓
Brain Knowledge
    ↓
TaskIR / capability priors / procedure priors
    ↓
verified execution
    ↓
Experience + failures + outcomes
    ↓
Brain Knowledge is enriched
    ↓
reusable Skill candidate
    ↓
verified replay / promotion gates
```

The design intentionally follows the idea that procedural memory should represent executable
procedures with activation/execution/termination conditions, while successful and failed
experiences remain auditable rather than being silently converted into trusted behavior.
