# SHURY Company 13 — C11 Evidence & Sources

## Purpose

C11 adds a company-level evidence boundary so research-oriented work carries inspectable source provenance without creating a second knowledge store.

## Implementation

- `app/organization/evidence.py`: declarative source records, skill policies, receipts and assessments.
- `app/organization/sources.toml`: source pointers, licensing metadata, authority scope and freshness policy.
- `app/organization/skills.py`: exposes evidence policy alongside existing SkillBank bindings.
- `app/organization/registry.py`: evidence assessment surface for Company routing.
- `app/knowledge/web_research.py`: explicit `retrieved_at` provenance for fetched Web/arXiv/GitHub evidence.
- `app/brain/kernel.py`: Company evidence verification at the canonical execution boundary.
- `app/brain/models.py`: explicit `company_evidence` runtime state.
- `app/interfaces/cli.py`: `/company-sources` inspection command.

## Policy

External evidence is evidence, not executable instructions. High-stakes skills can require registered authoritative sources, freshness, content hashes, retrieval timestamps and claim support. The registry contains references and metadata only; third-party source prose is never copied.
