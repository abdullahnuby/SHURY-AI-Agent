# SHURY Company 13 — C11 Release

Version: `25.0.0-alpha1-company13`

## Completed

- Declarative Company source registry.
- Skill-level evidence requirements without duplicating SkillBank.
- Evidence receipts with URL, source kind, source id, hash, retrieval time, publication date, freshness and licensing metadata.
- Canonical Brain Company evidence gate.
- `/company-sources` inspection command.
- Research output retrieval timestamps.

## Verification

- Company tests: 89/89 PASS after final hardening.
- `compileall`: PASS.
- `/company-sources builtin:web-research`: PASS.
- Existing local-data policies do not require external evidence.
- External research policy rejects missing retrieval provenance.

## Known unrelated baseline failures

The full repository suite still contains legacy `/agent` failures in the NLP/planner path. They are outside C11 and were not masked or rewritten by this phase.

## Boundary

The source registry contains pointers and metadata only. Third-party source text is not copied. External evidence remains untrusted until the applicable verification contract passes.
