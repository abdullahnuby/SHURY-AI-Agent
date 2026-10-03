# Synthetic 100K Scenario Seed

This corpus is a read-only prior library generated from curated task archetypes and anchored to the project's 100 real-user acceptance scenarios.

It is **not** user memory, not execution history, not evidence, and not promotion evidence. It must never by itself create a learned lesson or promote a Skill.

## Contents

- `data/seed/agent_scenarios_100k.db` — local FTS/search index used at runtime.
- `data/seed/agent_scenarios_100k.jsonl.gz` — portable canonical records.
- `data/seed/SEED_MANIFEST.json` — generation seed, counts, checksums and policy.
- `scripts/seed/generate.py` — deterministic generator.

## Coverage

The seed contains exactly 100,000 scenarios from 1,000 curated archetypes across 25 domains, with 4 language modes, 5 user styles, 5 difficulties and 5 interaction subtypes.

Domains include core computation, memory, knowledge/RAG, web/scientific research, GitHub, data analysis, workspace, development, skills, world modelling, planning, security, observability, documents, project management, productivity, communication, monitoring, data acquisition, QA, workflow composition, model selection, research operations and self-improvement.

## Runtime behavior

The Cognitive Core can retrieve a few relevant seed examples and use them as **non-authoritative prior examples**. Each example is explicitly labelled `synthetic_seed` and `not_execution_evidence`/`not_user_memory`.

Use `/seed-stats` and `/seed <query>` to inspect it from the CLI.

The corpus is deterministic. Regenerate it with `py scripts/seed/generate.py` and verify the manifest checksums before replacing a release corpus.
