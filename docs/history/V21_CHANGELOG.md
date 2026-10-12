# V21 CHANGELOG

## Skill Supply Chain + Progressive Skill Routing

V21 upgrades the agent from a research-memory system into a governed skill supply pipeline.

- Discovers real `SKILL.md` packages from GitHub, including curated skill ecosystems.
- Performs bounded recursive repository inspection and package materialization.
- Records upstream repository, branch, commit revision, file list, SHA-256, area and family routing metadata.
- Validates schema/security before admitting a package.
- Imports only machine-readable workflows whose tools exist in the local registry. Markdown prose is never converted into executable steps.
- Keeps externally acquired skills quarantined by default.
- Adds explicit human-approved trust promotion as a high-risk operation.
- Adds progressive skill routing: request -> area -> family -> skill root.
- Diversifies automatic skill acquisition by repository/family so one repository cannot consume the whole install budget.
- Distills runtime failures into descriptive Failure Skill Candidates for later evaluation and refinement, following the self-evolving search-agent direction.
- Keeps refresh/provenance checks and durable registry state.
- Adds CLI/tooling for discover, route, install, refresh, approve, inventory, and supply status.
