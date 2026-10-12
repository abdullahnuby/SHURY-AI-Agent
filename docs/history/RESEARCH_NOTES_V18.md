# V18 Research Notes — 2026-09-29

## Research signals

### Agentic RAG
- **Data-Centric Perspectives on Agentic RAG (ACL Findings 2026)** frames agentic retrieval around richer interactive trajectories and data lifecycle/evaluation, rather than a fixed retrieve-then-generate routine.
- **State-Aware RAG (ACL Findings 2026)** introduces explicit working memory for multi-hop reasoning and dynamic consolidation/update of intermediate evidence.
- **Agentic-R (ACL Findings 2026)** measures passage utility using both local query-passage relevance and global answer correctness, with iterative improvement of retrieval behavior.
- **AutoSearch (ACL Findings 2026)** optimizes for minimal sufficient search depth rather than rewarding indiscriminate over-searching.
- **SPARKLE (ACL 2026)** treats retrieval choice as an explicit policy that can be decoupled from the generator/retriever.
- **Search-P1 (ACL Industry 2026)** uses path-centric intermediate reward signals rather than only sparse terminal rewards.

### Skills
- **Anything2Skill (2026)** proposes structured skill contracts, procedural memory, taxonomy-aware compilation, lifecycle/version management, and retrieval of both evidence and reusable skills.
- **HASP (2026)** turns skills into executable program functions that can intervene at failure-prone states.
- **SkillGym (2026)** emphasizes verifier-backed environments, contrastive skill dependence, and verified trajectories.
- **SkillsBench / SWE-Skills-Bench (2026)** provide an important caution: skill utility is highly context-dependent; stale or mismatched skills can be neutral or harmful, so activation must remain evidence-driven.
- **Agent Skill Evaluation and Evolution (2026 survey)** organizes evolution around execution feedback, trajectory distillation, compression, and RL while highlighting safety and benchmark gaps.

## V18 implementation choices

Because this project intentionally avoids LLMs, embeddings, opaque policy networks, and remote model inference, V18 translates those research ideas into deterministic mechanisms:

1. structured SkillBank contracts and lifecycle
2. verified-runtime skill compilation
3. project-manifest skill generation
4. current-plan certification before skill reuse
5. reliability/cost/risk/information-value execution utility
6. minimal-sufficient exploration stop rule
7. path-centric execution outcome telemetry
8. automatic candidate promotion only after repeated verified success
9. automatic demotion on repeated observed failure

The implementation does not claim parity with model-trained systems; it adopts their architectural ideas where they can be made inspectable and reproducible without an LLM.
