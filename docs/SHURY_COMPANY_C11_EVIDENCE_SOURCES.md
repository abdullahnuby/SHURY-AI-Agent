# SHURY Company C11 — Evidence & Sources

## Design

The Company does not become a second knowledge base. The existing SkillBank remains the source of truth for skill content and lifecycle. C11 adds a thin provenance boundary that answers four questions:

1. What external source was used?
2. Is that source registered for the question it is meant to settle?
3. How fresh and reproducible is the evidence?
4. Can the Company show the evidence receipt at the execution boundary?

## Runtime chain

```
Skill
  ↓
Evidence Policy
  ↓
Observed tool output
  ↓
Evidence receipts
  ↓
Source registry resolution
  ↓
Company verification
```

The registry stores URLs, publisher, authority scope, licensing and checked dates. It never copies third-party source text.

## Current policy classes

- `builtin:web-research`: external evidence required; Web/arXiv/GitHub accepted; retrieval timestamp and content hash required.
- `builtin:research-report`: multiple external evidence items required; provenance is inherited from the research step that produced them.
- local analysis/audit skills do not require external sources.

This distinction matters: a local CSV analysis should be grounded in the file itself, while a research claim should carry an external evidence trail.

## Evidence boundary

Evidence is not automatically truth. The Company records the source and its metadata, but verification still decides whether a result can be treated as a completed governed output. External prose never becomes an executable workflow merely because it was retrieved.

## Research anchors reviewed in 2026

- `Cited but Not Verified` (arXiv 2605.06635) found that citation presence is a weak proxy for factual support, motivating explicit link/relevance/fact verification rather than citation-count scoring.
- `DeepTRACE` at ICLR 2026 audits statement-level support and citation accuracy across deep-research systems, motivating claim-to-evidence traceability.
- `Scientist-One` introduces a chain-of-evidence standard in which claims trace to grounding evidence, motivating native evidence chains instead of post-hoc citation decoration.

These are design inputs, not copied source content or claims that override SHURY's own runtime verification.
