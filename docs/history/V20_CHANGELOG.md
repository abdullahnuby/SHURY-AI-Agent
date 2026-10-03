## V20.0.0 — Open-World Research + Learning Memory

- Added a durable ResearchMemory separate from executable SkillBank.
- Added an open-world learning loop spanning Web + arXiv + GitHub.
- Added source-class utility telemetry (`web`, `arxiv`, `github`) learned from observed evidence quality/relevance/freshness.
- Added novelty detection against prior research memory and lexical related-evidence recall.
- Added a declarative research-to-skill candidate pipeline with provenance; external prose still never becomes executable workflow.
- Added `/learn`, `/learn-development`, `/research-status`, `/research-memory`, `/research-source-learning` and `/v20-benchmark`.
- Added development-learning workflow that observes local project stack/git state and researches the relevant build/test/manage ecosystem without mutating the project.
- Preserved the existing bounded public-network/SSRF/robots/rate-limit controls and V19 Skill Governance invariants.
