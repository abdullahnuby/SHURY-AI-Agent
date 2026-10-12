# Architecture V19 — Governed Skills + Adaptive Execution

```text
External Web / arXiv / GitHub / Local Runtime
                 |
                 v
          Evidence + Provenance
                 |
       +---------+---------+
       |                   |
   Knowledge RAG      Skill Candidate
                           |
                    SKILL.md validation
                           |
                    Security / Trust Gate
                 +---------+---------+
                 |                   |
             quarantine          local/verified
                 |                   |
                 +---------+---------+
                           |
                  Progressive Disclosure
                    metadata -> body -> resources
                           |
                    Machine-readable workflow?
                       /               \
                     no                 yes
                     |                    |
              declarative only     contract validation
                                           |
                                 current tool registry
                                           |
                                plan certification / STN
                                           |
                             Adaptive execution controller
                                           |
                      +--------------------+--------------------+
                      |                                         |
                current evidence                          skill experience
                      |                                         |
                      +--------------------+--------------------+
                                           |
                                Differential evaluator
                                   baseline vs skill
                                           |
                                  recency-weighted delta
                                           |
                              lifecycle recommendation
                              promote / observe / demote
```

## New V19 components

- `app/skill_standard.py`: Agent Skills-compatible package parsing/validation and progressive disclosure.
- `app/skill_governance.py`: trust/admission decisions and security findings.
- `app/skill_evaluation.py`: differential evaluation database and conservative lifecycle recommendations.
- `app/skill_research.py`: safe import of external skill packages and provenance-preserving research candidates.
- `app/v19_engine.py`: facade for package inspection, metadata/full activation view, and evidence reports.
- `app/tools/skill_research.py`: CLI/planner tools for package inspection, import and research-to-skill candidates.
- `app/v19_benchmark.py` and `tests/test_v19.py`: regression/benchmark coverage.

## Safety model

External skill packages are untrusted input. `SKILL.md` prose is never converted into commands. A workflow becomes executable only when supplied as machine-readable `workflow.json` or generated from a verified runtime execution. Even then, the live tool registry, plan validator, certificate, policy and approval layers remain authoritative.
