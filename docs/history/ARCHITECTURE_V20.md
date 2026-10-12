# Personal Agent V20 — Open-World Evidence Learning

```text
User Goal
   |
   v
Intent / Planner / Skill Governance
   |
   +--------------------+----------------------+
   |                    |                      |
Local RAG          Tool/Skill Memory      Open-World Research
   |                    |                      |
   |                    |             +--------+--------+
   |                    |             |        |        |
   |                    |           Web     arXiv   GitHub
   |                    |             +--------+--------+
   |                    |                      |
   |                    |          bounded fetch + provenance
   |                    |                      |
   +--------------------+-----------+----------+
                                Evidence
                                   |
                         relevance / quality /
                         freshness / novelty
                                   |
                            ResearchMemory
                                   |
                          +--------+--------+
                          |                 |
                   related evidence   source utility
                          |                 |
                          +--------+--------+
                                   |
                            local RAG index
                                   |
                      declarative Skill candidate
                                   |
                        differential evaluation
                                   |
                         approved/active only
                                   |
                         executable runtime
```

## V20 changes

### 1. Open-world routing
Queries are routed across heterogeneous public sources. The router is intentionally transparent and bounded; source classes are selected from explicit lexical intent signals.

### 2. Research memory
Research history is persisted in `data/research.db` independently from `data/skills.db`. Each evidence item retains source kind, URL, hash/provenance, quality, freshness, relevance, novelty and indexing state.

### 3. Learning signal
The agent records operational source utility by query context. This is not a truth probability and cannot authorize side effects. It is a secondary routing signal.

### 4. Novelty + related recall
Prior evidence is compared lexically against new evidence. New sources receive a novelty signal; related older evidence can be recalled to avoid rediscovering the same material blindly.

### 5. Procedural boundary
Research can create a declarative Skill candidate with evidence/provenance. Executable steps still require a validated machine-readable workflow or verified runtime-derived procedure and remain subject to registry/certificate/policy/approval.

### 6. Development learning
A local project can be inspected, observed through Git, and connected to current web/arXiv/GitHub evidence about its detected stack. This workflow is read-only and does not modify source code.
