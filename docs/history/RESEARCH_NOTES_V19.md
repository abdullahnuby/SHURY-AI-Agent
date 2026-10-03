# Research Notes — V19

Date: 2026-09-29

## 1. Agent Skills standard

The current Agent Skills specification defines a portable directory with `SKILL.md` plus optional `scripts/`, `references/`, and `assets/`. The specification requires lowercase hyphenated names, a useful description, optional compatibility/metadata/allowed-tools, and progressive disclosure: metadata at discovery, instructions on activation, and resources only as needed.

Source: https://agentskills.io/specification
GitHub reference: https://github.com/agentskills/agentskills

## 2. Skill acquisition and compilation

Anything2Skill (June 2026) frames the problem as compiling heterogeneous external knowledge into reusable procedural skills with invocation conditions, contraindications, workflow steps, constraints, outputs, evidence and confidence, then managing them in a versioned SkillBank.

Source: https://arxiv.org/abs/2606.09316

V19 adopts the important boundary: external prose is declarative evidence, while executable workflow requires a machine-readable contract or a verified runtime-derived procedure.

## 3. Skill optimization

SkillOpt (Microsoft Research, June 2026) treats skills as optimizable external parameters and reports controlled skill editing without changing model weights. This motivates V19's differential evaluation database and lifecycle gate: compare the same goal with and without the skill and optimize only when repeated evidence supports the change.

Source: https://www.microsoft.com/en-us/research/blog/skillopt-agent-skills-as-trainable-parameters/

## 4. Skill-induced failures

An August 2026 Microsoft Research study reports that skills can increase cost or reduce success and introduces differential analysis by comparing skill-guided and no-skill/reference runs. V19 therefore does not treat "skill exists" or "skill execution succeeded" as sufficient proof of usefulness.

Source: https://www.microsoft.com/en-us/research/publication/agent-skills-can-be-harmful-an-empirical-study-of-skill-induced-failures-in-llm-agents/

## 5. Long-horizon invocation shape

A September 7, 2026 preprint comparing agent skills with subagent invocation reports that reusable knowledge benefits from clear input/output contracts and that invocation organization matters for long-horizon tasks.

Source: https://arxiv.org/abs/2609.09233

V19 keeps explicit tool/skill contracts and a bounded planner rather than loading unlimited skill text into the main execution state.

## 6. Graph-shaped skills

A September 2026 AIP proposal represents skills as directed execution graphs with typed input/output edges and schema-validated YAML. V19's existing workflow dependency graph plus the optional `workflow.json` contract is the first deterministic step toward that model.

Source: https://jimwebber.org/publication/2026-agents+graph/

## 7. Scientific procedural skills

Scientific Agent Skills (August 2026) provides 163 procedural skills in 16 scientific areas, each organized around versioned human-readable instructions, references and runnable scripts. This informed V19's package structure, explicit resources and provenance preservation.

Source: https://arxiv.org/abs/2609.00065
GitHub: https://github.com/K-Dense-AI/scientific-agent-skills

## 8. RAG / agentic retrieval

Agentic-R (ACL 2026) and the 2026 data-centric Agentic RAG survey support iterative search, retrieval decisions interleaved with reasoning, and richer process data. V19 retains V16's adaptive retrieval portfolio and uses newly learned skill knowledge as an additional bounded procedural layer rather than silently replacing retrieval evidence.

Source: https://aclanthology.org/2026.findings-acl.785/
Project: https://github.com/fatty-belly/Awesome-AgenticRAG-Data/

## V19 design decisions

1. External skill text is never executable by implication.
2. Package metadata is cheap to discover; instructions/resources are loaded progressively.
3. External skills enter quarantine, not active status.
4. Skill usefulness is measured differentially against a baseline, not by raw success alone.
5. Current world/evidence remains authoritative over historical skill experience.
6. Promotion/demotion requires repeated observations and conservative thresholds.
7. Every imported package and research-derived candidate carries provenance/hash evidence.
